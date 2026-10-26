"""Shared data shapes for the Linux terminal table."""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_ORDER: tuple[str, ...] = (
    "codex",
    "claudeCode",
    "claudeDesktop",
    "deepseek",
    "opencode",
    "gemini",
    "omp",
    "antigravity",
    "workbuddy",
    "workbuddyAi",
    "zcode",
    "kimi",
    "grokBuild",
)

SOURCE_LABELS: dict[str, str] = {
    "codex": "Codex",
    "claudeCode": "Claude Code",
    "claudeDesktop": "Claude Desktop",
    "deepseek": "DSH",
    "opencode": "OpenCode",
    "gemini": "Gemini CLI",
    "omp": "omp",
    "antigravity": "Antigravity",
    "workbuddy": "WorkBuddy",
    "workbuddyAi": "WorkBuddy AI",
    "zcode": "ZCode",
    "kimi": "Kimi Code CLI",
    "grokBuild": "Grok Build",
}


@dataclass(frozen=True)
class AgentRow:
    id: str
    source: str
    project: str | None
    model: str | None
    phase: str
    live_output: float
    live_total: float
    today_output: int
    today_cost_micro: int
    today_unpriced: int
    is_subagent: bool
    parent_id: str | None
    last_line_ms: int | None


@dataclass(frozen=True)
class SourceRow:
    source: str
    live_output: float
    today_output: int
    today_cost_micro: int
    today_unpriced: int
    active_agents: int


@dataclass(frozen=True)
class Snapshot:
    now_ms: int
    today_start_ms: int
    live_output: float
    live_total: float
    estimated_share: float
    live_cost_micro_per_s: float
    live_cost_known_share: float
    today_output: int
    today_input: int
    today_requests: int
    today_cost_micro: int
    today_unpriced: int
    peak: float
    agents: tuple[AgentRow, ...]
    sources: tuple[SourceRow, ...]
    generating: int
    tools: int
    warnings: tuple[str, ...]
    scanned_files: int
    sources_available: bool


@dataclass(frozen=True)
class ScanConfig:
    codex_root: str | None = None
    claude_root: str | None = None
    dsh_root: str | None = None
    opencode_db: str | None = None
    gemini_dirs: tuple[str, ...] = ()
    omp_dirs: tuple[str, ...] = ()
    antigravity_stores: tuple[str, ...] = ()
    workbuddy_roots: tuple[tuple[str, str], ...] = ()
    zcode_root: str | None = None
    kimi_root: str | None = None
    grok_root: str | None = None
    enabled_sources: frozenset[str] = frozenset(SOURCE_ORDER)
