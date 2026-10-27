#!/usr/bin/env python3
"""Test the memory commands and the LOG fix.

MEMFIND accepts a byte sequence, a quoted string, and the ?? wildcard.  IV names a
memory address, VV reads the contents, SMV reports a failed write, and MEMS fixes
the range over-read.  LOG flushes the file and LOG STOP ends it.

The test starts the emulator with both the agent config and the MCP server, so it can
drive the debugger commands.  It needs RE_DOSBOXX set to the DOSBox-X binary.
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
from dosbox_agent import AgentClient, load_config  # noqa: E402
from mcp_client import McpClient, PtyProcess  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))
FIXTURE = Path(__file__).parent / "fixture" / "re_loop.com"


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class MemoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "RELOOP.COM")
        log_path = self.work_dir / "LOGCPU.TXT"
        if log_path.exists():
            log_path.unlink()
        self.socket_path = self.work_dir / f"memory_{os.getpid()}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"memory_{os.getpid()}.env"
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
        self.mcp_port = 9898
        self.emulator_config = self.work_dir / f"memory_{os.getpid()}.conf"
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
        self.mcp = McpClient(self.mcp_port)
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

    def tearDown(self) -> None:
        self.client.close()
        self.mcp.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def test_memfind_string(self) -> None:
        """MEMFIND finds the written byte sequence and reports every hit."""
        self.mcp.request("EXEC", "SMV 200 41 43 42")
        output = self.mcp.request("EXEC", "MEMFIND 41 43 42").text
        self.assertIn("Hit 1 at linear 00000200", output)

    def test_memfind_wildcard(self) -> None:
        """MEMFIND finds the sequence with the ?? wildcard."""
        self.mcp.request("EXEC", "SMV 210 41 99 42")
        output = self.mcp.request("EXEC", "MEMFIND 41 ?? 42").text
        self.assertIn("00000210", output)

    def test_vv(self) -> None:
        """IV names the address and VV reads the contents."""
        self.mcp.request("EXEC", "SMV 220 41 43 42")
        output = self.mcp.request("EXEC", "IV 22:0 v").text
        self.assertIn("linear 00000220", output)
        output = self.mcp.request("EXEC", "VV v").text
        self.assertIn("00424341", output)

    def test_smv_failure(self) -> None:
        """A write to an unmapped address is reported."""
        output = self.mcp.request("EXEC", "SMV 10000000 41").text
        self.assertIn("Memory write failed", output)

    def test_log_stop(self) -> None:
        """LOG STOP ends the log, and the file holds complete lines."""
        self.mcp.request("EXEC", "LOG 1000000")
        self.client.continue_(self.session.id)
        time.sleep(0.5)
        pause = self.client.pause(self.session.id)
        self.client.wait(self.session.id, pause.id, 10000)
        output = self.mcp.request("EXEC", "LOG STOP").text
        self.assertIn("stopped", output)
        log_path = self.work_dir / "LOGCPU.TXT"
        self.assertTrue(log_path.exists(), "no log file")
        data = log_path.read_text()
        self.assertTrue(data, "empty log file")
        self.assertTrue(data.endswith("\n"), "incomplete log file")


if __name__ == "__main__":
    unittest.main()
