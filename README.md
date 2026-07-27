# NexusFlow

**Візуальний конструктор workflow-сценаріїв.**
JSON описує граф (вузли + ребра) → рушій будує черги готових вузлів і виконує їх **паралельно у воркер-пулі** → стрімить логи.

Аналог n8n / Node-RED, максимально простий. UI - React Flow редактор з drag-and-drop і live-логами; backend - FastAPI + asyncio. Авто-документація API вимкнена: фронтенд - єдина точка входу.

> **Async Ready Pool.** Двигун - не «for node in topological_sort», а пул із 6 воркер-задач, які наввипередки беруть вузли з `asyncio.Queue` готовності. Дві незалежні гілки з `asyncio.sleep(1)` фінішують ~за 1 секунду, а не за 2. Усі мутації стану - атомарні під `asyncio.Lock`, тож вузли запускаються у чергу рівно один раз. Перша критична помилка виставляє `should_stop=True`: нові вузли не стартують, але вже запущені дограють до кінця (м'яка зупинка, без cancel'ів посеред I/O).

---

## Старт

**Вимоги:** Python 3.11+, Node.js 20+, Docker.

### Як запустити
Клонувати репозиторій: git clone [Посилання на репозиторій]
cd nexusflow
```bash
docker compose up
```
---

## Async Ready Pool - паралельний двигун

**Робота двигуна**:

```
                  ┌──────────────┐
                  │ ready_queue  │  asyncio.Queue (готові вузли)
                  └──────┬───────┘
                ┌────────┼────────┬────────┐
                ▼        ▼        ▼        ▼
            ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
            │ W1  │  │ W2  │  │ W3  │  │ … 6 │   фіксовані воркери
            └──┬──┘  └──┬──┘  └──┬──┘  └──┬──┘
               │        │        │        │
               ▼        ▼        ▼        ▼
            execute  execute  execute  execute    одночасно
               │        │        │        │
               └────────┴───┬────┴────────┘
                            ▼
                   ┌──────────────────┐
                   │  state.lock      │  атомарне оновлення:
                   │  + dead_edges    │   • node_outputs[id] = output
                   │  + finished      │   • children: in_degree--
                   │  + scheduled     │   • готові → put у чергу
                   └──────────────────┘
```

### Різниця між послідовним і моїм двигуном

| Сценарій                                | Послідовний двигун | Async Ready Pool |
|-----------------------------------------|--------------------|------------------|
| 2 паралельні I/O-вузли по 1 с           | ~2 с               | **~1 с**         |
| 6 паралельних вузлів × 0.5 с            | ~3 с               | **~0.5 с**       |
| 1 вузол падає, інший паралельний працює | помилка одразу     | падючий зупиняє пул, інший дограє |

Покрито тестами `test_two_parallel_sleeps_finish_in_about_one_second`, `test_six_parallel_sleeps_within_worker_pool_limit`, `test_failure_in_one_branch_lets_running_finish_but_blocks_new`.

### Гарантії потокобезпеки (`app/core/context.py`)

- `ExecutionContext.lock` - `asyncio.Lock` для всіх мутацій спільного стану.
- `should_stop: bool` - м'який прапорець зупинки. Воркер перевіряє його **перед** тим, як забрати наступний вузол із черги; уже запущений вузол виконується до кінця.
- `first_error: BaseException | None` - перша критична помилка, яку рушій передасть `JobManager` після того, як активні воркери дограли (job → `FAILED`).
- `resolve_template(template, input_data)` створює локальні snapshot'и `dict(self.node_outputs)` та `dict(input_data)` перед ітерацією - це уникає `RuntimeError: dictionary changed size during iteration`, коли паралельний воркер пише в `node_outputs` під час підстановки.
- **Глобального `current_input` немає.** Вхідні дані формуються двигуном **локально** для кожного виклику й передаються як параметр у `execute(context, input_data)` - це data isolation на рівні параметра функції, race-condition між паралельними вузлами неможлива в принципі.

---

## Frontend

Стек: **Vite 5 + React 18 + Tailwind 3 + `@xyflow/react` + `@tiptap/react`** + **`dagre`**, (локальна) i18n-бібліотек.

### Інтерфейс

```
┌─────────────────────────────────────────────────────────────┐
│ NexusFlow                                          [EN][UK] │
├──────────┬──────────────────────────────────────┬───────────┤
│ Palette  │                                      │ Settings  │
│  Nodes   │                                      │           │
│  Manual  │                                      │ id: t1    │
│  Read    │          React Flow Canvas           │ type: ... │
│  Write   │       (drag nodes from left)         │           │
│  Cond    │                                      │ ...form   │
│  Log     │                                      │           │
│  ─────   │                                      │           │
│  Saved   │                                      │           │
│   hello  │                                      │           │
│   math   ├──────────────────────────────────────┤ [delete]  │
│          │  [name] [Save] [Run workflow]        │           │
│          ├──────────────────────────────────────┤           │
│          │  Live logs (WebSocket)               │           │
│          │  [info] t1 : Executing...            │           │
└──────────┴──────────────────────────────────────┴───────────┘
```

