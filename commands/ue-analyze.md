Analyze Unreal Engine source code and populate the UE Knowledge Base.

## Arguments

$ARGUMENTS — What to analyze and optionally at what depth.

Format: `<target> [depth]`

**Target** (first argument):
- Class name: `AActor`, `UAbilitySystemComponent`, `FVector`
- Module: `Engine`, `GameplayAbilities`, `CoreUObject`
- Subsystem: `gameplay`, `gas`, `networking`
- `next` — auto-pick the most impactful unanalyzed area
- `status` — show current analysis progress and stop

**Depth** (optional second argument):
- `stub` — minimal: name, kind, parent, specifiers, doc_comment (~1 min/class)
- `shallow` — + summary, key_methods, key_properties, key_delegates, lifecycle (~3-5 min/class)
- `deep` — + full function/property details, call chains, narrative entry (~10-15 min/class)

If depth is not specified, use the default from the tier table below.

## Workflow

1. **Check existing coverage** — call `ue_analysis_status` to see what's already done.

2. **Determine target files** based on the argument:
   - If a class name (starts with A, U, F, E, I, S, T): find its header in `C:/UE_5.7/Engine/Source/` or `C:/UE_5.7/Engine/Plugins/`
   - If a module name: find all public headers in that module
   - If a subsystem: pick top classes for that subsystem
   - If `next`: pick the most impactful unanalyzed subsystem/class
   - If `status`: just show `ue_analysis_status` results and stop

3. **Search for existing data** — call `ue_search` or `ue_query_class` to check what already exists.

4. **Read the header file(s)** from the UE source tree.

5. **Extract and save structured data** based on analysis depth:

---

### Depth: stub

For each UCLASS/USTRUCT/UENUM/interface found in the header:
- `ue_save_class` with: name, kind, parent_class, outer_class, subsystem, module, header_path, class_specifiers, doc_comment
- Set `analysis_depth = "stub"`

**Goal**: build the inheritance graph quickly. Suitable for bulk module scanning (~30 classes per session).

---

### Depth: shallow

Everything from stub, plus for the main class:
- `ue_save_class` with additional fields:
  - `summary` — 1-3 sentence Claude-written description
  - `inheritance_chain` — full parent chain to root: `["APawn", "AActor", "UObject"]`
  - `interfaces` — implemented interfaces
  - `lifecycle_order` — e.g. `"Constructor -> PostInitializeComponents -> BeginPlay -> Tick -> EndPlay"`
  - `key_methods` — array of `{"name": "BeginPlay", "brief": "Called when play begins"}`
  - `key_properties` — array of `{"name": "RootComponent", "type": "USceneComponent*", "specifiers": "BlueprintReadOnly, VisibleAnywhere"}`
  - `key_delegates` — array of `{"name": "OnDestroyed", "signature": "FActorDestroyedSignature"}`
- Set `analysis_depth = "shallow"`

**Goal**: understand a class well enough to use it. Good for tier 3-4 classes.

---

### Depth: deep

Everything from shallow, plus detailed per-member analysis:

**Functions** — call `ue_save_function` for each important public/protected method:
- `name`, `class_name`, `subsystem`
- `return_type`, `parameters` (array of `{"name": "DeltaTime", "type": "float"}`)
- `signature_full` — complete C++ signature as in header
- `ufunction_specifiers` — e.g. `"BlueprintCallable, Category=\"Game\""`, verbatim from UFUNCTION()
- Boolean flags: `is_virtual`, `is_const`, `is_static`, `is_blueprint_callable`, `is_blueprint_event`, `is_rpc`
- `rpc_type` — `"Server"`, `"Client"`, `"NetMulticast"`, or `""` if not RPC
- `doc_comment` — verbatim `/** */` comment from source
- `summary` — Claude-written description of what the function does
- `call_context` — when/how this gets called (e.g. "Called by engine after all components are initialized")
- `call_order` — position in sequence (e.g. "After PostInitializeComponents, before ReceiveBeginPlay")
- `calls_into` — array of qualified names this function calls: `["AActor::ReceiveBeginPlay"]`
- `called_by` — array of qualified names that call this: `["UWorld::BeginPlay"]`

**Properties** — call `ue_save_property` for each UPROPERTY:
- `name`, `class_name`, `subsystem`, `property_type`
- `default_value` — if known from header or constructor
- `uproperty_specifiers` — verbatim from UPROPERTY(), e.g. `"EditAnywhere, BlueprintReadWrite, Replicated"`
- `is_replicated`, `replicated_using` — OnRep function name if using `ReplicatedUsing`
- `is_blueprint_visible`, `is_edit_anywhere`, `is_config`
- `doc_comment`, `summary`

**Narrative** — call `ue_save` to create a detailed overview entry:
- Link to the class via `entry_id` in `ue_save_class`
- Include architecture notes, common usage patterns, gotchas

Set `analysis_depth = "deep"`

**Goal**: complete reference for the most critical classes. Use for tier 1-2.

---

6. **Update parent classes** — call `ue_save_class` on parent classes to add this class to `known_children`.

7. **Log analysis** — call `ue_log_analysis` with:
   - `file_path` — relative path from Engine/Source/
   - `module`, `subsystem`, `analysis_depth`
   - `classes_found`, `functions_found`, `properties_found` — counts of items saved
   - `notes` — any observations about the file

8. **Report** — summarize:
   - What was analyzed (files, classes)
   - How many classes/functions/properties were saved
   - Depth achieved
   - Suggestions for what to analyze next

## Default depth by tier

| Tier | Classes | Default depth |
|------|---------|---------------|
| 1 | UObject, AActor, APawn, ACharacter, APlayerController, AGameModeBase, AGameStateBase | deep |
| 2 | UActorComponent, USceneComponent, UAbilitySystemComponent, UGameplayAbility, UGameplayEffect, UAttributeSet | deep |
| 3 | APlayerState, AController, AAIController, UMovementComponent, UCharacterMovementComponent, AInfo | shallow |
| 4 | Everything else | stub |

When the second argument is provided (e.g. `/ue-analyze AActor deep`), always use the specified depth regardless of tier.

## Rules

- **Search before saving**: always call `ue_search` or `ue_query_class` first to avoid duplicates. If entry exists — update it, don't create a new one.
- **Don't save private helpers**: skip internal implementation details, only document public/protected API.
- **Don't save deprecated API**: unless commonly misused.
- **Skip platform-specific code**: `#if PLATFORM_WINDOWS` etc.
- **Skip Editor-only code**: `#if WITH_EDITOR` — unless the analysis target is an Editor class.
- **Preserve doc comments verbatim**: copy `/** */` comments exactly as they appear in source.
- **Use correct subsystem**: match the class to the right subsystem from the valid list.
- **Multiple classes per file**: analyze all UCLASS/USTRUCT/UENUM in the header, not just the main one.
- **Depth is incremental**: if a class was previously analyzed at `stub`, running `shallow` adds to the existing data. Arrays are merged, depth only upgrades.
