#!/usr/bin/env python3
"""A minimal MCP control client and launcher for the fork tests.

DOSBox-X connects out to this client, so the client listens on a port and
accepts one connection.  The frame grammar is line based:

    BEGIN <id> OK <line_count>
    <line>...
    END <id>

An error frame holds no count, and a client reads to `END <id>`.

The tests are self-contained: they start the emulator with a small generated
config, so they need the binary only.
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import threading
import socket
import struct
import subprocess
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Response:
    request_id: str
    ok: bool
    lines: list[str] = field(default_factory=list)
    count: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Frame:
    identifier: str
    ok: bool
    count: int | None
    lines: list[str]


def read_frame(read_line: Callable[[], str]) -> Frame:
    """Read one frame.

    A success frame holds the line count, so the reader consumes exactly that
    many lines and a captured line cannot end the frame.  An error frame holds
    no count, so the reader reads to `END <id>`.
    """
    while True:
        line = read_line()
        if line.startswith("BEGIN "):
            break
    fields = line.split(" ", 3)
    identifier = fields[1] if len(fields) > 1 else ""
    status = fields[2] if len(fields) > 2 else ""
    count: int | None = None
    if len(fields) > 3:
        try:
            count = int(fields[3])
        except ValueError:
            count = None
    lines: list[str] = []
    if count is not None:
        for _ in range(count):
            lines.append(read_line())
        while True:
            if read_line().startswith("END "):
                break
    else:
        while True:
            inner = read_line()
            if inner.startswith("END "):
                break
            lines.append(inner)
    return Frame(identifier, status == "OK", count, lines)


class McpClient:
    """Listen for the emulator control connection and drive the debugger."""

    def __init__(self, port: int = 0, timeout: float = 60.0) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", port))
        self._server.listen(1)
        self._server.settimeout(timeout)
        self.port = self._server.getsockname()[1]
        self._timeout = timeout
        self._connection: socket.socket | None = None
        self._buffer = b""
        self._next_id = 0
        self.events: list[Frame] = []
        self.pending: list[Frame] = []

    def __enter__(self) -> "McpClient":
        self.accept()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def accept(self) -> None:
        self._connection, _ = self._server.accept()
        self._connection.settimeout(self._timeout)

    def drop_connection(self) -> None:
        """Drop the client side of the connection and let the emulator
        reconnect."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._buffer = b""

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._server.close()

    def _read_line(self) -> str:
        assert self._connection is not None
        while b"\n" not in self._buffer:
            chunk = self._connection.recv(65536)
            if not chunk:
                raise ConnectionError("the emulator closed the control connection")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode("utf-8", "replace")

    def send_line(self, line: str) -> None:
        assert self._connection is not None
        self._connection.sendall((line + "\n").encode())

    def send_raw(self, data: bytes) -> None:
        assert self._connection is not None
        self._connection.sendall(data)

    def read_frame(self) -> Frame:
        return read_frame(self._read_line)

    def send_request(self, command: str, payload: str = "") -> str:
        """Send a request and return its id, without waiting for a reply."""
        self._next_id += 1
        request_id = str(self._next_id)
        message = f"REQ {request_id} {command}"
        if payload:
            message += f" {payload}"
        self.send_line(message)
        return request_id

    def read_until(self, predicate: Callable[[Frame], bool],
                    timeout: float) -> Frame | None:
        """Read frames until one matches, and keep the other frames."""
        for store in (self.pending, self.events):
            for index, frame in enumerate(store):
                if predicate(frame):
                    return store.pop(index)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                frame = self.read_frame()
            except ConnectionError:
                return None
            if frame.identifier == "event":
                self.events.append(frame)
            if predicate(frame):
                return frame
            self.pending.append(frame)
        return None

    def request(self, command: str, payload: str = "",
                 timeout: float | None = None) -> Response:
        self._next_id += 1
        request_id = str(self._next_id)
        message = f"REQ {request_id} {command}"
        if payload:
            message += f" {payload}"
        if timeout is not None:
            assert self._connection is not None
            self._connection.settimeout(timeout)
        self.send_line(message)
        while True:
            frame = self.read_frame()
            if frame.identifier == request_id:
                return Response(request_id, frame.ok, frame.lines, frame.count)
            if frame.identifier == "event":
                self.events.append(frame)
            else:
                self.pending.append(frame)


def build_test_config(target: Path, port: int, memsize: int = 16) -> None:
    """Write a small config with the control port set."""
    target.write_text(
        "\n".join(
            [
                "[dosbox]",
                f"mcp_server={port}",
                f"memsize={memsize}",
                "machine=svga_s3",
                "",
                "[cpu]",
                "core=normal",
                "",
                "[autoexec]",
                "",
            ]
        )
    )


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]")