### Як зібрати workflow в редакторі

1. **Перетягни** `Manual trigger` з палітри ліворуч на канвас.
2. Перетягни `Log`. На вузлі справа з'явиться `source` handle, на новому ліворуч - `target`.
3. **З'єднай** їх, потягнувши від правого handle до лівого.
4. Клікни на `Log` → у правій панелі введи `message`, наприклад `Hello, {input.user}!`.
5. Введи назву сценарію та натисни **`Save`** - він з'явиться в палітрі ліворуч у секції *Saved workflows*. Будь-який запис у тій секції завантажується одним кліком.
6. Натисни **`Run workflow`**. Знизу побачиш `job_id` і **live-стрім логів** через WebSocket.

### Зміна мови

Кнопки `EN` / `UK` у правому верхньому куті. Стан зберігається в `localStorage` (ключ `nexusflow.lang`).

### Як додати ще один переклад

Файл `frontend/src/i18n.js`:
```javascript
export const SUPPORTED_LANGS = ["en", "uk", "pl"]; // <- додай код
export const translations = {
  en: { ... },
  uk: { ... },
  pl: { app: { title: "NexusFlow", subtitle: "Edytor scenariuszy" }, ... },
};
```
### Динамічна панель налаштувань

| JSON-Schema fragment                               | UI-рендер                                       |
|----------------------------------------------------|-------------------------------------------------|
| `type: "string"` (короткі поля)                    | `<input type="text">`                           |
| `type: "string"` для `message`/`content`/`prompt`/… | `<textarea>` (евристика по імені поля)         |
| `type: "boolean"`                                  | `<input type="checkbox">`                       |
| `type: "integer"` / `"number"`                     | `<input type="number">`                         |
| `enum: [...]`                                      | `<select>` із варіантами                        |
| `type: "object"` / `"array"`                       | `<textarea>` із live-валідацією JSON            |
| `name ∈ {initial_data, params}`                    | `<textarea>` JSON, незалежно від declared type  |
| `description` містить слово **"JSON"**             | `<textarea>` JSON, незалежно від declared type  |
| `anyOf: [{string},{null}]`                         | unwrap до non-null типу (Pydantic optional)     |

**Лейбл** поля: `t(\`config.<propName>\`, schema.title \|\| propName)` - спочатку i18n-ключ, потім бекендний `title`, потім сире ім'я. **Підказка під полем (hint)**: `schema.description` зі схеми (переклад опційний через `config.<propName>.hint`). Це означає: бекенд-розробник пише змістовний `description=` у Pydantic-полі один раз, і UI одразу показує hint під відповідним інпутом - без правок фронтенду.

---

## Збереження та завантаження сценаріїв

Сценарії зберігаються як JSON-файли у `workflows/`. UI редактор уміє:

