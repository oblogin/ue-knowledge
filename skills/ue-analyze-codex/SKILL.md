---
name: ue-analyze-codex
description: Systematically analyze Unreal Engine source code and save structured knowledge into the UE Knowledge Base through MCP tools. Use when the user asks to run ue-analyze, analyze a UE class/module/subsystem, choose analysis depth (stub/shallow/deep), continue unfinished coverage, or check analysis status.
---

# UE Analyze (Codex)

Treat requests like `ue-analyze <target> [depth]` as this workflow.

## Parse Arguments

Parse user input as `<target> [depth]`.

Use target values:
- Class name: `AActor`, `UAbilitySystemComponent`, `FVector`
- Module: `Engine`, `GameplayAbilities`, `CoreUObject`
- Subsystem: `gameplay`, `gas`, `networking`
- `next`: pick the most impactful unanalyzed area
- `status`: show analysis progress and stop

Use depth values:
- `stub`
- `shallow`
- `deep`

If depth is missing, apply the tier defaults in this skill.

## Execute Workflow

1. Call `ue_analysis_status` to check current coverage.
2. Resolve target files:
- For class names, find headers under `C:/UE_5.7/Engine/Source/` or `C:/UE_5.7/Engine/Plugins/`.
- For modules, collect public headers in that module.
- For subsystems, choose top-impact classes for that subsystem.
- For `next`, choose highest-impact unanalyzed class/subsystem from coverage data.
- For `status`, return status and stop.
3. Call `ue_search` or `ue_query_class` before saving to avoid duplicates.
4. Read the resolved header file(s).
5. Save structured data with depth-specific detail.
6. Update parent classes via `ue_save_class` so `known_children` stays current.
7. Record file analysis with `ue_log_analysis`.
8. Report analyzed files, saved counts, achieved depth, and next recommendations.

## Save Requirements by Depth

### stub

For each UCLASS/USTRUCT/UENUM/interface in each target header, call `ue_save_class` with:
- `name`, `kind`, `parent_class`, `outer_class`
- `subsystem`, `module`, `header_path`
- `class_specifiers`, `doc_comment`
- `analysis_depth = "stub"`

### shallow

Save everything from `stub`, plus on the main class:
- `summary`
- `inheritance_chain`
- `interfaces`
- `lifecycle_order`
- `key_methods` (array of `{name, brief}`)
- `key_properties` (array of `{name, type, specifiers}`)
- `key_delegates` (array of `{name, signature}`)
- `analysis_depth = "shallow"`

### deep

Save everything from `shallow`, plus:

Functions (`ue_save_function`) for important public/protected methods:
- `name`, `class_name`, `subsystem`
- `return_type`, `parameters`, `signature_full`
- `ufunction_specifiers`
- `is_virtual`, `is_const`, `is_static`
- `is_blueprint_callable`, `is_blueprint_event`
- `is_rpc`, `rpc_type`
- `doc_comment`, `summary`
- `call_context`, `call_order`
- `calls_into`, `called_by`

Properties (`ue_save_property`) for each UPROPERTY:
- `name`, `class_name`, `subsystem`, `property_type`
- `default_value`
- `uproperty_specifiers`
- `is_replicated`, `replicated_using`
- `is_blueprint_visible`, `is_edit_anywhere`, `is_config`
- `doc_comment`, `summary`

Narrative (`ue_save`) for class-level architecture/usage/gotchas.

Set `analysis_depth = "deep"`.

## Default Depth by Tier

- Tier 1: `UObject`, `AActor`, `APawn`, `ACharacter`, `APlayerController`, `AGameModeBase`, `AGameStateBase` -> `deep`
- Tier 2: `UActorComponent`, `USceneComponent`, `UAbilitySystemComponent`, `UGameplayAbility`, `UGameplayEffect`, `UAttributeSet` -> `deep`
- Tier 3: `APlayerState`, `AController`, `AAIController`, `UMovementComponent`, `UCharacterMovementComponent`, `AInfo` -> `shallow`
- Tier 4: everything else -> `stub`

If user explicitly sets depth, always honor explicit depth.

## Rules

- Search before save; update existing entries instead of creating duplicates.
- Skip private/internal helpers; focus on public/protected API.
- Skip deprecated APIs unless frequently misused.
- Skip platform-specific blocks like `#if PLATFORM_WINDOWS`.
- Skip Editor-only blocks (`#if WITH_EDITOR`) unless analyzing Editor targets.
- Copy UE doc comments verbatim from source.
- Analyze all UCLASS/USTRUCT/UENUM/interface declarations present in each header.
- Treat depth as incremental; only upgrade depth and merge arrays.
