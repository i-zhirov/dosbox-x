#include "dosbox.h"

#if defined(C_DEBUG) && defined(C_DOSBOX_AGENT)
#include "rpc_transport.h"

#include <algorithm>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>

#ifdef WIN32
#include <windows.h>
#include <sddl.h>
#pragma comment(lib, "Advapi32.lib")
#else
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#endif

namespace dosbox_agent {
namespace {

class NamedPipeTransport final : public IRpcTransport {
public:
    NamedPipeTransport() : impl(new Impl()) {}
    ~NamedPipeTransport() override { Stop(); }

    const char* Name() const override { return "named_pipe"; }

    bool ValidateConfiguration(const AgentConfig& config,
                               std::string* error) const override
    {
        if (config.endpoint.compare(0, 9, "\\\\.\\pipe\\") != 0 || config.endpoint.size() == 9) {
            if (error != NULL)
                *error = "Named pipe endpoint must use \\\\.\\pipe\\<name>";
            return false;
        }
        return true;
    }

    bool Start(const AgentConfig& config,
               RequestHandler handler,
               std::string* error) override
    {
        if (!ValidateConfiguration(config, error) || !handler)
            return false;

#ifndef WIN32
        if (error != NULL)
            *error = "Windows named pipes are unavailable on this platform";
        return false;
#else
        std::unique_lock<std::mutex> lock(impl->mutex);
        if (impl->listener.joinable()) {
            if (error != NULL)
                *error = "Named pipe transport is already running";
            return false;
        }

        impl->config = config;
        impl->handler = handler;
        impl->stopping = false;
        impl->ready = false;
        impl->start_succeeded = false;
        impl->start_error.clear();
        impl->listener = std::thread(&NamedPipeTransport::Run, this);
        impl->ready_condition.wait(lock, [this]() { return impl->ready; });
        if (impl->start_succeeded)
            return true;

        const std::string start_error = impl->start_error;
        lock.unlock();
        impl->listener.join();
        if (error != NULL)
            *error = start_error;
        return false;
#endif
    }

    void Stop() override
    {
#ifdef WIN32
        std::thread listener;
        std::vector<std::thread> client_workers;
        {
            std::lock_guard<std::mutex> lock(impl->mutex);
            if (!impl->listener.joinable())
                return;
            impl->stopping = true;
            for (std::vector<HANDLE>::const_iterator it = impl->active_pipes.begin();
                 it != impl->active_pipes.end(); ++it)
                CancelIoEx(*it, NULL);
            listener.swap(impl->listener);
        }
        listener.join();
        {
            std::lock_guard<std::mutex> lock(impl->mutex);
            client_workers.swap(impl->client_workers);
        }
        for (std::vector<std::thread>::iterator it = client_workers.begin();
             it != client_workers.end(); ++it)
            if (it->joinable())
                it->join();
#endif
    }

private:
    class Impl {
    public:
        std::mutex mutex;
        std::condition_variable ready_condition;
        AgentConfig config;
        RequestHandler handler;
        std::thread listener;
        bool stopping = false;
        bool ready = false;
        bool start_succeeded = false;
        std::string start_error;
#ifdef WIN32
        HANDLE active_pipe = INVALID_HANDLE_VALUE;
        std::vector<HANDLE> active_pipes;
        std::vector<std::thread> client_workers;
#endif
    };

    std::unique_ptr<Impl> impl;

#ifdef WIN32
    static bool WriteAll(const HANDLE pipe, const std::string& message)
    {
        std::size_t offset = 0;
        while (offset < message.size()) {
            const DWORD remaining = static_cast<DWORD>((std::min)(message.size() - offset,
                                                                    static_cast<std::size_t>(0xffffffffu)));
            DWORD written = 0;
            if (!WriteFile(pipe, message.data() + offset, remaining, &written, NULL) || written == 0)
                return false;
            offset += written;
        }
        return true;
    }

