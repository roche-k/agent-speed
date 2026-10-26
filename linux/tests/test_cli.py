import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentspeed_cli.cli import TerminalSession

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "linux" / "agentspeed"
TMP_ROOT = Path(__file__).resolve().parent / "tmp"


@contextmanager
def temp_dir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as directory:
        yield directory


def iso(ms):
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="milliseconds")


def write_codex_session(sessions, now, output=50, response_id="r1"):
    path = os.path.join(sessions, "rollout-test.jsonl")
    lines = [
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
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


def run_cli(*args, timeout=10):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "linux")
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
    )


class CliTests(unittest.TestCase):
    def test_help(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--interval", result.stdout)
        self.assertIn("--once", result.stdout)
        self.assertIn("--sources", result.stdout)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("agentspeed", result.stdout)
        self.assertIn((REPO_ROOT / "VERSION").read_text().strip(), result.stdout)

    def test_once_against_codex_log(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            os.makedirs(sessions)
            write_codex_session(sessions, int(time.time() * 1000))
            result = run_cli("--once", "--no-color", "--sources", "codex", "--codex", sessions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Codex", result.stdout)
        self.assertIn("gpt-test", result.stdout)
        self.assertIn("50", result.stdout)
        self.assertNotIn("\x1b[", result.stdout)

    def test_non_tty_runs_once(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            os.makedirs(sessions)
            write_codex_session(sessions, int(time.time() * 1000))
            result = run_cli("--no-color", "--sources", "codex", "--codex", sessions, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("Agent Speed"), 1)

    def test_sources_filter(self):
        with temp_dir() as directory:
            sessions = os.path.join(directory, "sessions")
            empty_claude = os.path.join(directory, "claude")
            os.makedirs(sessions)
            os.makedirs(empty_claude)
            write_codex_session(sessions, int(time.time() * 1000))
            result = run_cli(
                "--once",
                "--no-color",
                "--sources",
                "claude",
                "--codex",
                sessions,
                "--claude",
                empty_claude,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Codex", result.stdout)

    def test_terminal_session_restores_on_exception(self):
        stream = io.StringIO()
        with self.assertRaises(RuntimeError):
            with TerminalSession(stream):
                raise RuntimeError("boom")
        value = stream.getvalue()
        self.assertTrue(value.startswith("\x1b[?1049h\x1b[?25l"))
        self.assertTrue(value.endswith("\x1b[?25h\x1b[?1049l"))


if __name__ == "__main__":
    unittest.main()
