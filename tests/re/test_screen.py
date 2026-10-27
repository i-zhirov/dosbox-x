#!/usr/bin/env python3
"""Test the screen capture.

SCREEN TEXT writes the 25 text rows from B800:0, and SCREEN IMAGE schedules the
rendered frame as a PNG through the capture path.

The test runs the screen fixture and needs RE_DOSBOXX set to the DOSBox-X binary.
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
from mcp_client import PtyProcess  # noqa: E402

DOSBOXX = os.environ.get("RE_DOSBOXX", "dosbox-x")
WORK_DIR = Path(os.environ.get("RE_WORK_DIR", "work/re-tests"))
FIXTURE = Path(__file__).parent / "fixture" / "re_screen.com"

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class ScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "RESCR.COM")
        self.socket_path = self.work_dir / f"screen_{os.getpid()}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"screen_{os.getpid()}.env"
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
        self.session = self.client.start("RESCR.COM", mount_path=self.runtime_dir)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def run_and_stop(self, seconds: float = 0.5) -> None:
        """Run the fixture for a moment, then stop the guest."""
        self.client.continue_(self.session.id)
        time.sleep(seconds)
        pause = self.client.pause(self.session.id)
        wait = self.client.wait(self.session.id, pause.id, 10000)
        self.assertFalse(wait.running, "the target did not stop")

    def test_screen_text(self) -> None:
        """The text capture holds the 25 rows with the known characters."""
        self.run_and_stop(0.2)
        path = self.work_dir / "screen.txt"
        if path.exists():
            path.unlink()
        result = self.client.screen_capture(self.session.id, "text", path)
        self.assertEqual(result["mode"], "text")
        self.assertEqual(result["rows"], 25)
        self.assertEqual(result["columns"], 80)
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 25)
        self.assertEqual(lines[0][0], "A")
        self.assertEqual(lines[1][0], "B")
        self.assertTrue(all(len(line) == 80 for line in lines), lines)

    def test_screen_image(self) -> None:
        """The image capture writes a PNG."""
        path = self.work_dir / "screen.png"
        if path.exists():
            path.unlink()
        result = self.client.screen_capture(self.session.id, "image", path)
        self.assertEqual(result["mode"], "image")
        self.run_and_stop()
        self.assertTrue(path.exists(), "no image file")
        self.assertEqual(path.read_bytes()[:8], PNG_HEADER)


if __name__ == "__main__":
    unittest.main()
