---
name: ue-analyze-gemini
description: Systematically analyze Unreal Engine source code and save structured knowledge into the UE Knowledge Base. Use when asked to run ue-analyze, analyze a UE class/module/subsystem, or check analysis status.
---

# UE Analyze (Gemini)

This skill allows you to analyze Unreal Engine source code and save the findings into a local SQLite knowledge base.

## Core Tool: ue_interface.py

All interactions with the knowledge base are performed via the python script:
`skills/ue-analyze-gemini/scripts/ue_interface.py`

**Usage Pattern:**
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py <COMMAND> --args '<JSON_ARGS>'
```

**Commands:**
- `status`: Check analysis progress.
- `search`: Search the database.
- `save_class`: Save class details.
- `save_function`: Save function details.
- `save_property`: Save property details.
- `log_analysis`: Log that a file has been analyzed.

## Workflow: Analyze Target

When the user asks to analyze a target (Class, Module, Subsystem, or "next"):

### 1. Check Status
Run:
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py status --args '{}'
```

### 2. Identify Target Files
- **Class:** Find header in `C:/UE_5.7/Engine/Source/` (or similar).
- **Module:** Find all public headers in the module's directory.
- **Subsystem:** Pick key classes for that subsystem.
- **Next:** Choose highest priority unanalyzed item from status.

### 3. Check Existing Data
Before saving, search to avoid duplicates:
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py search --args '{"query": "ClassName"}'
```

### 4. Analyze & Save
Read the header file(s) and extract structured data.

**Depths:**
- **Stub:** Basic class info (name, parent, module).
- **Shallow:** Summary, inheritance, interfaces, key methods/properties.
- **Deep:** Full details including all public methods (`save_function`) and properties (`save_property`).

**Save Class:**
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py save_class --args '{
  "name": "AActor",
  "kind": "class",
  "subsystem": "gameplay",
  "module": "Engine",
  "header_path": "Runtime/Engine/Classes/GameFramework/Actor.h",
  "analysis_depth": "shallow"
  ...other fields...
}'
```

**Save Function (Deep only):**
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py save_function --args '{
  "name": "BeginPlay",
  "class_name": "AActor",
  "subsystem": "gameplay",
  ...
}'
```

**Save Property (Deep only):**
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py save_property --args '{
  "name": "PrimaryActorTick",
  "class_name": "AActor",
  "subsystem": "gameplay",
  "property_type": "FActorTickFunction",
  ...
}'
```

### 5. Log Analysis
After processing a file, record it:
```bash
python skills/ue-analyze-gemini/scripts/ue_interface.py log_analysis --args '{
  "file_path": "Runtime/Engine/Classes/GameFramework/Actor.h",
  "module": "Engine",
  "subsystem": "gameplay",
  "analysis_depth": "shallow",
  "classes_found": 1,
  "functions_found": 5,
  "properties_found": 2
}'
```

## Default Tiers
- **Tier 1 (Deep):** `UObject`, `AActor`, `APawn`, `ACharacter`, `AGameModeBase`, `USceneComponent`.
- **Tier 2 (Deep):** `UAbilitySystemComponent`, `UGameplayAbility`.
- **Tier 3 (Shallow):** `AController`, `APlayerState`.
- **Tier 4 (Stub):** Everything else.
