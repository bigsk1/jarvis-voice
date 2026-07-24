#!/usr/bin/env python3
"""Regression tests for cloud/local intelligence DB sync."""

import asyncio
import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from intelligence import IntelligenceLayer


def load_sync_module():
    script_path = PROJECT_ROOT / "bin" / "sync-intelligence-db.py"
    spec = importlib.util.spec_from_file_location("sync_intelligence_db", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncIntelligenceDbTests(unittest.TestCase):
    async def _seed_source(
        self,
        db_path: Path,
        query: str = "email this youtube video",
        tools: list[str] | None = None,
        web_id: str = "web-sync",
        preferred_tool: str = "send_email",
        preferred_workflow_id: str | None = None,
        sequence: list[str] | None = None,
        summary: str = "For sending YouTube links, use send_email as the primary action tool.",
    ) -> None:
        tools = tools or ["youtube_video", "send_email"]
        sequence = tools if sequence is None else sequence
        intel = IntelligenceLayer(str(db_path))
        intel._get_embedding = lambda text: np.array([1.0, 0.5])
        intel._get_persistable_embedding = intel._get_embedding
        context = {"web_conversation_id": web_id}
        if preferred_workflow_id:
            context["workflow_execution"] = {
                "is_workflow_interaction": True,
                "invocation": "autonomous_meta_tool",
                "actions": ["run"],
                "selected_workflow_id": preferred_workflow_id,
                "run_started": True,
                "run_completed": True,
                "cancelled": False,
                "outcome_success": True,
                "component_tools_used": [],
                "component_order_owner": "deterministic_workflow_recipe",
            }
        exp_id = await intel.record_experience(
            query=query,
            tools_used=tools,
            outcome={"success": True, "turns": len(tools)},
            context=context,
        )
        experience = intel.conn.execute(
            "SELECT * FROM experiences WHERE id = ?",
            (exp_id,),
        ).fetchone()
        await intel._store_insight(
            {
                "is_procedural": True,
                "knowledge_type": "procedural",
                "preferred_tool": preferred_tool,
                "preferred_workflow_id": preferred_workflow_id,
                "preferred_tool_sequence": sequence,
                "supporting_tools": sequence[:-1],
                "sequence_required": False,
                "trigger_signals": query.split()[:3],
                "primary_intent": query,
                "applies_to": query,
                "generalizability": "medium",
                "confidence": 0.8,
                "insight_summary": summary,
            },
            experience,
        )
        intel.close()

    def test_sync_preserves_new_insight_provenance_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(self._seed_source(cloud_db))

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            sync.load_config = lambda mode=None: None
            sync.get_embedding = lambda text: [1.0, 0.5]

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sync.sync_intelligence("local", dry_run=False))

            conn = sqlite3.connect(local_db)
            conn.row_factory = sqlite3.Row
            self.addCleanup(conn.close)

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insight_evidence").fetchone()[0], 1)

            insight = conn.execute("""
                SELECT source_web_conversation_id, preferred_tool_sequence, source_experience_id
                FROM insights
            """).fetchone()
            evidence = conn.execute("""
                SELECT web_conversation_id, tool_sequence, insight_id, experience_id
                FROM insight_evidence
            """).fetchone()

            self.assertEqual(insight["source_web_conversation_id"], "web-sync")
            self.assertEqual(insight["preferred_tool_sequence"], '["youtube_video", "send_email"]')
            self.assertEqual(insight["source_experience_id"], 1)
            self.assertEqual(evidence["web_conversation_id"], "web-sync")
            self.assertEqual(evidence["tool_sequence"], '["youtube_video", "send_email"]')
            self.assertEqual(evidence["insight_id"], 1)
            self.assertEqual(evidence["experience_id"], 1)

    def test_sync_preserves_preferred_workflow_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(
                self._seed_source(
                    cloud_db,
                    query="save a quick note",
                    tools=["workflow"],
                    preferred_tool="workflow",
                    preferred_workflow_id="quick_note",
                    sequence=[],
                    summary="Use quick_note for short saved-note requests.",
                )
            )

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            sync.load_config = lambda mode=None: None
            sync.get_embedding = lambda text: [1.0, 0.5]

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sync.sync_intelligence("local", dry_run=False))

            conn = sqlite3.connect(local_db)
            conn.row_factory = sqlite3.Row
            self.addCleanup(conn.close)
            insight = conn.execute(
                "SELECT preferred_workflow_id FROM insights"
            ).fetchone()
            evidence = conn.execute(
                "SELECT preferred_workflow_id FROM insight_evidence"
            ).fetchone()

            self.assertEqual(insight["preferred_workflow_id"], "quick_note")
            self.assertEqual(evidence["preferred_workflow_id"], "quick_note")

    def test_default_sync_merges_without_overwriting_target_only_learning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(self._seed_source(cloud_db))
            asyncio.run(self._seed_source(
                local_db,
                query="check bookmark for cheese",
                tools=["bookmark_search"],
                web_id="web-local-only",
                preferred_tool="bookmark_search",
                sequence=[],
                summary="For bookmark checks, use bookmark_search.",
            ))

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            sync.load_config = lambda mode=None: None
            sync.get_embedding = lambda text: [1.0, 0.5]

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sync.sync_intelligence("local", dry_run=False))
                self.assertTrue(sync.sync_intelligence("local", dry_run=False))

            conn = sqlite3.connect(local_db)
            conn.row_factory = sqlite3.Row
            self.addCleanup(conn.close)

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insight_evidence").fetchone()[0], 2)
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM experiences WHERE query = ?",
                ("check bookmark for cheese",),
            ).fetchone())

    def test_replace_sync_keeps_old_full_mirror_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(self._seed_source(cloud_db))
            asyncio.run(self._seed_source(
                local_db,
                query="check bookmark for cheese",
                tools=["bookmark_search"],
                web_id="web-local-only",
                preferred_tool="bookmark_search",
                sequence=[],
                summary="For bookmark checks, use bookmark_search.",
            ))

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            sync.load_config = lambda mode=None: None
            sync.get_embedding = lambda text: [1.0, 0.5]

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sync.sync_intelligence("local", dry_run=False, replace=True))

            conn = sqlite3.connect(local_db)
            conn.row_factory = sqlite3.Row
            self.addCleanup(conn.close)

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insight_evidence").fetchone()[0], 1)
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM experiences WHERE query = ?",
                ("check bookmark for cheese",),
            ).fetchone())


if __name__ == "__main__":
    unittest.main()
