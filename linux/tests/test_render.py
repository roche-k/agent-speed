import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentspeed_cli.model import AgentRow, Snapshot, SourceRow
from agentspeed_cli.render import (
    display_width,
    format_cost,
    format_cost_rate,
    format_speed,
    format_tokens,
    render,
    truncate,
)


def make_snapshot(*, project="app_trader_relay", warnings=()):
    agents = (
        AgentRow(
            id="codex-main",
            source="codex",
            project=project,
            model="gpt-6.1-sol",
            phase="generating",
            live_output=34.8,
            live_total=36.0,
            today_output=257_700,
            today_cost_micro=12_410_000,
            today_unpriced=0,
            is_subagent=False,
            parent_id=None,
            last_line_ms=1_793_000_000_000,
        ),
        AgentRow(
            id="codex-worker",
            source="codex",
            project="worker",
            model="gpt-6.1-sol",
            phase="idle",
            live_output=0.0,
            live_total=0.0,
            today_output=41_200,
            today_cost_micro=2_030_000,
            today_unpriced=0,
            is_subagent=True,
            parent_id="codex-main",
            last_line_ms=1_793_000_000_000,
        ),
        AgentRow(
            id="opencode:ses_1",
            source="opencode",
            project="agent-speed",
            model="deepseek-v4-flash",
            phase="idle",
            live_output=77.3,
            live_total=80.0,
            today_output=271_000,
            today_cost_micro=660_000,
            today_unpriced=0,
            is_subagent=False,
            parent_id=None,
            last_line_ms=1_793_000_000_000,
        ),
        AgentRow(
            id="claude-desktop",
            source="claudeDesktop",
            project="orbit",
            model="claude-opus-5-5",
            phase="idle",
            live_output=0.0,
            live_total=0.0,
            today_output=12_345,
            today_cost_micro=0,
            today_unpriced=0,
            is_subagent=False,
            parent_id=None,
            last_line_ms=1_793_000_000_000,
        ),
    )
    sources = (
        SourceRow(
            source="codex",
            live_output=34.8,
            today_output=298_900,
            today_cost_micro=14_440_000,
            today_unpriced=0,
            active_agents=1,
        ),
        SourceRow(
            source="opencode",
            live_output=77.3,
            today_output=271_000,
            today_cost_micro=660_000,
            today_unpriced=0,
            active_agents=0,
        ),
        SourceRow(
            source="claudeDesktop",
            live_output=0.0,
            today_output=12_345,
            today_cost_micro=0,
            today_unpriced=0,
            active_agents=0,
        ),
    )
    return Snapshot(
        now_ms=1_793_000_000_000,
        today_start_ms=1_792_972_800_000,
        live_output=142.9,
        live_total=150.0,
        estimated_share=0.4,
        live_cost_micro_per_s=2_836.5,
        live_cost_known_share=1.0,
        today_output=910_800,
        today_input=154_953_745,
        today_requests=911,
        today_cost_micro=47_900_000,
        today_unpriced=0,
        peak=591.1,
        agents=agents,
        sources=sources,
        generating=1,
        tools=0,
        warnings=warnings,
        scanned_files=30,
        sources_available=True,
    )


def empty_snapshot(*, sources_available):
    return Snapshot(
        now_ms=1_793_000_000_000,
        today_start_ms=1_792_972_800_000,
        live_output=0.0,
        live_total=0.0,
        estimated_share=0.0,
        live_cost_micro_per_s=0.0,
        live_cost_known_share=1.0,
        today_output=0,
        today_input=0,
        today_requests=0,
        today_cost_micro=0,
        today_unpriced=0,
        peak=0.0,
        agents=(),
        sources=(),
        generating=0,
        tools=0,
        warnings=(),
        scanned_files=0 if not sources_available else 1,
        sources_available=sources_available,
    )


class FormatTests(unittest.TestCase):
    def test_format_tokens(self):
        self.assertEqual(format_tokens(0), "0")
        self.assertEqual(format_tokens(999), "999")
        self.assertEqual(format_tokens(1000), "1.0k")
        self.assertEqual(format_tokens(12_345), "12.3k")
        self.assertEqual(format_tokens(1_234_567), "1.2M")

    def test_format_cost(self):
        self.assertEqual(format_cost(0), "$0.00")
        self.assertEqual(format_cost(47_900_000), "$47.90")

    def test_format_speed_and_rate(self):
        self.assertEqual(format_speed(34.84), "34.8")
        self.assertEqual(format_cost_rate(2_836.5), "$0.0028/s")

    def test_display_width_and_truncate(self):
        self.assertEqual(display_width("agent"), 5)
        self.assertEqual(display_width("代理"), 4)
        self.assertEqual(display_width("a代b"), 4)
        self.assertEqual(truncate("abcdef", 4), "abc…")
        self.assertEqual(truncate("abcdef", 4, ascii_only=True), "a...")


class RenderTests(unittest.TestCase):
    def test_full_table(self):
        text = render(make_snapshot(), width=100, color=False)
        self.assertIn("Agent Speed", text)
        self.assertIn("Codex", text)
        self.assertIn("OpenCode", text)
        self.assertIn("Claude Desktop", text)
        self.assertIn("│Claude Desktop", text)
        self.assertIn("34.8", text)
        self.assertIn("257.7k", text)
        self.assertIn("$12.41", text)
        self.assertNotIn("\x1b[", text)
        for line in text.splitlines():
            self.assertLessEqual(display_width(line), 100)

    def test_narrow_drops_model_and_cost(self):
        narrow = render(make_snapshot(), width=60, color=False)
        self.assertNotIn("MODEL", narrow)
        self.assertNotIn("COST", narrow)

    def test_tiny_drops_phase_and_today(self):
        tiny = render(make_snapshot(), width=40, color=False)
        self.assertNotIn("PHASE", tiny)
        self.assertNotIn("TODAY", tiny)

    def test_ascii_fallback(self):
        ascii_text = render(make_snapshot(), width=100, color=False, ascii_only=True)
        self.assertNotIn("┌", ascii_text)
        self.assertIn("+", ascii_text)

    def test_no_sources_message(self):
        empty = render(empty_snapshot(sources_available=False), width=80, color=False)
        self.assertIn("No agent logs found", empty)

    def test_no_active_agents_message(self):
        empty = render(empty_snapshot(sources_available=True), width=80, color=False)
        self.assertIn("No active agents", empty)

    def test_cjk_project_stays_within_width(self):
        text = render(make_snapshot(project="代理服务"), width=80, color=False)
        for line in text.splitlines():
            self.assertLessEqual(display_width(line), 80, line)

    def test_warnings_are_shown(self):
        text = render(make_snapshot(warnings=("zstd not found",)), width=100, color=False)
        self.assertIn("zstd not found", text)

    def test_color_adds_ansi(self):
        text = render(make_snapshot(), width=100, color=True)
        self.assertIn("\x1b[", text)
        self.assertIn("\x1b[0m", text)

    def test_every_line_fits_at_30_columns(self):
        snapshots = (
            make_snapshot(),
            empty_snapshot(sources_available=False),
            empty_snapshot(sources_available=True),
        )
        for snapshot in snapshots:
            text = render(snapshot, width=30, color=False)
            for line in text.splitlines():
                self.assertLessEqual(display_width(line), 30, line)

    def test_unpriced_requests_are_shown(self):
        text = render(replace(make_snapshot(), today_unpriced=2), width=100, color=False)
        self.assertIn("2 unpriced requests", text)


if __name__ == "__main__":
    unittest.main()
