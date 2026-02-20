"""
UE Knowledge Base — MCP server for Unreal Engine knowledge.

SQLite + FTS5 backed knowledge base accessible as MCP tools.
Designed to be populated by Claude as it learns about UE.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ── Database ──────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".ue-knowledge" / "knowledge.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    source_files TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    related_entries TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, subsystem, category, summary, content, tags,
    content=entries, content_rowid=id,
    tokenize='porter unicode61'
);

-- Keep FTS in sync automatically
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, subsystem, category, summary, content, tags)
    VALUES (new.id, new.title, new.subsystem, new.category, new.summary, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, subsystem, category, summary, content, tags)
    VALUES ('delete', old.id, old.title, old.subsystem, old.category, old.summary, old.content, old.tags);
    INSERT INTO entries_fts(rowid, title, subsystem, category, summary, content, tags)
    VALUES (new.id, new.title, new.subsystem, new.category, new.summary, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, subsystem, category, summary, content, tags)
    VALUES ('delete', old.id, old.title, old.subsystem, old.category, old.summary, old.content, old.tags);
END;

CREATE INDEX IF NOT EXISTS idx_entries_subsystem ON entries(subsystem);
CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
CREATE INDEX IF NOT EXISTS idx_entries_updated ON entries(updated_at DESC);

-- ── Structured code tables ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    parent_class TEXT,
    outer_class TEXT,
    subsystem TEXT NOT NULL,
    module TEXT NOT NULL,
    header_path TEXT NOT NULL,
    class_specifiers TEXT DEFAULT '',
    doc_comment TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    inheritance_chain TEXT DEFAULT '[]',
    known_children TEXT DEFAULT '[]',
    interfaces TEXT DEFAULT '[]',
    key_methods TEXT DEFAULT '[]',
    key_properties TEXT DEFAULT '[]',
    key_delegates TEXT DEFAULT '[]',
    lifecycle_order TEXT DEFAULT '',
    related_classes TEXT DEFAULT '[]',
    entry_id INTEGER,
    analysis_depth TEXT DEFAULT 'stub',
    source_line_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name);
CREATE INDEX IF NOT EXISTS idx_classes_parent ON classes(parent_class);
CREATE INDEX IF NOT EXISTS idx_classes_subsystem ON classes(subsystem);
CREATE INDEX IF NOT EXISTS idx_classes_module ON classes(module);
CREATE INDEX IF NOT EXISTS idx_classes_kind ON classes(kind);
CREATE INDEX IF NOT EXISTS idx_classes_depth ON classes(analysis_depth);

CREATE VIRTUAL TABLE IF NOT EXISTS classes_fts USING fts5(
    name, parent_class, summary, doc_comment, module, lifecycle_order,
    content=classes, content_rowid=id,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS classes_ai AFTER INSERT ON classes BEGIN
    INSERT INTO classes_fts(rowid, name, parent_class, summary, doc_comment, module, lifecycle_order)
    VALUES (new.id, new.name, new.parent_class, new.summary, new.doc_comment, new.module, new.lifecycle_order);
END;
CREATE TRIGGER IF NOT EXISTS classes_au AFTER UPDATE ON classes BEGIN
    INSERT INTO classes_fts(classes_fts, rowid, name, parent_class, summary, doc_comment, module, lifecycle_order)
    VALUES ('delete', old.id, old.name, old.parent_class, old.summary, old.doc_comment, old.module, old.lifecycle_order);
    INSERT INTO classes_fts(rowid, name, parent_class, summary, doc_comment, module, lifecycle_order)
    VALUES (new.id, new.name, new.parent_class, new.summary, new.doc_comment, new.module, new.lifecycle_order);
END;
CREATE TRIGGER IF NOT EXISTS classes_ad AFTER DELETE ON classes BEGIN
    INSERT INTO classes_fts(classes_fts, rowid, name, parent_class, summary, doc_comment, module, lifecycle_order)
    VALUES ('delete', old.id, old.name, old.parent_class, old.summary, old.doc_comment, old.module, old.lifecycle_order);
END;

CREATE TABLE IF NOT EXISTS functions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL UNIQUE,
    class_name TEXT,
    subsystem TEXT NOT NULL,
    return_type TEXT DEFAULT 'void',
    parameters TEXT DEFAULT '[]',
    signature_full TEXT DEFAULT '',
    ufunction_specifiers TEXT DEFAULT '',
    is_virtual BOOLEAN DEFAULT 0,
    is_const BOOLEAN DEFAULT 0,
    is_static BOOLEAN DEFAULT 0,
    is_blueprint_callable BOOLEAN DEFAULT 0,
    is_blueprint_event BOOLEAN DEFAULT 0,
    is_rpc BOOLEAN DEFAULT 0,
    rpc_type TEXT DEFAULT '',
    doc_comment TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    call_context TEXT DEFAULT '',
    call_order TEXT DEFAULT '',
    calls_into TEXT DEFAULT '[]',
    called_by TEXT DEFAULT '[]',
    entry_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_functions_class ON functions(class_name);
CREATE INDEX IF NOT EXISTS idx_functions_subsystem ON functions(subsystem);
CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);
CREATE INDEX IF NOT EXISTS idx_functions_qualified ON functions(qualified_name);

CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL UNIQUE,
    class_name TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    property_type TEXT NOT NULL,
    default_value TEXT DEFAULT '',
    uproperty_specifiers TEXT DEFAULT '',
    is_replicated BOOLEAN DEFAULT 0,
    replicated_using TEXT DEFAULT '',
    is_blueprint_visible BOOLEAN DEFAULT 0,
    is_edit_anywhere BOOLEAN DEFAULT 0,
    is_config BOOLEAN DEFAULT 0,
    doc_comment TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    entry_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_properties_class ON properties(class_name);
CREATE INDEX IF NOT EXISTS idx_properties_subsystem ON properties(subsystem);
CREATE INDEX IF NOT EXISTS idx_properties_qualified ON properties(qualified_name);

CREATE TABLE IF NOT EXISTS analysis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    module TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    analysis_depth TEXT NOT NULL,
    classes_found INTEGER DEFAULT 0,
    functions_found INTEGER DEFAULT 0,
    properties_found INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    analyzed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analysis_file ON analysis_log(file_path);
CREATE INDEX IF NOT EXISTS idx_analysis_module ON analysis_log(module);
"""

