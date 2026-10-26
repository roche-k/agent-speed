import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentspeed_cli.tail import Tail

TMP_ROOT = Path(__file__).resolve().parent / "tmp"


@contextmanager
def temp_dir():
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as directory:
        yield directory


def write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def append(path, data):
    with open(path, "ab") as handle:
        handle.write(data)


class TailTests(unittest.TestCase):
    def test_append_and_partial_line(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'{"a":1}\n{"b":2}\n')
            tail = Tail()
            self.assertEqual(tail.read(path), [b'{"a":1}', b'{"b":2}'])
            self.assertEqual(tail.read(path), [])
            append(path, b'{"c":3}\n{"d":')
            self.assertEqual(tail.read(path), [b'{"c":3}'])
            self.assertEqual(tail.read(path), [])
            append(path, b'4}\n')
            self.assertEqual(tail.read(path), [b'{"d":4}'])

    def test_truncate_resets(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'{"a":1}\n{"b":2}\n')
            tail = Tail()
            tail.read(path)
            write(path, b'{"c":3}\n')
            self.assertEqual(tail.read(path), [b'{"c":3}'])
            self.assertTrue(tail.reset)

    def test_rewrite_to_longer_resets(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'{"a":1}\n')
            tail = Tail()
            tail.read(path)
            write(path, b'{"b":2}\n{"c":3}\n{"d":4}\n')
            self.assertEqual(tail.read(path), [b'{"b":2}', b'{"c":3}', b'{"d":4}'])
            self.assertTrue(tail.reset)

    def test_start_at_skips_partial_first_line(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'{"a":1}\n{"b":2}\n{"c":3}\n')
            tail = Tail()
            tail.start_at(path, 3)
            self.assertEqual(tail.read(path), [b'{"b":2}', b'{"c":3}'])

    def test_start_at_line_boundary_keeps_first_line(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'{"a":1}\n{"b":2}\n')
            tail = Tail()
            tail.start_at(path, 8)
            self.assertEqual(tail.read(path), [b'{"b":2}'])

    def test_blank_and_oversized_lines_are_skipped(self):
        with temp_dir() as directory:
            path = os.path.join(directory, "a.jsonl")
            write(path, b'\n{"a":1}\n' + b"x" * (32 * 1024 * 1024 + 1) + b"\n")
            tail = Tail()
            self.assertEqual(tail.read(path), [b'{"a":1}'])


if __name__ == "__main__":
    unittest.main()
