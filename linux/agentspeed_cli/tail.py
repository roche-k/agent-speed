"""Incremental reader for plain JSONL transcripts.

The reference engine's `read_lines` assumes a byte offset in the middle of a file and
skips the first (possibly partial) line. The live table instead keeps the offset after
the last complete newline, so a half-written line is held until its newline arrives.
"""

from __future__ import annotations

import os

# METRICS 3.6: a line longer than 32 MiB is not a transcript line. Keep the same bound
# as reference.py without importing the engine from this low-level module.
MAX_LINE = 32 * 1024 * 1024


class Tail:
    def __init__(self) -> None:
        self.offset = 0
        self.identity: tuple[int, int] | None = None
        self.mtime_ns = 0
        self.reset = False

    def read(self, path: str) -> list[bytes]:
        stat = os.stat(path)
        identity = (stat.st_dev, stat.st_ino)
        self.reset = False
        if self.identity is None:
            self.identity = identity
            self.offset = 0
        elif (
            identity != self.identity
            or stat.st_size < self.offset
            or (stat.st_size == self.offset and stat.st_mtime_ns != self.mtime_ns)
        ):
            self.reset = True
            self.identity = identity
            self.offset = 0
        self.mtime_ns = stat.st_mtime_ns

        with open(path, "rb") as handle:
            handle.seek(self.offset)
            data = handle.read()
        end = data.rfind(b"\n")
        if end < 0:
            return []
        chunk = data[: end + 1]
        self.offset += len(chunk)
        return [line for line in chunk.split(b"\n")[:-1] if line.strip() and len(line) <= MAX_LINE]

    def start_at(self, path: str, offset: int) -> None:
        """Start reading at `offset`, discarding a partial line unless `offset` is a line boundary."""
        stat = os.stat(path)
        with open(path, "rb") as handle:
            if offset > 0:
                handle.seek(offset - 1)
                previous = handle.read(1)
                handle.seek(offset)
                if previous != b"\n":
                    handle.readline()
            else:
                handle.seek(0)
            self.offset = handle.tell()
        self.identity = (stat.st_dev, stat.st_ino)
        self.mtime_ns = stat.st_mtime_ns
        self.reset = False
