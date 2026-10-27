#!/usr/bin/env python3
"""Test the agent breakpoint and memory methods.

A linear and a selector execution breakpoint stop the target, a condition and a
hit count limit the stops, and state.set_registers writes the registers.

The tests run a small loop fixture and need RE_DOSBOXX set to the DOSBox-X
binary.  Build the fixture once with `sh tests/re/build_fixture.sh`.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "client" / "python"))
from dosbox_agent import AgentClient, MemoryAddress, load_config  # noqa: E402
from mcp_client import PtyProcess  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))
FIXTURE = Path(__file__).parent / "fixture" / "re_loop.com"

# The fixture sets AX and loops at this offset.
LOOP_OFFSET = 0x106


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class AgentMethodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "RELOOP.COM")
        self.socket_path = self.work_dir / f"methods_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"methods_{os.getpid()}_{self._testMethodName}.env"
        self.config_path.write_text(
            "\n".join(
                [
                    "transport=unix_socket",
                    f"endpoint={self.socket_path}",
                    f"dosbox_executable={Path(DOSBOXX).resolve()}",
                    f"dosbox_workdir={self.runtime_dir}",
                    "request_timeout_ms=60000",
                    "max_message_bytes=1048576",
                    "max_memory_read_bytes=65536",
                    "max_trace_events=10000",
                    "profile=test",
                    "",
                ]
            )
        )
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["TERM"] = "xterm-256color"
        self.child = PtyProcess(
            [DOSBOXX, "-nogui", "-nopromptfolder", "-agent-config", str(self.config_path)],
            self.work_dir,
            env,
        )
        deadline = time.monotonic() + 30
        while not self.socket_path.exists():
            if time.monotonic() >= deadline:
                self.fail(
                    "the socket file did not appear: "
                    + self.child.text()[-300:]
                )
            time.sleep(0.1)
        self.client = AgentClient(load_config(self.config_path))
        self.session = self.client.start("RELOOP.COM", mount_path=self.runtime_dir)
        registers = self.client.get_registers(self.session.id)
        self.segment = int(registers.segments["cs"], 16)
        self.linear = (self.segment << 4) + LOOP_OFFSET

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def stop_at(self, kind: str, address: MemoryAddress, **options: object) -> None:
        """Create a breakpoint, continue, and check the stop."""
        self.client.create_breakpoint(
            self.session.id, kind, address, **options)
        operation = self.client.continue_(self.session.id)
        wait = self.client.wait(self.session.id, operation.id, 10000)
        self.assertFalse(wait.running, "the target did not stop")
        self.assertEqual(wait.session.stop_reason.kind, "breakpoint")

    def test_breakpoint_linear(self) -> None:
        """A linear execution breakpoint stops the target."""
        breakpoint = self.client.create_breakpoint(
            self.session.id, "execution_linear", MemoryAddress.linear(self.linear))
        self.assertIsNotNone(breakpoint.resolved)
        self.assertEqual(int(breakpoint.resolved["linear"]), self.linear)
        self.stop_at("execution_linear", MemoryAddress.linear(self.linear))
        registers = self.client.get_registers(self.session.id)
        self.assertEqual(int(registers.instruction_pointer, 16), LOOP_OFFSET)

    def test_breakpoint_selector(self) -> None:
        """A selector execution breakpoint stops the target."""
        breakpoint = self.client.create_breakpoint(
            self.session.id, "execution_selector",
            MemoryAddress.segmented(self.segment, LOOP_OFFSET))
        self.assertEqual(breakpoint.kind, "execution_selector")
        self.stop_at("execution_selector",
                     MemoryAddress.segmented(self.segment, LOOP_OFFSET))
        registers = self.client.get_registers(self.session.id)
        self.assertEqual(int(registers.instruction_pointer, 16), LOOP_OFFSET)

    def test_breakpoint_condition(self) -> None:
        """A condition and a hit count limit the stops."""
        breakpoint = self.client.create_breakpoint(
            self.session.id, "execution",
            MemoryAddress.segmented(self.segment, LOOP_OFFSET),
            condition="AX==1234", hit_count=1)
        self.assertEqual(breakpoint.condition, "AX==1234")
        self.stop_at("execution",
                     MemoryAddress.segmented(self.segment, LOOP_OFFSET))

    def test_set_registers(self) -> None:
        """A register write changes the value and the state revision."""
        before = self.session.state_revision
        revision = self.client.set_registers(self.session.id, {"ebx": 0xABCD})
        self.assertGreater(revision, before)
        registers = self.client.get_registers(self.session.id)
        self.assertEqual(int(registers.general["ebx"], 16), 0xABCD)

    def test_capabilities(self) -> None:
        """The capabilities report the new breakpoint and register fields."""
        result = self.client.call("agent.capabilities")
        breakpoints = result["breakpoints"]
        self.assertTrue(breakpoints["execution_linear"])
        self.assertTrue(breakpoints["execution_selector"])
        self.assertTrue(breakpoints["condition"])
        self.assertTrue(result["state"]["set_registers"])


if __name__ == "__main__":
    unittest.main()