    HANDLE CreatePipe(std::string* error)
    {
        PSECURITY_DESCRIPTOR descriptor = NULL;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorA("D:P(A;;GA;;;OW)",
                                                                    SDDL_REVISION_1,
                                                                    &descriptor,
                                                                    NULL)) {
            *error = "Unable to create named pipe security descriptor";
            return INVALID_HANDLE_VALUE;
        }

        SECURITY_ATTRIBUTES attributes;
        attributes.nLength = sizeof(attributes);
        attributes.lpSecurityDescriptor = descriptor;
        attributes.bInheritHandle = FALSE;
        const DWORD buffer_size = static_cast<DWORD>((std::min)(impl->config.max_message_bytes,
                                                                 static_cast<std::size_t>(0xffffffffu)));
        HANDLE pipe = CreateNamedPipeA(impl->config.endpoint.c_str(),
                                       PIPE_ACCESS_DUPLEX,
                                       PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                                       PIPE_UNLIMITED_INSTANCES,
                                       buffer_size,
                                       buffer_size,
                                       0,
                                       &attributes);
        LocalFree(descriptor);
        if (pipe == INVALID_HANDLE_VALUE)
            *error = "Unable to create named pipe endpoint";
        return pipe;
    }

    void RemoveActivePipe(const HANDLE pipe)
    {
        std::lock_guard<std::mutex> lock(impl->mutex);
        for (std::vector<HANDLE>::iterator it = impl->active_pipes.begin();
             it != impl->active_pipes.end(); ++it) {
            if (*it == pipe) {
                impl->active_pipes.erase(it);
                break;
            }
        }
    }

    bool ServeClient(const HANDLE pipe)
    {
        std::string pending;
        char buffer[4096];
        for (;;) {
            DWORD read = 0;
            if (!ReadFile(pipe, buffer, sizeof(buffer), &read, NULL) || read == 0)
                return false;
            pending.append(buffer, read);

            for (;;) {
                const std::string::size_type line_end = pending.find('\n');
                if (line_end == std::string::npos) {
                    if (pending.size() > impl->config.max_message_bytes) {
                        const std::string response = impl->handler(std::string(impl->config.max_message_bytes + 1, 'x')) + "\n";
                        WriteAll(pipe, response);
                        return false;
                    }
                    break;
                }

                std::string request = pending.substr(0, line_end);
                pending.erase(0, line_end + 1);
                if (!request.empty() && request[request.size() - 1] == '\r')
                    request.erase(request.size() - 1);
                if (request.size() > impl->config.max_message_bytes) {
                    const std::string response = impl->handler(std::string(impl->config.max_message_bytes + 1, 'x')) + "\n";
                    WriteAll(pipe, response);
                    return false;
                }
                if (!WriteAll(pipe, impl->handler(request) + "\n"))
                    return false;
            }

            std::lock_guard<std::mutex> lock(impl->mutex);
            if (impl->stopping)
                return false;
        }
    }

    void ServeClientThread(const HANDLE pipe)
    {
        ServeClient(pipe);
        CloseHandle(pipe);
        RemoveActivePipe(pipe);
    }

    void Run()
    {
        bool first_pipe = true;
        for (;;) {
            std::string error;
            const HANDLE pipe = CreatePipe(&error);
            if (pipe == INVALID_HANDLE_VALUE) {
                std::lock_guard<std::mutex> lock(impl->mutex);
                if (first_pipe) {
                    impl->start_error = error;
                    impl->ready = true;
                    impl->ready_condition.notify_all();
                }
                return;
            }

            {
                std::lock_guard<std::mutex> lock(impl->mutex);
                impl->active_pipe = pipe;
                impl->active_pipes.push_back(pipe);
                if (first_pipe) {
                    impl->start_succeeded = true;
                    impl->ready = true;
                    impl->ready_condition.notify_all();
                    first_pipe = false;
                }
                if (impl->stopping) {
                    CloseHandle(pipe);
                    impl->active_pipe = INVALID_HANDLE_VALUE;
                    impl->active_pipes.pop_back();
                    return;
                }
            }

            const BOOL connected = ConnectNamedPipe(pipe, NULL);
            const DWORD connect_error = connected ? ERROR_SUCCESS : GetLastError();
            if (connected || connect_error == ERROR_PIPE_CONNECTED) {
                bool stopping = false;
                {
                    std::lock_guard<std::mutex> lock(impl->mutex);
                    stopping = impl->stopping;
                    if (!stopping)
                        impl->client_workers.push_back(std::thread(&NamedPipeTransport::ServeClientThread, this, pipe));
                }
                if (stopping) {
                    CloseHandle(pipe);
                    RemoveActivePipe(pipe);
                    return;
                }
            } else {
                CloseHandle(pipe);
                RemoveActivePipe(pipe);
            }

            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->active_pipe = INVALID_HANDLE_VALUE;
            if (impl->stopping)
                return;
        }
    }
#endif
};

class UnixSocketTransport final : public IRpcTransport {
public:
    UnixSocketTransport() : impl(new Impl()) {}
    ~UnixSocketTransport() override { Stop(); }

