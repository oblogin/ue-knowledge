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
# 4. Install the /ue-analyze skill (optional)
cp commands/ue-analyze.md ~/.claude/commands/ue-analyze.md

# 5. Install hooks (optional but recommended — see Hooks section below)

# 6. Restart Claude Code — tools will be available as mcp__ue-knowledge__*
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

#### Narrative entries

| Tool | Description |
|------|-------------|
| `ue_save` | Save a new knowledge entry |
| `ue_search` | Full-text search across entries (and optionally classes, functions, properties) |
| `ue_get` | Get full entry by ID |
| `ue_list` | List entries with optional subsystem/category filters |
| `ue_update` | Update an existing entry |
| `ue_delete` | Delete an entry by ID |
| `ue_stats` | Show total entries, breakdown by subsystem/category + structured data counts |

#### Structured code data

| Tool | Description |
|------|-------------|
| `ue_save_class` | Save/update a UE class, struct, enum, or interface. Upserts by name, merges arrays, upgrades depth |
| `ue_save_function` | Save a function/method. Upserts by qualified_name (ClassName::FuncName) |
| `ue_save_property` | Save a UPROPERTY. Upserts by qualified_name (ClassName::PropName) |
| `ue_query_class` | Full class info: hierarchy, methods, properties, delegates, linked narrative entry |
| `ue_query_hierarchy` | Traverse inheritance tree (parents, children, or both) with bounded recursion |
| `ue_query_calls` | Call chain queries: what calls a function / what it calls |
| `ue_analysis_status` | Analysis progress: coverage by module, subsystem, depth |
| `ue_log_analysis` | Record that a source file has been analyzed |
| `ue_save_batch` | Save multiple classes/functions/properties in a single transaction |

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

Returns compact results (id, title, subsystem, category, summary, tags, score) ranked by FTS5 relevance, plus `total_matches` for pagination. Use `ue_get` with the ID to load full content.

#### Multi-table search

```json
{
  "query": "BeginPlay",
  "tables": ["entries", "classes", "functions"],
  "subsystem": "gameplay"
}
```

Returns results grouped by table: `{"entries": [...], "classes": [...], "functions": [...]}`.

#### Tag filtering

```json
{
  "query": "actor",
  "tags": ["lifecycle", "beginplay"]
}
```

Only returns entries where all specified tags are present.

### Example: list

```json
{
  "subsystem": "gameplay",
  "category": "gotcha",
  "limit": 10
}
```

### Example: save_class

```json
{
  "name": "AActor",
  "kind": "class",
  "parent_class": "UObject",
  "subsystem": "gameplay",
  "module": "Engine",
  "header_path": "Runtime/Engine/Classes/GameFramework/Actor.h",
  "class_specifiers": "Blueprintable, BlueprintType",
  "summary": "Base class for all actors placed in the world.",
  "key_methods": [
    {"name": "BeginPlay", "brief": "Called when play begins"},
    {"name": "Tick", "brief": "Called every frame"}
  ],
  "analysis_depth": "shallow"
}
```

On upsert: arrays (known_children, interfaces, key_methods, etc.) are merged (union), analysis_depth only upgrades (stub < shallow < deep).

### Example: save_function

```json
{
  "name": "BeginPlay",
  "class_name": "AActor",
  "subsystem": "gameplay",
  "return_type": "void",
  "is_virtual": true,
  "ufunction_specifiers": "",
  "summary": "Called when the game starts or when spawned.",
  "calls_into": ["AActor::ReceiveBeginPlay"],
  "called_by": ["UWorld::BeginPlay"]
}
```

### Example: query_class

```json
{
  "class_name": "AActor",
  "include_methods": true,
  "include_properties": true
}
```

Returns full class data plus all functions and properties from the structured tables.

### Example: query_hierarchy

```json
{
  "class_name": "ACharacter",
  "direction": "both",
  "depth": 10,
  "max_children_per_level": 50,
  "max_total": 500
}
```

Returns `{"parents": ["APawn", "AActor", "UObject"], "children": [...]}`. When limits are hit, adds `"truncated": true`.

### Example: save_batch

