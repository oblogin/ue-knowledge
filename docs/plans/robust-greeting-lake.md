# Plan: Система заполнения UE Knowledge Base из исходников

## Context

UE Knowledge Base содержит одну таблицу `entries` для свободных заметок. Для систематического заполнения из исходников UE (40K файлов в Engine/Source, 85K в Plugins) нужна структурированная схема для классов, функций, свойств и их взаимосвязей, а также workflow для поэтапного анализа.

## Что меняется

### 1. Новые таблицы в `server.py` SCHEMA

**`classes`** — реестр UE классов/структур/enum/интерфейсов:
- `name`, `kind` (class/struct/enum/interface), `parent_class`, `subsystem`, `module`, `header_path`
- `class_specifiers` — UCLASS/USTRUCT спецификаторы как в исходнике
- `doc_comment` — оригинальный `/** */` комментарий
- `summary` — краткое описание от Claude
- `inheritance_chain`, `known_children`, `interfaces` — JSON-массивы
- `key_methods`, `key_properties`, `key_delegates` — JSON-массивы объектов с краткими описаниями
- `lifecycle_order` — текстовая цепочка вызовов lifecycle
- `analysis_depth` (stub / shallow / deep) — глубина анализа
- `entry_id` — FK на `entries` для связи с нарративной записью
- FTS5 таблица `classes_fts` + триггеры

**`functions`** — ключевые методы/функции:
- `name`, `qualified_name` (unique, например `AActor::BeginPlay`), `class_name`, `subsystem`
- `return_type`, `parameters` (JSON), `signature_full` — полная сигнатура
- `ufunction_specifiers` — спецификаторы как в исходнике
- Булевы флаги: `is_virtual`, `is_const`, `is_static`, `is_blueprint_callable`, `is_blueprint_event`, `is_rpc`
- `rpc_type` (Server/Client/NetMulticast)
- `doc_comment`, `summary`
- **Цепочки вызовов**: `call_context`, `call_order`, `calls_into` (JSON), `called_by` (JSON)

**`properties`** — UPROPERTY свойства:
- `name`, `qualified_name` (unique), `class_name`, `subsystem`
- `property_type`, `default_value`, `uproperty_specifiers`
- Булевы флаги: `is_replicated`, `is_blueprint_visible`, `is_edit_anywhere`, `is_config`
- `replicated_using` — имя OnRep функции
- `doc_comment`, `summary`

**`analysis_log`** — трекинг прогресса:
- `file_path`, `module`, `subsystem`, `analysis_depth`
- `classes_found`, `functions_found`, `properties_found`, `notes`, `analyzed_at`

### 2. Новые MCP tools (8 штук)

| Tool | Назначение |
|------|-----------|
| `ue_save_class` | Сохранить/обновить запись о классе. Upsert по `name` с мержем массивов |
| `ue_save_function` | Сохранить метод/функцию. Upsert по `qualified_name` |
| `ue_save_property` | Сохранить UPROPERTY. Upsert по `qualified_name` |
| `ue_query_class` | Полная информация о классе + его функции и свойства из всех таблиц |
| `ue_query_hierarchy` | Обход дерева наследования (вверх/вниз/оба направления) |
| `ue_query_calls` | Цепочки вызовов: кто вызывает функцию / что она вызывает |
| `ue_analysis_status` | Прогресс анализа: что покрыто, на какой глубине, что осталось |
| `ue_log_analysis` | Записать что файл был проанализирован |

Также расширить `ue_stats` — добавить counts по новым таблицам.

### 3. Логика merge-on-save

`ue_save_class`: если класс с таким `name` уже есть:
- Обновить непустые поля
- JSON-массивы (`known_children`, `interfaces`) — объединить (union), не заменять
- `analysis_depth` — только повышать (stub → shallow → deep)

`ue_save_function` / `ue_save_property`: upsert по `qualified_name` — обновить все предоставленные поля.

### 4. Skill `/ue-analyze`

Файл: `~/.claude/commands/ue-analyze.md`

Workflow:
1. Проверить `ue_analysis_status` — что уже покрыто
2. Определить целевые файлы (по имени класса / модулю / подсистеме / "next")
3. Читать заголовочные файлы из `C:/UE_5.7/Engine/Source/` или `Plugins/`
4. Извлекать данные по протоколу глубины:
   - **stub** (~1 мин): имя, kind, parent, specifiers, doc_comment → `ue_save_class`
   - **shallow** (~3-5 мин): + key_methods, key_properties, key_delegates, lifecycle → `ue_save_class`
   - **deep** (~10-15 мин): + полные `ue_save_function` / `ue_save_property` для каждого важного метода/свойства + нарратив через `ue_save`
5. Записать `ue_log_analysis`
6. Обновить `known_children` у родительских классов

### 5. Фазы заполнения

| Фаза | Подсистема | Ключевые классы | Глубина | ~Сессий |
|------|-----------|----------------|---------|---------|
| 1 | Gameplay Foundation | UObject, AActor, APawn, ACharacter, AController, APlayerController, GameMode/State, Components | deep для топ-6, shallow остальное | 3 |
| 2 | GAS | UAbilitySystemComponent, UGameplayAbility, UGameplayEffect, UAttributeSet | deep для топ-4 | 2 |
| 3 | Networking | Replication в AActor, ActorChannel, NetDriver | shallow-deep | 2 |
| 4 | Core UObject | UClass, UStruct, UFunction, GC, Serialization, Delegates | shallow-deep | 2 |
| 5 | UI (Slate/UMG) | UWidget, UUserWidget, SWidget | shallow | 2 |
| 6 | Animation | UAnimInstance, UAnimMontage, State Machines | shallow | 1 |
| 7 | AI | BehaviorTree, EQS, AIController | shallow | 1 |
| 8 | Enhanced Input | UInputAction, UInputMappingContext | shallow | 1 |
| 9 | Остальное | Niagara, PCG, MassEntity, WorldPartition, Chaos | stub-shallow | по необходимости |

Параллельно: **stub pass** по целым модулям (~30 классов за сессию) для быстрого построения графа наследования.

### 6. Что НЕ сохранять

- Приватные helper-методы
- Deprecated API (кроме часто используемых по ошибке)
- Платформо-специфичный код (`#if PLATFORM_WINDOWS`)
- Editor-only код (кроме фазы editor)
- Raw содержимое файлов — только извлечённую информацию

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `~/.ue-knowledge/server.py` | Добавить 4 таблицы в SCHEMA, новые методы KnowledgeDB, 8 MCP tools, handler routing |
| `~/.ue-knowledge/tests.py` | Тесты для каждой новой таблицы, tool, merge-логики |
| `~/.claude/commands/ue-analyze.md` | Создать skill для workflow анализа |
| `~/.ue-knowledge/README.md` | Документация по новым tools и workflow |
| `~/.claude/CLAUDE.md` | Обновить описание инструментов |

## Проверка

1. Запустить `python -m unittest tests -v` — все тесты зелёные
2. Запустить MCP сервер: `timeout 3 python server.py` — без ошибок
3. Сделать тестовый прогон: `/ue-analyze AActor` — проверить что данные корректно сохраняются
4. Проверить `ue_query_class AActor` — возвращает полную информацию
5. Проверить `ue_query_hierarchy AActor` — показывает UObject выше, APawn/AInfo ниже
6. Проверить `ue_stats` — показывает counts по всем таблицам
