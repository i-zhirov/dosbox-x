#!/usr/bin/env python3
"""Test the MCP frame robustness.

The success frame holds the line count, so a captured line cannot end the frame.
A capture above the line cap delivers the DROPPED line, and a close delivers the
BYE event with the reason.

The pure tests run everywhere.  The live tests start the emulator and need
RE_DOSBOXX set to the DOSBox-X binary.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Callable, Iterator

sys.path.insert(0, str(Path(__file__).parent))
from mcp_client import McpClient, PtyProcess, read_frame, start_emulator  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))


def reader_for(lines: list[str]) -> Callable[[], str]:
    iterator: Iterator[str] = iter(lines)
    return lambda: next(iterator)


class FrameTests(unittest.TestCase):
    def test_line_count(self) -> None:
        """A captured line that begins with END is read whole."""
        lines = ["BEGIN 7 OK 2", "END 5", "hello", "END 7"]
        frame = read_frame(reader_for(lines))
        self.assertEqual(frame.count, 2)
        self.assertEqual(frame.lines, ["END 5", "hello"])

    def test_error_frame_has_no_count(self) -> None:
        """An error frame holds no count, so the reader reads to END."""
        lines = ["BEGIN 8 ERR", "unknown request command", "END 8"]
        frame = read_frame(reader_for(lines))
        self.assertIsNone(frame.count)
        self.assertFalse(frame.ok)
        self.assertEqual(frame.lines, ["unknown request command"])


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class LiveFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.child, self.client = start_emulator(DOSBOXX, WORK_DIR)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()

    def test_line_count_live(self) -> None:
        """The success frame holds the count of the lines that follow."""
        response = self.client.request("EXEC", "HELP")
        self.assertTrue(response.ok)
        self.assertGreater(len(response.lines), 1)
        self.assertEqual(response.count, len(response.lines))

    def test_dropped_line_live(self) -> None:
        """A capture above the line cap holds the DROPPED line."""
        self.assertTrue(self.client.request("EXEC", "MEMFIND 0:0 20000").ok)
        response = self.client.request("EXEC", "MEMFIND L")
        dropped = [line for line in response.lines if line.startswith("DROPPED ")]
        self.assertTrue(dropped, response.text[-200:])
        self.assertGreater(int(dropped[0].split()[1]), 0)

    def test_bye_line_live(self) -> None:
        """A receive buffer overflow closes the connection with BYE."""
        payload = b"X" * (256 * 1024)
        for _ in range(8):
            try:
                self.client.send_raw(payload)
            except (BrokenPipeError, ConnectionResetError):
                break
        frame = self.client.read_frame()
        self.assertEqual(frame.identifier, "event")
        self.assertTrue(any(line.startswith("BYE ") for line in frame.lines),
                        frame.lines)

    def test_reconnect_live(self) -> None:
        """The emulator reconnects after the client drops the connection."""
        self.client.drop_connection()
        self.client.accept()
        response = self.client.request("PING")
        self.assertTrue(response.ok)
        self.assertEqual(response.lines, ["PONG"])


if __name__ == "__main__":
    unittest.main()