    const char* Name() const override { return "unix_socket"; }

    bool ValidateConfiguration(const AgentConfig& config,
                               std::string* error) const override
    {
        if (config.endpoint.empty() || config.endpoint[0] != '/') {
            if (error != NULL)
                *error = "Unix socket endpoint must be an absolute path";
            return false;
        }
        return true;
    }

    bool Start(const AgentConfig& config,
               RequestHandler handler,
               std::string* error) override
    {
        if (!ValidateConfiguration(config, error) || !handler)
            return false;

#ifndef WIN32
        std::unique_lock<std::mutex> lock(impl->mutex);
        if (impl->listener.joinable()) {
            if (error != NULL)
                *error = "Unix socket transport is already running";
            return false;
        }

        impl->config = config;
        impl->handler = handler;
        impl->stopping = false;
        impl->ready = false;
        impl->start_succeeded = false;
        impl->start_error.clear();
        impl->listener = std::thread(&UnixSocketTransport::Run, this);
        impl->ready_condition.wait(lock, [this]() { return impl->ready; });
        if (impl->start_succeeded)
            return true;

        const std::string start_error = impl->start_error;
        lock.unlock();
        impl->listener.join();
        if (error != NULL)
            *error = start_error;
        return false;
#else
        if (error != NULL)
            *error = "Unix sockets are unavailable on this platform";
        return false;
#endif
    }

    void Stop() override
    {
#ifndef WIN32
        std::thread listener;
        {
            std::lock_guard<std::mutex> lock(impl->mutex);
            if (!impl->listener.joinable())
                return;
            impl->stopping = true;
            if (impl->client_fd >= 0) {
                shutdown(impl->client_fd, SHUT_RDWR);
                close(impl->client_fd);
                impl->client_fd = -1;
            }
            if (impl->server_fd >= 0) {
                shutdown(impl->server_fd, SHUT_RDWR);
                close(impl->server_fd);
                impl->server_fd = -1;
            }
            listener.swap(impl->listener);
        }
        listener.join();
#endif
    }

private:
    class Impl {
    public:
        std::mutex mutex;
        std::condition_variable ready_condition;
        AgentConfig config;
        RequestHandler handler;
        std::thread listener;
        bool stopping = false;
        bool ready = false;
        bool start_succeeded = false;
        std::string start_error;
        int server_fd = -1;
        int client_fd = -1;
    };

    std::unique_ptr<Impl> impl;

#ifndef WIN32
    static bool WriteAll(const int fd, const std::string& message)
    {
        std::size_t offset = 0;
        while (offset < message.size()) {
            const ssize_t written = write(fd, message.data() + offset, message.size() - offset);
            if (written <= 0) {
                if (written < 0 && errno == EINTR)
                    continue;
                return false;
            }
            offset += static_cast<std::size_t>(written);
        }
        return true;
    }

