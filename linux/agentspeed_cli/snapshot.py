"""Live snapshot construction on top of the shared spec engine."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .model import AgentRow, ScanConfig, Snapshot, SourceRow, SOURCE_ORDER
from .tail import Tail


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


def _local_midnight_ms(now_ms: int) -> int:
    moment = datetime.fromtimestamp(now_ms / 1000).astimezone()
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def _process_lines(state: reference.FileState, lines: list[bytes], dedupe: reference.Deduper) -> None:
    handler = {
        "codex": reference.codex_line,
        "deepseek": reference.dsh_event,
        "gemini": reference.gemini_record,
        "omp": reference.omp_line,
        "workbuddy": reference.workbuddy_line,
        "workbuddyAi": reference.workbuddy_line,
    }.get(state.source, reference.claude_line)
    for raw in lines:
        try:
            obj = reference.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            state.malformed += 1
            continue
        if not isinstance(obj, dict):
            state.malformed += 1
            continue
        handler(state, obj, dedupe)


class LiveScanner:
    """Reads today's transcripts incrementally and produces a Snapshot per call."""

    def __init__(self, config: ScanConfig, price_table: str | None = None) -> None:
        self.config = config
        self.index = prices.Index(prices.load(price_table or prices.TABLE))
        self.dedupe = reference.Deduper()
        self.states: dict[str, reference.FileState] = {}
        self.tails: dict[str, Tail] = {}
        self.signatures: dict[str, tuple[int, int]] = {}
        self.harness_states: list[dict] = []
        self.opencode_signature: object | None = None
        self.files: list[tuple[float, str, str, str | None]] = []
        self.next_discovery_ms = 0
        self.warnings: set[str] = set()
        self.scanned_files = 0

    def scan(self, now_ms: int | None = None) -> Snapshot:
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        today_start_ms = _local_midnight_ms(now_ms)
        if now_ms >= self.next_discovery_ms:
            self._discover()
            self.next_discovery_ms = now_ms + 5000

        self.scanned_files = 0
        cutoff = today_start_ms - 15 * 60_000
        for mtime, path, source, root in self.files:
            if mtime * 1000 < cutoff:
                continue
            if source == "claudeCode":
                if "claudeCode" not in self.config.enabled_sources and "claudeDesktop" not in self.config.enabled_sources:
                    continue
            elif source not in self.config.enabled_sources:
                continue
            try:
                self._ingest(path, source, root)
            except Exception:
                self.warnings.add("some transcript files could not be read")

        self._ingest_opencode()
        self._ingest_harness()
        responses, agents = self._collect()

        malformed = sum(state.malformed for state in self.states.values())
        warnings = set(self.warnings)
        if malformed:
            warnings.add(f"{malformed} malformed lines")
        return build_snapshot(
            responses,
            agents,
            now_ms,
            today_start_ms,
            warnings=tuple(sorted(warnings)),
            scanned_files=self.scanned_files,
            price_index=self.index,
        )

    def _discover(self) -> None:
        try:
            self.files = reference.startup_files(
                self.config.codex_root or "",
                self.config.claude_root or "",
                self.config.dsh_root or "",
                self.config.gemini_dirs,
                self.config.omp_dirs,
                self.config.antigravity_stores,
                self.config.workbuddy_roots,
                include_archived=False,
            )
        except Exception:
            self.warnings.add("transcript discovery failed")

    @staticmethod
    def _signature(path: str) -> tuple[int, int]:
        stat = os.stat(path)
        return (stat.st_size, stat.st_mtime_ns)

    def _forget_owner(self, path: str) -> None:
        owners = self.dedupe.owners
        for key in [key for key, owner in owners.items() if owner == path]:
            del owners[key]

    def _ingest(self, path: str, source: str, root: str | None) -> None:
        if source == "antigravity":
            self.scanned_files += 1
            signature = self._signature(path)
            if self.signatures.get(path) == signature:
                return
            self._forget_owner(path)
            try:
                state = reference.antigravity_state(path, self.dedupe)
            except Exception:
                self.warnings.add("Antigravity data could not be read")
                return
            if state is not None:
                self.states[path] = state
            self.signatures[path] = signature
            return

        if path.endswith((".zstd", ".jsonl.zst")) or (
            source == "gemini" and path.endswith(".json")
        ):
            self.scanned_files += 1
            signature = self._signature(path)
            if self.signatures.get(path) == signature:
                return
            self._forget_owner(path)
            state = reference.FileState(path, source, root)
            try:
                reference.process_file(state, self.dedupe)
            except FileNotFoundError:
                if not os.path.exists(path):
                    self.warnings.add("some transcript files are unreadable")
                else:
                    self.warnings.add("zstd not found: compressed logs skipped")
                return
            except OSError:
                self.warnings.add("some transcript files are unreadable")
                return
            self.states[path] = state
            self.signatures[path] = signature
            return

        self.scanned_files += 1
        tail = self.tails.get(path)
        if tail is None:
            tail = Tail()
            self.tails[path] = tail
            size = os.path.getsize(path)
            if size > 256 * 1024 * 1024:
                tail.start_at(path, size - 64 * 1024 * 1024)
                if source == "omp":
                    state = reference.FileState(path, source, root)
                    self.states[path] = state
                    reference.omp_read_header(state, self.dedupe)
        lines = tail.read(path)
        state = self.states.get(path)
        if state is None or tail.reset:
            self._forget_owner(path)
            state = reference.FileState(path, source, root)
            self.states[path] = state
        if not lines:
            return
        if source == "omp" and not state.header_seen:
            reference.omp_read_header(state, self.dedupe)
        _process_lines(state, lines, self.dedupe)

    def _ingest_opencode(self) -> None:
        if not self.config.opencode_db or "opencode" not in self.config.enabled_sources:
            return
        if not os.path.exists(self.config.opencode_db):
            return
        self.scanned_files += 1
        try:
            signature: object = self._signature(self.config.opencode_db)
            wal = self.config.opencode_db + "-wal"
            if os.path.exists(wal):
                signature = (signature, self._signature(wal))
        except OSError:
            self.warnings.add("some transcript files are unreadable")
            return
        if signature == self.opencode_signature:
            return
        try:
            states = reference.opencode_states(self.config.opencode_db, self.dedupe)
        except sqlite3.Error:
            self.warnings.add("OpenCode database is busy")
            return
        except OSError:
            self.warnings.add("some transcript files are unreadable")
            return
        for path in [path for path in self.states if path.startswith("opencode:")]:
            del self.states[path]
        for state in states:
            self.states[state.path] = state
        self.opencode_signature = signature

    def _ingest_harness(self) -> None:
        states: list[dict] = []
        seen: set[str] = set()
        if self.config.zcode_root and "zcode" in self.config.enabled_sources:
            try:
                states.extend(harness.read_zcode(self.config.zcode_root, seen))
            except (OSError, sqlite3.Error):
                self.warnings.add("ZCode data could not be read")
        readers = (
            (self.config.kimi_root, "wire.jsonl", 4, harness.read_kimi, "kimi"),
            (self.config.grok_root, "updates.jsonl", 2, harness.read_grok, "grokBuild"),
        )
        for root, name, depth, reader, source in readers:
            if not root or source not in self.config.enabled_sources:
                continue
            try:
                paths = harness.discover(root, name, depth)
            except OSError:
                self.warnings.add("some harness sessions could not be read")
                continue
            for path in paths:
                try:
                    states.append(reader(path, seen))
                except (OSError, ValueError, KeyError):
                    self.warnings.add("some harness sessions could not be read")
        self.harness_states = [state for state in states if state.get("responses")]
        self.scanned_files += len(self.harness_states)

    def _collect(self) -> tuple[list[dict], list[dict]]:
        file_states = [
            state for path, state in self.states.items() if not path.startswith("opencode:")
        ]
        parents = reference.resolve_parents(file_states)
        responses: list[dict] = []
        agents: list[dict] = []
        for path, state in self.states.items():
            if state.source not in self.config.enabled_sources:
                continue
            for response in state.responses.values():
                responses.append(dict(response, source=state.source, agentId=path))
            parent = state.parent_session if path.startswith("opencode:") else parents.get(path)
            agents.append(
                dict(
                    id=path,
                    source=state.source,
                    model=state.model,
                    phase=state.phase,
                    inFlightStartMs=state.in_flight,
                    lastLineMs=state.last_line,
                    parentId=parent,
                    project=state.project,
                    isSubagent=state.is_subagent,
                )
            )

        zcode_by_id = {
            state["id"]: state["agentId"]
            for state in self.harness_states
            if state.get("source") == "zcode"
        }
        agent_ids = {state["agentId"] for state in self.harness_states}
        for state in self.harness_states:
            rows = state["responses"]
            for response in rows:
                responses.append(
                    dict(response, source=state["source"], agentId=state["agentId"])
                )
            if state.get("source") == "zcode":
                parent = zcode_by_id.get(state.get("parentId"))
            else:
                candidate = state.get("parentFile")
                parent = candidate if candidate in agent_ids else None
            model = None
            for response in reversed(rows):
                if response.get("model"):
                    model = response["model"]
                    break
            agents.append(
                dict(
                    id=state["agentId"],
                    source=state["source"],
                    model=model,
                    phase="idle",
                    inFlightStartMs=None,
                    lastLineMs=max((response.get("endMs") or 0) for response in rows),
                    parentId=parent,
                    project=state.get("project"),
                    isSubagent=bool(state.get("isSubagent")),
                )
            )
        return responses, agents