```json
{
  "items": [
    {"type": "class", "name": "AActor", "kind": "class", "subsystem": "gameplay", "module": "Engine", "header_path": "Actor.h"},
    {"type": "function", "name": "BeginPlay", "subsystem": "gameplay", "class_name": "AActor"},
    {"type": "property", "name": "RootComponent", "class_name": "AActor", "subsystem": "gameplay", "property_type": "USceneComponent*"}
  ]
}
```

Saves all items in a single transaction. Returns `{"saved": 3, "errors": [], "results": [...]}`.

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

## Structured Code Tables

In addition to free-form narrative entries, the KB has structured tables for systematic source code analysis.

### classes

Registry of UE classes, structs, enums, interfaces. Key fields:

| Field | Description |
|-------|-------------|
| `name` | Class name (unique key for upsert) |
| `kind` | `class`, `struct`, `enum`, `interface` |
| `parent_class` | Direct parent class name |
| `subsystem`, `module`, `header_path` | Location info |
| `class_specifiers` | UCLASS/USTRUCT specifiers as in source |
| `doc_comment` | Verbatim `/** */` comment |
| `summary` | Claude-generated description |
| `key_methods`, `key_properties`, `key_delegates` | JSON arrays of key members |
| `inheritance_chain`, `known_children`, `interfaces` | JSON arrays (merged on upsert) |
| `lifecycle_order` | Call order text |
| `analysis_depth` | `stub` / `shallow` / `deep` (only upgrades) |

### functions

Key methods/functions. Key fields:

| Field | Description |
|-------|-------------|
| `qualified_name` | Unique: `AActor::BeginPlay` |
| `signature_full` | Full C++ signature |
| `ufunction_specifiers` | UFUNCTION specifiers |
| `is_virtual`, `is_const`, `is_static` | Declaration flags |
| `is_blueprint_callable`, `is_blueprint_event`, `is_rpc` | UE flags |
| `calls_into`, `called_by` | JSON arrays — call chain tracking |
| `call_context`, `call_order` | When/how this gets called |

### properties

UPROPERTY fields. Key fields:

| Field | Description |
|-------|-------------|
| `qualified_name` | Unique: `AActor::RootComponent` |
| `property_type` | C++ type |
| `uproperty_specifiers` | Full specifiers from source |
| `is_replicated`, `replicated_using` | Replication info |
| `is_blueprint_visible`, `is_edit_anywhere`, `is_config` | Visibility flags |

### analysis_log

Tracks which files have been analyzed and at what depth.

### Merge-on-save behavior

- `ue_save_class`: if class already exists, merges JSON arrays (union) and upgrades depth (stub < shallow < deep)
- `ue_save_function` / `ue_save_property`: upsert by qualified_name — overwrites all provided fields

## Skill: /ue-analyze

Systematically analyze UE source code and populate the Knowledge Base. Reads headers from `C:/UE_5.7/Engine/Source/` and `C:/UE_5.7/Engine/Plugins/`.

### Usage

```
/ue-analyze AActor                  # Analyze a class (auto-selects depth by tier)
/ue-analyze AActor deep             # Force specific depth
/ue-analyze Engine                  # Analyze all public headers in a module
/ue-analyze Engine stub             # Stub pass across entire module
/ue-analyze gameplay                # Analyze top classes for a subsystem
/ue-analyze next                    # Auto-pick the most impactful unanalyzed target
/ue-analyze status                  # Show analysis progress and coverage
```

### Arguments

| Argument | Description |
|----------|-------------|
| Class name | `AActor`, `UAbilitySystemComponent` — find and analyze header |
| Module name | `Engine`, `GameplayAbilities` — analyze public headers in module |
| Subsystem | `gameplay`, `gas`, `networking` — pick top classes for subsystem |
| `next` | Auto-pick the most impactful unanalyzed area |
| `status` | Show `ue_analysis_status` breakdown and stop |

Optional second argument: `stub`, `shallow`, or `deep` to override default depth.

### Analysis depth levels

Three levels of analysis, each building on the previous:

#### stub (~1 min per class)

Minimal structural pass. Best for building the inheritance graph quickly.