    bool ServeClient(const int fd)
    {
        std::string pending;
        char buffer[4096];
        for (;;) {
            const ssize_t read_bytes = read(fd, buffer, sizeof(buffer));
            if (read_bytes <= 0) {
                if (read_bytes < 0 && errno == EINTR)
                    continue;
                return false;
            }
            pending.append(buffer, static_cast<std::size_t>(read_bytes));

            for (;;) {
                const std::string::size_type line_end = pending.find('\n');
                if (line_end == std::string::npos) {
                    if (pending.size() > impl->config.max_message_bytes) {
                        const std::string response = impl->handler(std::string(impl->config.max_message_bytes + 1, 'x')) + "\n";
                        WriteAll(fd, response);
                        return false;
                    }
                    break;
                }

                std::string request = pending.substr(0, line_end);
                pending.erase(0, line_end + 1);
                if (!request.empty() && request[request.size() - 1] == '\r')
                    request.erase(request.size() - 1);
                if (request.size() > impl->config.max_message_bytes) {
                    const std::string response = impl->handler(std::string(impl->config.max_message_bytes + 1, 'x')) + "\n";
                    WriteAll(fd, response);
                    return false;
                }
                if (!WriteAll(fd, impl->handler(request) + "\n"))
                    return false;
            }

            std::lock_guard<std::mutex> lock(impl->mutex);
            if (impl->stopping)
                return false;
        }
    }

    void Run()
    {
        struct sockaddr_un address;
        memset(&address, 0, sizeof(address));
        address.sun_family = AF_UNIX;
        if (impl->config.endpoint.size() >= sizeof(address.sun_path)) {
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->start_error = "Unix socket endpoint path is too long";
            impl->ready = true;
            impl->ready_condition.notify_all();
            return;
        }
        snprintf(address.sun_path, sizeof(address.sun_path), "%s", impl->config.endpoint.c_str());

        // Remove a stale socket path from a previous run.
        unlink(address.sun_path);

        const int server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (server_fd < 0) {
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->start_error = "Unable to create the Unix socket";
            impl->ready = true;
            impl->ready_condition.notify_all();
            return;
        }

        if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0 ||
                chmod(address.sun_path, 0600) < 0) {
            close(server_fd);
            unlink(address.sun_path);
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->start_error = "Unable to bind the Unix socket endpoint";
            impl->ready = true;
            impl->ready_condition.notify_all();
            return;
        }

        if (listen(server_fd, 1) < 0) {
            close(server_fd);
            unlink(address.sun_path);
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->start_error = "Unable to listen on the Unix socket endpoint";
            impl->ready = true;
            impl->ready_condition.notify_all();
            return;
        }

        {
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->server_fd = server_fd;
            impl->start_succeeded = true;
            impl->ready = true;
            impl->ready_condition.notify_all();
            if (impl->stopping) {
                close(server_fd);
                unlink(address.sun_path);
                impl->server_fd = -1;
                return;
            }
        }

        // Accept one client at a time and serve it.
        for (;;) {
            const int client_fd = accept(server_fd, NULL, NULL);
            if (client_fd < 0) {
                if (errno == EINTR)
                    continue;
                break;
            }

            bool stopping = false;
            {
                std::lock_guard<std::mutex> lock(impl->mutex);
                impl->client_fd = client_fd;
                stopping = impl->stopping;
            }
            if (stopping) {
                close(client_fd);
                break;
            }

            ServeClient(client_fd);
            close(client_fd);

            {
                std::lock_guard<std::mutex> lock(impl->mutex);
                impl->client_fd = -1;
                if (impl->stopping)
                    break;
            }
        }

        close(server_fd);
        unlink(address.sun_path);
        {
            std::lock_guard<std::mutex> lock(impl->mutex);
            impl->server_fd = -1;
        }
    }
#endif
};

} // namespace

std::unique_ptr<IRpcTransport> AGENT_CreateLocalTransport(const AgentTransport transport)
{
    switch (transport) {
    case AgentTransport::NamedPipe:
        return std::unique_ptr<IRpcTransport>(new NamedPipeTransport());
    case AgentTransport::UnixSocket:
        return std::unique_ptr<IRpcTransport>(new UnixSocketTransport());
    }
    return std::unique_ptr<IRpcTransport>();
}

} // namespace dosbox_agent
#endif // defined(C_DEBUG) && defined(C_DOSBOX_AGENT)
