#!/usr/bin/env python3
"""Test the agent Unix socket transport.

The agent channel answers on macOS through the Unix socket, the capabilities
report the protocol version and the feature flags, and a session call without a
session returns the typed error.

The tests need RE_DOSBOXX set to the DOSBox-X binary.
"""
from __future__ import annotations

import os
import stat
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "client" / "python"))
from dosbox_agent import AgentClient, SessionNotFoundError, load_config  # noqa: E402
from mcp_client import PtyProcess  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class AgentSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.socket_path = self.work_dir / f"agent_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"agent_{os.getpid()}_{self._testMethodName}.env"
        self.config_path.write_text(
            "\n".join(
                [
                    "transport=unix_socket",
                    f"endpoint={self.socket_path}",
                    f"dosbox_executable={Path(DOSBOXX).resolve()}",
                    f"dosbox_workdir={self.work_dir}",
                    "request_timeout_ms=5000",
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

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def test_socket_start(self) -> None:
        """The socket file exists with the 0600 mode."""
        self.assertTrue(self.socket_path.exists())
        mode = stat.S_IMODE(self.socket_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_capabilities(self) -> None:
        """The agent channel answers with the protocol version and the flags."""
        result = self.client.call("agent.capabilities")
        self.assertEqual(result["protocol_version"], "1.0")
        self.assertIn("debugger", result)
        self.assertIn("address_spaces", result)
        breakpoints = result["breakpoints"]
        self.assertTrue(breakpoints["memory_change"])
        self.assertIn("memory_change_address_spaces", breakpoints)

    def test_status(self) -> None:
        """A session call without a session returns the typed error."""
        with self.assertRaises(SessionNotFoundError) as caught:
            self.client.call("session.status", {"session_id": "missing"})
        self.assertEqual(caught.exception.reason, "SESSION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
