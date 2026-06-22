#!/usr/bin/env python3
"""Regression tests for Intelligence maintenance safety."""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from intelligence import IntelligenceLayer


def load_intelligence_service_module():
    service_path = (
        PROJECT_ROOT
        / "jarvis-intelligence"
        / "server"
        / "services"
        / "intelligence_service.py"
    )
    spec = importlib.util.spec_from_file_location("intelligence_service_test", service_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntelligenceMaintenanceTests(unittest.TestCase):
    def _make_intel(self, tmpdir: str) -> IntelligenceLayer:
        intel = IntelligenceLayer(str(Path(tmpdir) / "intel.db"))
        intel._get_embedding = lambda text: np.array([1.0, 0.25, 0.5])
        return intel

    def test_ui_service_initializes_fresh_local_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service_module = load_intelligence_service_module()
            local_db = Path(tmpdir) / "jarvis_intelligence_local.db"
            service_module.DB_PATHS["local"] = local_db

            service = service_module.IntelligenceService("local")
            stats = service.get_stats()

            self.assertTrue(local_db.exists())
            self.assertEqual(stats["experiences"]["total"], 0)
            self.assertEqual(stats["insights"]["total"], 0)

            conn = sqlite3.connect(local_db)
            self.addCleanup(conn.close)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(service_module.REQUIRED_TABLES.issubset(tables))

    def _insert_insight(
        self,
        intel: IntelligenceLayer,
        *,
        created_at: datetime,
        updated_at: datetime,
        confidence: float = 0.8,
    ) -> int:
        cursor = intel.conn.cursor()
        cursor.execute(
            """
            INSERT INTO insights (
                created_at, updated_at, insight_type, description,
                applies_to_pattern, preferred_tools, confidence,
                strength, evidence_count, times_applied, times_helpful,
                times_failed, consecutive_failures
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at.isoformat(),
                updated_at.isoformat(),
                "tool_preference",
                "Use crypto_price for current crypto prices.",
                "Current crypto price queries",
                '{"crypto_price": 0.8}',
                confidence,
                0.5,
                1,
                0,
                0,
                0,
                0,
            ),
        )
        intel.conn.commit()
        return cursor.lastrowid

    def test_decay_uses_updated_at_not_only_created_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            insight_id = self._insert_insight(
                intel,
                created_at=datetime.now() - timedelta(days=45),
                updated_at=datetime.now(),
                confidence=0.8,
            )

            stats = asyncio.run(intel.run_decay_job(force=True))
            confidence = intel.conn.execute(
                "SELECT confidence FROM insights WHERE id = ?",
                (insight_id,),
            ).fetchone()["confidence"]

            self.assertEqual(stats["decayed"], 0)
            self.assertAlmostEqual(confidence, 0.8)

    def test_decay_dry_run_does_not_write_or_record_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            insight_id = self._insert_insight(
                intel,
                created_at=datetime.now() - timedelta(days=45),
                updated_at=datetime.now() - timedelta(days=45),
                confidence=0.8,
            )

            stats = asyncio.run(intel.run_decay_job(force=True, dry_run=True))
            row = intel.conn.execute(
                "SELECT confidence FROM insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
            maintenance_rows = intel.conn.execute(
                "SELECT COUNT(*) FROM meta_knowledge WHERE meta_type = 'decay_job_run'"
            ).fetchone()[0]

            self.assertTrue(stats["dry_run"])
            self.assertGreater(stats["decayed"], 0)
            self.assertAlmostEqual(row["confidence"], 0.8)
            self.assertEqual(maintenance_rows, 0)

    def test_decay_caps_time_window_to_previous_decay_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            insight_id = self._insert_insight(
                intel,
                created_at=datetime.now() - timedelta(days=100),
                updated_at=datetime.now() - timedelta(days=100),
                confidence=0.8,
            )
            intel.conn.execute(
                """
                INSERT INTO meta_knowledge (
                    meta_type, description, observation, conclusion, action_taken, confidence, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "decay_job_run",
                    "Previous decay maintenance job executed",
                    "Checked test insights",
                    "Previous decay applied",
                    "decay_applied",
                    1.0,
                    (datetime.now() - timedelta(days=14)).isoformat(),
                ),
            )
            intel.conn.commit()

            stats = asyncio.run(intel.run_decay_job(force=True))
            confidence = intel.conn.execute(
                "SELECT confidence FROM insights WHERE id = ?",
                (insight_id,),
            ).fetchone()["confidence"]

            expected = 0.8 * (0.95 ** (14 / 7))
            self.assertEqual(stats["decayed"], 1)
            self.assertAlmostEqual(confidence, expected, places=4)

    def test_ui_delete_experience_unlinks_evidence_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            exp_id = asyncio.run(
                intel.record_experience(
                    query="email this youtube video",
                    tools_used=["youtube_video", "send_email"],
                    outcome={"success": True, "turns": 2},
                    context={"web_conversation_id": "web-delete"},
                )
            )
            experience = intel.conn.execute(
                "SELECT * FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone()
            insight_id = asyncio.run(
                intel._store_insight(
                    {
                        "is_procedural": True,
                        "knowledge_type": "procedural",
                        "preferred_tool": "send_email",
                        "applies_to": "Sending YouTube links",
                        "confidence": 0.8,
                        "insight_summary": "Use send_email for sending YouTube links.",
                    },
                    experience,
                )
            )
            intel.close()

            service_module = load_intelligence_service_module()
            service_module.DB_PATHS["cloud"] = Path(tmpdir) / "intel.db"
            service = service_module.IntelligenceService("cloud")
            self.assertTrue(service.delete_experience(exp_id))

            conn = sqlite3.connect(Path(tmpdir) / "intel.db")
            conn.row_factory = sqlite3.Row
            self.addCleanup(conn.close)

            self.assertIsNone(conn.execute(
                "SELECT 1 FROM experiences WHERE id = ?",
                (exp_id,),
            ).fetchone())
            insight = conn.execute(
                "SELECT source_experience_id, source_web_conversation_id FROM insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
            evidence = conn.execute(
                "SELECT experience_id, web_conversation_id, query FROM insight_evidence WHERE insight_id = ?",
                (insight_id,),
            ).fetchone()

            self.assertIsNone(insight["source_experience_id"])
            self.assertEqual(insight["source_web_conversation_id"], "web-delete")
            self.assertIsNone(evidence["experience_id"])
            self.assertEqual(evidence["web_conversation_id"], "web-delete")
            self.assertIn("youtube", evidence["query"])

    def test_ui_experience_list_sort_filters_and_summary_are_global(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            intel = self._make_intel(tmpdir)
            asyncio.run(
                intel.record_experience(
                    query="answer from memory",
                    tools_used=[],
                    outcome={"success": True, "turns": 1},
                    context={},
                )
            )
            asyncio.run(
                intel.record_experience(
                    query="current bitcoin price",
                    tools_used=["crypto_price"],
                    outcome={"success": True, "turns": 1},
                    context={},
                )
            )
            canvas_exp_id = asyncio.run(
                intel.record_experience(
                    query="current bitcoin price and canvas",
                    tools_used=["crypto_price", "canvas"],
                    outcome={"success": True, "turns": 3},
                    context={},
                )
            )
            raw_data = intel.conn.execute(
                "SELECT raw_data FROM experiences WHERE id = ?",
                (canvas_exp_id,),
            ).fetchone()["raw_data"]
            raw_data = json.loads(raw_data)
            raw_data["completion_guard"] = {"status": "repaired"}
            intel.conn.execute(
                "UPDATE experiences SET raw_data = ? WHERE id = ?",
                (json.dumps(raw_data), canvas_exp_id),
            )
            intel.conn.commit()
            intel.close()

            service_module = load_intelligence_service_module()
            service_module.DB_PATHS["cloud"] = Path(tmpdir) / "intel.db"
            service = service_module.IntelligenceService("cloud")

            sorted_experiences, total = service.list_experiences(limit=1, sort="tools")
            self.assertEqual(total, 3)
            self.assertEqual(sorted_experiences[0]["id"], canvas_exp_id)

            canvas_only, canvas_total = service.list_experiences(tool="canvas")
            self.assertEqual(canvas_total, 1)
            self.assertEqual(canvas_only[0]["id"], canvas_exp_id)

            repaired, repaired_total = service.list_experiences(completion_guard_status="repaired")
            self.assertEqual(repaired_total, 1)
            self.assertEqual(repaired[0]["id"], canvas_exp_id)

            summary = service.get_experience_summary()
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["tool_count"]["none"], 1)
            self.assertEqual(summary["tool_count"]["single"], 1)
            self.assertEqual(summary["tool_count"]["multi"], 1)
            self.assertEqual(summary["completion_guard"]["repaired"], 1)
            tool_counts = {tool["name"]: tool["count"] for tool in summary["tools"]}
            self.assertEqual(tool_counts["crypto_price"], 2)
            self.assertEqual(tool_counts["canvas"], 1)


if __name__ == "__main__":
    unittest.main()
