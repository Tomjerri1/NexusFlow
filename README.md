# NexusFlow

**Візуальний конструктор workflow-сценаріїв.**
JSON описує граф (вузли + ребра) → рушій будує черги готових вузлів і виконує їх **паралельно у воркер-пулі** → стрімить логи через WebSocket.

Аналог n8n / Node-RED, максимально простий. UI — React Flow редактор з drag-and-drop і live-логами; backend — FastAPI + asyncio. Авто-документація API вимкнена: фронтенд — єдина точка входу.

> **Async Ready Pool.** Двигун — не «for node in topological_sort», а пул із 6 воркер-задач, які наввипередки беруть вузли з `asyncio.Queue` готовності. Дві незалежні гілки з `asyncio.sleep(1)` фінішують ~за 1 секунду, а не за 2. Усі мутації стану — атомарні під `asyncio.Lock`, тож вузли запускаються у чергу рівно один раз. Перша критична помилка виставляє `should_stop=True`: нові вузли не стартують, але вже запущені дограють до кінця (м'яка зупинка, без cancel'ів посеред I/O).

---

## Зміст

- [Швидкий старт](#швидкий-старт)
- [Async Ready Pool — паралельний двигун](#async-ready-pool--паралельний-двигун)
- [Frontend (React Flow редактор)](#frontend-react-flow-редактор)
- [Збереження та завантаження сценаріїв](#збереження-та-завантаження-сценаріїв)
- [Гібридна модель декларативного мапінгу](#гібридна-модель-декларативного-мапінгу)
- [Автоматична конвертація типів між портами](#автоматична-конвертація-типів-між-портами)
- [Перевірка ациклічності на етапі валідації](#перевірка-ациклічності-на-етапі-валідації)
- [Пропуск «мертвих» гілок (dead-branch cascade)](#пропуск-мертвих-гілок-dead-branch-cascade)
- [Trigger Rules (правила активації вузла)](#trigger-rules-правила-активації-вузла)
- [Input Referencing (code-first скорочення)](#input-referencing-code-first-скорочення)
- [Read-only режим (Static Connections)](#readonly-режим-зв-язків)
- [Динамічна панель налаштувань](#динамічна-панель-налаштувань-json-schema-driven)
- [WebSocket: live-логи](#websocket-live-логи)
- [Архітектура](#архітектура)
- [Структура проєкту](#структура-проєкту)
- [Тести](#тести)
- [Як додати новий тип вузла](#як-додати-новий-тип-вузла)

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

## Async Ready Pool — паралельний двигун

Раніше двигун був послідовний: топологічно відсортував — і пройшовся `for node in sorted_nodes`. Це коректно, але **марнує паралельність**: дві незалежні гілки чекали одна одну. У новій версії `WorkflowEngine` — **Async Ready Pool**:

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

### Що це дає

| Сценарій                                | Послідовний двигун | Async Ready Pool |
|-----------------------------------------|--------------------|------------------|
| 2 паралельні I/O-вузли по 1 с           | ~2 с               | **~1 с**         |
| 6 паралельних вузлів × 0.5 с            | ~3 с               | **~0.5 с**       |
| 1 вузол падає, інший паралельний працює | помилка одразу     | падючий зупиняє пул, інший дограє |

Покрито тестами `test_two_parallel_sleeps_finish_in_about_one_second`, `test_six_parallel_sleeps_within_worker_pool_limit`, `test_failure_in_one_branch_lets_running_finish_but_blocks_new`.

### Гарантії потокобезпеки (`app/core/context.py`)

- `ExecutionContext.lock` — `asyncio.Lock` для всіх мутацій спільного стану.
- `should_stop: bool` — м'який прапорець зупинки. Воркер перевіряє його **перед** тим, як забрати наступний вузол із черги; уже запущений вузол виконується до кінця.
- `first_error: BaseException | None` — перша критична помилка, яку рушій передасть `JobManager` після того, як активні воркери дограли (job → `FAILED`).
- `resolve_template(template, input_data)` створює локальні snapshot'и `dict(self.node_outputs)` та `dict(input_data)` перед ітерацією — це уникає `RuntimeError: dictionary changed size during iteration`, коли паралельний воркер пише в `node_outputs` під час підстановки.
- **Глобального `current_input` немає.** Вхідні дані формуються двигуном **локально** для кожного виклику й передаються як параметр у `execute(context, input_data)` — це data isolation на рівні параметра функції, race-condition між паралельними вузлами неможлива в принципі.

### Атомарність переводу нащадків у `ready`

Контракт «нащадок потрапляє у чергу рівно один раз» захищено `state.lock` у `_finalize_node`:

```python
async with state.lock:
    state.finished.add(node.id)             # фінішуємо себе
    state.pending_count -= 1
    # для condition: проштампувати «не обрану» гілку як dead_edge
    # ...
    ready_now = await self._propagate_finish(state, context, node.id)
# put_nowait у чергу — поза lock, бо queue-операція потокобезпечна сама собою.
for child_id in ready_now:
    state.queue.put_nowait(child_id)
```

`_propagate_finish` для кожного нащадка викликає `_evaluate_child`, який повертає `'ready' | 'dead' | 'wait'`:

- `all_success` (AND): один мертвий батько → `dead`. Усі живі та зафінішовані → `ready`. Інакше → `wait`.
- `one_success` (OR): хоча б один живий батько зафінішував → `ready` (у момент ентрі двигун збере `input_data` від усіх батьків, що встигли). Усі батьки зафінішували, серед них немає живих → `dead`.

«Смерть» поширюється каскадно: якщо нащадок переходить у `dead`, його теж додають у `pending_finished` і переоцінюють вже його нащадків.

### `try / finally` навколо `execute()`

```python
try:
    output = await node.execute(context, input_data)
    success = True
except Exception as exc:
    await context.log(node.id, f"Error: {exc}", level="error")
    context.request_stop(exc)        # перша помилка → should_stop=True
finally:
    await self._finalize_node(state, context, node_def, success, output)
```

`finally` гарантує: навіть коли вузол падає, його стан оновлюється і нащадки переоцінюються (стають мертвими). Це і є вимога атомарності з ТЗ.

### Чому пул на 6 воркерів

Дефолт `MAX_WORKERS=6` — компроміс між паралелізмом для I/O-важких графів і захистом від OOM на гігантських воркфлоу. Для тюнінгу під своє навантаження передайте інший ліміт у конструктор: `WorkflowEngine(max_workers=16)`. У продуктивному `JobManager` лишився дефолт.

### Timezone-aware мітки часу

Усі мітки часу (`Job.started_at`, `Job.finished_at`, `LogEntry.timestamp`) формуємо як `datetime.now(timezone.utc)`. У Python 3.12+ `datetime.utcnow()` — deprecated, бо повертав naive-datetime, який нечутний до часового поясу. Нова форма явно `tzinfo=UTC`: однозначна серіалізація у JSON / WebSocket-стрім та коректне порівняння з `datetime`-ами, що приходять зовні.

---

## Frontend (React Flow редактор)

Стек: **Vite 5 + React 18 + Tailwind 3 + `@xyflow/react`**, без TypeScript і без зовнішніх i18n-бібліотек.

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
2. Перетягни `Log`. На вузлі справа з'явиться `source` handle, на новому ліворуч — `target`.
3. **З'єднай** їх, потягнувши від правого handle до лівого.
4. Клікни на `Log` → у правій панелі введи `message`, наприклад `Hello, {input.user}!`.
5. Введи назву сценарію та натисни **`Save`** — він з'явиться в палітрі ліворуч у секції *Saved workflows*. Будь-який запис у тій секції завантажується одним кліком.
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
Жодних додаткових налаштувань — `LangSwitcher` сам підбере новий код.

### Динамічні порти у вузлах

Кожен вузол на канвасі рендерить свої вхідні/вихідні `Handle` **зі схеми**, отриманої з `GET /api/nodes/schema`. Це означає:

- Один і той самий React-компонент `CustomNode` обслуговує всі типи — кількість і назви хендлів беруться з бекенду.
- Якщо ти додаєш новий вузол на бекенді з декораторами `@input_port` / `@output_port`, фронтенд автоматично відображає правильні точки з'єднання — **без змін у JSX**.
- Якщо схема ще не завантажилась — рендериться один target/source як fallback.
- **Порти розкладаються через CSS Flexbox** (двома вертикальними колонками — inputs ліворуч, outputs праворуч), без жодних абсолютних `top: <px>`. Це працює для будь-якої кількості портів: рядки автоматично рівномірно заповнюють висоту вузла, а React Flow коректно бере координати handle'ів із DOM. Раніше використовувалась константа `PORT_ROW_PX` із ручним підрахунком — її прибрано.

### Readonly-режим зв'язків

Редагування ребер та вузлів блокується у двох випадках:

1. **Глобальний прапорець** `is_readonly: true` на самому `Workflow` (поле моделі `app/schemas/workflow.py`). Двигун у `_collect_effective_edges` проштамповує всім ребрам `is_readonly=True`, а UI ставить `nodesDraggable={false}`, `nodesConnectable={false}`, `edgesReconnectable={false}`. Користувач може дивитися граф і конфіги, але не редагувати їх. Вмикається чекбоксом **«Read-only workflow»** в `RunPanel` (значення прокидається у `flowToWorkflow(..., { isReadonly })` і зберігається у JSON).
2. **Декларативні `static_connections`** хоча б на одному з типів вузлів на канвасі (декоратор `@static_connection` у Python). Тоді на ребра діє той самий блок (читай: «архітектор зашив у код, що цей зв'язок порт→порт є частиною контракту вузла, не дай UI його зламати»).

У правому верхньому куті канвасу з'являється бейдж `Edges are read-only / Зв'язки лише для читання`. У `ConfigPanel` усі поля стають `disabled`, а зверху — попередження «Workflow is read-only».

### Динамічна панель налаштувань (JSON-Schema driven)

Права панель `ConfigPanel.jsx` повністю керується JSON-схемою з бекенду — жодних `if (type === "read_file") ...`. Компонент бере `schemas[type].config_schema` з контексту `useNodeSchemas()` й рендерить поля по `properties`, мапуючи declared type на конкретний control:

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

**Лейбл** поля: `t(\`config.<propName>\`, schema.title \|\| propName)` — спочатку i18n-ключ, потім бекендний `title`, потім сире ім'я. **Підказка під полем (hint)**: `schema.description` зі схеми (переклад опційний через `config.<propName>.hint`). Це означає: бекенд-розробник пише змістовний `description=` у Pydantic-полі один раз, і UI одразу показує hint під відповідним інпутом — без правок фронтенду.

Якщо ти додаєш новий вузол із Pydantic-конфігом, **жодного коду у фронтенді змінювати не потрібно** — поля з'являться автоматично, із правильними контролами та підказками. Коли поле логічно є JSON-значенням, але типізоване в Python як `str` (наприклад, серіалізований payload), просто додай `Field(..., description="...JSON payload...")` — фронтенд побачить «JSON» у описі та вимкне валідовану JSON-textarea.

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

## Збереження та завантаження сценаріїв

Сценарії зберігаються як JSON-файли у `workflows/`. UI редактор уміє:

- **Завантажувати** будь-який збережений сценарій одним кліком — у лівій палітрі під списком вузлів є секція **«Saved workflows / Збережені сценарії»** зі списком імен (`GET /workflows`). Клацання по імені тягне `GET /workflows/<name>`, конвертує JSON у React Flow-стан і замінює канвас. Координати не зберігаються в JSON — UI робить простий **layered-layout** на основі топологічних рівнів (`x = layer × 280, y = slot × 130`), тож одразу видно граф.
- **Зберігати** поточний канвас однією кнопкою — у `RunPanel` поруч із «Run workflow» з'явилася кнопка **«Save / Зберегти»**. Вона серіалізує канвас у backend-формат (включно з `source_handle` / `target_handle`), кидає `POST /workflows`, і після успіху палітра автоматично оновлює список (через лічильник `workflowsRefresh` в `App.jsx`).

### REST-контракт

| Метод   | Шлях                  | Призначення                                  |
|---------|-----------------------|----------------------------------------------|
| `GET`   | `/workflows`          | список імен збережених сценаріїв (`string[]`) |
| `GET`   | `/workflows/{name}`   | повний JSON сценарію                          |
| `POST`  | `/workflows`          | зберегти сценарій (тіло — `Workflow` JSON)    |
| `DELETE`| `/workflows/{name}`   | видалити сценарій                             |

Ім'я обмежене регулярним виразом `[A-Za-z0-9_-]{1,64}` — крапки, слеші та пробіли заборонені (фронтенд показує текст помилки з бекенду під полем введення).

### Приклад: сценарій із коду → відображення в UI

Файл `create_math_workflow.py` у корені створює `Code_First_Math` через Python API і зберігає у `workflows/`. Запусти його, перезавантаж editor — `Code_First_Math` з'явиться у секції **Saved workflows**:

```bash
python create_math_workflow.py
# Сценарій успішно створено за шляхом: .../workflows/MyVisualFlow.json
```

Після цього:

1. Відкрий `http://localhost:5173`.
2. У палітрі ліворуч → клац на `Code_First_Math` → граф з'являється на канвасі.
3. Зміни щось → введи нову назву (наприклад `MyVisualFlow`) → натисни **Save** → у списку зліва з'являється новий запис.

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

    async def execute(self, context, input_data: dict):
        # Локальний `input_data` — двигун передає його сам; глобального
        # current_input більше немає (data isolation для паралельного пулу).
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

- Якщо `target_handle` не вказано — працює **legacy merge**: усі виходи живих батьків зливаються у локальний `input_data`, що передається у `execute(context, input_data)`. Шаблони `{input.foo}` читаються саме з нього.
- `source_handle = "true" | "false"` досі означає гілку condition'а (а не порт даних) — двигун розпізнає це за іменем.
- Маршрутизатор обгорнено у `try/except`: помилка мапінгу логується як `warning`, але не валить весь job — вузол отримає порожній вхід.

## Перевірка ациклічності на етапі валідації

`Workflow` — це DAG (directed acyclic graph). Перевірка проводиться **прямо у Pydantic-валідаторі** `_check_graph_integrity`, тож кожен сконструйований `Workflow`-обʼєкт гарантовано без циклів. Тобто якщо ваш код успішно зробив `Workflow.model_validate(...)` / `Workflow(...)` — далі по pipeline ніхто не побачить графа з циклом, і не доведеться писати «а раптом хтось десь...» захисти.

### Як це працює

У валідатор зашито:

```python
from app.core.scheduler import CycleDetectedError, topological_sort

try:
    topological_sort(self.nodes, self.edges)
except CycleDetectedError as exc:
    raise ValueError(
        f"Workflow graph is not a DAG — cycle detected involving "
        f"nodes: {exc.cycle_node_ids}"
    ) from exc
```

Імпорт **лінивий** (всередині методу), бо `app.core.scheduler` сам тягне `Edge`/`Node` із цього ж модуля — top-level import дав би циркулярну залежність. Лінива форма безпечна: метод викликається лише під час `model_validate(...)`, на той момент модулі вже завантажені.

### Що бачить користувач

| Шлях входу                         | Поведінка                                                                  |
|------------------------------------|----------------------------------------------------------------------------|
| `Workflow.model_validate({...})`   | `pydantic.ValidationError` з повідомленням `… cycle detected involving nodes: ['a', 'b']` |
| `Workflow(name=..., nodes=..., edges=...)` (Python API) | те саме `ValidationError`                          |
| `POST /jobs/run` із циклом         | FastAPI повертає **HTTP 422** (Pydantic body-validation) з тим самим текстом |
| `load_workflow("name_with_cycle")` | `ValidationError` із `model_validate_json` — завантажити збережений сценарій з циклом неможливо |

### Покрите тестами

- `tests/test_schemas.py::test_workflow_rejects_cyclic_graph` — `A→B`, `B→A` → ValidationError зі словом `cycle` та переліком `['a', 'b']` у тексті.
- `tests/test_schemas.py::test_workflow_rejects_self_loop` — навіть `A→A` (self-loop) ловиться.
- `tests/test_api.py::test_cycle_rejected_at_request_validation` — кінець-в-кінець через REST: 422 + потрібний текст.
- `tests/test_engine.py::test_topological_sort_detects_cycle` — низькорівнева перевірка `topological_sort` із прямим створенням `Node`/`Edge` (без `Workflow`-валідації).

> **Чому 422, а не 400.** Pydantic-валідація тіла запиту триггерить стандартний FastAPI-`RequestValidationError`, який мапиться у `HTTP 422 Unprocessable Entity` — це коректніший статус для невалідного вхідного payload'у, ніж 400 (загальна «bad request»). Тіло відповіді ідентифікує цикл за словом `cycle` та списком вузлів.

---

## Пропуск «мертвих» гілок (dead-branch cascade)

Коли `condition`-вузол обирає одну гілку (`true` або `false`), уся **інша** гілка має бути повністю проігнорована — `execute()` для нащадків не викликається. У `WorkflowEngine` це реалізовано через дві множини, які наповнюються в міру топологічного обходу графа:

| Множина        | Що тримає                                          |
|----------------|----------------------------------------------------|
| `dead_edges`   | ключі ребер `(from, to, source_handle)`, що не несуть даних |
| `dead_nodes`   | id вузлів, які повністю пропускаються              |

### Правила «смерті»

Вузол потрапляє у `dead_nodes`, якщо:

1. Він стоїть на `true`/`false`-гілці condition'а, яку **не** обрано (умова напряму марнує вхідне ребро у `dead_edges` через `_mark_dead_edges`).
2. **Усі** його вхідні ребра — мертві (`_is_alive` повертає `False`).

Як тільки вузол додається у `dead_nodes`, метод `_mark_node_dead` одразу проштамповує **всі його вихідні ребра** у `dead_edges`. Це і є каскад: завдяки топологічному порядку наступні нащадки автоматично розпізнаються як мертві у `_is_alive`, навіть якщо мають кілька вхідних ребер — головне, щоб **усі** вони прийшли з мертвих джерел.

### Що відбувається у логах

Кожен пропущений вузол публікує `LogEntry(level="info", message="Skipped due to dead branch")`. У live-консолі це рядок із id вузла та зрозумілим текстом — користувач одразу бачить, чому певний крок не виконався, замість мовчазного «нічого не сталося».

### Приклад

```
T1 → C (condition: input.flag)
       ├─true → A → B → D
       └─false → X → Y
```

Якщо `input.flag = True`:

- ✅ `A`, `B`, `D` виконуються по true-гілці.
- ❌ false-edge `C→X` стає мертвим (`_mark_dead_edges`).
- ❌ `X` має лише одне вхідне ребро — мертве → `X` у `dead_nodes`. Його outbound `X→Y` теж мертвий.
- ❌ `Y` — усі inbound мертві (єдиний — це `X→Y`) → `Y` теж у `dead_nodes`.
- У логах: `Skipped due to dead branch` для `X` та `Y`.

Це покривається тестами `tests/test_engine.py::test_dead_branch_cascades_through_chain` та `test_dead_branch_kills_node_with_other_inputs_only_from_dead_branch`.

> Зворотний бік цього контракту: **якщо вузол має хоч одне живе вхідне ребро ззовні мертвої гілки** — він залишається живим. Тобто node, що зливає дані з true-гілки condition'а та з незалежного джерела (`T2 → D`), все одно виконається на true-вибірці. «Мертвість» поширюється лише через ребра, не через сусідство.

---

## Trigger Rules (правила активації вузла)

Кожен вузол має системне поле `trigger_rule` (Pydantic-модель `Node`), яке диктує двигуну, **коли** саме викликати `execute()` для цього вузла, виходячи зі стану його вхідних ребер. Це базова властивість, доступна для **будь-якого** типу вузла — не частина `config`.

| Значення        | Семантика                                   | Коли використовувати                                          |
|-----------------|---------------------------------------------|---------------------------------------------------------------|
| `all_success` (default) | **AND** — fire лише якщо ВСІ вхідні ребра живі | Класичний DAG-pipeline: всі попередники мають відпрацювати    |
| `one_success`   | **OR** — fire якщо хоча б ОДНЕ вхідне ребро живе | Merge-вузол після condition'а; fail-over; «будь-який тригер» |

Стартові вузли (без вхідних ребер) активуються **завжди**, незалежно від `trigger_rule`.

### Чому дефолт — `all_success`

Це консервативна семантика: вона ловить помилки в дизайні графа, де користувач не очікував, що частина гілки померла. Якщо ви свідомо хочете merge-поведінку — треба явно перемкнути вузол на `one_success` (один клік у UI або одне поле у JSON). Це більш «fail loud», ніж старий дефолт.

### JSON-приклад

```json
{
  "id": "merge",
  "type": "log",
  "config": {"message": "Branch finished"},
  "trigger_rule": "one_success"
}
```

Якщо `trigger_rule` не вказано — Pydantic підставить `"all_success"`. Поле серіалізується у JSON лише коли воно НЕ дефолтне (мінімізує файли збережених воркфлоу).

### UI

У `ConfigPanel` зверху, прямо під системним рядком `id` / `type`, з'являється `<select>` з варіантами **«All Inputs (AND)»** та **«Any Input (OR)»** + локалізована підказка. Вибір одразу записується у `node.data.trigger_rule` і потрапляє у backend-формат через `flowToWorkflow`.

### Code-First (Python API)

Для скриптів генерації (на кшталт `create_complex_workflow.py`) трігер-правило передається як звичайний kwarg у Pydantic-модель `Node`:

```python
from app.schemas.workflow import Edge, Node, Workflow

wf = Workflow(
    name="condition_with_merge",
    nodes=[
        Node(id="t1", type="manual_trigger", config={"initial_data": {"v": 200}}),
        Node(id="c1", type="condition", config={"expression": "input.v > 100"}),
        Node(id="lt", type="log", config={"message": "big"}),
        Node(id="lf", type="log", config={"message": "small"}),
        # ↓↓↓ merge має fire'итися, як тільки одна з гілок жива
        Node(id="merge", type="log",
             config={"message": "Branch finished"},
             trigger_rule="one_success"),
    ],
    edges=[
        Edge(from_node="t1", to_node="c1"),
        Edge(from_node="c1", to_node="lt", source_handle="true"),
        Edge(from_node="c1", to_node="lf", source_handle="false"),
        Edge(from_node="lt", to_node="merge"),
        Edge(from_node="lf", to_node="merge"),
    ],
)
```

Без `trigger_rule="one_success"` цей merge помер би разом із dead-branch (бо одне з його вхідних ребер мертве при дефолтному `all_success`).

### Як це інтегрується з dead-branch cascade

`_is_alive` спершу перевіряє inbound-ребра (живе/мертве через `dead_edges`/`dead_nodes`), а потім застосовує `trigger_rule`:

- `all_success` → `all(_edge_alive(e) for e in inbound)`
- `one_success` → `any(_edge_alive(e) for e in inbound)`

Якщо вузол мертвий — він додається в `dead_nodes`, його outbound-ребра штампуються в `dead_edges` (каскад). Тобто `trigger_rule` визначає **поріг** активації, а каскад поширення «смерті» вглиб графа працює однаково для обох правил.

Покривається тестами `tests/test_engine.py::test_trigger_rule_*` (3 тести: AND блокує merge при частково мертвих входах; OR пропускає merge коли хоч одне ребро живе; OR теж пропускає merge коли ВСІ входи мертві).

---

## Input Referencing (code-first скорочення)

Коли ти будуєш воркфлоу **в Python-коді** (через `Node(...)` / `Workflow(...)`), масив `edges=[Edge(...)]` швидко стає шумним. Замість цього кожен вузол може оголосити свої вхідні зв'язки прямо у параметрі `inputs`. Workflow-валідатор розгорне їх у канонічний `edges`-масив автоматично — той самий, який бачить фронтенд.

### Формат

```python
Node(
    id="...",
    type="...",
    config={...},
    inputs={
        # 1) Просто id вузла-джерела → source_handle="output" (default).
        #    Це стандарт для більшості вузлів NexusFlow (custom_code, log, …).
        "input": "processor_1",

        # 2) Кортеж (source_node_id, source_handle) — явне порт-у-порт.
        #    Використовуй, коли source-порт не "output" (наприклад,
        #    manual_trigger.data, read_file.content):
        "content": ("reader_1", "content"),

        # 3) Список джерел → ФАН-ІН: декілька ребер у той самий target-порт.
        #    Кожен елемент — або str, або (str, str). Корисно для merge-вузлів
        #    та condition'ів, що зливають кілька значень у один input:
        "input": [
            ("trigger_1", "data"),       # threshold з тригера
            ("processor_1", "output"),   # count із кастом-коду
        ],

        # 4) Керуючі (control-flow) ключі для гілок condition'а —
        #    створюють ребро з source_handle="true"/"false" БЕЗ target_handle:
        "@on_true":  "condition_1",
        "@on_false": "condition_1",
    },
)
```

| Ключ                          | Значення                                  | Що згенерується (Edge)                                                  |
|-------------------------------|-------------------------------------------|-------------------------------------------------------------------------|
| `"target": "src_id"`          | bare string                               | `Edge(src_id.output → self.target)` — default source_handle = `"output"` |
| `"target": ("src", "port")`   | tuple                                     | `Edge(src.port → self.target)`                                          |
| `"target": [v1, v2, …]`       | list of strings/tuples (fan-in)           | окремий Edge для кожного елемента списку, всі з тим самим target-портом |
| `"@on_true": "cond_id"`       | bare string                               | `Edge(cond_id.true → self)` (без target_handle)                         |
| `"@on_false": "cond_id"`      | bare string                               | `Edge(cond_id.false → self)`                                            |

> **Важливо.** Дефолтний `source_handle = "output"` — це угода для зручності. Якщо твій вузол-джерело має output під іншою назвою (`manual_trigger.data`, `read_file.content`, `write_file.path`/`bytes_written` тощо) — обов'язково використовуй tuple-форму, інакше двигун шукатиме неіснуючий ключ `"output"` у вихідному словнику й передасть `None`.

### Що відбувається при валідації

`Workflow.model_validate(...)` запускає `_resolve_inputs_to_edges` (`mode="after"`), який:

1. Збирає унікальні ключі вже наявних `edges` як `(from, to, source_handle, target_handle)`.
2. Проходить по всіх вузлах. Для кожного запису в `inputs`:
   - якщо ключ — `@on_true`/`@on_false`, створює control-edge від condition'а;
   - інакше нормалізує значення в **список** атомів (одиничне значення → `[value]`, список → as-is) і для кожного атома створює окремий `Edge` із target_handle = ключ. Атом-string → `source_handle="output"`; атом-tuple → явний source_handle.
3. **Дедуплікує** проти existing-набору (можеш безпечно поєднувати `inputs` із ручними `edges` — дублікатів не буде).
4. Запускається ПЕРЕД `_check_graph_integrity`, тож згенеровані ребра теж проходять перевірку: невідомий source_node → `ValidationError` із текстом `"Edge references unknown source node: ..."`.

### Поле `edges` тепер опціональне

Коли всі звʼязки оголошені через `inputs`, `edges=[]` можна взагалі не передавати:

```python
Workflow(name="...", nodes=[...])  # edges генеруються з inputs
```

### `inputs` НЕ потрапляє у JSON

Поле `inputs` маркіроване як `Field(default=None, exclude=True)` — це **code-only shortcut**. У збереженому `workflows/<name>.json` живе виключно канонічний `edges`-масив (саме його читає фронтенд через `workflowToFlow`). Це означає: round-trip `Python → save_workflow → load_workflow` дає `Workflow` з повним `edges`, але без `inputs` на вузлах. Ніяких розбіжностей між «джерелом коду» і «тим що бачить UI».


### Автоматична конвертація типів між портами (Pydantic-driven)

Коли значення приходить через port-mapping, рушій (`_route_inputs`) дивиться на `type_hint` цільового вхідного порту (з `@input_port(type_hint="...")`) і **просто пропускає значення через Pydantic-валідатор**. Замість ручних таблиць типів і самописної конвертації — мінімалістичний `TYPE_MAPPING` + один `TypeAdapter`:

```python
TYPE_MAPPING = {
    "int": int, "integer": int,
    "float": float, "number": float,
    "str": str, "string": str,
    "bool": bool, "boolean": bool,
    "dict": dict, "object": dict,
    "list": list, "array": list,
    "any": Any, "": Any,
}

_LAX_CONFIG = ConfigDict(coerce_numbers_to_str=True)

def _try_convert(value, expected: str):
    target = TYPE_MAPPING.get(expected.lower())
    if target is None or target is Any:
        return value
    try:
        return TypeAdapter(target, config=_LAX_CONFIG).validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"cannot convert ... : {exc.errors()[0]['msg']}") from exc
```

Що це означає на практиці — Pydantic у lax-режимі автоматично робить:

- `"42" → 42`, `"3.14" → 3.14`, `"true"/"false" → bool`,
- `int/float → str` (через `coerce_numbers_to_str=True`),
- `tuple → list`, валідні `dict`-літерали,
- усе несумісне (наприклад, `dict` у `path: str`) — `ValidationError`, який ми перевертаємо в `TypeError`.

Якщо конвертація провалилася — у `context.log` з'являється `warning`:
```
Type mismatch on port 'path': expected str, got dict (auto-convert failed: …) — passing original value
```
**Виконання НЕ зупиняється** — оригінальне значення проходить як є. Це частина філософії «fail loud, але не валити job через дрібний type-mismatch». Якщо тип `any` (за замовчуванням) — перевірок взагалі немає.

> Раніше тут жили константи `_NUMERIC_TYPES`/`_STR_TYPES`/… і функції `_python_kind` + `_matches` + ручний 60-рядковий `_try_convert`. Тепер це 15 рядків + бібліотека, яку ми й так використовуємо. Менше коду — менше місця для багів.

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
| `app/api/jobs.py` | приймає `POST /jobs/run`, делегує `JobManager` (перевірка ациклічності тепер у `Workflow`-валідаторі — request-body відсіюється FastAPI до handler'а) |
| `app/api/websocket.py` | WS-підписка з replay'ем історії — щоб пізні підписники не пропустили нічого |
| `app/core/scheduler.py` | топологічне сортування Kahn'а, `CycleDetectedError` (тепер використовується лише як ациклічна перевірка перед стартом пулу) |
| `app/core/engine.py` | **Async Ready Pool** — 6 паралельних воркерів, `asyncio.Queue` готових вузлів, атомарне поширення «фініш-сигналу» під `state.lock`, м'яка зупинка через `context.should_stop`, dead-edges каскад |
| `app/core/job_manager.py` | реєстр `Job` + супервайзер `asyncio.create_task`, sentinel `done` після фінішу |
| `app/core/log_broker.py` | pub/sub на `asyncio.Queue` per `job_id` |
| `app/core/context.py` | `ExecutionContext` — потокобезпечна спільна пам'ять (`asyncio.Lock`, `should_stop`, `first_error`) + `resolve_template(template, input_data)` зі snapshot'ами |
| `app/nodes/base.py` | `BaseNode` ABC + `NODE_REGISTRY` + декоратори `@input_port`, `@output_port`, `@node_info`, `@static_connection`, `@register_node` + `get_schema()` |
| `app/nodes/<name>.py` | реалізація конкретного вузла (один файл — один вузол) |
| `app/schemas/` | Pydantic-моделі: `Workflow`, `Node`, `Edge`, `Job`, `LogEntry`, конфіги вузлів |
| `app/storage/file_storage.py` | сейв/лоад `Workflow` як JSON, валідація імен (`[A-Za-z0-9_-]{1,64}`) |

### Контракт виконання

1. `POST /jobs/run` валідує JSON через Pydantic + робить топ-сорт → 422, якщо є цикл.
2. `JobManager.submit()` створює `Job(PENDING)`, запускає `asyncio.create_task(_run)` і повертає одразу 202.
3. `WorkflowEngine.run()` стартує **Async Ready Pool**:
   - **Pre-flight:** перевіряє типи всіх вузлів у `NODE_REGISTRY` + один прохід `topological_sort` як ациклічна перевірка (порядок виконання тепер диктує черга готовності, а не список).
   - **Initial enqueue:** усі вузли без вхідних ребер кладуться у `ready_queue` під `state.lock`.
   - **6 воркер-задач** (`max_workers=6` за замовчуванням) у циклі: перевіряють `context.should_stop` → беруть `node_id` із черги → формують локальний `input_data` (snapshot під lock'ом, без жодних мутацій спільного `current_input`) → викликають `execute(context, input_data)`.
   - **`try / finally`:** результат записується у `node_outputs[id]` та поширюється на нащадків ATOMICALLY під `state.lock`:
     - successful: condition-вузол додає не-обрану гілку у `dead_edges`.
     - failed: вузол → `dead_nodes`, усі outbound-ребра → `dead_edges`, виставляється `should_stop=True` + запам'ятовується перша помилка.
     - для кожного нащадка `_evaluate_child` повертає `ready` / `dead` / `wait` за `trigger_rule` (AND/OR); готові кладуться у чергу, мертві — каскадно поширюють «смерть».
   - **Маршрутизація даних:**
     - `input_data` — локальний для виклику dict: merge виходів живих батьків + накладений зверху port-mapping (для шаблонів `{input.x}`).
     - `node_inputs[<id>][<port>]` — для ребер із `target_handle`: значення з `node_outputs[<from>][<source_handle>]` копіюється у конкретний вхідний порт. Доступне через `context.get_input(node_id, port_name)`.
     - Якщо `source_handle` ∈ {`"true"`, `"false"`} — це гілка condition'а, тому на target_handle потрапляє весь вихідний словник (а не порт даних).
     - Static-зв'язки з `@static_connection` додаються до набору ребер як readonly.
   - **Termination:** як тільки `pending_count == 0` (усі вузли або зафінішували, або позначені мертвими) — `done_event` сигналить main-таск, який кладе `None`-sentinel'и для всіх воркерів і чекає `gather`. Якщо першу помилку було збережено — `run()` re-raise'ить її назовні (job → FAILED).
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

`resolve_template(template, input_data)` замінює:
- `{input.foo}` / `{input.foo.bar}` — з локального `input_data`, переданого вузлу двигуном
- `{nodes.<id>.foo}` — зі **snapshot'у** `node_outputs` (`dict(self.node_outputs)`, щоб уникнути race з паралельними воркерами)

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
    ├── test_schemas.py         # схеми + DAG-валідація
    ├── test_nodes.py           # юніт-тести 7 вузлів (тепер усі через execute(ctx, input_data))
    ├── test_engine.py          # 3 приклади + dead-branch cascade + trigger_rule + Async Ready Pool (паралельність та failure isolation)
    └── test_api.py             # REST + WS + /api/nodes/schema
```

---

## Тести

### Backend
```bash
pytest                                                                # усі тести
pytest --cov=app.core --cov=app.nodes --cov-report=term-missing       # з покриттям
```

Поточний стан: **117 passed** — попередні 112 тестів MVP + **5 нових Async Ready Pool тестів** (паралельне виконання двох гілок зі sleep'ами за ~1 c, 6-вузловий пул за ~0.5 c, м'яка зупинка одного брата при падінні іншого, блокування невзятого вузла після `should_stop`, snapshot-безпечні шаблони під паралельним записом).

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

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        url_input = context.get_input(self.id, "url")
        raw = url_input if isinstance(url_input, str) and url_input else self.config.url
        url = context.resolve_template(raw, input_data)
        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
            response = await client.request(self.config.method, url)
        return {
            "status": response.status_code,
            "body": response.text,
            "url": url,
        }
```

> Декоратори `@input_port` / `@output_port` / `@node_info` повністю опційні — без них вузол усе ще працює через legacy merge у `input_data`. Але якщо ти їх додаси, вузол одразу отримає коректну схему в `/api/nodes/schema` і динамічні хендли на канвасі.

> **Важливо.** Підпис `execute()` тепер `(self, context, input_data)`. `input_data` — це готовий для цього виклику dict, який двигун зібрав з виходів живих батьків + port-mapping. Шаблони `{input.foo}` читаються саме з нього (`context.resolve_template(template, input_data)`). Глобального `current_input` більше немає — це гарантія data isolation у паралельному пулі.

### Крок 4: (вже зроблено) — auto-discovery

`app/nodes/__init__.py` викликає `discover_nodes(__name__)` під час старту, який сканує всі `.py`-файли в пакеті й реєструє підкласи `BaseNode` із непорожнім `type_name` у `NODE_REGISTRY`. Жодних змін у цьому файлі не потрібно.

Перезапусти сервер — `http_request` доступний у будь-якому JSON-workflow:

```json
{"id": "h1", "type": "http_request", "config": {"url": "https://api.example.com/{input.id}"}}
```

### Крок 5 (опційно): тести

Додай `tests/test_nodes.py::test_http_request_*` за зразком решти.

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
