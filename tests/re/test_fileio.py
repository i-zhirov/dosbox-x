#!/usr/bin/env python3
"""Test the file-I/O recorder.

The recorder writes one JSON object per line with the event, the name, the
handle, the offset, and the count.  A stop ends the trace.

The test runs the file-I/O fixture and needs RE_DOSBOXX set to the DOSBox-X
binary.
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
FIXTURE = Path(__file__).parent / "fixture" / "re_fileio.com"


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class FileIoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "REFIO.COM")
        self.trace_path = self.work_dir / "fileio.jsonl"
        if self.trace_path.exists():
            self.trace_path.unlink()
        self.socket_path = self.work_dir / f"fileio_{os.getpid()}_{self._testMethodName}.sock"
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.config_path = self.work_dir / f"fileio_{os.getpid()}_{self._testMethodName}.env"
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
        self.session = self.client.start("REFIO.COM", mount_path=self.runtime_dir)

    def tearDown(self) -> None:
        self.client.close()
        self.child.close()
        if self.socket_path.exists():
            self.socket_path.unlink()

    def run_and_stop(self) -> None:
        """Run the fixture's file calls, then stop the guest."""
        self.client.fileio_start(self.session.id, self.trace_path)
        self.client.continue_(self.session.id)
        time.sleep(0.5)
        self.client.pause(self.session.id)

    def test_fileio_start(self) -> None:
        """The trace holds the open and the read of REFIO.COM."""
        self.run_and_stop()
        page = self.client.fileio_read(self.session.id, limit=100)
        records = page["records"]
        self.assertTrue(records, "no records")
        self.assertTrue(self.trace_path.exists())
        opened = [
            r for r in records
            if r["event"] == "open" and r["name"] == "REFIO.COM"
        ]
        self.assertTrue(opened, records)
        read = [
            r for r in records
            if r["event"] == "read" and r["name"] == "REFIO.COM"
        ]
        self.assertTrue(read, records)
        self.assertEqual(read[0]["count"], 8)
        self.assertEqual(read[0]["offset"], 0)

    def test_fileio_stop(self) -> None:
        """A stop ends the trace, and the file holds one record per line."""
        self.run_and_stop()
        count = self.client.fileio_stop(self.session.id)
        self.assertGreater(count, 0)
        lines = self.trace_path.read_text().splitlines()
        self.assertEqual(len(lines), count)
        self.assertTrue(all(line.startswith("{") for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