What gets saved:
- `ue_save_class`: name, kind, parent_class, outer_class, subsystem, module, header_path, class_specifiers, doc_comment
- All UCLASS/USTRUCT/UENUM in the header (not just the main one)

Use case: bulk scanning entire modules to build the class hierarchy.

#### shallow (~3-5 min per class)

Adds human-readable descriptions and key member summaries.

Everything from stub, plus:
- `ue_save_class`: summary, inheritance_chain, interfaces, lifecycle_order
- `key_methods`: array of `{name, brief}` for the most important methods
- `key_properties`: array of `{name, type, specifiers}` for key UPROPERTY fields
- `key_delegates`: array of `{name, signature}` for delegates/events

Use case: understanding a class well enough to use it correctly.

#### deep (~10-15 min per class)

Full analysis with per-method and per-property detail, plus call chains.

Everything from shallow, plus:
- `ue_save_function` for each public/protected method:
  - Full C++ signature, return type, parameters
  - UFUNCTION specifiers (BlueprintCallable, Server, etc.)
  - Flags: virtual, const, static, blueprint_callable, blueprint_event, is_rpc
  - doc_comment, summary, call_context, call_order
  - Call chains: calls_into (what this function calls), called_by (who calls it)
- `ue_save_property` for each UPROPERTY:
  - C++ type, default value, full UPROPERTY specifiers
  - Replication: is_replicated, replicated_using (OnRep function)
  - Visibility: is_blueprint_visible, is_edit_anywhere, is_config
  - doc_comment, summary
- `ue_save` narrative entry with a detailed overview linked to the class

Use case: complete reference for the most important classes.

### Default depth by class tier

| Tier | Classes | Default depth |
|------|---------|---------------|
| 1 — Core gameplay | UObject, AActor, APawn, ACharacter, APlayerController, AGameModeBase, AGameStateBase | deep |
| 2 — Components & GAS | UActorComponent, USceneComponent, UAbilitySystemComponent, UGameplayAbility, UGameplayEffect | deep |
| 3 — Extended gameplay | APlayerState, AController, AAIController, UMovementComponent, UCharacterMovementComponent | shallow → deep |
| 4 — Everything else | All other classes | stub → shallow |

### Workflow

1. **Check coverage** → `ue_analysis_status`
2. **Find target headers** → Glob/Grep in UE source tree
3. **Search for existing data** → `ue_search` / `ue_query_class`
4. **Read and analyze headers** → extract structured data
5. **Save data** → `ue_save_class`, `ue_save_function`, `ue_save_property`
6. **Update parents** → add this class to parent's `known_children`
7. **Log progress** → `ue_log_analysis`
8. **Report** → what was saved, what to analyze next

### Rules

- Always search before saving to avoid duplicates
- Only save public/protected API — skip private helpers
- Skip deprecated API (unless commonly misused)
- Skip platform-specific code (`#if PLATFORM_WINDOWS`)
- Preserve doc comments verbatim from source
- Analyze all UCLASS/USTRUCT/UENUM in a header, not just the main one

## Hooks

Optional hooks that automate knowledge retrieval and saving. They detect UE projects by looking for `.uproject` files and only fire in UE project directories — in non-UE projects they silently return `{}`.

### Available hooks

| Hook | Event | What it does |
|------|-------|-------------|
| `ue-kb-session-start.sh` | `UserPromptSubmit` | On first prompt in a UE project, reminds Claude to search the KB for relevant context. Fires once per session (lock file). |
| `ue-kb-prompt-context.sh` | `UserPromptSubmit` | On every prompt in a UE project, adds a persistent reminder to save UE knowledge before ending. Lightweight, no blocking. |
| `ue-kb-save-reminder.sh` | `Stop` | Before ending a session in a UE project, blocks stop and reminds Claude to save any UE knowledge learned. Fires once (second stop proceeds). |

### UE project detection

Hooks detect Unreal Engine projects by:

1. Looking for `*.uproject` files in the current directory and up to 2 parent directories
2. Checking common UE Engine paths (`C:/UE_5.7`, `C:/UE_5.5`, etc.) when the working directory contains "Unreal" or "UE_"

If neither condition is met, hooks output `{}` and have zero effect.

### Install hooks

