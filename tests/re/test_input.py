#!/usr/bin/env python3
"""Test the key and mouse injection.

KEY pushes a key into the BIOS key buffer and MOUSE drives the mouse state.  The
fixture records the key and the mouse state in its data segment, and the test reads
the record.

The test runs the input fixture and needs RE_DOSBOXX set to the DOSBox-X binary.
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
FIXTURE = Path(__file__).parent / "fixture" / "re_input.com"

RECORD_BASE = 0x20000
KEY_OFFSET = 0x300
BUTTON_OFFSET = 0x304
MOUSE_X_OFFSET = 0x306
MOUSE_Y_OFFSET = 0x308
POLL_AXIS_OFFSET = 0x30C


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class InputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "REFIN.COM")
        self.socket_path = self.work_dir / f"input_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"input_{os.getpid()}_{self._testMethodName}.env"
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
        self.session = self.client.start("REFIN.COM", mount_path=self.runtime_dir)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def run_and_stop(self, seconds: float = 0.5) -> None:
        """Run the guest for a moment, then stop it.

        The fixture resets the mouse driver at its start, so the injection happens
        after the guest has started.
        """
        self.client.continue_(self.session.id)
        time.sleep(seconds)
        pause = self.client.pause(self.session.id)
        wait = self.client.wait(self.session.id, pause.id, 10000)
        self.assertFalse(wait.running, "the target did not stop")

    def read_record(self, offset: int, length: int) -> bytes:
        return self.client.read_memory(
            self.session.id,
            MemoryAddress.linear(RECORD_BASE + offset),
            length,
        ).data

    def test_key(self) -> None:
        """The injected key reaches the BIOS key buffer."""
        self.run_and_stop(0.2)
        result = self.client.input_key(self.session.id, text="1")
        self.assertEqual(result["injected"], 1)
        self.run_and_stop()
        self.assertEqual(self.read_record(KEY_OFFSET, 1), b"1")

    def test_mouse(self) -> None:
        """The injected move and click reach the mouse state."""
        move = self.client.input_mouse(self.session.id, "move", x=96, y=48)
        self.assertEqual(move["action"], "move")
        self.run_and_stop(0.2)
        move = self.client.input_mouse(self.session.id, "move", x=96, y=48)
        self.assertEqual(move["action"], "move")
        self.assertEqual(move["x"], 96)
        click = self.client.input_mouse(self.session.id, "click", button=1)
        self.assertEqual(click["button"], 1)
        self.run_and_stop()
        # The guest reaches the mouse poll.  The poll axis is 3.
        self.assertEqual(
            int.from_bytes(self.read_record(POLL_AXIS_OFFSET, 2), "little"), 3
        )

    def test_key_stop(self) -> None:
        """A key stop is reported."""
        result = self.client.input_key(self.session.id, stop=True)
        self.assertTrue(result["stopped"])


if __name__ == "__main__":
    unittest.main()
