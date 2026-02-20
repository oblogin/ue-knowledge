# Plan: 10 улучшений UE Knowledge Base MCP Server

## Context

Сервер работает, 133 теста зелёные, схема с 5 таблицами. Код-ревью выявило 10 улучшений: критичные баги (FTS-поиск только по 2 из 5 таблиц, каскадное удаление, неограниченная рекурсия, json.loads без обработки ошибок) и полезные фичи (фильтр по тегам, batch-операция, нормализация тегов, индексы на FK, пагинация, версионирование схемы).

## Порядок реализации

### Фаза 1 — Фундамент схемы

**1. Версионирование схемы (Improvement 10)**
- Добавить таблицу `schema_version` в `SCHEMA`
- Добавить `MIGRATIONS` список (version, description, sql_statements)
- Добавить `_current_schema_version()` и `_run_migrations()` в KnowledgeDB
- Вызывать `_run_migrations()` в `__init__` после `executescript(SCHEMA)`

**2. Индексы на entry_id (Improvement 8)**
- В `SCHEMA`: добавить `idx_classes_entry_id`, `idx_functions_entry_id`, `idx_properties_entry_id`
- Migration v1: те же CREATE INDEX IF NOT EXISTS для существующих БД

**3. FTS на functions и properties (Improvement 1)**
- В `SCHEMA`: добавить `functions_fts` и `properties_fts` (FTS5) + 6 триггеров
- Migration v2: создать FTS-таблицы + триггеры + `INSERT INTO ...fts VALUES('rebuild')`
- Новый метод `search_all()` — единый поиск по всем 4 FTS-таблицам
- Расширить `ue_search` tool: новый параметр `tables` (массив из `entries/classes/functions/properties`)
- Без `tables` — старое поведение (только entries), обратная совместимость

**4. Каскадное удаление (Improvement 2)**
- В `delete()`: перед DELETE добавить 3 UPDATE для SET entry_id = NULL в classes/functions/properties

### Фаза 2 — Целостность данных

**5. Безопасный JSON (Improvement 4)**
- Новая функция `_safe_json_loads(value, default=None)` — try/except с fallback на []
- Заменить все 12 вызовов `json.loads()` на `_safe_json_loads()`
- Места: `_merge_json_arrays`, `get_class`, `query_calls`, `query_class_full`, `_handle` (ue_search/ue_get/ue_list)

**6. Нормализация тегов (Improvement 7)**
- Новый метод `_normalize_tags(tags)` — lowercase, strip, dedup, сохраняя порядок
- Применить в `save()` и `update()` перед json.dumps(tags)

**7. Ограничение рекурсии (Improvement 3)**
- `query_hierarchy()`: новые параметры `max_children_per_level=50`, `max_total=500`
- Добавить `LIMIT` в SQL-запрос children
- Добавить счётчик `total_count`, при превышении — `result["truncated"] = True`
- `ue_query_hierarchy` tool: добавить 2 параметра в inputSchema
- Обновить handler в `_handle()`

### Фаза 3 — Новые фичи

**8. Фильтрация по тегам (Improvement 5)**
- Новый метод `_filter_by_tags(rows, tags)` — post-query фильтр по JSON-тегам
- `search()`: новый параметр `tags` — case-insensitive, все указанные теги должны присутствовать
- `ue_search` tool: добавить `tags` в inputSchema

**9. Метаданные пагинации (Improvement 9)**
- `search()`: добавить COUNT-запрос, вернуть `(rows, total_matches)` вместо `rows`
- `list_entries()`: аналогично вернуть `(rows, total)`
- `_handle` ue_search/ue_list: добавить `total_matches` в ответ
- **Breaking change для внутренних вызовов**: обновить все тесты, вызывающие `search()` и `list_entries()` (~15 тестов)

**10. Batch-операция (Improvement 6)**
- Добавить `_commit=True` параметр в `save_class`, `save_function`, `save_property`
- Новый метод `save_batch(items)`: каждый item = `{type: "class"|"function"|"property", ...fields}`
- Вызывает save_* с `_commit=False`, потом один `commit()`
- Ошибки в отдельных items не ломают остальные (записываются в `errors`)
- Новый MCP tool `ue_save_batch` + handler

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `server.py` | SCHEMA: +1 таблица, +2 FTS, +6 триггеров, +3 индекса. KnowledgeDB: 7 новых методов, 8 изменённых. TOOLS: 3 изменённых tool, 1 новый. _handle: 4 изменённых handler, 1 новый |
| `tests.py` | ~15 существующих тестов обновить (search/list возвращают tuple). ~56 новых тестов. 7 новых test-классов |
| `README.md` | Обновить документацию: новый tool ue_save_batch, изменённые параметры ue_search и ue_query_hierarchy |

## Проверка

1. `python -m unittest tests -v` — все ~189 тестов зелёные
2. `timeout 3 python server.py` — без ошибок
3. Удалить knowledge.db, перезапустить сервер — схема + миграции создаются с нуля
4. Создать БД без миграций (старый формат), запустить новый сервер — миграции применяются
5. Проверить через MCP: `ue_search` с `tables=["functions"]` находит сохранённые функции
6. Проверить: `ue_search` с `tags=["actor"]` фильтрует корректно
7. Проверить: `ue_save_batch` сохраняет 3 item-а атомарно
8. Проверить: `ue_delete` entry с linked class — entry_id в классе становится NULL
