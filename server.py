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
        return {"total": total, "by_subsystem": by_subsystem, "by_category": by_category}


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
        description="Show statistics about the UE knowledge base: total entries, breakdown by subsystem and category.",
        inputSchema={
            "type": "object",
            "properties": {},
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
