# AGENTS.md

## Table of Contents

- [Project Overview](#project-overview)
- [Technical Context](#technical-context)
- [Project Structure](#project-structure)
- [Build And Test Commands](#build-and-test-commands)
- [Contribution Instructions](#contribution-instructions)
- [Code Guidelines](#code-guidelines)
    - [System Design](#system-design)
    - [Architecture](#architecture)
    - [Code Quality](#code-quality)
    - [Testing](#testing)
    - [Dependency Management](#dependency-management)
    - [Configuration & Documentation](#configuration--documentation)
    - [Other](#other)

## Project Overview

This repository is the `re-tools` fork of DOSBox-X, a DOS emulator with
accurate emulation and wide hardware support.  The fork adds
reverse-engineering features to the built-in debugger.  The maintainers of the
Screamer (1995) reconstruction project use the debugger to collect run-time
evidence from a protected-mode DOS/4GW program.

## Technical Context

- **Language/Version**: C++11.
- **Primary Dependencies**: SDL2, SDL2_net, ncurses, fluid-synth, libslirp,
  freetype, libpng, and zlib.
- **Storage**: files on disk.  The emulator holds no database.
- **Testing**: GoogleTest, in the tree.  The debug build compiles the suite, and
  the `-tests` flag runs it.
- **Target Platform**: macOS arm64 for the fork work.  Upstream supports the
  other host platforms.
- **Project Type**: desktop app (emulator).
- **Performance Goals**: the debugger must not slow the emulation by more than
  15 percent on the entry-probe workload.
- **Constraints**: the fork base is the upstream tag `dosbox-x-v2026.10.01`.  The
  debugger needs `C_DEBUG` and `C_HEAVY_DEBUG`.  The agent API needs
  `C_DOSBOX_AGENT`.
- **Scale/Scope**: one project, one game, and a small patch set.

## Project Structure

```text
src/
├── debug/        # the built-in debugger, the MCP channel, and the agent bridge
├── cpu/          # the CPU cores and the breakpoint check call sites
├── dos/          # the DOS kernel, the file I/O, and the bundled DOS4GW
├── ints/         # the BIOS and the DOS interrupts, including INT 15h
├── agent/        # the structured debugger API
├── hardware/     # the device emulation, including the mouse
├── gui/          # SDL main, the menu, and the config options
├── shell/        # the DOS shell and the guest commands
└── builtin/      # the bundled guest programs, including DOS4GW.EXE
tests/            # the GoogleTest suites, including the agent tests
```

## Build And Test Commands

- **Build**: run `./autogen.sh`, then
  `./configure --enable-debug=heavy --enable-sdl2 --disable-sdl2test --disable-sdltest --enable-dosbox_agent`,
  then `make -j`.
- **Test**: run `src/dosbox-x -tests` from the repository root.
- **Run**: run `src/dosbox-x -conf <config>`.
- **Debugger**: start with `src/dosbox-x -break-start -conf <config>` and set
  `mcp_server = <port>` in the `[dosbox]` section to drive the debugger.

## Contribution Instructions

- You MUST verify every change with the build and the test suite.
- You MUST add a test in `tests/` for every behavior change, and you MUST run
  the suite before a commit.
- You MUST record the command and its output in the commit message body.
- You MUST put every behavior change behind a config option when a real program
  can disagree with the change.
- You MUST keep a debugger command inert until a script calls it.
- You MUST keep one commit per change, and you MUST NOT mix two changes in one
  commit.
- You MUST rebase the branch on the next upstream release tag instead of merging.
- You MUST match the surrounding upstream style in a patched file.
- You MUST update the Project Structure section of `AGENTS.md` when the project
  structure changes.
- If a prompt asks for a refactoring or an improvement, capture the resulting
  rule in the relevant Code Guidelines section of `AGENTS.md`.
- After completing a task, you MUST verify the code against the Code Guidelines in
  `AGENTS.md`.

## Code Guidelines

### System Design

- The emulator runs as a long-lived process with a main loop.  Clean up the
  resources (the sockets, the file handles, and the threads) at the exit
  functions.  Do not rely on the process exit.
- The emulation runs on one thread.  The MCP channel runs its socket I/O on a
  second thread, and it touches the debugger state only through the request
  queue.  Do not call the debugger state from the I/O thread.
- A debugger command runs on the emulation thread.  It must not block the
  emulation for a long time.
- A stop leaves the guest state unchanged, except for the documented effect of
  the stop.  A resume must not change the guest state.
- Shut down the control server and the agent server at the exit functions.
- Report a fatal error through the emulator log, and keep the log flushable.

### Architecture

- Separation of Concerns: the debugger core holds the address model and the
  recorders.  The MCP channel and the agent channel are adapters, and they hold
  no behavior.
- Single Responsibility Principle: one function has one task.  The address resolver
  resolves an address, and the coverage recorder records the addresses.
- Dependency Direction: the channels depend on the debugger core.  The core depends
  on the CPU and the memory API, and it depends on no channel.
- Explicit Boundaries: the channels expose a documented request set.  A client does
  not reach into the debugger internals.
- Data Flow Clarity: a request resolves an address, arms a breakpoint or a
  recorder, stops the emulation, and builds one stop record.
- Minimize Coupling, Maximize Cohesion: `src/debug/` holds the debugger
  knowledge.  The other modules do not parse a debugger request.
- Make Invalid States Impossible: the address resolver rejects an unresolved
  selector with an error.  It never masks an offset in silence.
- Observability Built-in: a command reports its input and its result.  The pipeline
  records every check with its evidence.
- Keep It Boring: use the upstream patterns.  A new debugger command follows the
  shape of the existing command next to it.

Layers:

| Layer | Responsibility | Example |
| --- | --- | --- |
| CPU and memory | run the guest and report the current state | `src/cpu/core_normal.cpp` |
| Debugger core | resolve an address, arm a breakpoint or a recorder, and build a stop record | `src/debug/debug.cpp` |
| Channels | expose the core to a client | `src/debug/debug_mcp.cpp`, `src/agent/` |
| BIOS | emulate the firmware, including `INT 15h` | `src/ints/bios.cpp` |

```text
guest -> CPU and memory -> debugger core -> channels -> client
```

### Code Quality

- A new function carries a comment when the upstream code next to it does.
- A new command follows the parse shape of the command next to it in
  `ParseCommand`.
- A new config option goes into `src/dosbox.cpp`, with a section, a type, a
  default, and a help text.
- An error raises a clear message, or it reports the error to the client.  It never
  fails in silence.
- A name follows the upstream style of the file.  The debugger code uses the
  upstream naming.
- The fork does not reformat a file it touches.  A patch holds the change only.

### Testing

- The fork places a test in `tests/`, next to the test the feature relates to.
- The test names the behavior it pins, and it holds one behavior.
- A debugger command test drives the command through the debugger, and it checks
  the result, not the implementation.
- A patch without a test does not merge.
- The fork records the command and the output in the commit message body.

### Dependency Management

- Pin every dependency version explicitly.  The build uses the host packages,
  and the release records the versions.
- Prefer the standard library.  Add a dependency only for significant value.
- Use the maintained sources only.  The host dependencies come from Homebrew, and
  ncurses comes from the system.
- Minimize the dependency count.  A fork patch adds no new dependency.
- Use the latest stable version, and check the registry before an addition.

**Rationale**: fewer and well-vetted dependencies reduce the security, the
supply-chain, and the maintenance cost.

### Configuration & Documentation

- A behavior change sits behind a config option in the `[dosbox]` or the
  `[debug]` section.  The option carries a default and a help text.
- A debugger command is inert until a script calls it.  It changes no behavior
  on its own.
- Update `README.debugger` when a debugger command changes.
- Update the reference config files (`dosbox-x.reference.conf` and
  `dosbox-x.reference.full.conf`) when a config option changes.
- Update `AGENTS.md` when the project structure or the build changes.
- Commit no secret.  The tree holds none.

### Other

- A commit subject names the change in the imperative mood, and it is at most 72
  characters.
- The commit body holds the command and the output that verify the change.
- One commit holds one change.
