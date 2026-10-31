#!/usr/bin/env python3
"""Test the MCP stop events.

A code breakpoint hit delivers STOP breakpoint with the linear address, the
breakpoint id, and the condition result.  A CPU log count end delivers
STOP log_end, and a guest exit delivers STOP exit.

The live tests run the game and need RE_GAME_DIR set to the game directory and
RE_DOSBOXX set to the DOSBox-X binary.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_client import (  # noqa: E402
    McpClient,
    PtyProcess,
    start_game_emulator,
)

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
GAME_DIR = Path(os.environ.get("RE_GAME_DIR", ""))
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))

ENTRY_SELECTOR = "0150"
ENTRY_EIP = "1F20F8"


def stop_lines(frame) -> list[str]:
    return [line for line in frame.lines if line.startswith("STOP ")]


@unittest.skipUnless(os.environ.get("RE_GAME_DIR"), "RE_GAME_DIR is not set")
class StopEventTests(unittest.TestCase):
    def setUp(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.child, self.client = start_game_emulator(
            DOSBOXX, GAME_DIR, WORK_DIR)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()

    def test_breakpoint_event(self) -> None:
        """A code breakpoint hit delivers STOP breakpoint with the address."""
        self.assertTrue(self.client.request(
            "EXEC", f"BPX S:{ENTRY_SELECTOR}:{ENTRY_EIP}").ok)
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and any(
                line.startswith("STOP breakpoint") for line in frame.lines),
            120)
        self.assertIsNotNone(event, "no breakpoint event")
        fields = stop_lines(event)[0].split()
        self.assertEqual(fields[1], "breakpoint")
        self.assertNotEqual(int(fields[2], 16), 0)
        self.assertEqual(fields[3], "0")
        self.assertEqual(fields[4], "1")

    def test_selector_entry_breakpoint(self) -> None:
        """S:<selector>:* stops at the first instruction in the selector."""
        self.assertTrue(self.client.request(
            "EXEC", f"BPX S:{ENTRY_SELECTOR}:*").ok)
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and any(
                line.startswith("STOP breakpoint") for line in frame.lines),
            120)
        self.assertIsNotNone(event, "no breakpoint event")
        state = self.client.request("EXEC", "EV CS EIP")
        self.assertTrue(state.ok)
        fields = state.lines[-1].split()
        self.assertEqual(fields[0].upper(), ENTRY_SELECTOR.upper())
        self.assertEqual(fields[1].upper(), ENTRY_EIP.upper())

    def test_condition_event(self) -> None:
        """A conditional hit delivers the condition result 1."""
        self.assertTrue(self.client.request(
            "EXEC", f"BPX S:{ENTRY_SELECTOR}:{ENTRY_EIP} IF EAX==0").ok)
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and any(
                line.startswith("STOP breakpoint") for line in frame.lines),
            120)
        self.assertIsNotNone(event, "no breakpoint event")
        self.assertEqual(stop_lines(event)[0].split()[4], "1")

    def test_condition_skip(self) -> None:
        """A skipped hit delivers no stop, and the later stop arrives."""
        self.assertTrue(self.client.request(
            "EXEC", f"BPX S:{ENTRY_SELECTOR}:{ENTRY_EIP} IF EAX==1").ok)
        self.assertTrue(self.client.request("EXEC", "BPINT 21 30").ok)
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and any(
                line.startswith("STOP breakpoint") for line in frame.lines),
            120)
        self.assertIsNotNone(event, "no breakpoint event")
        # The version call stops, and the entry breakpoint has no hit.
        self.assertEqual(stop_lines(event)[0].split()[1], "breakpoint")
        listed = self.client.request("EXEC", "BPLIST")
        self.assertTrue(any("IF EAX==00000001 (hits 0)" in line
                            for line in listed.lines), listed.lines)

    def test_log_end_event(self) -> None:
        """A CPU log count end delivers STOP log_end."""
        self.assertTrue(self.client.request("EXEC", "LOGS 100").ok)
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and any(
                line.startswith("STOP log_end") for line in frame.lines),
            60)
        self.assertIsNotNone(event, "no log_end event")
        self.assertEqual(stop_lines(event)[0].split()[1], "log_end")


@unittest.skipUnless(os.environ.get("RE_GAME_DIR"), "RE_GAME_DIR is not set")
class ExitEventTests(unittest.TestCase):
    def test_exit_event(self) -> None:
        """A guest exit delivers STOP exit."""
        client = McpClient()
        work_dir = WORK_DIR.resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        config = work_dir / f"exit_{client.port}.conf"
        config.write_text(
            "\n".join(
                [
                    "[dosbox]",
                    f"mcp_server={client.port}",
                    "",
                    "[autoexec]",
                    "exit",
                    "",
                ]
            )
        )
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["TERM"] = "xterm-256color"
        child = PtyProcess(
            [DOSBOXX, "-nogui", "-break-start", "-exit",
             "-conf", str(config)],
            work_dir,
            env,
        )
        try:
            client.accept()
            self.assertTrue(client.request("EXEC", "RUN").ok)
            event = client.read_until(
                lambda frame: frame.identifier == "event" and any(
                    line.startswith("STOP exit") for line in frame.lines),
                30)
            self.assertIsNotNone(event, "no exit event")
            self.assertEqual(stop_lines(event)[0].split()[1], "exit")
        finally:
            client.close()
            child.close()


if __name__ == "__main__":
    unittest.main()