- **Завантажувати** будь-який збережений сценарій одним кліком - у лівій палітрі під списком вузлів є секція **«Saved workflows / Збережені сценарії»** зі списком імен (`GET /workflows`). Клацання по імені тягне `GET /workflows/<name>`, конвертує JSON у React Flow-стан і замінює канвас. **Координати тепер живуть у `Node.ui_metadata.position`** - див. секцію [UI Metadata Pocket + Dagre auto-layout](#ui-metadata-pocket--dagre-auto-layout). Якщо позицій нема (старий сценарій або щойно згенерований із Python-коду), фронтенд авто-розкладає граф через **Dagre** (`rankdir: LR`) і вузли не накладаються.
- **Зберігати** поточний канвас однією кнопкою - у `RunPanel` поруч із «Run workflow» з'явилася кнопка **«Save / Зберегти»**. Вона серіалізує канвас у backend-формат (включно з `source_handle` / `target_handle` і `ui_metadata.position`), кидає `POST /workflows`, і після успіху палітра автоматично оновлює список (через лічильник `workflowsRefresh` в `App.jsx`).


### Покрите тестами

- `tests/test_schemas.py::test_workflow_rejects_cyclic_graph` - `A→B`, `B→A` → ValidationError зі словом `cycle` та переліком `['a', 'b']` у тексті.
- `tests/test_schemas.py::test_workflow_rejects_self_loop` - навіть `A→A` (self-loop) ловиться.
- `tests/test_api.py::test_cycle_rejected_at_request_validation` - кінець-в-кінець через REST: 422 + потрібний текст.
- `tests/test_engine.py::test_topological_sort_detects_cycle` - низькорівнева перевірка `topological_sort` із прямим створенням `Node`/`Edge` (без `Workflow`-валідації).

---

## Архітектура

```
                       HTTP / WS  (FastAPI)
                              │
    ┌─────────────────────────┼─────────────────────────┐
    │                         │                         │
 /workflows                /jobs                    /ws/jobs
 (CRUD JSON)         (POST run, GET status)       (live logs)
    │                         │                         │
    │                         ▼                         │
    │                  ┌─────────────┐                  │
    │                  │ JobManager  │                  │
    │                  │  (in-mem)   │──┐               │
    │                  └─────┬───────┘  │ підписка      │
    │                        │          ▼               │
    │                        │   ┌─────────────┐        │
    │                        │   │  LogBroker  │◄───────┤
    │                        │   │ (pub/sub на │        │
    │                        │   │ asyncio.Q)  │        │
    │                        │   └──────▲──────┘        │
    │                        │          │ publish       │
    │                        ▼          │               │
    │                  ┌─────────────┐  │               │
    │                  │WorkflowEngine│ │               │
    │                  │ Async Ready │  │               │
    │                  │    Pool     │  │               │
    │                  │             │  │               │
    │                  │ ready_queue │  │               │
    │                  │     ↕       │  │               │
    │                  │ 6 workers ──┼──┘               │
    │                  │     ↕       │                  │
    │                  │ state.lock  │                  │
    │                  └─────┬───────┘                  │
    │                        │                          │
    │                        ▼                          │
    │                  ┌─────────────┐                  │
    │                  │NODE_REGISTRY│                  │
    │                  │  (5 типів)  │                  │
    │                  └─────────────┘                  │
    └───────────────────────────────────────────────────┘
                              │
                              ▼
                       data/  workflows/   (файлова система)
```

### Ключові компоненти

| Модуль | Відповідальність |
|---|---|
| `app/api/workflows.py` | CRUD над JSON-файлами в `workflows/` |
| `app/api/jobs.py` | приймає `POST /jobs/run`, делегує `JobManager` (перевірка ациклічності тепер у `Workflow`-валідаторі - request-body відсіюється FastAPI до handler'а) |
| `app/api/websocket.py` | WS-підписка з replay'ем історії - щоб пізні підписники не пропустили нічого |
| `app/core/scheduler.py` | топологічне сортування Kahn'а, `CycleDetectedError` (тепер використовується лише як ациклічна перевірка перед стартом пулу) |
| `app/core/engine.py` | **Async Ready Pool** - 6 паралельних воркерів, `asyncio.Queue` готових вузлів, атомарне поширення «фініш-сигналу» під `state.lock`, м'яка зупинка через `context.should_stop`, dead-edges каскад |
| `app/core/job_manager.py` | реєстр `Job` + супервайзер `asyncio.create_task`, sentinel `done` після фінішу, TTL із `MAX_JOBS=500` + `task.cancel()` для завислих корутин (див. [TTL у JobManager](#ttl-у-jobmanager-захист-від-витоку-памяті)) |
| `app/core/log_broker.py` | pub/sub на `asyncio.Queue` per `job_id` |
| `app/core/context.py` | `ExecutionContext` - потокобезпечна спільна пам'ять (`asyncio.Lock`, `should_stop`, `first_error`) + `resolve_template(template, input_data)` зі snapshot'ами |
| `app/nodes/base.py` | `BaseNode` ABC + прапорець `is_visual_only` (для нот-стікерів, що ігноруються рушієм) + `NODE_REGISTRY` + декоратори `@input_port`, `@output_port`, `@node_info`, `@static_connection`, `@register_node` + `get_schema()` |
| `app/nodes/<name>.py` | реалізація конкретного вузла (один файл - один вузол) |
| `app/schemas/` | Pydantic-моделі: `Workflow`, `Node`, `Edge`, `Job`, `LogEntry`, конфіги вузлів. `_check_graph_integrity` робить fail-loud перевірки: унікальність id, валідність посилань ребер, ациклічність та [satisfaction обов'язкових портів](#розумна-валідація-обовязкових-портів) |
| `app/storage/file_storage.py` | сейв/лоад `Workflow` як JSON, валідація імен (`[A-Za-z0-9_-]{1,64}`) |

### Вбудовані типи вузлів

| `type_name` | Що робить | Inputs (порти) | Outputs (порти) |
|---|---|---|---|
| `manual_trigger` | повертає `config.initial_data` | - | `data` |
| `read_file` | `aiofiles` читає файл за `config.path` | `path` | `content`, `size`, `path` |
| `write_file` | пише текст у файл (sandbox: `data/`) | `path`, `content` | `path`, `bytes_written`, `append` |
| `condition` | безпечне булеве вираження через `simpleeval` | `input` | `true`, `false`, `result` |
| `log` | рендерить `config.message`, публікує `LogEntry` | `input`, `message` | `output` (passthrough) |
| `custom_code` | викликає `async main()` зі `scripts/<name>.py` | `input` | `output` |
| `expression` | обчислює довільний sandbox-вираз | `expression`, `input` | `result` |
| `note` | **візуальний стікер для документування графа** (`is_visual_only=True`); рушій повністю ігнорує | - | - |

## Тести

### Backend
```bash
pytest                                                                # усі тести
pytest --cov=app.core --cov=app.nodes --cov-report=term-missing       # з покриттям
```

Поточний стан: **119 passed** - 117 тестів попередніх етапів + **2 нових тести фільтрації візуальних вузлів**.

---