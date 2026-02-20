"""Tests for UE Knowledge Base MCP server."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import (
    KnowledgeDB,
    VALID_SUBSYSTEMS,
    VALID_CATEGORIES,
    _handle,
    SCHEMA,
)


class TestSchema(unittest.TestCase):
    """Database schema: tables, indexes, triggers, pragmas."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_wal_mode(self):
        mode = self.db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode, "wal")

    def test_tables_exist(self):
        tables = {
            r[0]
            for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("entries", tables)
        self.assertIn("entries_fts", tables)

    def test_indexes_exist(self):
        indexes = {
            r[0]
            for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        self.assertIn("idx_entries_subsystem", indexes)
        self.assertIn("idx_entries_category", indexes)
        self.assertIn("idx_entries_updated", indexes)

    def test_triggers_exist(self):
        triggers = {
            r[0]
            for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        self.assertEqual(triggers, {"entries_ai", "entries_au", "entries_ad"})

    def test_empty_db_stats(self):
        stats = self.db.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["by_subsystem"], {})
        self.assertEqual(stats["by_category"], {})


class TestSave(unittest.TestCase):
    """Saving entries: normal flow, validation, duplicates."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def _save_sample(self, title="AActor lifecycle", **overrides):
        defaults = dict(
            title=title,
            subsystem="gameplay",
            category="class",
            summary="Base actor lifecycle.",
            content="BeginPlay -> Tick -> EndPlay",
        )
        defaults.update(overrides)
        return self.db.save(**defaults)

    def test_save_returns_id(self):
        result = self._save_sample()
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)

    def test_save_increments_id(self):
        id1 = self._save_sample("Entry A")
        id2 = self._save_sample("Entry B")
        self.assertEqual(id2, id1 + 1)

    def test_save_with_optional_fields(self):
        entry_id = self._save_sample(
            source_files=["Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h"],
            tags=["actor", "lifecycle"],
            related_entries=[],
        )
        entry = self.db.get(entry_id)
        self.assertEqual(json.loads(entry["tags"]), ["actor", "lifecycle"])
        self.assertEqual(
            json.loads(entry["source_files"]),
            ["Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h"],
        )

    def test_save_sets_timestamps(self):
        entry_id = self._save_sample()
        entry = self.db.get(entry_id)
        self.assertIsNotNone(entry["created_at"])
        self.assertIsNotNone(entry["updated_at"])
        self.assertEqual(entry["created_at"], entry["updated_at"])

    def test_save_invalid_subsystem(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_sample(subsystem="invalid")
        self.assertIn("Invalid subsystem", str(ctx.exception))

    def test_save_invalid_category(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_sample(category="invalid")
        self.assertIn("Invalid category", str(ctx.exception))

    def test_save_all_valid_subsystems(self):
        for i, sub in enumerate(VALID_SUBSYSTEMS):
            result = self._save_sample(title=f"Entry {sub}", subsystem=sub)
            self.assertIsInstance(result, int)

    def test_save_all_valid_categories(self):
        for cat in VALID_CATEGORIES:
            result = self._save_sample(title=f"Entry {cat}", category=cat)
            self.assertIsInstance(result, int)

    def test_duplicate_title_rejected(self):
        self._save_sample("Duplicate Title")
        result = self._save_sample("Duplicate Title")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["duplicate"])
        self.assertIn("existing_id", result)

    def test_duplicate_check_is_exact(self):
        self._save_sample("AActor lifecycle")
        result = self._save_sample("AActor lifecycle overview")
        self.assertIsInstance(result, int)


class TestGet(unittest.TestCase):
    """Getting entries by ID."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_get_existing(self):
        entry_id = self.db.save("Test", "core", "class", "s", "c")
        entry = self.db.get(entry_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["title"], "Test")
        self.assertEqual(entry["subsystem"], "core")

    def test_get_nonexistent(self):
        self.assertIsNone(self.db.get(9999))

    def test_get_returns_all_fields(self):
        entry_id = self.db.save("Test", "core", "class", "sum", "content")
        entry = self.db.get(entry_id)
        expected_keys = {
            "id", "title", "subsystem", "category", "summary", "content",
            "source_files", "tags", "related_entries", "created_at", "updated_at",
        }
        self.assertEqual(set(entry.keys()), expected_keys)


class TestSearch(unittest.TestCase):
    """FTS5 full-text search."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.db.save("AActor lifecycle", "gameplay", "class", "Actor lifecycle hooks.", "BeginPlay Tick EndPlay")
        self.db.save("APawn movement", "gameplay", "class", "Pawn movement component.", "AddMovementInput")
        self.db.save("UPROPERTY specifiers", "core", "macro", "Property macro specifiers.", "EditAnywhere BlueprintReadWrite Replicated")
        self.db.save("Replication overview", "networking", "architecture", "How replication works.", "DOREPLIFETIME GetLifetimeReplicatedProps")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_search_finds_match(self):
        results = self.db.search("lifecycle")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["title"], "AActor lifecycle")

    def test_search_prefix_matching(self):
        # porter stemmer: "replication" -> "replic", so prefix "replic" matches
        results = self.db.search("replic")
        titles = [r["title"] for r in results]
        self.assertIn("Replication overview", titles)

    def test_search_multiple_terms(self):
        results = self.db.search("actor lifecycle")
        self.assertGreater(len(results), 0)

    def test_search_filter_by_subsystem(self):
        results = self.db.search("class", subsystem="core")
        for r in results:
            self.assertEqual(r["subsystem"], "core")

    def test_search_filter_by_category(self):
        results = self.db.search("replication", category="architecture")
        for r in results:
            self.assertEqual(r["category"], "architecture")

    def test_search_respects_limit(self):
        results = self.db.search("a", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_search_empty_query(self):
        self.assertEqual(self.db.search(""), [])
        self.assertEqual(self.db.search("   "), [])

    def test_search_quotes_sanitized(self):
        results = self.db.search('actor "test')
        # Should not raise, may or may not find results
        self.assertIsInstance(results, list)

    def test_search_only_quotes(self):
        results = self.db.search('" " "')
        self.assertIsInstance(results, list)

    def test_search_no_content_in_results(self):
        results = self.db.search("lifecycle")
        self.assertGreater(len(results), 0)
        self.assertNotIn("content", results[0])

    def test_search_has_score(self):
        results = self.db.search("lifecycle")
        self.assertIn("score", results[0])

    def test_search_no_match(self):
        results = self.db.search("xyznonexistent")
        self.assertEqual(results, [])


class TestList(unittest.TestCase):
    """Listing entries with filters."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.db.save("A", "gameplay", "class", "s", "c")
        self.db.save("B", "gameplay", "gotcha", "s", "c")
        self.db.save("C", "core", "class", "s", "c")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_list_all(self):
        entries = self.db.list_entries()
        self.assertEqual(len(entries), 3)

    def test_list_filter_subsystem(self):
        entries = self.db.list_entries(subsystem="gameplay")
        self.assertEqual(len(entries), 2)

    def test_list_filter_category(self):
        entries = self.db.list_entries(category="class")
        self.assertEqual(len(entries), 2)

    def test_list_filter_both(self):
        entries = self.db.list_entries(subsystem="gameplay", category="class")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "A")

    def test_list_limit(self):
        entries = self.db.list_entries(limit=1)
        self.assertEqual(len(entries), 1)

    def test_list_offset(self):
        all_entries = self.db.list_entries()
        offset_entries = self.db.list_entries(offset=1)
        self.assertEqual(len(offset_entries), len(all_entries) - 1)

    def test_list_ordered_by_updated(self):
        entries = self.db.list_entries()
        dates = [e["updated_at"] for e in entries]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_list_empty_filter(self):
        entries = self.db.list_entries(subsystem="networking")
        self.assertEqual(entries, [])


class TestUpdate(unittest.TestCase):
    """Updating entries."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.entry_id = self.db.save("Original", "core", "class", "s", "c")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_update_title(self):
        self.assertTrue(self.db.update(self.entry_id, title="Updated"))
        self.assertEqual(self.db.get(self.entry_id)["title"], "Updated")

    def test_update_summary(self):
        self.assertTrue(self.db.update(self.entry_id, summary="New summary"))
        self.assertEqual(self.db.get(self.entry_id)["summary"], "New summary")

    def test_update_content(self):
        self.assertTrue(self.db.update(self.entry_id, content="New content"))
        self.assertEqual(self.db.get(self.entry_id)["content"], "New content")

    def test_update_subsystem(self):
        self.assertTrue(self.db.update(self.entry_id, subsystem="gameplay"))
        self.assertEqual(self.db.get(self.entry_id)["subsystem"], "gameplay")

    def test_update_tags_list(self):
        self.assertTrue(self.db.update(self.entry_id, tags=["a", "b"]))
        entry = self.db.get(self.entry_id)
        self.assertEqual(json.loads(entry["tags"]), ["a", "b"])

    def test_update_bumps_updated_at(self):
        before = self.db.get(self.entry_id)["updated_at"]
        self.db.update(self.entry_id, title="Changed")
        after = self.db.get(self.entry_id)["updated_at"]
        self.assertNotEqual(before, after)

    def test_update_invalid_subsystem(self):
        with self.assertRaises(ValueError):
            self.db.update(self.entry_id, subsystem="bad")

    def test_update_invalid_category(self):
        with self.assertRaises(ValueError):
            self.db.update(self.entry_id, category="bad")

    def test_update_nonexistent(self):
        self.assertFalse(self.db.update(9999, title="X"))

    def test_update_no_fields(self):
        self.assertFalse(self.db.update(self.entry_id))

    def test_update_ignores_unknown_fields(self):
        self.assertFalse(self.db.update(self.entry_id, unknown_field="x"))

    def test_update_reflects_in_fts(self):
        self.db.update(self.entry_id, title="UniqueXYZTitle")
        results = self.db.search("UniqueXYZTitle")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.entry_id)


class TestDelete(unittest.TestCase):
    """Deleting entries."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.entry_id = self.db.save("ToDelete", "core", "class", "s", "c")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_delete_existing(self):
        self.assertTrue(self.db.delete(self.entry_id))
        self.assertIsNone(self.db.get(self.entry_id))

    def test_delete_nonexistent(self):
        self.assertFalse(self.db.delete(9999))

    def test_delete_removes_from_fts(self):
        self.db.delete(self.entry_id)
        results = self.db.search("ToDelete")
        self.assertEqual(results, [])

    def test_delete_updates_stats(self):
        self.assertEqual(self.db.stats()["total"], 1)
        self.db.delete(self.entry_id)
        self.assertEqual(self.db.stats()["total"], 0)


class TestHandle(unittest.TestCase):
    """MCP _handle dispatcher: args safety, routing, error handling."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.entry_id = self.db.save("HandleTest", "core", "class", "s", "c")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_handle_save(self):
        result = _handle(self.db, "ue_save", {
            "title": "New Entry",
            "subsystem": "core",
            "category": "pattern",
            "summary": "Test",
            "content": "Content",
        })
        self.assertTrue(result["saved"])
        self.assertIn("id", result)

    def test_handle_search(self):
        result = _handle(self.db, "ue_search", {"query": "HandleTest"})
        self.assertIn("results", result)
        self.assertIn("count", result)

    def test_handle_get(self):
        result = _handle(self.db, "ue_get", {"id": self.entry_id})
        self.assertEqual(result["title"], "HandleTest")
        self.assertIsInstance(result["tags"], list)
        self.assertIsInstance(result["source_files"], list)

    def test_handle_get_not_found(self):
        result = _handle(self.db, "ue_get", {"id": 9999})
        self.assertIn("error", result)

    def test_handle_list(self):
        result = _handle(self.db, "ue_list", {})
        self.assertIn("entries", result)
        self.assertIn("count", result)

    def test_handle_update_does_not_mutate_args(self):
        args = {"id": self.entry_id, "summary": "Updated"}
        args_copy = dict(args)
        _handle(self.db, "ue_update", args)
        self.assertEqual(args, args_copy)

    def test_handle_delete(self):
        result = _handle(self.db, "ue_delete", {"id": self.entry_id})
        self.assertTrue(result["deleted"])

    def test_handle_stats(self):
        result = _handle(self.db, "ue_stats", {})
        self.assertIn("total", result)
        self.assertIn("by_subsystem", result)
        self.assertIn("by_category", result)

    def test_handle_unknown_tool(self):
        result = _handle(self.db, "ue_nonexistent", {})
        self.assertIn("error", result)

    def test_handle_save_duplicate_via_handle(self):
        result = _handle(self.db, "ue_save", {
            "title": "HandleTest",
            "subsystem": "core",
            "category": "class",
            "summary": "Dup",
            "content": "Dup",
        })
        self.assertTrue(result.get("duplicate"))


class TestStats(unittest.TestCase):
    """Statistics accuracy."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()
        self.db.save("A", "gameplay", "class", "s", "c")
        self.db.save("B", "gameplay", "gotcha", "s", "c")
        self.db.save("C", "core", "macro", "s", "c")

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_total(self):
        self.assertEqual(self.db.stats()["total"], 3)

    def test_by_subsystem(self):
        stats = self.db.stats()
        self.assertEqual(stats["by_subsystem"]["gameplay"], 2)
        self.assertEqual(stats["by_subsystem"]["core"], 1)

    def test_by_category(self):
        stats = self.db.stats()
        self.assertEqual(stats["by_category"]["class"], 1)
        self.assertEqual(stats["by_category"]["gotcha"], 1)
        self.assertEqual(stats["by_category"]["macro"], 1)


if __name__ == "__main__":
    unittest.main()
