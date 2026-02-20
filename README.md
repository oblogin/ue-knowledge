# UE Knowledge Base

Local MCP server for building a persistent Unreal Engine knowledge base. Designed to be populated by Claude as it explores UE source code. SQLite + FTS5 full-text search, zero dependencies beyond `mcp`.

## Install

### Prerequisites

- Python 3.10+
- `mcp` library (installed with EchoVault or standalone: `pip install mcp`)

### Setup

```bash
# 1. Create the directory (if not exists)
mkdir -p ~/.ue-knowledge

# 2. Copy server.py to ~/.ue-knowledge/
cp server.py ~/.ue-knowledge/server.py

# 3. Register in Claude Code (global)
# Add to ~/.claude.json under "mcpServers":
```

```jsonc
// ~/.claude.json
{
  "mcpServers": {
    "ue-knowledge": {
      "command": "python",
      "args": ["C:/Users/<username>/.ue-knowledge/server.py"],
      "type": "stdio"
    }
  }
}
```

```bash
# 4. Restart Claude Code — tools will be available as mcp__ue-knowledge__*
```

### Project-level setup

To install for a specific project instead of globally, create `.mcp.json` in the project root:

```jsonc
// <project>/.mcp.json
{
  "mcpServers": {
    "ue-knowledge": {
      "command": "python",
      "args": ["C:/Users/<username>/.ue-knowledge/server.py"],
      "type": "stdio"
    }
  }
}
```

### Verify

After restarting Claude Code, ask:

```
Search the UE knowledge base for "actor"
```

If tools are loaded, Claude will call `ue_search`. On a fresh install with empty DB, it will return 0 results — that's correct.

## Usage

Once installed, Claude uses the knowledge base through MCP tools automatically. The workflow:

1. **Before working with UE code** — Claude calls `ue_search` to check if relevant knowledge exists
2. **While reading UE source** — Claude calls `ue_save` to record what it learns
3. **When revisiting a topic** — Claude calls `ue_get` to load full details of a known entry

### MCP Tools

| Tool | Description |
|------|-------------|
| `ue_save` | Save a new knowledge entry |
| `ue_search` | Full-text search across all entries |
| `ue_get` | Get full entry by ID |
| `ue_list` | List entries with optional subsystem/category filters |
| `ue_update` | Update an existing entry |
| `ue_delete` | Delete an entry by ID |
| `ue_stats` | Show total entries, breakdown by subsystem and category |

### Example: save

```json
{
  "title": "AActor lifecycle overview",
  "subsystem": "gameplay",
  "category": "class",
  "summary": "AActor key lifecycle: Constructor → PostInitializeComponents → BeginPlay → Tick → EndPlay → Destroyed.",
  "content": "## AActor Lifecycle\n\n1. **Constructor** — CDO only, no world access\n2. **PostInitializeComponents()** — components ready\n3. **BeginPlay()** — actor starts playing\n4. **Tick(float DeltaTime)** — every frame\n5. **EndPlay(EEndPlayReason)** — being removed\n6. **Destroyed()** — after EndPlay\n\n> Do NOT call GetWorld() in constructors.",
  "source_files": ["Engine/Source/Runtime/Engine/Classes/GameFramework/Actor.h"],
  "tags": ["actor", "lifecycle", "beginplay", "tick"]
}
```

### Example: search

```json
{
  "query": "actor replication",
  "subsystem": "networking",
  "limit": 5
}
```

Returns compact results (id, title, subsystem, category, summary, tags, score) ranked by FTS5 relevance. Use `ue_get` with the ID to load full content.

### Example: list

```json
{
  "subsystem": "gameplay",
  "category": "gotcha",
  "limit": 10
}
```

## Entry Structure

Each entry has:

| Field | Required | Description |
|-------|----------|-------------|
| `title` | yes | Short title, max 80 chars |
| `subsystem` | yes | UE subsystem (see list below) |
| `category` | yes | Entry type (see list below) |
| `summary` | yes | 1-3 sentence summary for search results |
| `content` | yes | Full markdown content with code examples |
| `source_files` | no | Array of UE source file paths |
| `tags` | no | Array of lowercase tags |
| `related_entries` | no | Array of related entry IDs |

### Subsystems

