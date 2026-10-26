"""Live snapshot construction on top of the shared spec engine."""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

from .model import AgentRow, ScanConfig, Snapshot, SourceRow, SOURCE_ORDER


class EngineUnavailable(RuntimeError):
    """The spec engine could not be found next to this checkout."""


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = Path(os.environ.get("AGENT_SPEED_SPEC") or (REPO_ROOT / "spec"))
TOOLS_DIR = SPEC_DIR / "tools"

if not (TOOLS_DIR / "reference.py").is_file():
    raise EngineUnavailable(
        "Agent Speed's spec engine was not found. Run the CLI from a repository checkout, "
        "or set AGENT_SPEED_SPEC to the spec directory."
    )

sys.dont_write_bytecode = True
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import harness_reference as harness  # noqa: E402
import prices  # noqa: E402
import reference  # noqa: E402

_DEFAULT_INDEX: prices.Index | None = None


def _default_index() -> prices.Index:
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is None:
        _DEFAULT_INDEX = prices.Index(prices.load(prices.TABLE))
    return _DEFAULT_INDEX


def _effective_phase(agent: dict, now_ms: int) -> str:
    phase = agent.get("phase") or "idle"
    last_line = agent.get("lastLineMs")
    if phase == "generating" and last_line is not None and now_ms - last_line > 300_000:
        return "idle"
    return phase


def _today_totals(responses: list[dict], today_start_ms: int) -> tuple[int, int, int]:
    today = [response for response in responses if response["endMs"] >= today_start_ms]
    output = sum(response["output"] for response in today)
    cost = sum(
        response["costMicroUsd"] for response in today if response.get("costMicroUsd") is not None
    )
    unpriced = sum(
        response.get("requestCount", 1) for response in today if response.get("costMicroUsd") is None
    )
    return output, cost, unpriced


def build_snapshot(
    responses: list[dict],
    agents: list[dict],
    now_ms: int,
    today_start_ms: int,
    warnings: tuple[str, ...] = (),
    scanned_files: int = 0,
    price_index: prices.Index | None = None,
) -> Snapshot:
    priced: list[dict] = []
    index = price_index
    for response in responses:
        response = dict(response)
        if "costMicroUsd" not in response:
            if index is None:
                index = _default_index()
            response["costMicroUsd"] = (
                index.price(response) if reference.has_day(response["endMs"]) else None
            )
        priced.append(response)
    responses = priced

    live_output, live_total, estimated_share = reference.live_rate(responses, agents, now_ms)
    live_cost, known_share = reference.live_cost(responses, agents, now_ms)
    stats = reference.today_stats(responses, today_start_ms, now_ms)
    order, parent_map = reference.agent_list(responses, agents, now_ms)

    by_agent: dict[str, list[dict]] = defaultdict(list)
    for response in responses:
        by_agent[response["agentId"]].append(response)
    by_id = {agent["id"]: agent for agent in agents}

    rows: list[AgentRow] = []
    for agent_id in order:
        agent = by_id.get(agent_id)
        if agent is None:
            continue
        phase = _effective_phase(agent, now_ms)
        live_agent = dict(agent)
        live_agent["phase"] = phase
        agent_live, agent_total, _ = reference.live_rate(by_agent[agent_id], [live_agent], now_ms)
        today_output, today_cost, today_unpriced = _today_totals(
            by_agent[agent_id], today_start_ms
        )
        rows.append(
            AgentRow(
                id=agent_id,
                source=agent.get("source") or "",
                project=agent.get("project"),
                model=agent.get("model"),
                phase=phase,
                live_output=agent_live,
                live_total=agent_total,
                today_output=today_output,
                today_cost_micro=today_cost,
                today_unpriced=today_unpriced,
                is_subagent=bool(agent.get("isSubagent")),
                parent_id=parent_map.get(agent_id),
                last_line_ms=agent.get("lastLineMs"),
            )
        )

    source_rows: list[SourceRow] = []
    for source in SOURCE_ORDER:
        source_responses = [response for response in responses if response["source"] == source]
        source_agents = [agent for agent in agents if agent.get("source") == source]
        source_live = (
            reference.live_rate(source_responses, source_agents, now_ms)[0]
            if source_responses or source_agents
            else 0.0
        )
        today_output, today_cost, today_unpriced = _today_totals(
            source_responses, today_start_ms
        )
        if today_output == 0 and source_live == 0:
            continue
        source_rows.append(
            SourceRow(
                source=source,
                live_output=source_live,
                today_output=today_output,
                today_cost_micro=today_cost,
                today_unpriced=today_unpriced,
                active_agents=sum(
                    1 for agent in source_agents if _effective_phase(agent, now_ms) == "generating"
                ),
            )
        )

    generating = sum(1 for agent in agents if _effective_phase(agent, now_ms) == "generating")
    tools = sum(1 for agent in agents if _effective_phase(agent, now_ms) == "tools")

    return Snapshot(
        now_ms=now_ms,
        today_start_ms=today_start_ms,
        live_output=live_output,
        live_total=live_total,
        estimated_share=estimated_share,
        live_cost_micro_per_s=live_cost,
        live_cost_known_share=known_share,
        today_output=stats["output"],
        today_input=stats["input"],
        today_requests=stats["requests"],
        today_cost_micro=stats["cost"],
        today_unpriced=stats["unpriced"],
        peak=stats["peak"],
        agents=tuple(rows),
        sources=tuple(source_rows),
        generating=generating,
        tools=tools,
        warnings=tuple(warnings),
        scanned_files=scanned_files,
        sources_available=scanned_files > 0,
    )


def default_scan_config() -> ScanConfig:
    home = os.path.expanduser("~")
    codex_root = (
        os.path.join(os.environ["CODEX_HOME"], "sessions")
        if os.environ.get("CODEX_HOME")
        else os.path.join(home, ".codex", "sessions")
    )
    claude_root = (
        os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects")
        if os.environ.get("CLAUDE_CONFIG_DIR")
        else os.path.join(home, ".claude", "projects")
    )
    dsh_root = (
        os.path.join(os.environ["DSH_HOME"], "sessions")
        if os.environ.get("DSH_HOME")
        else os.path.join(home, ".dsh", "sessions")
    )
    opencode_db = os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"),
        "opencode",
        "opencode.db",
    )
    zcode_root = os.path.join(
        os.environ.get("ZCODE_DATA_BASE_DIR") or home, ".zcode", "cli", "db"
    )
    kimi_root = os.path.join(
        os.environ.get("KIMI_CODE_HOME") or os.path.join(home, ".kimi-code"), "sessions"
    )
    grok_root = os.path.join(
        os.environ.get("GROK_HOME") or os.path.join(home, ".grok"), "sessions"
    )
    return ScanConfig(
        codex_root=codex_root,
        claude_root=claude_root,
        dsh_root=dsh_root,
        opencode_db=opencode_db,
        gemini_dirs=tuple(reference.gemini_roots()),
        omp_dirs=tuple(reference.omp_roots()),
        antigravity_stores=tuple(reference.antigravity_stores()),
        workbuddy_roots=tuple(reference.workbuddy_roots()),
        zcode_root=zcode_root,
        kimi_root=kimi_root,
        grok_root=grok_root,
    )
