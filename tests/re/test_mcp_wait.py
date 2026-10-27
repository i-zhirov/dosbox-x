#!/usr/bin/env python3
"""Test the MCP WAIT request.

WAIT returns at the next stop with the stop record, or TIMEOUT when the wait
expires.  A WAIT that arrives while the debugger is stopped returns at once.

The tests start the emulator and need RE_DOSBOXX set to the DOSBox-X binary.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_client import start_emulator  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class WaitTests(unittest.TestCase):
    def setUp(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.child, self.client = start_emulator(DOSBOXX, WORK_DIR)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()

    def test_wait_returns_at_stop(self) -> None:
        """The reply holds the stop record at the next stop."""
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        wait_id = self.client.send_request("WAIT", "30000")
        # A BREAK request stops the guest, so the wait completes with a stop.
        self.assertTrue(self.client.request("BREAK").ok)
        reply = self.client.read_until(
            lambda frame: frame.identifier == wait_id, 60)
        self.assertIsNotNone(reply, "no WAIT reply")
        stop = [line for line in reply.lines if line.startswith("STOP ")]
        self.assertTrue(stop, reply.lines)
        # The event for the same stop holds the same record.  The earlier
        # startup stop delivers its own event.
        event = self.client.read_until(
            lambda frame: frame.identifier == "event" and stop[0] in frame.lines, 10)
        self.assertIsNotNone(event, "no STOP event")

    def test_wait_times_out(self) -> None:
        """The reply holds TIMEOUT when the wait expires."""
        self.assertTrue(self.client.request("EXEC", "RUN").ok)
        response = self.client.request("WAIT", "300", timeout=30)
        self.assertTrue(response.ok)
        self.assertEqual(response.lines, ["TIMEOUT"])

    def test_wait_while_stopped(self) -> None:
        """The reply arrives at once while the debugger is stopped."""
        response = self.client.request("WAIT", "5000")
        self.assertTrue(response.ok)
        stop = [line for line in response.lines if line.startswith("STOP ")]
        self.assertTrue(stop, response.lines)

    def test_wait_parse_errors(self) -> None:
        """A missing and a bad timeout are errors."""
        missing = self.client.request("WAIT")
        self.assertFalse(missing.ok)
        self.assertIn("missing wait timeout", missing.text)
        bad = self.client.request("WAIT", "abc")
        self.assertFalse(bad.ok)
        self.assertIn("not a non-negative number", bad.text)


if __name__ == "__main__":
    unittest.main()
