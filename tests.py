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
    VALID_KINDS,
    DEPTH_ORDER,
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
        for t in ("entries", "entries_fts", "classes", "classes_fts",
                   "functions", "properties", "analysis_log"):
            self.assertIn(t, tables)

    def test_indexes_exist(self):
        indexes = {
            r[0]
            for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        expected = {
            "idx_entries_subsystem", "idx_entries_category", "idx_entries_updated",
            "idx_classes_name", "idx_classes_parent", "idx_classes_subsystem",
            "idx_classes_module", "idx_classes_kind", "idx_classes_depth",
            "idx_functions_class", "idx_functions_subsystem", "idx_functions_name",
            "idx_functions_qualified",
            "idx_properties_class", "idx_properties_subsystem", "idx_properties_qualified",
            "idx_analysis_file", "idx_analysis_module",
        }
        for idx in expected:
            self.assertIn(idx, indexes)

    def test_triggers_exist(self):
        triggers = {
            r[0]
            for r in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        expected = {"entries_ai", "entries_au", "entries_ad",
                     "classes_ai", "classes_au", "classes_ad"}
        self.assertEqual(triggers, expected)

    def test_empty_db_stats(self):
        stats = self.db.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["by_subsystem"], {})
        self.assertEqual(stats["by_category"], {})
        self.assertEqual(stats["structured"]["classes"], 0)
        self.assertEqual(stats["structured"]["functions"], 0)
        self.assertEqual(stats["structured"]["properties"], 0)
        self.assertEqual(stats["structured"]["files_analyzed"], 0)


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


# ── Structured code table tests ───────────────────────────────────────────────


class _DBTestCase(unittest.TestCase):
    """Base class with setUp/tearDown for temp DB."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        with patch("server.DB_PATH", Path(self.tmp.name)):
            self.db = KnowledgeDB()

    def tearDown(self):
        self.db.close()
        Path(self.tmp.name).unlink(missing_ok=True)


class TestSaveClass(_DBTestCase):
    """Saving classes: create, upsert/merge, validation."""

    def _save_actor(self, **overrides):
        defaults = dict(
            name="AActor", kind="class", subsystem="gameplay",
            module="Engine", header_path="Runtime/Engine/Classes/GameFramework/Actor.h",
        )
        defaults.update(overrides)
        return self.db.save_class(**defaults)

    def test_create_returns_id(self):
        result = self._save_actor()
        self.assertTrue(result["upserted"])
        self.assertEqual(result["action"], "created")
        self.assertGreater(result["id"], 0)

    def test_get_class(self):
        self._save_actor(summary="Base actor class")
        cls = self.db.get_class("AActor")
        self.assertIsNotNone(cls)
        self.assertEqual(cls["name"], "AActor")
        self.assertEqual(cls["kind"], "class")
        self.assertEqual(cls["summary"], "Base actor class")

    def test_get_class_nonexistent(self):
        self.assertIsNone(self.db.get_class("UNonexistent"))

    def test_upsert_updates_existing(self):
        self._save_actor()
        result = self._save_actor(summary="Updated summary")
        self.assertEqual(result["action"], "updated")
        cls = self.db.get_class("AActor")
        self.assertEqual(cls["summary"], "Updated summary")

    def test_upsert_merges_arrays(self):
        self._save_actor(known_children=["APawn"])
        self._save_actor(known_children=["AInfo", "APawn"])
        cls = self.db.get_class("AActor")
        self.assertEqual(sorted(cls["known_children"]), ["AInfo", "APawn"])

    def test_upsert_merges_interfaces(self):
        self._save_actor(interfaces=["INavAgentInterface"])
        self._save_actor(interfaces=["IVisualLoggerDebugSnapshotInterface"])
        cls = self.db.get_class("AActor")
        self.assertEqual(len(cls["interfaces"]), 2)

    def test_depth_only_upgrades(self):
        self._save_actor(analysis_depth="stub")
        self._save_actor(analysis_depth="shallow")
        cls = self.db.get_class("AActor")
        self.assertEqual(cls["analysis_depth"], "shallow")

    def test_depth_does_not_downgrade(self):
        self._save_actor(analysis_depth="deep")
        self._save_actor(analysis_depth="stub")
        cls = self.db.get_class("AActor")
        self.assertEqual(cls["analysis_depth"], "deep")

    def test_invalid_kind(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_actor(kind="invalid")
        self.assertIn("Invalid kind", str(ctx.exception))

    def test_invalid_subsystem(self):
        with self.assertRaises(ValueError) as ctx:
            self._save_actor(subsystem="invalid")
        self.assertIn("Invalid subsystem", str(ctx.exception))

    def test_all_valid_kinds(self):
        for kind in VALID_KINDS:
            result = self.db.save_class(
                name=f"Test{kind}", kind=kind, subsystem="core",
                module="Core", header_path="test.h",
            )
            self.assertTrue(result["upserted"])

    def test_json_arrays_deserialized_on_get(self):
        self._save_actor(
            key_methods=[{"name": "BeginPlay", "brief": "Start"}],
            key_properties=[{"name": "RootComponent", "type": "USceneComponent*", "specifiers": ""}],
            key_delegates=[{"name": "OnDestroyed", "signature": "FActorDestroyedSignature"}],
        )
        cls = self.db.get_class("AActor")
        self.assertIsInstance(cls["key_methods"], list)
        self.assertEqual(cls["key_methods"][0]["name"], "BeginPlay")
        self.assertIsInstance(cls["key_properties"], list)
        self.assertIsInstance(cls["key_delegates"], list)

    def test_parent_class_stored(self):
        self._save_actor(parent_class="UObject")
        cls = self.db.get_class("AActor")
        self.assertEqual(cls["parent_class"], "UObject")

    def test_timestamps_set(self):
        self._save_actor()
        cls = self.db.get_class("AActor")
        self.assertIsNotNone(cls["created_at"])
        self.assertIsNotNone(cls["updated_at"])

    def test_stats_counts_classes(self):
        self._save_actor()
        stats = self.db.stats()
        self.assertEqual(stats["structured"]["classes"], 1)
        self.assertIn("stub", stats["structured"]["by_depth"])


class TestSaveFunction(_DBTestCase):
    """Saving functions: create, upsert, validation."""

    def _save_beginplay(self, **overrides):
        defaults = dict(
            name="BeginPlay", subsystem="gameplay",
            class_name="AActor", return_type="void",
            is_virtual=True, summary="Called when play begins.",
        )
        defaults.update(overrides)
        return self.db.save_function(**defaults)

    def test_create(self):
        result = self._save_beginplay()
        self.assertTrue(result["upserted"])
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["qualified_name"], "AActor::BeginPlay")

    def test_upsert_updates(self):
        self._save_beginplay()
        result = self._save_beginplay(summary="Updated desc")
        self.assertEqual(result["action"], "updated")

    def test_qualified_name_auto(self):
        result = self._save_beginplay()
        self.assertEqual(result["qualified_name"], "AActor::BeginPlay")

    def test_free_function_no_class(self):
        result = self.db.save_function(name="IsValid", subsystem="core")
        self.assertEqual(result["qualified_name"], "IsValid")

    def test_invalid_subsystem(self):
        with self.assertRaises(ValueError):
            self.db.save_function(name="Foo", subsystem="invalid")

    def test_parameters_stored(self):
        self._save_beginplay(parameters=[{"name": "DeltaTime", "type": "float"}])
        row = self.db.conn.execute(
            "SELECT parameters FROM functions WHERE qualified_name = 'AActor::BeginPlay'"
        ).fetchone()
        params = json.loads(row[0])
        self.assertEqual(params[0]["name"], "DeltaTime")

    def test_boolean_flags(self):
        self._save_beginplay(
            is_virtual=True, is_blueprint_callable=True, is_rpc=True,
            rpc_type="Server",
        )
        row = self.db.conn.execute(
            "SELECT is_virtual, is_blueprint_callable, is_rpc, rpc_type FROM functions WHERE qualified_name = 'AActor::BeginPlay'"
        ).fetchone()
        self.assertEqual(row[0], 1)  # is_virtual
        self.assertEqual(row[1], 1)  # is_blueprint_callable
        self.assertEqual(row[2], 1)  # is_rpc
        self.assertEqual(row[3], "Server")

    def test_call_chains_stored(self):
        self._save_beginplay(
            calls_into=["AActor::PostInitializeComponents"],
            called_by=["UWorld::BeginPlay"],
        )
        row = self.db.conn.execute(
            "SELECT calls_into, called_by FROM functions WHERE qualified_name = 'AActor::BeginPlay'"
        ).fetchone()
        self.assertIn("PostInitializeComponents", row[0])
        self.assertIn("UWorld::BeginPlay", row[1])

    def test_stats_counts_functions(self):
        self._save_beginplay()
        stats = self.db.stats()
        self.assertEqual(stats["structured"]["functions"], 1)


class TestSaveProperty(_DBTestCase):
    """Saving properties: create, upsert, validation."""

    def _save_rootcomp(self, **overrides):
        defaults = dict(
            name="RootComponent", class_name="AActor",
            subsystem="gameplay", property_type="TObjectPtr<USceneComponent>",
            uproperty_specifiers="BlueprintReadOnly, VisibleAnywhere",
        )
        defaults.update(overrides)
        return self.db.save_property(**defaults)

    def test_create(self):
        result = self._save_rootcomp()
        self.assertTrue(result["upserted"])
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["qualified_name"], "AActor::RootComponent")

    def test_upsert_updates(self):
        self._save_rootcomp()
        result = self._save_rootcomp(summary="Updated")
        self.assertEqual(result["action"], "updated")

    def test_invalid_subsystem(self):
        with self.assertRaises(ValueError):
            self._save_rootcomp(subsystem="invalid")

    def test_replication_fields(self):
        self._save_rootcomp(
            is_replicated=True,
            replicated_using="OnRep_RootComponent",
        )
        row = self.db.conn.execute(
            "SELECT is_replicated, replicated_using FROM properties WHERE qualified_name = 'AActor::RootComponent'"
        ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "OnRep_RootComponent")

    def test_blueprint_flags(self):
        self._save_rootcomp(
            is_blueprint_visible=True,
            is_edit_anywhere=True,
            is_config=False,
        )
        row = self.db.conn.execute(
            "SELECT is_blueprint_visible, is_edit_anywhere, is_config FROM properties WHERE qualified_name = 'AActor::RootComponent'"
        ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 1)
        self.assertEqual(row[2], 0)

    def test_stats_counts_properties(self):
        self._save_rootcomp()
        stats = self.db.stats()
        self.assertEqual(stats["structured"]["properties"], 1)


class TestQueryHierarchy(_DBTestCase):
    """Hierarchy traversal: parents and children."""

    def setUp(self):
        super().setUp()
        self.db.save_class(name="UObject", kind="class", subsystem="core",
                           module="CoreUObject", header_path="UObject/Object.h")
        self.db.save_class(name="AActor", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Actor.h", parent_class="UObject")
        self.db.save_class(name="APawn", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Pawn.h", parent_class="AActor")
        self.db.save_class(name="ACharacter", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Character.h", parent_class="APawn")
        self.db.save_class(name="AInfo", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Info.h", parent_class="AActor")

    def test_parents_chain(self):
        result = self.db.query_hierarchy("ACharacter", direction="parents")
        self.assertEqual(result["parents"], ["APawn", "AActor", "UObject"])
        self.assertEqual(result["children"], [])

    def test_children(self):
        result = self.db.query_hierarchy("AActor", direction="children")
        child_names = [c["name"] for c in result["children"]]
        self.assertIn("APawn", child_names)
        self.assertIn("AInfo", child_names)

    def test_both_directions(self):
        result = self.db.query_hierarchy("APawn", direction="both")
        self.assertIn("AActor", result["parents"])
        child_names = [c["name"] for c in result["children"]]
        self.assertIn("ACharacter", child_names)

    def test_root_has_no_parents(self):
        result = self.db.query_hierarchy("UObject", direction="parents")
        self.assertEqual(result["parents"], [])

    def test_leaf_has_no_children(self):
        result = self.db.query_hierarchy("ACharacter", direction="children")
        self.assertEqual(result["children"], [])

    def test_depth_limit(self):
        result = self.db.query_hierarchy("ACharacter", direction="parents", depth=1)
        self.assertEqual(len(result["parents"]), 1)
        self.assertEqual(result["parents"][0], "APawn")

    def test_nested_children_structure(self):
        result = self.db.query_hierarchy("AActor", direction="children")
        # APawn should have ACharacter as child
        pawn = next(c for c in result["children"] if c["name"] == "APawn")
        char_names = [c["name"] for c in pawn["children"]]
        self.assertIn("ACharacter", char_names)


class TestQueryCalls(_DBTestCase):
    """Call chain queries."""

    def setUp(self):
        super().setUp()
        self.db.save_function(
            name="BeginPlay", subsystem="gameplay", class_name="AActor",
            summary="Called when play begins.",
            call_context="Called by engine after all components initialized.",
            call_order="After PostInitializeComponents",
            calls_into=["AActor::ReceiveBeginPlay"],
            called_by=["UWorld::BeginPlay"],
        )

    def test_query_by_qualified_name(self):
        result = self.db.query_calls("AActor::BeginPlay")
        self.assertEqual(result["function"], "AActor::BeginPlay")
        self.assertIn("calls_into", result)
        self.assertIn("called_by", result)

    def test_query_by_plain_name(self):
        result = self.db.query_calls("BeginPlay")
        self.assertEqual(result["function"], "AActor::BeginPlay")

    def test_callees_only(self):
        result = self.db.query_calls("AActor::BeginPlay", direction="callees")
        self.assertIn("calls_into", result)
        self.assertNotIn("called_by", result)

    def test_callers_only(self):
        result = self.db.query_calls("AActor::BeginPlay", direction="callers")
        self.assertIn("called_by", result)
        self.assertNotIn("calls_into", result)

    def test_not_found(self):
        result = self.db.query_calls("Nonexistent::Func")
        self.assertIn("error", result)


class TestQueryClassFull(_DBTestCase):
    """Full class query with linked functions and properties."""

    def setUp(self):
        super().setUp()
        self.db.save_class(
            name="AActor", kind="class", subsystem="gameplay",
            module="Engine", header_path="Actor.h",
            parent_class="UObject", summary="Base actor.",
        )
        self.db.save_function(
            name="BeginPlay", subsystem="gameplay", class_name="AActor",
            summary="Begin play.", is_virtual=True,
        )
        self.db.save_property(
            name="RootComponent", class_name="AActor",
            subsystem="gameplay", property_type="USceneComponent*",
        )

    def test_full_query(self):
        result = self.db.query_class_full("AActor")
        self.assertEqual(result["name"], "AActor")
        self.assertEqual(len(result["functions"]), 1)
        self.assertEqual(result["functions"][0]["name"], "BeginPlay")
        self.assertEqual(len(result["properties_detail"]), 1)
        self.assertEqual(result["properties_detail"][0]["name"], "RootComponent")

    def test_exclude_methods(self):
        result = self.db.query_class_full("AActor", include_methods=False)
        self.assertNotIn("functions", result)

    def test_exclude_properties(self):
        result = self.db.query_class_full("AActor", include_properties=False)
        self.assertNotIn("properties_detail", result)

    def test_not_found(self):
        result = self.db.query_class_full("UNonexistent")
        self.assertIn("error", result)

    def test_linked_narrative_entry(self):
        entry_id = self.db.save("AActor lifecycle", "gameplay", "class", "s", "c")
        self.db.save_class(
            name="AActor", kind="class", subsystem="gameplay",
            module="Engine", header_path="Actor.h", entry_id=entry_id,
        )
        result = self.db.query_class_full("AActor")
        self.assertIn("narrative_entry", result)
        self.assertEqual(result["narrative_entry"]["id"], entry_id)


class TestAnalysisLog(_DBTestCase):
    """Analysis logging and status."""

    def test_log_analysis(self):
        result = self.db.log_analysis(
            file_path="Runtime/Engine/Classes/GameFramework/Actor.h",
            module="Engine", subsystem="gameplay", analysis_depth="shallow",
            classes_found=3, functions_found=15, properties_found=8,
        )
        self.assertTrue(result["logged"])
        self.assertGreater(result["id"], 0)

    def test_log_invalid_subsystem(self):
        with self.assertRaises(ValueError):
            self.db.log_analysis(
                file_path="test.h", module="Test",
                subsystem="invalid", analysis_depth="stub",
            )

    def test_analysis_status_empty(self):
        result = self.db.analysis_status()
        self.assertEqual(result["total_classes"], 0)
        self.assertEqual(result["files_analyzed"], 0)

    def test_analysis_status_with_data(self):
        self.db.save_class(name="AActor", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Actor.h", analysis_depth="shallow")
        self.db.log_analysis(
            file_path="Actor.h", module="Engine",
            subsystem="gameplay", analysis_depth="shallow",
        )
        result = self.db.analysis_status()
        self.assertEqual(result["total_classes"], 1)
        self.assertEqual(result["files_analyzed"], 1)
        self.assertEqual(result["by_depth"]["shallow"], 1)
        self.assertIn("Engine", result["breakdown"])

    def test_analysis_status_filter_by_module(self):
        self.db.log_analysis(file_path="A.h", module="Engine", subsystem="gameplay", analysis_depth="shallow")
        self.db.log_analysis(file_path="B.h", module="CoreUObject", subsystem="core", analysis_depth="stub")
        result = self.db.analysis_status(module="Engine")
        self.assertIn("Engine", result["breakdown"])
        self.assertNotIn("CoreUObject", result["breakdown"])

    def test_analysis_status_filter_by_subsystem(self):
        self.db.log_analysis(file_path="A.h", module="Engine", subsystem="gameplay", analysis_depth="shallow")
        self.db.log_analysis(file_path="B.h", module="CoreUObject", subsystem="core", analysis_depth="stub")
        result = self.db.analysis_status(subsystem="gameplay")
        # breakdown should only contain Engine (the one with gameplay subsystem)
        for key, depths in result["breakdown"].items():
            total = sum(depths.values())
            self.assertGreater(total, 0)

    def test_stats_counts_files_analyzed(self):
        self.db.log_analysis(file_path="A.h", module="M", subsystem="core", analysis_depth="stub")
        stats = self.db.stats()
        self.assertEqual(stats["structured"]["files_analyzed"], 1)


class TestHandleStructured(_DBTestCase):
    """MCP _handle dispatcher for structured code tools."""

    def test_handle_save_class(self):
        result = _handle(self.db, "ue_save_class", {
            "name": "AActor", "kind": "class", "subsystem": "gameplay",
            "module": "Engine", "header_path": "Actor.h",
            "summary": "Base actor",
        })
        self.assertTrue(result["upserted"])
        self.assertEqual(result["name"], "AActor")

    def test_handle_save_class_invalid_kind(self):
        with self.assertRaises(ValueError):
            _handle(self.db, "ue_save_class", {
                "name": "AActor", "kind": "invalid", "subsystem": "gameplay",
                "module": "Engine", "header_path": "Actor.h",
            })

    def test_handle_save_function(self):
        result = _handle(self.db, "ue_save_function", {
            "name": "BeginPlay", "subsystem": "gameplay",
            "class_name": "AActor", "is_virtual": True,
        })
        self.assertTrue(result["upserted"])
        self.assertEqual(result["qualified_name"], "AActor::BeginPlay")

    def test_handle_save_property(self):
        result = _handle(self.db, "ue_save_property", {
            "name": "RootComponent", "class_name": "AActor",
            "subsystem": "gameplay", "property_type": "USceneComponent*",
        })
        self.assertTrue(result["upserted"])
        self.assertEqual(result["qualified_name"], "AActor::RootComponent")

    def test_handle_query_class(self):
        self.db.save_class(name="AActor", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Actor.h")
        result = _handle(self.db, "ue_query_class", {"class_name": "AActor"})
        self.assertEqual(result["name"], "AActor")

    def test_handle_query_class_not_found(self):
        result = _handle(self.db, "ue_query_class", {"class_name": "UNonexistent"})
        self.assertIn("error", result)

    def test_handle_query_hierarchy(self):
        self.db.save_class(name="UObject", kind="class", subsystem="core",
                           module="CoreUObject", header_path="Object.h")
        self.db.save_class(name="AActor", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Actor.h", parent_class="UObject")
        result = _handle(self.db, "ue_query_hierarchy", {
            "class_name": "AActor", "direction": "parents",
        })
        self.assertIn("UObject", result["parents"])

    def test_handle_query_calls(self):
        self.db.save_function(name="BeginPlay", subsystem="gameplay", class_name="AActor",
                              calls_into=["AActor::ReceiveBeginPlay"])
        result = _handle(self.db, "ue_query_calls", {"function_name": "AActor::BeginPlay"})
        self.assertEqual(result["function"], "AActor::BeginPlay")

    def test_handle_analysis_status(self):
        result = _handle(self.db, "ue_analysis_status", {})
        self.assertIn("total_classes", result)
        self.assertIn("files_analyzed", result)

    def test_handle_log_analysis(self):
        result = _handle(self.db, "ue_log_analysis", {
            "file_path": "Actor.h", "module": "Engine",
            "subsystem": "gameplay", "analysis_depth": "shallow",
        })
        self.assertTrue(result["logged"])

    def test_handle_save_class_does_not_mutate_args(self):
        args = {"name": "AActor", "kind": "class", "subsystem": "gameplay",
                "module": "Engine", "header_path": "Actor.h"}
        args_copy = dict(args)
        _handle(self.db, "ue_save_class", args)
        self.assertEqual(args, args_copy)

    def test_handle_stats_includes_structured(self):
        self.db.save_class(name="AActor", kind="class", subsystem="gameplay",
                           module="Engine", header_path="Actor.h")
        result = _handle(self.db, "ue_stats", {})
        self.assertIn("structured", result)
        self.assertEqual(result["structured"]["classes"], 1)


if __name__ == "__main__":
    unittest.main()
