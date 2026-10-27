#!/usr/bin/env python3
"""Test the coverage recorder.

The recorder sets one bit per executed byte over a linear range.  The dump writes
the covered ranges, the stats report the covered count, and a reset clears the
record.

The test starts the emulator with both the agent config and the MCP server, so it
can drive the agent methods and the debugger commands.  It needs RE_DOSBOXX set to
the DOSBox-X binary.
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
from mcp_client import McpClient, PtyProcess  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))
FIXTURE = Path(__file__).parent / "fixture" / "re_loop.com"

# The fixture's code segment range, in bytes, and its loop offset.
CODE_LENGTH = 0x200
LOOP_OFFSET = 0x106


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "RELOOP.COM")
        self.socket_path = self.work_dir / f"coverage_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"coverage_{os.getpid()}_{self._testMethodName}.env"
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
        # The emulator config carries the MCP port for the debugger commands.
        # A free port, so a previous emulator cannot hold it.
        self.mcp = McpClient()
        self.mcp_port = self.mcp.port
        self.emulator_config = self.work_dir / "coverage.conf"
        self.emulator_config.write_text(
            "\n".join(
                [
                    "[dosbox]",
                    f"mcp_server={self.mcp_port}",
                    "memsize=16",
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
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["TERM"] = "xterm-256color"
        self.child = PtyProcess(
            [DOSBOXX, "-nogui", "-nopromptfolder", "-conf",
             str(self.emulator_config), "-agent-config", str(self.config_path)],
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
        self.mcp.accept()
        self.client = AgentClient(load_config(self.config_path))
        self.session = self.client.start("RELOOP.COM", mount_path=self.runtime_dir)
        registers = self.client.get_registers(self.session.id)
        self.segment = int(registers.segments["cs"], 16)
        self.linear = self.segment << 4

    def tearDown(self) -> None:
        self.client.close()
        self.mcp.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def run_and_stop(self) -> None:
        """Run the fixture's loop, then stop it."""
        self.client.coverage_start(
            self.session.id, MemoryAddress.linear(self.linear), CODE_LENGTH)
        operation = self.client.continue_(self.session.id)
        time.sleep(0.5)
        self.client.pause(self.session.id)

    def test_coverage_start(self) -> None:
        """The record reports a covered byte count and the ranges."""
        self.run_and_stop()
        coverage = self.client.coverage_read(self.session.id)
        self.assertGreater(coverage["covered"], 0)
        self.assertEqual(coverage["start"], self.linear)
        self.assertEqual(coverage["length"], CODE_LENGTH)
        ranges = coverage["ranges"]
        self.assertTrue(ranges, "no covered range")
        self.assertTrue(
            any(r["start"] <= self.linear + LOOP_OFFSET <= r["end"] for r in ranges),
            ranges,
        )

    def test_coverage_dump(self) -> None:
        """The dump writes a range that covers the fixture's entry."""
        self.run_and_stop()
        dump_path = self.work_dir / "coverage_dump.txt"
        response = self.mcp.request("EXEC", f"COVER DUMP {dump_path}")
        self.assertTrue(response.ok)
        self.assertTrue(dump_path.exists())
        ranges = dump_path.read_text().splitlines()
        self.assertTrue(ranges, "the dump is empty")
        self.assertTrue(
            any(
                int(line.split("-")[0], 16) <= self.linear + LOOP_OFFSET
                <= int(line.split("-")[1], 16)
                for line in ranges
                if "-" in line
            ),
            ranges,
        )

    def test_coverage_reset(self) -> None:
        """A reset clears the covered byte count."""
        self.run_and_stop()
        self.assertTrue(self.client.coverage_read(self.session.id)["covered"] > 0)
        self.assertTrue(self.mcp.request("EXEC", "COVER RESET").ok)
        stats = self.mcp.request("EXEC", "COVER STATS")
        self.assertTrue(any("covered 0 of" in line for line in stats.lines),
                        stats.lines)


if __name__ == "__main__":
    unittest.main()