Add to `~/.claude/settings.json` under `"hooks"`:

```jsonc
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": {},
        "hooks": [
          // ... your existing hooks ...
          {
            "type": "command",
            "command": "bash ~/.ue-knowledge/hooks/ue-kb-session-start.sh"
          },
          {
            "type": "command",
            "command": "bash ~/.ue-knowledge/hooks/ue-kb-prompt-context.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": {},
        "hooks": [
          // ... your existing hooks ...
          {
            "type": "command",
            "command": "bash ~/.ue-knowledge/hooks/ue-kb-save-reminder.sh"
          }
        ]
      }
    ]
  }
}
```

### How hooks interact with EchoVault

If you also use EchoVault hooks, both sets run together without conflict:

- **EchoVault hooks** fire in every project — general session memory
- **UE KB hooks** fire only in UE projects — engine-specific knowledge

The Stop hooks stack: EchoVault reminds to save session decisions, UE KB reminds to save engine knowledge. Both use separate lock files (`/tmp/echovault-hooks/` and `/tmp/ue-kb-hooks/`), so they don't interfere with each other.

### Uninstall hooks

Remove the three `ue-kb-*` entries from `~/.claude/settings.json` under `hooks`.

## How It Works

```
~/.ue-knowledge/
├── server.py        # MCP server (single file)
├── knowledge.db     # SQLite database (auto-created)
├── tests.py         # Test suite (195 tests)
├── commands/
│   └── ue-analyze.md            # /ue-analyze skill (copy to ~/.claude/commands/)
├── hooks/
│   ├── ue-kb-session-start.sh   # First-prompt context loader
│   ├── ue-kb-prompt-context.sh  # Persistent save reminder
│   └── ue-kb-save-reminder.sh   # Stop blocker for saving
└── README.md        # This file
```

**Database tables:**
- `entries` + `entries_fts` — free-form narrative knowledge entries
- `classes` + `classes_fts` — structured class/struct/enum/interface registry
- `functions` + `functions_fts` — methods and functions with call chain tracking
- `properties` + `properties_fts` — UPROPERTY fields with specifiers and replication info
- `analysis_log` — source file analysis progress tracking
- `schema_version` — migration tracking for schema upgrades

**Features:**
- **SQLite + FTS5** — full-text search with BM25 ranking and porter stemming across all 4 content tables
- **WAL mode** — write-ahead logging for reliability
- **Triggers** — FTS indexes stay in sync automatically on insert/update/delete (12 triggers)
- **Indexes** — on all key lookup fields including entry_id foreign keys
- **Upsert with merge** — classes merge arrays on update, depth only upgrades
- **Duplicate detection** — prevents saving entries with identical titles
- **Validation** — subsystem, category, kind values are validated server-side
- **Schema versioning** — automatic migrations for upgrading existing databases
- **Cascade delete** — deleting an entry nullifies entry_id in linked classes/functions/properties
- **Tag normalization** — tags are lowercased, stripped, and deduplicated on save
- **Safe JSON parsing** — graceful fallback on corrupted JSON fields
- **Bounded recursion** — hierarchy queries have configurable max_children_per_level and max_total limits
- **Batch save** — save multiple items in a single transaction for performance
- **Pagination metadata** — search and list return total_matches alongside results
- **Multi-table search** — search_all queries entries, classes, functions, and properties in one call

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
# 1. Remove hooks from ~/.claude/settings.json
# Delete the ue-kb-session-start, ue-kb-prompt-context, ue-kb-save-reminder entries

# 2. Remove MCP server from ~/.claude.json
# Delete the "ue-knowledge" entry under "mcpServers"

# 3. Remove CLAUDE.md instructions (if added)
# Edit ~/.claude/CLAUDE.md and remove the UE Knowledge Base section

# 4. Remove files
rm -rf ~/.ue-knowledge

# 5. Clean up lock files
rm -rf /tmp/ue-kb-hooks
```

## Limitations

- **No semantic/vector search** — only keyword-based FTS5. Could add `sqlite-vec` + embeddings later.
- **Single-agent** — no concurrent write protection beyond SQLite's built-in locking.
- **No CLI** — management only through MCP tools or direct SQLite queries.
