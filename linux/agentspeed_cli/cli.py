"""Command-line entry point and live loop for the Linux terminal table."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path

from .model import ScanConfig, SOURCE_ORDER
from .render import render

SOURCE_ALIASES = {
    "claude": "claudeCode",
    "dsh": "deepseek",
    "grok": "grokBuild",
    "workbuddy-ai": "workbuddyAi",
}


class TerminalSession:
    """Alternate screen plus hidden cursor, restored on every exit path."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def __enter__(self):
        try:
            self.stream.write("\x1b[?1049h\x1b[?25l")
            self.stream.flush()
        except OSError:
            pass
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.stream.write("\x1b[?25h\x1b[?1049l")
            self.stream.flush()
        except OSError:
            pass
        return False


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentspeed",
        description="Live token speed of local AI agents, in a terminal table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between live frames")
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--ascii", action="store_true", help="use ASCII borders and symbols")
    parser.add_argument(
        "--sources",
        default=None,
        help="comma-separated sources (default: all): " + ", ".join(SOURCE_ORDER),
    )
    parser.add_argument("--prices", default=None, help="price table for today's cost")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--codex", default=None, help="Codex sessions folder")
    parser.add_argument("--claude", default=None, help="Claude projects folder")
    parser.add_argument("--dsh", default=None, help="DSH sessions folder")
    parser.add_argument("--opencode", default=None, help="OpenCode database or its folder")
    parser.add_argument("--gemini", action="append", default=None, help="Gemini CLI tmp folder (repeatable)")
    parser.add_argument("--omp", action="append", default=None, help="omp sessions folder (repeatable)")
    parser.add_argument(
        "--antigravity",
        action="append",
        default=None,
        help="Antigravity store or conversations folder (repeatable)",
    )
    parser.add_argument("--workbuddy", default=None, help="WorkBuddy data or projects folder")
    parser.add_argument("--workbuddy-ai", default=None, help="WorkBuddy AI data or projects folder")
    parser.add_argument("--zcode", default=None, help="ZCode data folder, database folder, or db.sqlite")
    parser.add_argument("--kimi", default=None, help="Kimi Code CLI sessions folder")
    parser.add_argument("--grok", default=None, help="Grok Build sessions folder")
    return parser


def _parse_sources(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset(SOURCE_ORDER)
    selected: set[str] = set()
    for part in value.split(","):
        key = part.strip()
        if not key:
            continue
        key = SOURCE_ALIASES.get(key, key)
        if key not in SOURCE_ORDER:
            raise ValueError(f"unknown source: {part.strip()}")
        selected.add(key)
    return frozenset(selected)


def _config_from_args(args, snapshot_module) -> ScanConfig:
    config = snapshot_module.default_scan_config()
    enabled = _parse_sources(args.sources)
    changes: dict = {}

    if args.codex:
        changes["codex_root"] = args.codex
    if args.claude:
        changes["claude_root"] = args.claude
    if args.dsh:
        changes["dsh_root"] = args.dsh
    if args.opencode:
        path = args.opencode
        if os.path.isdir(path):
            path = os.path.join(path, "opencode.db")
        changes["opencode_db"] = path
    if args.gemini is not None:
        changes["gemini_dirs"] = tuple(args.gemini)
    if args.omp is not None:
        changes["omp_dirs"] = tuple(args.omp)
    if args.antigravity is not None:
        changes["antigravity_stores"] = tuple(
            store
            for setting in args.antigravity
            for store in snapshot_module.reference.antigravity_stores(setting=setting)
        )
    if args.workbuddy is not None or args.workbuddy_ai is not None:
        changes["workbuddy_roots"] = tuple(
            snapshot_module.reference.workbuddy_roots(
                settings={"workbuddy": args.workbuddy, "workbuddyAi": args.workbuddy_ai}
            )
        )
    if args.zcode:
        changes["zcode_root"] = args.zcode
    if args.kimi:
        changes["kimi_root"] = args.kimi
    if args.grok:
        changes["grok_root"] = args.grok
    config = replace(config, **changes)

    if "codex" not in enabled:
        config = replace(config, codex_root=None)
    if "claudeCode" not in enabled and "claudeDesktop" not in enabled:
        config = replace(config, claude_root=None)
    if "deepseek" not in enabled:
        config = replace(config, dsh_root=None)
    if "opencode" not in enabled:
        config = replace(config, opencode_db=None)
    if "gemini" not in enabled:
        config = replace(config, gemini_dirs=())
    if "omp" not in enabled:
        config = replace(config, omp_dirs=())
    if "antigravity" not in enabled:
        config = replace(config, antigravity_stores=())
    if "workbuddy" not in enabled and "workbuddyAi" not in enabled:
        config = replace(config, workbuddy_roots=())
    else:
        config = replace(
            config,
            workbuddy_roots=tuple(
                (source, root)
                for source, root in config.workbuddy_roots
                if source in enabled
            ),
        )
    if "zcode" not in enabled:
        config = replace(config, zcode_root=None)
    if "kimi" not in enabled:
        config = replace(config, kimi_root=None)
    if "grokBuild" not in enabled:
        config = replace(config, grok_root=None)
    return replace(config, enabled_sources=enabled)


def _run_live(scanner, args) -> int:
    stop = False

    def handler(signum, frame):
        nonlocal stop
        stop = True

    previous = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):
            pass

    try:
        with TerminalSession(sys.stdout):
            sys.stdout.write("\x1b[H\x1b[2J")
            sys.stdout.flush()
            while not stop:
                started = time.monotonic()
                width = shutil.get_terminal_size((100, 24)).columns
                snapshot = scanner.scan()
                frame = render(
                    snapshot,
                    width=width,
                    color=not args.no_color,
                    ascii_only=args.ascii,
                    interval=args.interval,
                )
                sys.stdout.write("\x1b[H" + frame + "\x1b[J")
                sys.stdout.flush()
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, args.interval - elapsed))
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except Exception as exc:
        print(f"agentspeed: {exc}", file=sys.stderr)
        return 1
    finally:
        for sig, old in previous.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"agentspeed {_version()} (linux)")
        return 0
    if args.interval < 0.5:
        parser.error("--interval must be at least 0.5 seconds")
    try:
        _parse_sources(args.sources)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        from . import snapshot as snapshot_module
    except RuntimeError as exc:
        print(f"agentspeed: {exc}", file=sys.stderr)
        return 2

    try:
        config = _config_from_args(args, snapshot_module)
        scanner = snapshot_module.LiveScanner(config, args.prices)
    except Exception as exc:
        print(f"agentspeed: {exc}", file=sys.stderr)
        return 2

    if args.once or not sys.stdout.isatty():
        snapshot = scanner.scan()
        width = shutil.get_terminal_size((100, 24)).columns
        color = sys.stdout.isatty() and not args.no_color
        try:
            print(render(snapshot, width=width, color=color, ascii_only=args.ascii, interval=args.interval))
        except BrokenPipeError:
            return 0
        return 0
    return _run_live(scanner, args)
