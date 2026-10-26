import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentspeed_cli.model import ScanConfig
from agentspeed_cli.snapshot import build_snapshot, default_scan_config

NOW = 10_000_000
TODAY_START = 0


def sample_responses():
    return [
        dict(
            key="a",
            source="codex",
            agentId="a",
            model="m",
            startMs=NOW - 2000,
            endMs=NOW,
            input=10,
            output=100,
            final=True,
            costMicroUsd=1000,
        ),
        dict(
            key="b",
            source="codex",
            agentId="b",
            model="m",
            startMs=NOW - 1000,
            endMs=NOW,
            input=5,
            output=50,
            final=True,
            costMicroUsd=None,
        ),
    ]


def sample_agents():
    return [
        dict(
            id="a",
            source="codex",
            model="m",
            phase="generating",
            inFlightStartMs=NOW - 1000,
            lastLineMs=NOW,
            parentId=None,
            project="proj",
            isSubagent=False,
        ),
        dict(
            id="b",
            source="codex",
            model="m",
            phase="idle",
            inFlightStartMs=None,
            lastLineMs=NOW,
            parentId="a",
            project="proj",
            isSubagent=True,
        ),
    ]


class SnapshotTests(unittest.TestCase):
    def test_totals_agents_and_sources(self):
        snapshot = build_snapshot(sample_responses(), sample_agents(), NOW, TODAY_START, scanned_files=2)
        self.assertEqual(snapshot.today_output, 150)
        self.assertEqual(snapshot.today_cost_micro, 1000)
        self.assertEqual(snapshot.today_unpriced, 1)
        self.assertEqual(snapshot.generating, 1)
        self.assertEqual(snapshot.agents[0].id, "a")
        self.assertEqual(snapshot.agents[1].parent_id, "a")
        self.assertEqual(snapshot.sources[0].source, "codex")
        self.assertEqual(snapshot.sources[0].today_output, 150)
        self.assertGreater(snapshot.live_output, 0)
        self.assertTrue(snapshot.sources_available)

    def test_empty_snapshot(self):
        snapshot = build_snapshot([], [], NOW, TODAY_START)
        self.assertEqual(snapshot.today_output, 0)
        self.assertEqual(snapshot.today_cost_micro, 0)
        self.assertEqual(snapshot.agents, ())
        self.assertEqual(snapshot.sources, ())
        self.assertFalse(snapshot.sources_available)

    def test_stale_generating_agent_becomes_idle(self):
        agents = sample_agents()
        agents[0]["lastLineMs"] = NOW - 301_000
        snapshot = build_snapshot([], agents, NOW, TODAY_START)
        self.assertEqual(snapshot.generating, 0)
        self.assertEqual(snapshot.agents[0].phase, "idle")

    def test_default_config_honours_codex_home(self):
        with patch.dict(os.environ, {"CODEX_HOME": "/x"}, clear=False):
            config = default_scan_config()
        self.assertIsInstance(config, ScanConfig)
        self.assertEqual(config.codex_root, "/x/sessions")
        self.assertIn("codex", config.enabled_sources)


if __name__ == "__main__":
    unittest.main()
