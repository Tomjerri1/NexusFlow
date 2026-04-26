# NexusFlow

**Візуальний конструктор workflow-сценаріїв.**
JSON описує граф (вузли + ребра) → рушій топологічно сортує → виконує вузли асинхронно → стрімить логи через WebSocket.

Аналог n8n / Node-RED, максимально простий. UI — React Flow редактор з drag-and-drop і live-логами; backend — FastAPI + asyncio. Авто-документація API вимкнена: фронтенд — єдина точка входу.

---

## Зміст

- [Швидкий старт](#швидкий-старт)
- [Frontend (React Flow редактор)](#frontend-react-flow-редактор)
- [Гібридна модель декларативного мапінгу](#гібридна-модель-декларативного-мапінгу)
- [WebSocket: live-логи](#websocket-live-логи)
- [Архітектура](#архітектура)
- [Структура проєкту](#структура-проєкту)
- [Тести](#тести)
- [Як додати новий тип вузла](#як-додати-новий-тип-вузла)
- [Обмеження MVP і майбутнє](#обмеження-mvp-і-майбутнє)

---

## Швидкий старт

**Вимоги:** Python 3.11+, Node.js 20+.

Потрібні **два процеси** — backend (FastAPI) і frontend (Vite dev-server).

### Backend (термінал 1)

```bash
# через pip:
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux:    source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
# або через uv:  uv sync && uv run uvicorn app.main:app --reload
```

Backend на `http://localhost:8000`. Авто-документація API вимкнена навмисно — `/docs`, `/redoc`, `/openapi.json` повертають 404.

### Frontend (термінал 2)

```bash
cd frontend
npm install
npm run dev
```

Editor на `http://localhost:5173`. Vite dev-сервер проксить `/jobs`, `/workflows`, `/ws/jobs/*` на бекенд автоматично.

Перевірка backend'а окремо:
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Frontend (React Flow редактор)

Стек: **Vite 5 + React 18 + Tailwind 3 + `@xyflow/react`**, без TypeScript і без зовнішніх i18n-бібліотек.

### Інтерфейс

```
┌─────────────────────────────────────────────────────────────┐
│ NexusFlow                                          [EN][UK] │
├──────────┬──────────────────────────────────────┬───────────┤
│ Palette  │                                      │ Settings  │
│          │                                      │           │
│ Manual   │                                      │ id: t1    │
│ Read     │          React Flow Canvas           │ type: ... │
│ Write    │       (drag nodes from left)         │           │
│ Cond     │                                      │ ...form   │
│ Log      │                                      │           │
│          ├──────────────────────────────────────┤ [delete]  │
│          │  Run [_____ name ____] [Run workflow]│           │
│          ├──────────────────────────────────────┤           │
│          │  Live logs (WebSocket)               │           │
│          │  [info] t1 : Executing...            │           │
└──────────┴──────────────────────────────────────┴───────────┘
```

### Як зібрати workflow в редакторі

1. **Перетягни** `Manual trigger` з палітри ліворуч на канвас.
2. Перетягни `Log`. На вузлі справа з'явиться `source` handle, на новому ліворуч — `target`.
3. **З'єднай** їх, потягнувши від правого handle до лівого.
4. Клікни на `Log` → у правій панелі введи `message`, наприклад `Hello, {input.user}!`.
5. Натисни **`Run workflow`**. Знизу побачиш `job_id` і **live-стрім логів** через WebSocket.

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
Жодних додаткових налаштувань — `LangSwitcher` сам підбере новий код.

### Динамічні порти у вузлах

Кожен вузол на канвасі рендерить свої вхідні/вихідні `Handle` **зі схеми**, отриманої з `GET /api/nodes/schema`. Це означає:

- Один і той самий React-компонент `CustomNode` обслуговує всі типи — кількість і назви хендлів беруться з бекенду.
- Якщо ти додаєш новий вузол на бекенді з декораторами `@input_port` / `@output_port`, фронтенд автоматично відображає правильні точки з'єднання — **без змін у JSX**.
- Якщо схема ще не завантажилась — рендериться один target/source як fallback.

### Readonly-режим зв'язків

Якщо у схемі будь-якого з вузлів на канвасі є `static_connections: [{ ..., is_readonly: true }]`, редагування ребер блокується (`nodesConnectable=false`, видалення ліній ігнорується), а у правому верхньому куті канвасу з'являється бейдж `Edges are read-only`.

### Запуск прикладу через REST (без UI)

Якщо хочеш скриптом:
```bash
curl -X POST http://localhost:8000/jobs/run \
  -H "Content-Type: application/json" \
  -d "{\"workflow\": $(cat examples/01_hello_world.json)}"
```

Або зберегти й запускати за іменем:
```bash
curl -X POST http://localhost:8000/workflows -H "Content-Type: application/json" -d @examples/01_hello_world.json
curl -X POST http://localhost:8000/jobs/run -H "Content-Type: application/json" -d '{"workflow_name": "hello_world"}'
```

---

## Гібридна модель декларативного мапінгу

NexusFlow підтримує **типізований маршрут даних між портами**: замість того, щоб зливати весь output попереднього вузла в один словник, можна явно прокинути значення з конкретного вихідного порту в конкретний вхідний.

### Декларативні метадані у Python

Усе оголошується декораторами на класі вузла (`app/nodes/base.py`):

```python
from app.nodes.base import (
    BaseNode, input_port, output_port, node_info, static_connection,
)

@node_info(
    display_name="Write File",
    category="io",
    color="#7c3aed",
    icon="file-pen",
    description="Writes text content to a sandboxed file.",
)
@input_port("path", type_hint="str", required=True)
@input_port("content", type_hint="str", required=False)
@output_port("path", type_hint="str")
@output_port("bytes_written", type_hint="int")
class WriteFileNode(BaseNode):
    type_name = "write_file"
    config_model = WriteFileConfig

    async def execute(self, context):
        path = context.get_input(self.id, "path") or self.config.path
        content = context.get_input(self.id, "content") or self.config.content
        ...
```

- `@input_port` / `@output_port` записують `PortSpec` у `cls.__inputs__` / `cls.__outputs__`.
- `@node_info` — UI-метадані (`display_name`, `category`, `color`, `icon`, `description`).
- `@static_connection(source_port, target_node, target_port)` — *гібридна* частина: жорстко зашитий зв'язок порт→порт, який не можна редагувати з UI. У JSON-маніфесті він серіалізується з прапорцем `is_readonly: true`.
- `BaseNode.get_schema()` збирає це все в JSON-маніфест разом із `model_json_schema()` конфігу.

### JSON-маршрутизація на ребрах

`Edge` тепер має два хендли:

```json
{
  "from": "trigger",
  "to": "writer",
  "source_handle": "user_path",
  "target_handle": "path"
}
```

Перед `execute()` двигун (`app/core/engine.py`) копіює `node_outputs["trigger"]["user_path"]` у `node_inputs["writer"]["path"]`. Усередині вузла читається через `context.get_input("writer", "path")`.

Зворотна сумісність:

- Якщо `target_handle` не вказано — працює **legacy merge**: усі виходи живих батьків зливаються у `context.current_input` (як у MVP).
- `source_handle = "true" | "false"` досі означає гілку condition'а (а не порт даних) — двигун розпізнає це за іменем.
- Маршрутизатор обгорнено у `try/except`: помилка мапінгу логується як `warning`, але не валить весь job — вузол отримає порожній вхід.

### `GET /api/nodes/schema`

Ендпоінт повертає JSON-маніфест усіх вузлів із `NODE_REGISTRY` для динамічного фронтенду:

```bash
curl http://localhost:8000/api/nodes/schema | jq '.nodes[0]'
```

```json
{
  "type_name": "write_file",
  "info": {
    "display_name": "Write File",
    "category": "io",
    "color": "#7c3aed",
    "icon": "file-pen",
    "description": "Writes text content to a sandboxed file under data/."
  },
  "inputs":  [ {"name": "path", "type": "str", "required": true,  "description": "..."} ],
  "outputs": [ {"name": "path", "type": "str", "required": false, "description": "..."} ],
  "static_connections": [],
  "config_schema": { "type": "object", "properties": { ... } }
}
```

Фронтенд (`frontend/src/nodeSchema.js`) тягне цей маніфест у `NodeSchemaProvider` і:

- `CustomNode.jsx` рендерить `<Handle id="<port>" />` циклом по `inputs` / `outputs`.
- Якщо хоч один вузол на канвасі має непорожні `static_connections`, `FlowCanvas` блокує редагування ліній.

---

## WebSocket: live-логи

Ендпоінт: `ws://localhost:8000/ws/jobs/{job_id}`.

Сервер стрімить кожен `LogEntry` як JSON. Останнє повідомлення — sentinel із `level: "done"`, після якого з'єднання закривається. Якщо підключитися після того, як job уже завершилася, WS зробить **replay** історії з `job.logs` — нічого не пропустиш.

Перевірити з консолі (потрібен [`websocat`](https://github.com/vi/websocat)):
```bash
websocat ws://localhost:8000/ws/jobs/<job_id>
```

Або з браузерного DevTools:
```js
const ws = new WebSocket("ws://localhost:8000/ws/jobs/<job_id>");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

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
    │                  │              │ │               │
    │                  │ topo sort →  │ │               │
    │                  │ for node:    │ │               │
    │                  │   collect    │ │               │
    │                  │   input from │ │               │
    │                  │   parents →  │ │               │
    │                  │   execute →  │ │               │
    │                  │   log        ├─┘               │
    │                  └─────┬────────┘                 │
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
| `app/api/jobs.py` | приймає `POST /jobs/run`, робить **pre-check** на цикл, делегує `JobManager` |
| `app/api/websocket.py` | WS-підписка з replay'ем історії — щоб пізні підписники не пропустили нічого |
| `app/core/scheduler.py` | топологічне сортування Kahn'а, `CycleDetectedError` |
| `app/core/engine.py` | прогін DAG, обробка `condition`-розгалужень через `dead_edges` |
| `app/core/job_manager.py` | реєстр `Job` + супервайзер `asyncio.create_task`, sentinel `done` після фінішу |
| `app/core/log_broker.py` | pub/sub на `asyncio.Queue` per `job_id` |
| `app/core/context.py` | `ExecutionContext` — спільна пам'ять між вузлами + `resolve_template` |
| `app/nodes/base.py` | `BaseNode` ABC + `NODE_REGISTRY` + декоратори `@input_port`, `@output_port`, `@node_info`, `@static_connection`, `@register_node` + `get_schema()` |
| `app/nodes/<name>.py` | реалізація конкретного вузла (один файл — один вузол) |
| `app/schemas/` | Pydantic-моделі: `Workflow`, `Node`, `Edge`, `Job`, `LogEntry`, конфіги вузлів |
| `app/storage/file_storage.py` | сейв/лоад `Workflow` як JSON, валідація імен (`[A-Za-z0-9_-]{1,64}`) |

### Контракт виконання

1. `POST /jobs/run` валідує JSON через Pydantic + робить топ-сорт → 400, якщо є цикл.
2. `JobManager.submit()` створює `Job(PENDING)`, запускає `asyncio.create_task(_run)` і повертає одразу 202.
3. `WorkflowEngine.run()` йде по топологічно відсортованих вузлах:
   - **Жива гілка?** — є хоч один вхідний edge, який не в `dead_edges` і чий батько не в `skipped`.
   - **Маршрутизація даних:**
     - `current_input` — мерджа виходів усіх живих батьків (legacy / шаблони `{input.x}`).
     - `node_inputs[<id>][<port>]` — для ребер із `target_handle`: значення з `node_outputs[<from>][<source_handle>]` копіюється у конкретний вхідний порт. Доступне через `context.get_input(node_id, port_name)`.
     - Якщо `source_handle` ∈ {`"true"`, `"false"`} — це гілка condition'а, тому на target_handle потрапляє весь вихідний словник (а не порт даних).
     - Static-зв'язки з `@static_connection` додаються до набору ребер як readonly.
   - **Виконання** через `NODE_REGISTRY[type](id, config).execute(ctx)`.
   - Для `condition`-вузла: на основі `output["result"]` додаємо у `dead_edges` ребра з протилежним `source_handle`.
4. Кожен крок логується через `ExecutionContext.log → LogBroker.publish` → попадає одночасно і в `job.logs` (підписка `JobManager`'а), і у WS-черги клієнтів.
5. У `finally` `_run` публікує sentinel `LogEntry(level="done")` — WS-клієнти закривають з'єднання.

### Вбудовані типи вузлів

| `type_name` | Що робить | Inputs (порти) | Outputs (порти) |
|---|---|---|---|
| `manual_trigger` | повертає `config.initial_data` | — | `data` |
| `read_file` | `aiofiles` читає файл за `config.path` | `path` | `content`, `size`, `path` |
| `write_file` | пише текст у файл (sandbox: `data/`) | `path`, `content` | `path`, `bytes_written`, `append` |
| `condition` | безпечне булеве вираження через `simpleeval` | `input` | `true`, `false`, `result` |
| `log` | рендерить `config.message`, публікує `LogEntry` | `input`, `message` | `output` (passthrough) |
| `custom_code` | викликає `async main()` зі `scripts/<name>.py` | `input` | `output` |
| `expression` | обчислює довільний sandbox-вираз | `expression`, `input` | `result` |

### Шаблони у конфігах

`resolve_template` замінює:
- `{input.foo}` / `{input.foo.bar}` — з `current_input`
- `{nodes.<id>.foo}` — з `node_outputs`

Невідомий ключ підставляється як `<missing:foo>` (fail-loud, але не падає).

### Безпека

- **`write_file`**: дозволено тільки запис у `data/`. Перевірка `Path.resolve().relative_to(SANDBOX_DIR)` — спроба `../../etc/passwd` кидає `PathTraversalError`.
- **`condition`**: НЕ використовує `eval()`. Вираз переписується (`input.x` → `input["x"]`) і виконується в `simpleeval.EvalWithCompoundTypes`.
- **`workflows/`**: ім'я файлу обмежене regex `[A-Za-z0-9_-]{1,64}`.

---

## Структура проєкту

```
nexusflow/
├── pyproject.toml
├── README.md
├── CLAUDE.md                   # трекер прогресу етапів
├── .gitignore
│
├── app/
│   ├── main.py                 # FastAPI app + lifespan + роутери
│   ├── api/
│   │   ├── workflows.py        # CRUD
│   │   ├── jobs.py             # run / status / list
│   │   └── websocket.py        # WS /ws/jobs/{id}
│   ├── core/
│   │   ├── engine.py           # WorkflowEngine
│   │   ├── scheduler.py        # топсорт + CycleDetectedError
│   │   ├── context.py          # ExecutionContext + resolve_template
│   │   ├── job_manager.py      # реєстр Job + супервайзер
│   │   └── log_broker.py       # pub/sub
│   ├── nodes/
│   │   ├── base.py             # BaseNode + NODE_REGISTRY
│   │   ├── manual_trigger.py
│   │   ├── read_file.py
│   │   ├── write_file.py
│   │   ├── condition.py
│   │   └── log_node.py
│   ├── schemas/
│   │   ├── workflow.py
│   │   ├── node_configs.py
│   │   └── job.py
│   └── storage/
│       └── file_storage.py
│
├── examples/
│   ├── 01_hello_world.json
│   ├── 02_read_write_copy.json
│   └── 03_condition_branching.json
│
├── workflows/                  # збережені користувачем сценарії (gitignored)
├── data/                       # пісочниця для read_file/write_file
│   └── input.txt
│
└── tests/
    ├── conftest.py             # FakeBroker, ctx-фікстура, sys.path
    ├── test_schemas.py         # 20 тестів
    ├── test_nodes.py           # 20 тестів
    ├── test_engine.py          # 9 тестів (включно з прогоном 3 прикладів)
    └── test_api.py             # 16 тестів (REST + WS)
```

---

## Тести

### Backend
```bash
pytest                                                                # усі 65 тестів
pytest --cov=app.core --cov=app.nodes --cov-report=term-missing       # з покриттям
```

Поточний стан: **65 passed**, **96 % coverage** для `app/core/` + `app/nodes/`.

### Frontend
```bash
cd frontend
npm run build         # production build (без помилок типу/збірки)
```

### Live integration (Windows / PowerShell)
```powershell
powershell -File run_integration_test.ps1
# Запускає uvicorn, перевіряє /health, /docs (має бути 404 — авто-доки вимкнені), POST hello_world,
# чекає завершення job та виводить останній лог.
```

---

## Як додати новий тип вузла

Один файл — один вузол. Це власне **єдина зміна**, потрібна для розширення.

### Крок 1: створити Pydantic-конфіг у `app/schemas/node_configs.py`

```python
class HttpRequestConfig(BaseModel):
    url: str = Field(min_length=1)
    method: Literal["GET", "POST"] = "GET"
    timeout_s: float = 5.0


CONFIG_MAP["http_request"] = HttpRequestConfig
```

(Опційно — якщо хочеш, щоб `validate_node_config` упізнавав новий тип одразу.)

### Крок 2: додати тип у Literal у `app/schemas/workflow.py`

```python
NodeType = Literal[
    "manual_trigger", "read_file", "write_file", "condition", "log",
    "http_request",   # <-- додано
]
```

### Крок 3: створити `app/nodes/http_request.py`

```python
import httpx

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import HttpRequestConfig


@node_info(
    display_name="HTTP Request",
    category="net",
    color="#0ea5e9",
    icon="globe",
    description="Issues an HTTP request and returns the body.",
)
@input_port("url", type_hint="str", required=False, description="Override of config.url")
@output_port("status", type_hint="int")
@output_port("body", type_hint="str")
@output_port("url", type_hint="str")
class HttpRequestNode(BaseNode):
    type_name = "http_request"
    config_model = HttpRequestConfig

    async def execute(self, context: ExecutionContext) -> dict:
        url_input = context.get_input(self.id, "url")
        raw = url_input if isinstance(url_input, str) and url_input else self.config.url
        url = context.resolve_template(raw)
        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
            response = await client.request(self.config.method, url)
        return {
            "status": response.status_code,
            "body": response.text,
            "url": url,
        }
```

> Декоратори `@input_port` / `@output_port` / `@node_info` повністю опційні — без них вузол усе ще працює через legacy `current_input`-merge. Але якщо ти їх додаси, вузол одразу отримає коректну схему в `/api/nodes/schema` і динамічні хендли на канвасі.

### Крок 4: (вже зроблено) — auto-discovery

`app/nodes/__init__.py` викликає `discover_nodes(__name__)` під час старту, який сканує всі `.py`-файли в пакеті й реєструє підкласи `BaseNode` із непорожнім `type_name` у `NODE_REGISTRY`. Жодних змін у цьому файлі не потрібно.

Перезапусти сервер — `http_request` доступний у будь-якому JSON-workflow:

```json
{"id": "h1", "type": "http_request", "config": {"url": "https://api.example.com/{input.id}"}}
```

### Крок 5 (опційно): тести

Додай `tests/test_nodes.py::test_http_request_*` за зразком решти.

---

## Обмеження MVP і майбутнє

### MVP свідомо НЕ робить

- **Без БД.** `Job` і `Workflow` живуть в RAM (лише `Workflow` персистяться у файли). Після рестарту сервера задачі губляться.
- **Без черги задач.** Усе через `asyncio.create_task` у тому ж процесі. Не для production-навантаження.
- **Без автентифікації.** API відкритий.
- **Без циклів у графі.** Тільки DAG.
- **Без paralleled-fan-out.** Топ-сорт виконує вузли послідовно, навіть якщо вони незалежні.
- **Тільки ПК-операції.** Без IoT, AI, Telegram, БД-вузлів.

### Roadmap (далі курсової)

| Напрям | Що зробити |
|---|---|
| Персистентність | SQLite/Postgres для `Job`-історії та `Workflow` (замість JSON-файлів) |
| Автентифікація | API-ключі / OAuth |
| Паралельність | виконання незалежних вузлів через `asyncio.gather` |
| Цикли / loop-вузол | окремий `loop`-тип з лімітом ітерацій |
| Нові вузли | `http_request`, `telegram`, `openai`, `cron_trigger`, `webhook_trigger` |
| Фронтенд | React Flow / drag-and-drop редактор графа |
| Розподілене виконання | воркери на Celery/Arq, broker на Redis |

---

## Технологічний стек

| Категорія | Бібліотека | Призначення |
|---|---|---|
| API | FastAPI 0.115+, Uvicorn 0.32+ | REST + WebSocket (авто-документація вимкнена) |
| Валідація | Pydantic 2.10+ | моделі Workflow / Node / Job |
| Async I/O | aiofiles 25+ | неблокуюче читання/запис файлів |
| Eval | simpleeval 1.0+ | безпечне обчислення виразів у `condition` |
| Тести | pytest 8 + pytest-asyncio + pytest-cov + httpx | модульні + інтеграційні + WS |

Python 3.11+ обов'язковий (через `Type | None` синтаксис, `asyncio.Queue` typing).
