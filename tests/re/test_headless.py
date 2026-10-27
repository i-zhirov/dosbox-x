#!/usr/bin/env python3
"""Test the headless mode.

With `mcp_server` set and no terminal, the debugger commands and the control
channel work, and the ncurses interface does not draw.  With `mcp_server` zero
and no terminal, the debugger reports the guard and the process stays up.

The tests need RE_DOSBOXX set to the DOSBox-X binary.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_client import start_headless_emulator  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))
GUARD = "not available unless you start DOSBox-X from a terminal"


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class HeadlessTests(unittest.TestCase):
    def setUp(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)

    def test_headless_commands(self) -> None:
        """The debugger commands answer with no terminal when mcp_server is set."""
        child, client = start_headless_emulator(DOSBOXX, WORK_DIR)
        try:
            self.assertFalse(os.isatty(child.process.stdin.fileno()))
            cpu = client.request("EXEC", "CPU")
            self.assertTrue(cpu.ok)
            self.assertTrue(any("cr0:" in line for line in cpu.lines),
                            cpu.lines)
            state = client.request("EXEC", "EV CS EIP")
            self.assertTrue(state.ok)
            self.assertTrue(any(line.startswith("f000") for line in state.lines),
                            state.lines)
            self.assertNotIn(GUARD, child.text())
        finally:
            client.close()
            child.close()

    def test_no_tty_guard(self) -> None:
        """With mcp_server zero and no terminal, the guard reports and the
        process stays up."""
        child, _ = start_headless_emulator(DOSBOXX, WORK_DIR, mcp_server=False)
        try:
            self.assertTrue(child.wait_for(GUARD, 30), child.text()[-300:])
            self.assertIsNone(child.process.poll())
        finally:
            child.close()

    def test_headless_log(self) -> None:
        """The emulator log holds the command output."""
        child, client = start_headless_emulator(DOSBOXX, WORK_DIR)
        try:
            self.assertTrue(client.request("EXEC", "CPU").ok)
            self.assertTrue(child.wait_for("cr0:", 10), child.text()[-300:])
        finally:
            client.close()
            child.close()


if __name__ == "__main__":
    unittest.main()