VALID_SUBSYSTEMS = [
    "core", "gameplay", "gas", "rendering", "networking", "ui",
    "input", "animation", "ai", "physics", "audio", "editor",
    "build", "containers", "delegates", "async", "niagara",
    "pcg", "world-partition", "mass-entity", "chaos", "other",
]

VALID_CATEGORIES = [
    "class", "function", "pattern", "gotcha", "architecture",
    "example", "config", "macro", "module", "best-practice",
]

VALID_KINDS = ["class", "struct", "enum", "interface"]
DEPTH_ORDER = {"stub": 0, "shallow": 1, "deep": 2}


class KnowledgeDB:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def _check_duplicate(self, title):
        row = self.conn.execute(
            "SELECT id, title FROM entries WHERE title = ?", (title,)
        ).fetchone()
        return dict(row) if row else None

    def save(self, title, subsystem, category, summary, content,
             source_files=None, tags=None, related_entries=None):
        if subsystem not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{subsystem}'. Valid: {', '.join(VALID_SUBSYSTEMS)}")
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: '{category}'. Valid: {', '.join(VALID_CATEGORIES)}")

        duplicate = self._check_duplicate(title)
        if duplicate:
            return {"duplicate": True, "existing_id": duplicate["id"], "title": duplicate["title"]}

        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO entries
               (title, subsystem, category, summary, content,
                source_files, tags, related_entries, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title, subsystem, category, summary, content,
                json.dumps(source_files or []),
                json.dumps(tags or []),
                json.dumps(related_entries or []),
                now, now,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def search(self, query, limit=10, subsystem=None, category=None):
        terms = [t.replace('"', '').strip() for t in query.strip().split()]
        terms = [t for t in terms if t]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{t}"*' for t in terms)

        sql = """
            SELECT e.id, e.title, e.subsystem, e.category, e.summary, e.tags,
                   -entries_fts.rank AS score
            FROM entries_fts
            JOIN entries e ON e.id = entries_fts.rowid
            WHERE entries_fts MATCH ?
        """
        params = [fts_query]

        if subsystem:
            sql += " AND e.subsystem = ?"
            params.append(subsystem)
        if category:
            sql += " AND e.category = ?"
            params.append(category)

        sql += " ORDER BY score DESC LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def get(self, entry_id):
        row = self.conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_entries(self, subsystem=None, category=None, limit=20, offset=0):
        sql = "SELECT * FROM entries WHERE 1=1"
        params = []
        if subsystem:
            sql += " AND subsystem = ?"
            params.append(subsystem)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def update(self, entry_id, **fields):
        existing = self.get(entry_id)
        if not existing:
            return False

        if "subsystem" in fields and fields["subsystem"] not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{fields['subsystem']}'")
        if "category" in fields and fields["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: '{fields['category']}'")

        allowed = {"title", "subsystem", "category", "summary", "content",
                    "source_files", "tags", "related_entries"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False

        for k in ("source_files", "tags", "related_entries"):
            if k in updates and isinstance(updates[k], list):
                updates[k] = json.dumps(updates[k])

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [entry_id]
        self.conn.execute(f"UPDATE entries SET {set_clause} WHERE id = ?", values)
        self.conn.commit()
        return True

    def delete(self, entry_id):
        cursor = self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def stats(self):
        total = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        by_subsystem = dict(self.conn.execute(
            "SELECT subsystem, COUNT(*) FROM entries GROUP BY subsystem ORDER BY COUNT(*) DESC"
        ).fetchall())
        by_category = dict(self.conn.execute(
            "SELECT category, COUNT(*) FROM entries GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall())
        classes_total = self.conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        functions_total = self.conn.execute("SELECT COUNT(*) FROM functions").fetchone()[0]
        properties_total = self.conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        files_analyzed = self.conn.execute("SELECT COUNT(*) FROM analysis_log").fetchone()[0]
        by_depth = dict(self.conn.execute(
            "SELECT analysis_depth, COUNT(*) FROM classes GROUP BY analysis_depth"
        ).fetchall())
        return {
            "total": total, "by_subsystem": by_subsystem, "by_category": by_category,
            "structured": {
                "classes": classes_total, "functions": functions_total,
                "properties": properties_total, "files_analyzed": files_analyzed,
                "by_depth": by_depth,
            },
        }

    # ── Classes ───────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_json_arrays(old_json, new_list):
        old = json.loads(old_json) if old_json else []
        merged = list(old)
        for item in (new_list or []):
            if item not in merged:
                merged.append(item)
        return json.dumps(merged)

    def save_class(self, name, kind, subsystem, module, header_path, **kwargs):
        if kind not in VALID_KINDS:
            raise ValueError(f"Invalid kind: '{kind}'. Valid: {', '.join(VALID_KINDS)}")
        if subsystem not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{subsystem}'")

        now = datetime.now(timezone.utc).isoformat()
        existing = self.conn.execute("SELECT * FROM classes WHERE name = ?", (name,)).fetchone()

        if existing:
            existing = dict(existing)
            updates = {}
            # Simple fields: update if provided and non-empty
            for field in ("parent_class", "outer_class", "class_specifiers", "doc_comment",
                          "summary", "lifecycle_order", "entry_id", "source_line_count"):
                val = kwargs.get(field)
                if val is not None and val != "":
                    updates[field] = val
            # Always allow updating subsystem, module, header_path, kind
            updates["subsystem"] = subsystem
            updates["module"] = module
            updates["header_path"] = header_path
            updates["kind"] = kind
            # Merge JSON arrays
            for field in ("inheritance_chain", "known_children", "interfaces",
                          "key_methods", "key_properties", "key_delegates", "related_classes"):
                new_val = kwargs.get(field)
                if new_val:
                    updates[field] = self._merge_json_arrays(existing[field], new_val)
            # Upgrade depth only
            new_depth = kwargs.get("analysis_depth", "stub")
            if DEPTH_ORDER.get(new_depth, 0) > DEPTH_ORDER.get(existing["analysis_depth"], 0):
                updates["analysis_depth"] = new_depth
            updates["updated_at"] = now
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [name]
                self.conn.execute(f"UPDATE classes SET {set_clause} WHERE name = ?", values)
                self.conn.commit()
            return {"upserted": True, "id": existing["id"], "name": name, "action": "updated"}
        else:
            json_fields = {}
            for field in ("inheritance_chain", "known_children", "interfaces",
                          "key_methods", "key_properties", "key_delegates", "related_classes"):
                json_fields[field] = json.dumps(kwargs.get(field) or [])

            cursor = self.conn.execute(
                """INSERT INTO classes
                   (name, kind, parent_class, outer_class, subsystem, module, header_path,
                    class_specifiers, doc_comment, summary,
                    inheritance_chain, known_children, interfaces,
                    key_methods, key_properties, key_delegates,
                    lifecycle_order, related_classes, entry_id,
                    analysis_depth, source_line_count, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name, kind, kwargs.get("parent_class"), kwargs.get("outer_class"),
                    subsystem, module, header_path,
                    kwargs.get("class_specifiers", ""), kwargs.get("doc_comment", ""),
                    kwargs.get("summary", ""),
                    json_fields["inheritance_chain"], json_fields["known_children"],
                    json_fields["interfaces"], json_fields["key_methods"],
                    json_fields["key_properties"], json_fields["key_delegates"],
                    kwargs.get("lifecycle_order", ""), json_fields["related_classes"],
                    kwargs.get("entry_id"),
                    kwargs.get("analysis_depth", "stub"),
                    kwargs.get("source_line_count", 0),
                    now, now,
                ),
            )
            self.conn.commit()
            return {"upserted": True, "id": cursor.lastrowid, "name": name, "action": "created"}

    def get_class(self, name):
        row = self.conn.execute("SELECT * FROM classes WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for f in ("inheritance_chain", "known_children", "interfaces",
                  "key_methods", "key_properties", "key_delegates", "related_classes"):
            d[f] = json.loads(d[f]) if d[f] else []
        return d

    def query_hierarchy(self, class_name, direction="both", depth=10):
        result = {"class": class_name, "parents": [], "children": []}
        if direction in ("parents", "both"):
            current = class_name
            for _ in range(depth):
                row = self.conn.execute(
                    "SELECT name, parent_class FROM classes WHERE name = ?", (current,)
                ).fetchone()
                if not row or not row["parent_class"]:
                    break
                result["parents"].append(row["parent_class"])
                current = row["parent_class"]
        if direction in ("children", "both"):
            def _get_children(name, d):
                if d <= 0:
                    return []
                rows = self.conn.execute(
                    "SELECT name FROM classes WHERE parent_class = ?", (name,)
                ).fetchall()
                children = []
                for r in rows:
                    children.append({"name": r["name"], "children": _get_children(r["name"], d - 1)})
                return children
            result["children"] = _get_children(class_name, depth)
        return result

    # ── Functions ─────────────────────────────────────────────────────────────

    def save_function(self, name, subsystem, **kwargs):
        if subsystem not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{subsystem}'")
        class_name = kwargs.get("class_name")
        qualified = f"{class_name}::{name}" if class_name else name
        now = datetime.now(timezone.utc).isoformat()

        existing = self.conn.execute(
            "SELECT id FROM functions WHERE qualified_name = ?", (qualified,)
        ).fetchone()

        fields = {
            "name": name, "qualified_name": qualified, "class_name": class_name,
            "subsystem": subsystem, "return_type": kwargs.get("return_type", "void"),
            "parameters": json.dumps(kwargs.get("parameters") or []),
            "signature_full": kwargs.get("signature_full", ""),
            "ufunction_specifiers": kwargs.get("ufunction_specifiers", ""),
            "is_virtual": kwargs.get("is_virtual", False),
            "is_const": kwargs.get("is_const", False),
            "is_static": kwargs.get("is_static", False),
            "is_blueprint_callable": kwargs.get("is_blueprint_callable", False),
            "is_blueprint_event": kwargs.get("is_blueprint_event", False),
            "is_rpc": kwargs.get("is_rpc", False),
            "rpc_type": kwargs.get("rpc_type", ""),
            "doc_comment": kwargs.get("doc_comment", ""),
            "summary": kwargs.get("summary", ""),
            "call_context": kwargs.get("call_context", ""),
            "call_order": kwargs.get("call_order", ""),
            "calls_into": json.dumps(kwargs.get("calls_into") or []),
            "called_by": json.dumps(kwargs.get("called_by") or []),
            "entry_id": kwargs.get("entry_id"),
            "updated_at": now,
        }

        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [qualified]
            self.conn.execute(f"UPDATE functions SET {set_clause} WHERE qualified_name = ?", values)
            self.conn.commit()
            return {"upserted": True, "id": existing["id"], "qualified_name": qualified, "action": "updated"}
        else:
            fields["created_at"] = now
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            cursor = self.conn.execute(
                f"INSERT INTO functions ({cols}) VALUES ({placeholders})", list(fields.values())
            )
            self.conn.commit()
            return {"upserted": True, "id": cursor.lastrowid, "qualified_name": qualified, "action": "created"}

    def query_calls(self, function_name, direction="both", depth=3):
        # Find by qualified_name or plain name
        row = self.conn.execute(
            "SELECT * FROM functions WHERE qualified_name = ? OR name = ? LIMIT 1",
            (function_name, function_name)
        ).fetchone()
        if not row:
            return {"error": f"Function '{function_name}' not found."}
        row = dict(row)
        result = {
            "function": row["qualified_name"],
            "summary": row["summary"],
            "call_context": row["call_context"],
            "call_order": row["call_order"],
        }
        if direction in ("callees", "both"):
            result["calls_into"] = json.loads(row["calls_into"]) if row["calls_into"] else []
        if direction in ("callers", "both"):
            result["called_by"] = json.loads(row["called_by"]) if row["called_by"] else []
        return result

    def query_class_full(self, class_name, include_methods=True, include_properties=True):
        cls = self.get_class(class_name)
        if not cls:
            return {"error": f"Class '{class_name}' not found."}
        result = dict(cls)
        if include_methods:
            rows = self.conn.execute(
                "SELECT * FROM functions WHERE class_name = ?", (class_name,)
            ).fetchall()
            result["functions"] = []
            for r in rows:
                d = dict(r)
                d["parameters"] = json.loads(d["parameters"]) if d["parameters"] else []
                d["calls_into"] = json.loads(d["calls_into"]) if d["calls_into"] else []
                d["called_by"] = json.loads(d["called_by"]) if d["called_by"] else []
                result["functions"].append(d)
        if include_properties:
            rows = self.conn.execute(
                "SELECT * FROM properties WHERE class_name = ?", (class_name,)
            ).fetchall()
            result["properties_detail"] = [dict(r) for r in rows]
        # Link narrative entry
        if cls.get("entry_id"):
            entry = self.get(cls["entry_id"])
            if entry:
                result["narrative_entry"] = {"id": entry["id"], "title": entry["title"]}
        return result

    # ── Properties ────────────────────────────────────────────────────────────

    def save_property(self, name, class_name, subsystem, property_type, **kwargs):
        if subsystem not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{subsystem}'")
        qualified = f"{class_name}::{name}"
        now = datetime.now(timezone.utc).isoformat()

        existing = self.conn.execute(
            "SELECT id FROM properties WHERE qualified_name = ?", (qualified,)
        ).fetchone()

        fields = {
            "name": name, "qualified_name": qualified, "class_name": class_name,
            "subsystem": subsystem, "property_type": property_type,
            "default_value": kwargs.get("default_value", ""),
            "uproperty_specifiers": kwargs.get("uproperty_specifiers", ""),
            "is_replicated": kwargs.get("is_replicated", False),
            "replicated_using": kwargs.get("replicated_using", ""),
            "is_blueprint_visible": kwargs.get("is_blueprint_visible", False),
            "is_edit_anywhere": kwargs.get("is_edit_anywhere", False),
            "is_config": kwargs.get("is_config", False),
            "doc_comment": kwargs.get("doc_comment", ""),
            "summary": kwargs.get("summary", ""),
            "entry_id": kwargs.get("entry_id"),
            "updated_at": now,
        }

        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [qualified]
            self.conn.execute(f"UPDATE properties SET {set_clause} WHERE qualified_name = ?", values)
            self.conn.commit()
            return {"upserted": True, "id": existing["id"], "qualified_name": qualified, "action": "updated"}
        else:
            fields["created_at"] = now
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            cursor = self.conn.execute(
                f"INSERT INTO properties ({cols}) VALUES ({placeholders})", list(fields.values())
            )
            self.conn.commit()
            return {"upserted": True, "id": cursor.lastrowid, "qualified_name": qualified, "action": "created"}

    # ── Analysis Log ──────────────────────────────────────────────────────────

    def log_analysis(self, file_path, module, subsystem, analysis_depth, **kwargs):
        if subsystem not in VALID_SUBSYSTEMS:
            raise ValueError(f"Invalid subsystem: '{subsystem}'")
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO analysis_log
               (file_path, module, subsystem, analysis_depth,
                classes_found, functions_found, properties_found, notes, analyzed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                file_path, module, subsystem, analysis_depth,
                kwargs.get("classes_found", 0), kwargs.get("functions_found", 0),
                kwargs.get("properties_found", 0), kwargs.get("notes", ""), now,
            ),
        )
        self.conn.commit()
        return {"logged": True, "id": cursor.lastrowid}

    def analysis_status(self, group_by="module", module=None, subsystem=None):
        result = {}
        # Overall counts
        result["total_classes"] = self.conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        result["total_functions"] = self.conn.execute("SELECT COUNT(*) FROM functions").fetchone()[0]
        result["total_properties"] = self.conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        result["files_analyzed"] = self.conn.execute("SELECT COUNT(*) FROM analysis_log").fetchone()[0]
        result["by_depth"] = dict(self.conn.execute(
            "SELECT analysis_depth, COUNT(*) FROM classes GROUP BY analysis_depth"
        ).fetchall())

        sql = "SELECT {col}, analysis_depth, COUNT(*) as cnt FROM analysis_log"
        params = []
        wheres = []
        if module:
            wheres.append("module = ?")
            params.append(module)
        if subsystem:
            wheres.append("subsystem = ?")
            params.append(subsystem)
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        col = "module" if group_by == "module" else "subsystem" if group_by == "subsystem" else "analysis_depth"
        sql = sql.format(col=col)
        sql += f" GROUP BY {col}, analysis_depth ORDER BY {col}"
        rows = self.conn.execute(sql, params).fetchall()
        breakdown = {}
        for r in rows:
            key = r[0]
            if key not in breakdown:
                breakdown[key] = {}
            breakdown[key][r[1]] = r[2]
        result["breakdown"] = breakdown
        return result


# ── MCP Server ────────────────────────────────────────────────────────────────

SUBSYSTEMS_STR = ", ".join(VALID_SUBSYSTEMS)
CATEGORIES_STR = ", ".join(VALID_CATEGORIES)

TOOLS = [
    Tool(
        name="ue_save",
        description=(
            "Save an Unreal Engine knowledge entry. Call this whenever you learn "
            "something about UE: classes, patterns, gotchas, architecture, macros, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title (max 80 chars). E.g. 'AActor lifecycle hooks'.",
                },
                "subsystem": {
                    "type": "string",
                    "enum": VALID_SUBSYSTEMS,
                    "description": f"UE subsystem: {SUBSYSTEMS_STR}.",
                },
                "category": {
                    "type": "string",
                    "enum": VALID_CATEGORIES,
                    "description": f"Entry type: {CATEGORIES_STR}.",
                },
                "summary": {
                    "type": "string",
                    "description": "1-3 sentence summary for search results.",
                },
                "content": {
                    "type": "string",
                    "description": "Full detailed content. Include code examples, inheritance chains, important notes. Markdown supported.",
                },
                "source_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UE source file paths where this is defined (e.g. 'Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h').",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant tags for filtering.",
                },
                "related_entries": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs of related entries.",
                },
            },
            "required": ["title", "subsystem", "category", "summary", "content"],
        },
    ),
    Tool(
        name="ue_search",
        description=(
            "Search the UE knowledge base using full-text search. "
            "Returns matching entries ranked by relevance. "
            "Use this to find previously recorded knowledge about UE classes, patterns, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms (e.g. 'actor replication', 'gameplay ability').",
                },
                "subsystem": {
                    "type": "string",
                    "enum": VALID_SUBSYSTEMS,
                    "description": "Filter by subsystem (optional).",
                },
                "category": {
                    "type": "string",
                    "enum": VALID_CATEGORIES,
                    "description": "Filter by category (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="ue_get",
        description="Get a full UE knowledge entry by its ID, including all details.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Entry ID.",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="ue_list",
        description=(
            "List UE knowledge entries, optionally filtered by subsystem and/or category. "
            "Returns entries sorted by most recently updated."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "subsystem": {
                    "type": "string",
                    "enum": VALID_SUBSYSTEMS,
                    "description": "Filter by subsystem (optional).",
                },
                "category": {
                    "type": "string",
                    "enum": VALID_CATEGORIES,
                    "description": "Filter by category (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20).",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip first N results for pagination (default 0).",
                    "default": 0,
                },
            },
        },
    ),
    Tool(
        name="ue_update",
        description="Update an existing UE knowledge entry. Only provided fields are changed.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Entry ID to update.",
                },
                "title": {"type": "string"},
                "subsystem": {"type": "string", "enum": VALID_SUBSYSTEMS},
                "category": {"type": "string", "enum": VALID_CATEGORIES},
                "summary": {"type": "string"},
                "content": {"type": "string"},
                "source_files": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "related_entries": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="ue_delete",
        description="Delete a UE knowledge entry by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Entry ID to delete.",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="ue_stats",
        description="Show statistics about the UE knowledge base: total entries, breakdown by subsystem and category. Also shows structured data counts (classes, functions, properties).",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    # ── Structured code tools ─────────────────────────────────────────────
    Tool(
        name="ue_save_class",
        description=(
            "Save structured info about a UE class, struct, enum, or interface. "
            "Upserts by name: if exists, merges arrays and upgrades depth."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Class name: 'AActor', 'FVector', 'ENetRole'"},
                "kind": {"type": "string", "enum": VALID_KINDS},
                "parent_class": {"type": "string"},
                "outer_class": {"type": "string", "description": "Enclosing class for nested types"},
                "subsystem": {"type": "string", "enum": VALID_SUBSYSTEMS},
                "module": {"type": "string", "description": "Module: 'Engine', 'CoreUObject', 'GameplayAbilities'"},
                "header_path": {"type": "string", "description": "Relative path from Engine/Source/"},
                "class_specifiers": {"type": "string", "description": "UCLASS/USTRUCT specifiers as in source"},
                "doc_comment": {"type": "string", "description": "Verbatim /** */ comment from source"},
                "summary": {"type": "string", "description": "1-3 sentence description"},
                "inheritance_chain": {"type": "array", "items": {"type": "string"}, "description": "Parent chain to root: ['AActor', 'UObject']"},
                "known_children": {"type": "array", "items": {"type": "string"}},
                "interfaces": {"type": "array", "items": {"type": "string"}},
                "key_methods": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "brief": {"type": "string"}}}},
                "key_properties": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}, "specifiers": {"type": "string"}}}},
                "key_delegates": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "signature": {"type": "string"}}}},
                "lifecycle_order": {"type": "string", "description": "Call order: 'Constructor -> BeginPlay -> Tick -> EndPlay'"},
                "related_classes": {"type": "array", "items": {"type": "string"}},
                "entry_id": {"type": "integer", "description": "Link to entries table row"},
                "analysis_depth": {"type": "string", "enum": ["stub", "shallow", "deep"]},
                "source_line_count": {"type": "integer"},
            },
            "required": ["name", "kind", "subsystem", "module", "header_path"],
        },
    ),
    Tool(
        name="ue_save_function",
        description=(
            "Save structured info about a UE function/method. "
            "Upserts by qualified_name (ClassName::FuncName)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "class_name": {"type": "string", "description": "Owning class, or null for free functions"},
                "subsystem": {"type": "string", "enum": VALID_SUBSYSTEMS},
                "return_type": {"type": "string"},
                "parameters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}}},
                "signature_full": {"type": "string", "description": "Full signature as in header"},
                "ufunction_specifiers": {"type": "string"},
                "is_virtual": {"type": "boolean"},
                "is_const": {"type": "boolean"},
                "is_static": {"type": "boolean"},
                "is_blueprint_callable": {"type": "boolean"},
                "is_blueprint_event": {"type": "boolean"},
                "is_rpc": {"type": "boolean"},
                "rpc_type": {"type": "string", "enum": ["", "Server", "Client", "NetMulticast"]},
                "doc_comment": {"type": "string"},
                "summary": {"type": "string"},
                "call_context": {"type": "string", "description": "When/how this gets called"},
                "call_order": {"type": "string", "description": "Position in call sequence"},
                "calls_into": {"type": "array", "items": {"type": "string"}, "description": "Qualified names this calls"},
                "called_by": {"type": "array", "items": {"type": "string"}, "description": "Qualified names that call this"},
            },
            "required": ["name", "subsystem"],
        },
    ),
    Tool(
        name="ue_save_property",
        description=(
            "Save structured info about a UPROPERTY. "
            "Upserts by qualified_name (ClassName::PropName)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "class_name": {"type": "string"},
                "subsystem": {"type": "string", "enum": VALID_SUBSYSTEMS},
                "property_type": {"type": "string", "description": "'float', 'uint8:1', 'TObjectPtr<USceneComponent>'"},
                "default_value": {"type": "string"},
                "uproperty_specifiers": {"type": "string", "description": "Full specifiers as in source"},
                "is_replicated": {"type": "boolean"},
                "replicated_using": {"type": "string", "description": "OnRep function name"},
                "is_blueprint_visible": {"type": "boolean"},
                "is_edit_anywhere": {"type": "boolean"},
                "is_config": {"type": "boolean"},
                "doc_comment": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["name", "class_name", "subsystem", "property_type"],
        },
    ),
    Tool(
        name="ue_query_class",
        description="Get full structured info about a UE class: hierarchy, methods, properties, delegates, linked narrative entry.",
        inputSchema={
            "type": "object",
            "properties": {
                "class_name": {"type": "string"},
                "include_methods": {"type": "boolean", "default": True},
                "include_properties": {"type": "boolean", "default": True},
            },
            "required": ["class_name"],
        },
    ),
    Tool(
        name="ue_query_hierarchy",
        description="Query class inheritance: find parents, children, or full chain.",
        inputSchema={
            "type": "object",
            "properties": {
                "class_name": {"type": "string"},
                "direction": {"type": "string", "enum": ["parents", "children", "both"], "default": "both"},
                "depth": {"type": "integer", "default": 10},
            },
            "required": ["class_name"],
        },
    ),
    Tool(
        name="ue_query_calls",
        description="Query call relationships: what calls a function, or what it calls.",
        inputSchema={
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "'AActor::BeginPlay' or just 'BeginPlay'"},
                "direction": {"type": "string", "enum": ["callers", "callees", "both"], "default": "both"},
                "depth": {"type": "integer", "default": 3},
            },
            "required": ["function_name"],
        },
    ),
    Tool(
        name="ue_analysis_status",
        description="Check analysis progress: files analyzed, depth coverage, gaps.",
        inputSchema={
            "type": "object",
            "properties": {
                "group_by": {"type": "string", "enum": ["module", "subsystem", "depth"], "default": "module"},
                "module": {"type": "string"},
                "subsystem": {"type": "string"},
            },
        },
    ),
    Tool(
        name="ue_log_analysis",
        description="Record that a source file has been analyzed. Track progress.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "module": {"type": "string"},
                "subsystem": {"type": "string", "enum": VALID_SUBSYSTEMS},
                "analysis_depth": {"type": "string", "enum": ["stub", "shallow", "deep"]},
                "classes_found": {"type": "integer"},
                "functions_found": {"type": "integer"},
                "properties_found": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["file_path", "module", "subsystem", "analysis_depth"],
        },
    ),
]


def create_server():
    db = KnowledgeDB()
    server = Server("ue-knowledge")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            result = _handle(db, name, arguments)
        except Exception as e:
            result = {"error": str(e)}
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    return server, db


def _handle(db: KnowledgeDB, name: str, args: dict):
    if name == "ue_save":
        result = db.save(
            title=args["title"],
            subsystem=args["subsystem"],
            category=args["category"],
            summary=args["summary"],
            content=args["content"],
            source_files=args.get("source_files"),
            tags=args.get("tags"),
            related_entries=args.get("related_entries"),
        )
        if isinstance(result, dict):
            return result
        return {"saved": True, "id": result, "title": args["title"]}

    elif name == "ue_search":
        results = db.search(
            query=args["query"],
            limit=args.get("limit", 10),
            subsystem=args.get("subsystem"),
            category=args.get("category"),
        )
        # Return compact results (no full content in search)
        compact = []
        for r in results:
            compact.append({
                "id": r["id"],
                "title": r["title"],
                "subsystem": r["subsystem"],
                "category": r["category"],
                "summary": r["summary"],
                "tags": json.loads(r["tags"]) if r["tags"] else [],
                "score": round(r.get("score", 0), 3),
            })
        return {"results": compact, "count": len(compact)}

    elif name == "ue_get":
        entry = db.get(args["id"])
        if not entry:
            return {"error": f"Entry {args['id']} not found."}
        entry["source_files"] = json.loads(entry["source_files"] or "[]")
        entry["tags"] = json.loads(entry["tags"] or "[]")
        entry["related_entries"] = json.loads(entry["related_entries"] or "[]")
        return entry

    elif name == "ue_list":
        entries = db.list_entries(
            subsystem=args.get("subsystem"),
            category=args.get("category"),
            limit=args.get("limit", 20),
            offset=args.get("offset", 0),
        )
        compact = []
        for e in entries:
            compact.append({
                "id": e["id"],
                "title": e["title"],
                "subsystem": e["subsystem"],
                "category": e["category"],
                "summary": e["summary"],
                "tags": json.loads(e["tags"]) if e["tags"] else [],
                "updated_at": e["updated_at"],
            })
        return {"entries": compact, "count": len(compact)}

    elif name == "ue_update":
        entry_id = args["id"]
        fields = {k: v for k, v in args.items() if k != "id"}
        ok = db.update(entry_id, **fields)
        if not ok:
            return {"error": f"Entry {entry_id} not found or no changes."}
        return {"updated": True, "id": entry_id}

    elif name == "ue_delete":
        ok = db.delete(args["id"])
        if not ok:
            return {"error": f"Entry {args['id']} not found."}
        return {"deleted": True, "id": args["id"]}

    elif name == "ue_stats":
        return db.stats()

    # ── Structured code tools ────────────────────────────────────────────

    elif name == "ue_save_class":
        required = {k: args[k] for k in ("name", "kind", "subsystem", "module", "header_path")}
        optional = {k: v for k, v in args.items() if k not in required}
        return db.save_class(**required, **optional)

    elif name == "ue_save_function":
        required = {"name": args["name"], "subsystem": args["subsystem"]}
        optional = {k: v for k, v in args.items() if k not in ("name", "subsystem")}
        return db.save_function(**required, **optional)

    elif name == "ue_save_property":
        required = {k: args[k] for k in ("name", "class_name", "subsystem", "property_type")}
        optional = {k: v for k, v in args.items() if k not in required}
        return db.save_property(**required, **optional)

    elif name == "ue_query_class":
        return db.query_class_full(
            class_name=args["class_name"],
            include_methods=args.get("include_methods", True),
            include_properties=args.get("include_properties", True),
        )

    elif name == "ue_query_hierarchy":
        return db.query_hierarchy(
            class_name=args["class_name"],
            direction=args.get("direction", "both"),
            depth=args.get("depth", 10),
        )

    elif name == "ue_query_calls":
        return db.query_calls(
            function_name=args["function_name"],
            direction=args.get("direction", "both"),
            depth=args.get("depth", 3),
        )

    elif name == "ue_analysis_status":
        return db.analysis_status(
            group_by=args.get("group_by", "module"),
            module=args.get("module"),
            subsystem=args.get("subsystem"),
        )

    elif name == "ue_log_analysis":
        required = {k: args[k] for k in ("file_path", "module", "subsystem", "analysis_depth")}
        optional = {k: v for k, v in args.items() if k not in required}
        return db.log_analysis(**required, **optional)

    return {"error": f"Unknown tool: {name}"}


async def main():
    server, db = create_server()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
