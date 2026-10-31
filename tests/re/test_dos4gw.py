#!/usr/bin/env python3
"""Test the DOS/4GW INT 15h AX=BFDE services.

The fork answers two DOS/4GW services behind the [dos] dos4gw_api option: the
BX=000Ah host-present check returns AX=0000h with the sign bit clear, and the
BX=0015h CX=0005h call writes 0010h at the word ES:000Ah and the caller's CS at
the word ES:000Ch.  Every other call keeps the unknown-call behavior.

The fixture records the answers at 0x2000:0x300.  The test needs RE_DOSBOXX set to
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
FIXTURE = Path(__file__).parent / "fixture" / "re_int15.com"

RECORD_BASE = 0x20000
RECORD_OFFSET = 0x300
RECORD_LENGTH = 16
HOST_AX = 0x00
BUFFER_AX = 0x04
BUFFER_WORD_A = 0x06
BUFFER_WORD_C = 0x08
FIXTURE_CS = 0x0A
OTHER_AX = 0x0C

UNKNOWN_AH = 0x86


@unittest.skipUnless(os.environ.get("RE_DOSBOXX"), "RE_DOSBOXX is not set")
class Dos4gwTests(unittest.TestCase):
    _counter = 0

    def setUp(self) -> None:
        self.work_dir = WORK_DIR.resolve()
        self.runtime_dir = self.work_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, self.runtime_dir / "REINT15.COM")
        self.child = None
        self.client = None
        self.mcp = None
        self.session = None

    def tearDown(self) -> None:
        if self.client is not None:
            self.client.close()
        if self.mcp is not None:
            self.mcp.close()
        if self.child is not None:
            self.child.close()

    def start(self, off: bool = False) -> None:
        """Start the emulator and the session, with the option on or off."""
        Dos4gwTests._counter += 1
        name = f"d4g_{os.getpid()}_{Dos4gwTests._counter}"
        socket_path = self.work_dir / f"{name}.sock"
        if socket_path.exists():
            socket_path.unlink()
        config_path = self.work_dir / f"{name}.env"
        config_path.write_text(
            "\n".join(
                [
                    "transport=unix_socket",
                    f"endpoint={socket_path}",
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
        self.mcp = McpClient()
        emulator_config = self.work_dir / f"{name}.conf"
        lines = [
            "[dosbox]",
            f"mcp_server={self.mcp.port}",
            "memsize=16",
            "machine=svga_s3",
            "",
        ]
        if off:
            lines += ["[dos]", "dos4gw_api=false", ""]
        emulator_config.write_text("\n".join(lines))
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["TERM"] = "xterm-256color"
        self.child = PtyProcess(
            [DOSBOXX, "-nogui", "-nopromptfolder", "-conf",
             str(emulator_config), "-agent-config", str(config_path)],
            self.work_dir,
            env,
        )
        deadline = time.monotonic() + 30
        while not socket_path.exists():
            if time.monotonic() >= deadline:
                self.fail(
                    "the socket file did not appear: "
                    + self.child.text()[-300:]
                )
            time.sleep(0.1)
        self.mcp.accept()
        self.client = AgentClient(load_config(config_path))
        self.session = self.client.start("REINT15.COM", mount_path=self.runtime_dir)

    def run_and_read(self) -> bytes:
        """Run the fixture, then read its record."""
        self.client.continue_(self.session.id)
        time.sleep(0.3)
        pause = self.client.pause(self.session.id)
        wait = self.client.wait(self.session.id, pause.id, 10000)
        self.assertFalse(wait.running, "the target did not stop")
        return self.client.read_memory(
            self.session.id,
            MemoryAddress.linear(RECORD_BASE + RECORD_OFFSET),
            RECORD_LENGTH,
        ).data

    @staticmethod
    def word(record: bytes, offset: int) -> int:
        return int.from_bytes(record[offset : offset + 2], "little")

    def test_host_present_check_answers(self) -> None:
        """The BX=000Ah host-present check returns an AX with the sign bit clear."""
        self.start(off=False)
        record = self.run_and_read()
        self.assertEqual(self.word(record, HOST_AX) & 0x8000, 0)

    def test_buffer_service_writes_the_words(self) -> None:
        """The BX=0015h CX=0005h call writes the two words."""
        self.start(off=False)
        record = self.run_and_read()
        self.assertEqual(self.word(record, BUFFER_WORD_A), 0x0010)
        self.assertEqual(
            self.word(record, BUFFER_WORD_C), self.word(record, FIXTURE_CS)
        )

    def test_other_functions_keep_the_unknown_call(self) -> None:
        """A BX=0000h call keeps the unknown-call return."""
        self.start(off=False)
        record = self.run_and_read()
        self.assertEqual(self.word(record, OTHER_AX) >> 8, UNKNOWN_AH)

    def test_disabled_option_keeps_the_unknown_call(self) -> None:
        """With the option off, both services keep the unknown call."""
        self.start(off=True)
        record = self.run_and_read()
        self.assertEqual(self.word(record, HOST_AX) >> 8, UNKNOWN_AH)
        self.assertEqual(self.word(record, BUFFER_AX) >> 8, UNKNOWN_AH)
        self.assertEqual(self.word(record, BUFFER_WORD_A), 0xDEAD)
        self.assertEqual(self.word(record, BUFFER_WORD_C), 0xBEEF)


if __name__ == "__main__":
    unittest.main()
