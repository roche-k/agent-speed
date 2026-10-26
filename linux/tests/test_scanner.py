import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentspeed_cli.model import ScanConfig, Snapshot
from agentspeed_cli import snapshot as snapshot_module
from agentspeed_cli.snapshot import LiveScanner

TMP_ROOT = Path(__file__).resolve().parent / "tmp"


@contextmanager
def temp_dir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as directory:
        yield directory


def iso(ms):
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="milliseconds")


def codex_lines(now, output=50, response_id="r1"):
    return [
        {
            "timestamp": iso(now - 3000),
            "type": "session_meta",
            "payload": {
                "id": "thread-1",
                "cwd": "/tmp/proj",
                "model_provider": "openai",
                "source": "cli",
            },
        },
        {
            "timestamp": iso(now - 3000),
            "type": "turn_context",
            "payload": {"cwd": "/tmp/proj", "model": "gpt-test"},
        },
        {
            "timestamp": iso(now - 3000),
            "type": "event_msg",
            "payload": {"type": "task_started"},
        },
        {
            "timestamp": iso(now - 2000),
            "type": "response_item",
            "payload": {"type": "reasoning", "summary": []},
        },
        {
            "timestamp": iso(now - 1000),
            "type": "token_usage_record",
            "payload": {
                "thread_id": "thread-1",
                "response_id": response_id,
                "usage": {"input_tokens": 100, "output_tokens": output},
            },
        },
    ]


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")


def append_lines(path, lines):
    with open(path, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")


class ScannerTests(unittest.TestCase):
    def test_codex_incremental_and_reset(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            os.makedirs(sessions)
            path = os.path.join(sessions, "rollout-test.jsonl")
            now = int(time.time() * 1000)
            write_lines(path, codex_lines(now, output=50, response_id="r1"))

            scanner = LiveScanner(
                ScanConfig(codex_root=sessions, enabled_sources=frozenset({"codex"}))
            )
            snap = scanner.scan(now)
            self.assertEqual(snap.today_output, 50)
            self.assertEqual(len(snap.agents), 1)
            self.assertEqual(snap.agents[0].source, "codex")
            self.assertEqual(snap.agents[0].model, "gpt-test")
            self.assertTrue(snap.sources_available)

            append_lines(
                path,
                [
                    {
                        "timestamp": iso(now + 1000),
                        "type": "token_usage_record",
                        "payload": {
                            "thread_id": "thread-1",
                            "response_id": "r2",
                            "usage": {"input_tokens": 10, "output_tokens": 25},
                        },
                    }
                ],
            )
            snap = scanner.scan(now + 1000)
            self.assertEqual(snap.today_output, 75)

            write_lines(path, codex_lines(now + 2000, output=30, response_id="r3"))
            snap = scanner.scan(now + 2000)
            self.assertEqual(snap.today_output, 30)

    def test_missing_zstd_is_a_warning(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            os.makedirs(sessions)
            now = int(time.time() * 1000)
            write_lines(os.path.join(sessions, "rollout-test.jsonl"), codex_lines(now))
            with open(os.path.join(sessions, "rollout-compressed.jsonl.zst"), "wb") as handle:
                handle.write(b"not zstd")

            real_process_file = snapshot_module.reference.process_file

            def process_file(state, dedupe):
                if state.path.endswith(".zst"):
                    raise FileNotFoundError("zstd")
                return real_process_file(state, dedupe)

            scanner = LiveScanner(
                ScanConfig(codex_root=sessions, enabled_sources=frozenset({"codex"}))
            )
            with patch.object(snapshot_module.reference, "process_file", side_effect=process_file):
                snap = scanner.scan(now)
            self.assertIsInstance(snap, Snapshot)
            self.assertTrue(any("zstd" in warning for warning in snap.warnings))
            self.assertEqual(snap.today_output, 50)

    def test_source_filter_excludes_codex(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            os.makedirs(sessions)
            now = int(time.time() * 1000)
            write_lines(os.path.join(sessions, "rollout-test.jsonl"), codex_lines(now))

            scanner = LiveScanner(
                ScanConfig(codex_root=sessions, enabled_sources=frozenset({"claudeCode"}))
            )
            snap = scanner.scan(now)
            self.assertEqual(snap.today_output, 0)
            self.assertEqual(snap.agents, ())


if __name__ == "__main__":
    unittest.main()
