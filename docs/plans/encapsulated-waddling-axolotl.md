# Unity Knowledge Base — План реализации

## Контекст

Существует работающий MCP-сервер `ue-knowledge` (~1600 строк Python) с SQLite + FTS5 базой знаний по Unreal Engine. Пользователь хочет аналогичную систему для Unity C# Scripting API. Создаём отдельный проект в `~/.unity-knowledge/`.

## Структура проекта

```
~/.unity-knowledge/
├── server.py                          # MCP-сервер (адаптация ue-knowledge)
├── .mcp.json                          # Конфигурация MCP
├── .gitignore                         # knowledge.db, __pycache__, *.db-*
├── .claude/settings.local.json        # Разрешения для инструментов
├── hooks/
│   ├── unity-kb-session-start.sh      # Первый промпт — напомнить поиск в KB
│   ├── unity-kb-prompt-context.sh     # Каждый промпт — напомнить сохранение
│   └── unity-kb-save-reminder.sh      # Stop — блокировать до сохранения
├── skills/
│   └── unity-analyze-codex/SKILL.md   # Skill /unity-analyze
└── workflows/
    └── unity-analyze.md               # Workflow для Gemini Code
```

## Ключевые адаптации UE → Unity

### Subsystems (22 шт.)
`core` · `gameplay` · `rendering` · `physics` · `physics-2d` · `ui` · `input` · `animation` · `ai` · `audio` · `networking` · `editor` · `assets` · `scenes` · `ecs` · `rendering-pipeline` · `serialization` · `async` · `testing` · `build` · `xr` · `other`

### Categories (10 шт.)
`class` · `function` · `pattern` · `gotcha` · `architecture` · `example` · `config` · `attribute` (вместо macro) · `package` (вместо module) · `best-practice`

### Kinds: `class` · `struct` · `enum` · `interface` · `delegate` (новый)

### Qualified name: `Class.Method` (точка вместо `::`)

### Схема classes
| UE → Unity |
|---|
| `outer_class` → `enclosing_type` |
| `module` → `namespace` |
| `header_path` → `assembly` |
| `class_specifiers` → `attributes` |
| `key_delegates` → `key_events` |

### Схема functions
| Убрано | Добавлено |
|---|---|
| `is_const`, `ufunction_specifiers` | `attributes` |
| `is_blueprint_callable` | `is_coroutine` |
| `is_blueprint_event` | `is_async` |
| `is_rpc`, `rpc_type` | `is_unity_message`, `is_editor_only` |
| — | `is_abstract`, `is_override`, `access_modifier` |

### Схема properties
| Убрано | Добавлено |
|---|---|
| `uproperty_specifiers` | `attributes` |
| `is_replicated` | `is_serialized` |
| `replicated_using` | `serialization_backend` |
| `is_blueprint_visible` | `is_inspector_visible` |
| `is_edit_anywhere` | `is_readonly` |
| `is_config` | `is_static`, `access_modifier`, `property_kind` |

### analysis_log
- `file_path` → `source_url` (Unity docs URLs)
- `module` → `package` (Unity пакеты)

### Hooks: детекция Unity-проекта
- Ищем `ProjectSettings/ProjectSettings.asset` или `Assembly-CSharp.csproj` в PWD + 2 уровня вверх

## Шаги реализации

### 1. Создать директорию и структуру `~/.unity-knowledge/`

### 2. Написать `server.py`
Адаптировать `~/.ue-knowledge/server.py`:
- Заменить все `ue_` → `unity_`, `ue-knowledge` → `unity-knowledge`
- Заменить VALID_SUBSYSTEMS, VALID_CATEGORIES, VALID_KINDS
- Адаптировать CREATE TABLE для classes, functions, properties, analysis_log
- Обновить FTS5 виртуальные таблицы и триггеры под новые колонки
- Обновить KnowledgeDB методы (save_class, save_function, save_property, etc.)
- Обновить определения 17 инструментов под Unity-схему
- Обновить _handle() маршрутизацию

### 3. Написать `.mcp.json`, `.gitignore`, `.claude/settings.local.json`

### 4. Написать 3 hook-скрипта
Адаптировать из ue-knowledge, заменить детекцию .uproject на ProjectSettings/

### 5. Написать skill `/unity-analyze` и workflow
Адаптировать для работы с Unity Scripting Reference (docs.unity3d.com)

### 6. Дополнить `~/.claude/CLAUDE.md`
Добавить секцию Unity Knowledge Base по аналогии с UE

### 7. Зарегистрировать MCP-сервер
`claude mcp add unity-knowledge --scope user -- python C:/Users/oblog/.unity-knowledge/server.py`

## Файлы-источники (для адаптации)
- `C:\Users\oblog\.ue-knowledge\server.py` — основной сервер (1588 строк)
- `C:\Users\oblog\.ue-knowledge\hooks\*` — шаблоны хуков
- `C:\Users\oblog\.ue-knowledge\commands\ue-analyze.md` — шаблон skill
- `C:\Users\oblog\.claude\CLAUDE.md` — для дополнения

## Верификация
1. Запустить `python server.py` — сервер стартует без ошибок
2. Через Claude Code вызвать `unity_stats` — ответ с пустой базой
3. Вызвать `unity_save` с тестовой записью — успешно сохранено
4. Вызвать `unity_search` — находит запись
5. Вызвать `unity_save_class` — upsert работает
6. Зайти в Unity-проект — хуки срабатывают
