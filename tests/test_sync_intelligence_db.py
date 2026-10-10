#!/usr/bin/env python3
"""Regression tests for cloud/local intelligence DB sync."""

import asyncio
import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from embedding_metadata import (
    INTELLIGENCE_CONTEXT_NAMESPACE,
    INTELLIGENCE_INSIGHT_NAMESPACE,
    INTELLIGENCE_OUTCOME_NAMESPACE,
    INTELLIGENCE_PATTERN_NAMESPACE,
    INTELLIGENCE_QUERY_NAMESPACE,
    record_embedding_namespace_complete,
)
from embeddings import EMBEDDING_DIMENSIONS
from intelligence import IntelligenceLayer

TEST_VECTOR = [1.0, 0.5] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


def load_sync_module():
    script_path = PROJECT_ROOT / "bin" / "sync-intelligence-db.py"
    spec = importlib.util.spec_from_file_location("sync_intelligence_db", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncIntelligenceDbTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch("intelligence.get_intel_logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

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
        intel._get_embedding = lambda text, **kwargs: np.array(TEST_VECTOR)
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
        for namespace in (
            INTELLIGENCE_QUERY_NAMESPACE,
            INTELLIGENCE_CONTEXT_NAMESPACE,
            INTELLIGENCE_OUTCOME_NAMESPACE,
            INTELLIGENCE_INSIGHT_NAMESPACE,
            INTELLIGENCE_PATTERN_NAMESPACE,
        ):
            record_embedding_namespace_complete(intel.conn, namespace)
        intel.conn.commit()
        intel.close()

    def _sync_fixture(self, root, target_mode="local", seed_target=False):
        paths = {mode: root / f"{mode}.db" for mode in ("cloud", "local")}
        source_mode = "cloud" if target_mode == "local" else "local"
        asyncio.run(self._seed_source(paths[source_mode]))
        if seed_target:
            asyncio.run(self._seed_source(
                paths[target_mode], query="find a saved page", tools=["bookmark_search"],
                web_id="web-target-only", preferred_tool="bookmark_search", sequence=[],
                summary="Use bookmark_search for saved pages.",
            ))
        sync = load_sync_module()
        sync.get_db_paths = lambda: paths
        sync.get_embedding = lambda text, **kwargs: [0.25] * sync.EMBEDDING_DIMENSIONS
        return sync, paths, source_mode

    def _run_sync(self, sync, target_mode="local"):
        with contextlib.redirect_stdout(io.StringIO()):
            return sync.sync_intelligence(target_mode)

    def test_matching_insight_refreshes_without_duplicate_rows_or_embeddings(self):
        for target_mode in ("cloud", "local"):
            with self.subTest(target_mode=target_mode), tempfile.TemporaryDirectory() as tmpdir:
                sync, paths, source_mode = self._sync_fixture(Path(tmpdir), target_mode)
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    before = conn.execute("SELECT id, insight_embedding, pattern_embedding FROM insights").fetchone()
                with sqlite3.connect(paths[source_mode]) as conn:
                    conn.execute("""
                        UPDATE insights SET updated_at='2040-01-01 00:00:00',
                            trigger_signals='["email", "video"]', reasoning='Refined source rule',
                            confidence=0.95, strength=0.9, evidence_count=5,
                            times_applied=10, times_helpful=8, times_failed=2
                    """)
                self.assertTrue(self._run_sync(sync, target_mode))
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM insights").fetchone()
                    self.assertEqual(conn.execute("SELECT count(*) FROM insights").fetchone()[0], 1)
                    self.assertEqual((row['id'], row['insight_embedding'], row['pattern_embedding']), before)
                    self.assertEqual(row['trigger_signals'], '["email", "video"]')
                    self.assertEqual(row['reasoning'], 'Refined source rule')
                    self.assertEqual(row['confidence'], 0.95)
                    self.assertEqual(row['strength'], 0.9)
                    self.assertEqual(row['evidence_count'], 5)
                    self.assertEqual(row['times_applied'], 0)
                    self.assertEqual(row['times_helpful'], 0)
                    self.assertEqual(row['times_failed'], 0)

    def test_destination_feedback_survives_later_source_refinements(self):
        for target_mode in ("cloud", "local"):
            with self.subTest(target_mode=target_mode), tempfile.TemporaryDirectory() as tmpdir:
                sync, paths, source_mode = self._sync_fixture(Path(tmpdir), target_mode)
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    conn.execute("""
                        UPDATE insights SET confidence=0.4, strength=0.2, times_applied=3,
                            times_helpful=1, times_failed=2, consecutive_failures=2,
                            last_outcome='failure', last_applied='2030-01-01 00:00:00'
                    """)
                for confidence in (0.95, 0.99):
                    with sqlite3.connect(paths[source_mode]) as conn:
                        conn.execute("""
                            UPDATE insights SET updated_at='2040-01-01 00:00:00',
                                confidence=?, reasoning='Updated source reasoning'
                        """, (confidence,))
                    self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    self.assertEqual(conn.execute("""
                        SELECT confidence,strength,times_applied,times_helpful,times_failed,
                            consecutive_failures,last_outcome,last_applied,reasoning FROM insights
                    """).fetchone(), (
                        0.4, 0.2, 3, 1, 2, 2, 'failure', '2030-01-01 00:00:00', 'Updated source reasoning',
                    ))
                    self.assertEqual(conn.execute("SELECT feedback_owned FROM intelligence_sync_state").fetchone()[0], 1)

    def test_legacy_matching_insight_preserves_feedback_and_refreshes_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir))
            asyncio.run(self._seed_source(paths['local']))
            with sqlite3.connect(paths['local']) as conn:
                conn.execute("UPDATE insights SET confidence=0.4, times_applied=2, updated_at='2020-01-01'")
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("UPDATE insights SET confidence=0.95, reasoning='New reasoning', updated_at='2040-01-01'")
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM insights").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT confidence,times_applied,reasoning FROM insights").fetchone(), (0.4, 2, 'New reasoning'))

    def test_source_does_not_erase_newer_destination_edits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir))
            asyncio.run(self._seed_source(paths['local']))
            with sqlite3.connect(paths['local']) as conn:
                conn.execute("UPDATE insights SET confidence=0.4, reasoning='Destination edit', updated_at='2050-01-01'")
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("UPDATE insights SET confidence=0.95, reasoning='Older source edit', updated_at='2040-01-01'")
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("UPDATE insights SET confidence=0.99, reasoning='Later source refinement', updated_at='2060-01-01'")
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT confidence,reasoning FROM insights").fetchone(), (0.4, 'Later source refinement'))

    def test_old_source_schema_does_not_clear_destination_trigger_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir))
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                expected = conn.execute("SELECT trigger_signals FROM insights").fetchone()[0]
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("ALTER TABLE insights DROP COLUMN trigger_signals")
                conn.execute("UPDATE insights SET updated_at='2040-01-01', reasoning='Legacy source refinement'")
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT trigger_signals FROM insights").fetchone()[0], expected)

    def test_completed_destination_reflection_is_not_requeued(self):
        for target_mode in ("cloud", "local"):
            with self.subTest(target_mode=target_mode), tempfile.TemporaryDirectory() as tmpdir:
                sync, paths, _ = self._sync_fixture(Path(tmpdir), target_mode)
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    conn.execute("UPDATE reflection_queue SET processed=1")
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    self.assertEqual(conn.execute("SELECT processed FROM reflection_queue").fetchall(), [(1,)])

    def test_nested_ids_remap_once_with_collisions_and_forward_references(self):
        for target_mode in ("cloud", "local"):
            with self.subTest(target_mode=target_mode), tempfile.TemporaryDirectory() as tmpdir:
                sync, paths, source_mode = self._sync_fixture(Path(tmpdir), target_mode, seed_target=True)
                asyncio.run(self._seed_source(paths[source_mode], query='second source sample', web_id='web-second'))
                with sqlite3.connect(paths[source_mode]) as conn:
                    raw = json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=1").fetchone()[0])
                    raw['completion_guard'] = {'experience_id': 1, 'status': 'accepted'}
                    raw['context']['tool_results'] = {'experience_id': 1, 'id': 'external-file-id'}
                    raw['user_signals']['previous_experience_id_candidate'] = 2
                    raw['user_correction_shadow'] = {
                        'latest': {'previous_experience_id': 2},
                        'history': [{'previous_experience_id': 1}, {'previous_experience_id': 999}],
                    }
                    conn.execute("UPDATE experiences SET raw_data=? WHERE id=1", (json.dumps(raw),))
                self.assertTrue(self._run_sync(sync, target_mode))
                self.assertTrue(self._run_sync(sync, target_mode))
                with sqlite3.connect(paths[target_mode]) as conn:
                    raw = json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=2").fetchone()[0])
                    self.assertEqual(raw['context']['experience_id'], 2)
                    self.assertEqual(raw['completion_guard']['experience_id'], 2)
                    self.assertEqual(raw['user_signals']['previous_experience_id_candidate'], 3)
                    self.assertEqual(raw['user_correction_shadow']['latest']['previous_experience_id'], 3)
                    self.assertEqual(raw['user_correction_shadow']['history'], [{'previous_experience_id': 2}, {'previous_experience_id': None}])
                    self.assertEqual(raw['context']['tool_results'], {'experience_id': 1, 'id': 'external-file-id'})

    def test_legacy_nested_id_repair_keeps_destination_feedback_and_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir), seed_target=True)
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                raw = json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=2").fetchone()[0])
                raw['context']['experience_id'] = 1
                raw['completion_guard'] = {'experience_id': 1, 'status': 'accepted'}
                raw['feedback'] = {'latest': {'rating': 1}}
                raw['user_correction_shadow'] = {'latest': {'previous_experience_id': 1}}
                conn.execute("UPDATE experiences SET raw_data=? WHERE id=2", (json.dumps(raw),))
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                raw = json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=2").fetchone()[0])
                self.assertEqual(raw['context']['experience_id'], 2)
                self.assertEqual(raw['completion_guard']['experience_id'], 2)
                self.assertEqual(raw['feedback'], {'latest': {'rating': 1}})
                self.assertEqual(raw['user_correction_shadow']['latest']['previous_experience_id'], 1)

    def test_refinements_and_metadata_repairs_roll_back_with_embedding_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir), seed_target=True)
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                raw = json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=2").fetchone()[0])
                raw['context']['experience_id'] = 1
                conn.execute("UPDATE experiences SET raw_data=? WHERE id=2", (json.dumps(raw),))
                before = conn.execute("SELECT confidence,reasoning FROM insights WHERE source_web_conversation_id='web-sync'").fetchone()
                checkpoint = conn.execute("SELECT * FROM intelligence_sync_state").fetchall()
            asyncio.run(self._seed_source(paths['cloud'], query='new source row'))
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("UPDATE insights SET confidence=0.99,reasoning='New refinement',updated_at='2040-01-01'")
            def fail_new_row(text, **kwargs):
                if text == 'new source row':
                    raise RuntimeError('embedding unavailable')
                return [0.25] * sync.EMBEDDING_DIMENSIONS
            sync.get_embedding = fail_new_row
            self.assertFalse(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT confidence,reasoning FROM insights WHERE source_web_conversation_id='web-sync'").fetchone(), before)
                self.assertEqual(json.loads(conn.execute("SELECT raw_data FROM experiences WHERE id=2").fetchone()[0])['context']['experience_id'], 1)
                self.assertEqual(conn.execute("SELECT * FROM intelligence_sync_state").fetchall(), checkpoint)

    def test_metadata_remap_preserves_invalid_json_and_non_object_payloads(self):
        sync = load_sync_module()
        for raw in (None, 'invalid JSON', '[]', 'null'):
            with self.subTest(raw=raw):
                self.assertEqual(sync.remap_experience_metadata(raw, 2, {1: 2}), raw)

    def test_duplicate_source_experiences_do_not_translate_metadata_twice(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir), seed_target=True)
            asyncio.run(self._seed_source(
                paths['local'], query='another saved page', tools=['bookmark_search'],
                preferred_tool='bookmark_search', sequence=[], summary='Use saved pages.',
            ))
            with sqlite3.connect(paths['cloud']) as conn:
                conn.row_factory = sqlite3.Row
                original = dict(conn.execute("SELECT * FROM experiences WHERE id=1").fetchone())
                raw = json.loads(original['raw_data'])
                raw['user_signals']['previous_experience_id_candidate'] = 1
                original['raw_data'] = json.dumps(raw)
                conn.execute("UPDATE experiences SET raw_data=? WHERE id=1", (original['raw_data'],))
                original.pop('id')
                columns = ','.join(original)
                placeholders = ','.join('?' for _ in original)
                conn.execute(f"INSERT INTO experiences ({columns}) VALUES ({placeholders})", tuple(original.values()))
                original['query'] = 'later distinct source experience'
                conn.execute(f"INSERT INTO experiences ({columns}) VALUES ({placeholders})", tuple(original.values()))
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                row = conn.execute("SELECT id,raw_data FROM experiences WHERE query='email this youtube video'").fetchone()
                self.assertEqual(row[0], 3)
                self.assertEqual(json.loads(row[1])['user_signals']['previous_experience_id_candidate'], 3)

    def test_explicit_replace_resets_previous_destination_feedback_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sync, paths, _ = self._sync_fixture(Path(tmpdir))
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                conn.execute("UPDATE insights SET confidence=0.4,times_failed=1")
            self.assertTrue(self._run_sync(sync))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT feedback_owned FROM intelligence_sync_state").fetchone()[0], 1)
            with sqlite3.connect(paths['cloud']) as conn:
                conn.execute("UPDATE insights SET confidence=0.95")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sync.sync_intelligence('local', replace=True))
            with sqlite3.connect(paths['local']) as conn:
                self.assertEqual(conn.execute("SELECT confidence,times_failed FROM insights").fetchone(), (0.95, 0))
                self.assertEqual(conn.execute("SELECT feedback_owned FROM intelligence_sync_state").fetchall(), [(0,)])

    def test_sync_preserves_new_insight_provenance_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(self._seed_source(cloud_db))

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            sync.load_config = lambda mode=None: None
            sync.get_embedding = lambda text, **kwargs: list(TEST_VECTOR)

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
            sync.get_embedding = lambda text, **kwargs: list(TEST_VECTOR)

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
            sync.get_embedding = lambda text, **kwargs: list(TEST_VECTOR)

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
            sync.get_embedding = lambda text, **kwargs: list(TEST_VECTOR)

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

    def test_embedding_failure_rolls_back_complete_sync(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cloud_db = tmpdir / "cloud.db"
            local_db = tmpdir / "local.db"
            asyncio.run(self._seed_source(cloud_db))

            sync = load_sync_module()
            sync.get_db_paths = lambda: {"cloud": cloud_db, "local": local_db}
            calls = 0

            def flaky_embedding(text, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("embedding host lost")
                return list(TEST_VECTOR)

            sync.get_embedding = flaky_embedding
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(sync.sync_intelligence("local", dry_run=False))

            conn = sqlite3.connect(local_db)
            self.addCleanup(conn.close)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM insights").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
