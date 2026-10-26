"""Width-aware ANSI table for the Linux terminal."""

from __future__ import annotations

import os
import time
import unicodedata
from dataclasses import dataclass

from .model import AgentRow, Snapshot, SOURCE_LABELS


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    return sum(_char_width(ch) for ch in text)


def truncate(text: str, width: int, ascii_only: bool = False) -> str:
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    ellipsis = "..." if ascii_only else "…"
    if display_width(ellipsis) >= width:
        return ellipsis[:width]
    limit = width - display_width(ellipsis)
    out: list[str] = []
    used = 0
    for ch in text:
        step = _char_width(ch)
        if used + step > limit:
            break
        out.append(ch)
        used += step
    return "".join(out) + ellipsis


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = width - display_width(text)
    if gap <= 0:
        return text
    return text + " " * gap if align == "left" else " " * gap + text


def _paint(text: str, code: str, color: bool) -> str:
    if not color or not code:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def format_tokens(value: int) -> str:
    value = max(0, int(value))
    if value < 1_000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1_000:.1f}k"
    return f"{value / 1_000_000:.1f}M"


def format_cost(micro_usd: int) -> str:
    return f"${max(0, int(micro_usd)) / 1_000_000:.2f}"


def format_speed(value: float) -> str:
    return f"{max(0.0, float(value)):.1f}"


def format_cost_rate(micro_usd_per_s: float) -> str:
    return f"${max(0.0, float(micro_usd_per_s)) / 1_000_000:.4f}/s"


@dataclass(frozen=True)
class _Column:
    key: str
    header: str
    width: int
    align: str = "left"


def _layout(width: int) -> list[_Column]:
    has_model = width >= 72
    has_cost = width > 60
    has_today = width >= 50
    has_phase = width >= 44
    source_w = 12 if width >= 72 else 10 if width >= 50 else 8
    model_w = 20 if width >= 90 else 18
    keys = ["source", "agent"]
    if has_model:
        keys.append("model")
    if has_phase:
        keys.append("phase")
    keys.append("speed")
    if has_today:
        keys.append("today")
    if has_cost:
        keys.append("cost")

    def fixed() -> int:
        return (
            source_w
            + (model_w if has_model else 0)
            + (7 if has_phase else 0)
            + 8
            + (10 if has_today else 0)
            + (10 if has_cost else 0)
        )

    def total(agent_w: int) -> int:
        return fixed() + agent_w + len(keys) + 1

    agent_w = max(6, width - (len(keys) + 1) - fixed())
    if total(agent_w) > width and has_model:
        model_w = max(10, model_w - (total(agent_w) - width))
        agent_w = max(6, width - (len(keys) + 1) - fixed())
    if total(agent_w) > width:
        source_w = max(6, source_w - (total(agent_w) - width))
        agent_w = max(6, width - (len(keys) + 1) - fixed())

    columns: list[_Column] = []
    for key in keys:
        if key == "source":
            columns.append(_Column("source", "SOURCE", source_w))
        elif key == "agent":
            columns.append(_Column("agent", "AGENT", agent_w))
        elif key == "model":
            columns.append(_Column("model", "MODEL", model_w))
        elif key == "phase":
            columns.append(_Column("phase", "PHASE", 7))
        elif key == "speed":
            columns.append(_Column("speed", "TOK/S", 8, "right"))
        elif key == "today":
            columns.append(_Column("today", "TODAY", 10, "right"))
        elif key == "cost":
            columns.append(_Column("cost", "COST", 10, "right"))
    return columns


def _short_id(agent_id: str, ascii_only: bool) -> str:
    name = agent_id[9:] if agent_id.startswith("opencode:") else agent_id
    name = os.path.basename(name)
    if name.endswith(".jsonl"):
        name = name[:-6]
    if len(name) > 18:
        name = name[:17] + ("..." if ascii_only else "…")
    return name


def _agent_label(row: AgentRow, ascii_only: bool) -> str:
    name = row.project or _short_id(row.id, ascii_only)
    if row.is_subagent or row.parent_id:
        name = ("  \\- " if ascii_only else "  └─ ") + name
    return name


def _phase_label(phase: str, ascii_only: bool) -> str:
    symbols = {"generating": "*" if ascii_only else "●", "tools": "+" if ascii_only else "●",
               "idle": "-" if ascii_only else "○"}
    labels = {"generating": "gen", "tools": "tools", "idle": "idle"}
    return f"{symbols.get(phase, '?')} {labels.get(phase, phase)}"


def _phase_color(phase: str) -> str:
    return {"generating": "32", "tools": "33", "idle": "2"}.get(phase, "")


def _speed_color(value: float) -> str:
    if value >= 50:
        return "31;1"
    if value >= 30:
        return "33"
    if value >= 10:
        return "32"
    return "2"


