#!/usr/bin/env python3
"""Regression tests for Intelligence maintenance safety."""

import asyncio
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
