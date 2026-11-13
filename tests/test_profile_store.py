"""Tests for ProfileStore persistence, baseline protection, and JSON export/import."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ip_matcher.profile_store import ProfileStore


class TestProfileStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProfileStore(Path(self.tmp.name) / "test.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_baseline_is_created_once_and_protected(self) -> None:
        b1 = self.store.ensure_baseline({"timezone_id": "Iran Standard Time", "geo_id": 116})
        b2 = self.store.ensure_baseline({"timezone_id": "UTC", "geo_id": 244})
        self.assertEqual(b1["id"], b2["id"])
        self.assertEqual(b2["state"]["geo_id"], 116)
        self.assertFalse(self.store.delete_snapshot(b1["id"]))

    def test_auto_snapshot_pruning_and_undo_lookup(self) -> None:
        for idx in range(5):
            self.store.save_snapshot(
                name=f"Auto {idx}",
                kind="auto",
                state={"geo_id": idx},
                max_auto_keep=3,
            )
        autos = self.store.list_snapshots(kind="auto")
        self.assertEqual(len(autos), 3)
        latest = self.store.get_latest_auto_snapshot()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["name"], "Auto 4")

    def test_export_and_import_roundtrip(self) -> None:
        self.store.save_snapshot("Germany Work", "custom", {"geo_id": 94, "culture": "de-DE"})
        exported = self.store.export_profiles_json()

        store2 = ProfileStore(Path(self.tmp.name) / "test2.db")
        count = store2.import_profiles_json(exported)
        self.assertEqual(count, 1)
        items = store2.list_snapshots()
        self.assertEqual(items[0]["name"], "Germany Work")
        self.assertEqual(items[0]["state"]["geo_id"], 94)


if __name__ == "__main__":
    unittest.main()