class PtyProcess:
    """Run the emulator on a pseudo terminal, because the debugger needs a
    terminal until the headless mode lands.

    A drain thread reads the master, so the output is always available and the
    child never blocks on a full terminal buffer.
    """

    def __init__(self, argv: list[str], cwd: Path,
                 env: dict[str, str] | None = None) -> None:
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        self.process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave)
        self._output: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        try:
            while not self._stop.is_set():
                chunk = os.read(self.master, 65536)
                if not chunk:
                    break
                self._output.append(chunk)
        except OSError:
            pass

    def text(self) -> str:
        return ANSI_RE.sub("", b"".join(self._output).decode("utf-8", "replace"))

    def clear(self) -> None:
        self._output.clear()

    def wait_for(self, marker: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if marker in self.text():
                return True
            if self.process.poll() is not None:
                return False
            time.sleep(0.3)
        return False

    def close(self) -> None:
        self._stop.set()
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.close(self.master)
        except OSError:
            pass


def build_game_config(game_dir: Path, target: Path, port: int) -> None:
    """Write a probe config from the game config with the control port set."""
    text = (game_dir / "dosboxScreamer.conf").read_text()
    text = text.replace("fullscreen=true", "fullscreen=false")
    text = text.replace("output=opengl", "output=surface")
    text = text.replace("[dosbox]\n", f"[dosbox]\nmcp_server={port}\n", 1)
    target.write_text(text)


def start_game_emulator(dosboxx: str, game_dir: Path, work_dir: Path):
    """Start the emulator with the game and the debugger, and return the
    child and the connected client."""
    import shutil

    client = McpClient()
    work_dir = work_dir.resolve()
    run_dir = work_dir / "run"
    game_copy = run_dir / "game"
    if game_copy.exists():
        shutil.rmtree(game_copy)
    run_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cp", "-cR", str(game_dir), str(game_copy)],
                            capture_output=True)
    if result.returncode != 0:
        subprocess.run(["cp", "-R", str(game_dir), str(game_copy)], check=True)
    config = work_dir / "probe.conf"
    build_game_config(game_dir, config, client.port)
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["TERM"] = "xterm-256color"
    child = PtyProcess(
        [dosboxx, "-nogui", "-nopromptfolder", "-break-start", "-conf", "../probe.conf",
         "-conf", "game/dosboxScreamer_single.conf"],
        run_dir,
        env,
    )
    client.accept()
    return child, client


class PipeProcess:
    """Run the emulator with no terminal, so the debugger must run headless.

    The standard streams are pipes, so isatty() is false for all three.
    """

    def __init__(self, argv: list[str], cwd: Path,
                 env: dict[str, str] | None = None) -> None:
        self.process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._output: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        assert self.process.stdout is not None
        try:
            while not self._stop.is_set():
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    break
                self._output.append(chunk)
        except OSError:
            pass

    def text(self) -> str:
        return ANSI_RE.sub("", b"".join(self._output).decode("utf-8", "replace"))

    def wait_for(self, marker: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if marker in self.text():
                return True
            if self.process.poll() is not None:
                return False
            time.sleep(0.3)
        return False

    def close(self) -> None:
        self._stop.set()
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if self.process.stdout is not None:
            self.process.stdout.close()


def start_headless_emulator(dosboxx: str, work_dir: Path, memsize: int = 16,
                            mcp_server: bool = True):
    """Start the emulator with no terminal and return the child and the client.

    With `mcp_server` set the debugger runs headless.  Without it the debugger
    reports the terminal guard.
    """
    client = McpClient() if mcp_server else None
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    config = work_dir / "headless.conf"
    build_test_config(config, client.port if client is not None else 0, memsize)
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    child = PipeProcess(
        [dosboxx, "-nogui", "-nopromptfolder", "-break-start", "-conf", str(config)],
        work_dir,
        env,
    )
    if client is not None:
        client.accept()
    return child, client


def start_emulator(dosboxx: str, work_dir: Path, memsize: int = 16):
    """Start the emulator with the debugger and the control server, and return
    the child and the connected client."""
    client = McpClient()
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    config = work_dir / f"test_{client.port}.conf"
    build_test_config(config, client.port, memsize)
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["TERM"] = "xterm-256color"
    child = PtyProcess(
        [dosboxx, "-nogui", "-nopromptfolder", "-break-start", "-conf", str(config)],
        work_dir,
        env,
    )
    client.accept()
    return child, client