| Subsystem | Covers |
|-----------|--------|
| `core` | UObject, reflection, GC, serialization, FName, TSharedPtr |
| `gameplay` | AActor, APawn, ACharacter, AController, GameMode, GameState |
| `gas` | Gameplay Ability System, abilities, effects, attributes |
| `rendering` | Materials, shaders, render pipeline, Nanite, Lumen |
| `networking` | Replication, RPC, NetDriver, relevancy |
| `ui` | Slate, UMG, CommonUI, HUD |
| `input` | Enhanced Input System, input mappings |
| `animation` | AnimBP, montages, state machines, IK |
| `ai` | Behavior Trees, EQS, AI Controller, perception |
| `physics` | Chaos, collision, physics bodies, constraints |
| `audio` | Sound system, MetaSounds, attenuation |
| `editor` | Editor extensions, custom tools, detail customization |
| `build` | Build system, modules, plugins, .Build.cs, .Target.cs |
| `containers` | TArray, TMap, TSet, TOptional, TVariant |
| `delegates` | Delegates, events, multicast delegates |
| `async` | Tasks, async, latent actions, GameplayTasks |
| `niagara` | Niagara particle system |
| `pcg` | Procedural Content Generation framework |
| `world-partition` | World Partition, data layers, streaming |
| `mass-entity` | Mass Entity (ECS framework) |
| `chaos` | Chaos destruction system |
| `other` | Anything that doesn't fit above |

### Categories

| Category | When to use |
|----------|-------------|
| `class` | Documenting a class/struct: hierarchy, key methods, purpose |
| `function` | Documenting a specific function: signature, behavior, usage |
| `pattern` | Recurring pattern or idiom: how to properly do X in UE |
| `gotcha` | Non-obvious behavior, pitfall, common mistake |
| `architecture` | High-level design: how a subsystem is organized, data flow |
| `example` | Code example: complete, working snippet |
| `config` | Configuration: ini settings, console variables, project settings |
| `macro` | UE macros: UPROPERTY, UFUNCTION, USTRUCT, UCLASS specifiers |
| `module` | Module documentation: what it contains, dependencies |
| `best-practice` | Recommended approach endorsed by Epic or community consensus |

## How It Works

```
~/.ue-knowledge/
├── server.py        # MCP server (single file)
├── knowledge.db     # SQLite database (auto-created)
└── README.md        # This file
```

- **SQLite + FTS5** — full-text search with BM25 ranking and porter stemming
- **WAL mode** — write-ahead logging for reliability
- **Triggers** — FTS index stays in sync automatically on insert/update/delete
- **Indexes** — on `subsystem`, `category`, and `updated_at` for fast filtering
- **Duplicate detection** — prevents saving entries with identical titles
- **Validation** — subsystem and category values are validated server-side

## Data Management

### Browse the database directly

```bash
sqlite3 ~/.ue-knowledge/knowledge.db

# Count entries
SELECT COUNT(*) FROM entries;

# List all gotchas
SELECT id, title, subsystem FROM entries WHERE category = 'gotcha';

# Full-text search
SELECT id, title, -rank AS score
FROM entries_fts
WHERE entries_fts MATCH '"actor"*'
ORDER BY score DESC;

# Entries per subsystem
SELECT subsystem, COUNT(*) as cnt
FROM entries
GROUP BY subsystem
ORDER BY cnt DESC;
```

### Backup

```bash
cp ~/.ue-knowledge/knowledge.db ~/.ue-knowledge/knowledge.db.backup
```

### Reset

```bash
rm ~/.ue-knowledge/knowledge.db
# DB will be recreated on next server start
```

### Export to JSON

```bash
sqlite3 -json ~/.ue-knowledge/knowledge.db "SELECT * FROM entries" > entries.json
```

## Uninstall

```bash
# 1. Remove from ~/.claude.json — delete the "ue-knowledge" entry under "mcpServers"

# 2. Remove files
rm -rf ~/.ue-knowledge

# 3. Remove CLAUDE.md instructions (if added)
# Edit ~/.claude/CLAUDE.md and remove the UE Knowledge Base section
```

## Limitations

- **No semantic/vector search** — only keyword-based FTS5. Could add `sqlite-vec` + embeddings later.
- **Single-agent** — no concurrent write protection beyond SQLite's built-in locking.
- **No CLI** — management only through MCP tools or direct SQLite queries.
