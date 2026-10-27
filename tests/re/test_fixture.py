#!/usr/bin/env python3
"""Test the fixture: the memory methods and a breakpoint at the loop.

The fixture writes 0x41 and 0x4243 at its data segment offset 0x200, calls the
DOS version service, and loops at offset 0x115.  The test reads and writes the
known bytes, and it stops at the loop.

The test runs the fixture and needs RE_DOSBOXX set to the DOSBox-X binary.
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
FIXTURE = Path(__file__).parent / "fixture" / "re_fixture.com"

LOOP_OFFSET = 0x115
DATA_OFFSET = 0x200


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "REFIX.COM")
        self.socket_path = self.work_dir / f"fixture_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"fixture_{os.getpid()}_{self._testMethodName}.env"
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
            [DOSBOXX, "-nogui", "-nopromptfolder", "-agent-config",
             str(self.config_path)],
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
        self.session = self.client.start("REFIX.COM", mount_path=self.runtime_dir)
        registers = self.client.get_registers(self.session.id)
        self.segment = int(registers.segments["cs"], 16)
        self.data_segment = int(registers.segments["ds"], 16)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def stop_at_loop(self) -> None:
        self.client.create_breakpoint(
            self.session.id, "execution",
            MemoryAddress.segmented(self.segment, LOOP_OFFSET))
        operation = self.client.continue_(self.session.id)
        wait = self.client.wait(self.session.id, operation.id, 10000)
        self.assertFalse(wait.running, "the target did not stop")

    def test_memory_read(self) -> None:
        """The fixture's known bytes are read at the data segment."""
        self.stop_at_loop()
        address = MemoryAddress.segmented(self.data_segment, DATA_OFFSET)
        read = self.client.read_memory(self.session.id, address, 3)
        self.assertEqual(read.data, b"\x41\x43\x42")

    def test_memory_write(self) -> None:
        """A memory write changes the value and the digest."""
        self.stop_at_loop()
        address = MemoryAddress.segmented(self.data_segment, DATA_OFFSET)
        before = self.client.read_memory(self.session.id, address, 1)
        written = self.client.write_memory(self.session.id, address, b"\x5a")
        self.assertEqual(written.byte_count, 1)
        self.assertNotEqual(written.after_sha256, written.before_sha256)
        after = self.client.read_memory(self.session.id, address, 1)
        self.assertEqual(after.data, b"\x5a")

    def test_breakpoint_at_loop(self) -> None:
        """The breakpoint stops at the loop, after the version call."""
        self.stop_at_loop()
        registers = self.client.get_registers(self.session.id)
        self.assertEqual(int(registers.instruction_pointer, 16), LOOP_OFFSET)


if __name__ == "__main__":
    unittest.main()