def _cell_text(row: AgentRow, key: str, ascii_only: bool) -> str:
    if key == "source":
        return SOURCE_LABELS.get(row.source, row.source)
    if key == "agent":
        return _agent_label(row, ascii_only)
    if key == "model":
        return row.model or ("-" if ascii_only else "—")
    if key == "phase":
        return _phase_label(row.phase, ascii_only)
    if key == "speed":
        return format_speed(row.live_output)
    if key == "today":
        return format_tokens(row.today_output)
    if key == "cost":
        return format_cost(row.today_cost_micro)
    return ""


def _cell_color(row: AgentRow, key: str) -> str:
    if key == "model":
        return "2"
    if key == "phase":
        return _phase_color(row.phase)
    if key == "speed":
        return _speed_color(row.live_output)
    return ""


def _border(widths: list[int], left: str, mid: str, right: str, horizontal: str) -> str:
    return left + mid.join(horizontal * width for width in widths) + right


def _row(cells: list[tuple[str, str]], columns: list[_Column], color: bool, ascii_only: bool) -> str:
    rendered: list[str] = []
    for (text, code), column in zip(cells, columns):
        padded = _pad(truncate(text, column.width, ascii_only), column.width, column.align)
        rendered.append(_paint(padded, code, color))
    separator = "|" if ascii_only else "│"
    return separator + separator.join(rendered) + separator


def _table(columns: list[_Column], rows: list[list[tuple[str, str]]], color: bool, ascii_only: bool) -> str:
    widths = [column.width for column in columns]
    if ascii_only:
        top = _border(widths, "+", "+", "+", "-")
        middle = _border(widths, "+", "+", "+", "-")
        bottom = top
    else:
        top = _border(widths, "┌", "┬", "┐", "─")
        middle = _border(widths, "├", "┼", "┤", "─")
        bottom = _border(widths, "└", "┴", "┘", "─")
    header = _row([(column.header, "1") for column in columns], columns, color, ascii_only)
    body = [_row(cells, columns, color, ascii_only) for cells in rows]
    return "\n".join([top, header, middle, *body, bottom])


def _source_lines(snapshot: Snapshot, width: int, ascii_only: bool, color: bool) -> list[str]:
    label = "BY SOURCE" if width < 50 else "TODAY BY SOURCE"
    if not snapshot.sources:
        return [_paint(f"{label}  no usage today", "2", color)]
    parts = [
        f"{SOURCE_LABELS.get(source.source, source.source)} {format_tokens(source.today_output)} "
        f"{format_cost(source.today_cost_micro)}"
        for source in snapshot.sources
    ]
    lines: list[str] = []
    current = label + "  "
    for part in parts:
        candidate = current + ("" if current.endswith("  ") else "   ") + part
        if display_width(candidate) <= width:
            current = candidate
        else:
            lines.append(current.rstrip())
            current = " " * (len(label) + 2) + part
    lines.append(current.rstrip())
    return [_paint(line, "2", color) for line in lines]


def _quit_line(width: int, interval: float, warnings: tuple[str, ...], ascii_only: bool, color: bool) -> str:
    separator = "  |  " if ascii_only else "  ·  "
    warning_text = ", ".join(warnings) if warnings else "none"
    text = f"Ctrl-C quit{separator}interval {interval:.1f}s{separator}warnings: {warning_text}"
    return _paint(truncate(text, width, ascii_only), "2", color)


def render(
    snapshot: Snapshot,
    width: int = 100,
    color: bool = True,
    ascii_only: bool = False,
    interval: float = 2.0,
) -> str:
    width = max(30, int(width))
    separator = "  |  " if ascii_only else "  ·  "
    clock = time.strftime("%H:%M:%S", time.localtime(snapshot.now_ms / 1000))
    header = separator.join(
        [
            "Agent Speed",
            f"live {format_speed(snapshot.live_output)} tok/s",
            f"today {format_tokens(snapshot.today_output)} out",
            format_cost(snapshot.today_cost_micro),
            f"{snapshot.generating} generating",
            clock,
        ]
    )
    lines = [_paint(truncate(header, width, ascii_only), "1", color)]

    if not snapshot.sources_available:
        lines.extend(
            [
                "",
                "No agent logs found. Start an agent or check the source paths with --help.",
                "",
                _quit_line(width, interval, snapshot.warnings, ascii_only, color),
            ]
        )
        return "\n".join(lines)

    if not snapshot.agents:
        lines.extend(
            [
                "",
                "No active agents in the last 10 minutes.",
                "",
                *_source_lines(snapshot, width, ascii_only, color),
                _quit_line(width, interval, snapshot.warnings, ascii_only, color),
            ]
        )
        return "\n".join(lines)

    columns = _layout(width)
    rows = [
        [(_cell_text(agent, column.key, ascii_only), _cell_color(agent, column.key)) for column in columns]
        for agent in snapshot.agents
    ]
    lines.extend(
        [
            _table(columns, rows, color, ascii_only),
            "",
            *_source_lines(snapshot, width, ascii_only, color),
            _quit_line(width, interval, snapshot.warnings, ascii_only, color),
        ]
    )
    return "\n".join(lines)
