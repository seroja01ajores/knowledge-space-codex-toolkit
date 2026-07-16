# Knowledge Space Codex Toolkit

[Русский](#русская-версия) · [English](#english-version)

## Русская версия

Переносимый, не привязанный к конкретному стенду плагин Codex для работы с
проектами Knowledge Space (KS) через официальный API и для анализа архитектуры
проекта в редактируемой диаграмме.

Плагин объединяет два связанных направления:

- **Инженерия проектов KS** — первичное исследование, аудит без изменений,
  восстановление учебных и тестовых проектов, работа с моделями, классами,
  показателями, формулами, объектами, таблицами данных, дашбордами,
  публикациями, диаграммами Ганта, интеграциями и BPMS, а также безопасные
  изменения с последующей проверкой через API и интерфейс.
- **Цикл KS ↔ Diagramm** — ограниченное и проверяемое чтение резервной копии,
  преобразование структуры в Diagramm JSON 1.2, отображение атрибутов,
  показателей, формул и количества объектов, подготовка контролируемого плана
  изменений, сборка клонированной структурной копии и предварительная проверка
  восстановления в изолированный проект.

Публичная версия не содержит адреса рабочего стенда KS, UUID реальных
проектов, клиентских данных, логинов, паролей, токенов, cookie, SSH-ключей или
реальных резервных копий.

### Что даёт плагин

| Задача | Что делает плагин |
| --- | --- |
| Разобраться в незнакомом проекте KS | Создаёт снимок через API в режиме чтения и проверяет структуру и доступные артефакты интерфейса |
| Восстановить учебный или эталонный проект | Ведёт работу в отдельном тестовом проекте и требует явной проверки результата |
| Исправить модели, классы, дашборды или публикации | Сначала строит dry-run план, точно связывает его с проектом, выполняет узкое изменение и машинное чтение результата |
| Работать с интеграциями и BPMS | Использует отдельный контур точного подтверждения; функциональность не запрещена полностью, но не запускается случайно |
| Посмотреть большой проект как схему | Формирует Diagramm JSON с классами, связями, полями KS, атрибутами, показателями, формулами и количеством объектов по классам |
| Вернуть изменения диаграммы в KS | Сравнивает структуру с исходником по хешам и собирает отдельную клонированную копию без перезаписи оригинала |
| Освоить недокументированное действие интерфейса | Поддерживает цикл: обезличенная фиксация → сравнение → нормализация → тест → добавление подтверждённого шаблона |

### Работа с проектами KS

Навык `ks-codex` предназначен для проектно-ограниченных операций через API:

- проверка окружения, доступности стенда и выбранного UUID проекта;
- безопасная инвентаризация моделей, классов, показателей, формул и объектов;
- анализ данных, таблиц, дашбордов, публикаций и диаграмм Ганта;
- восстановление и проверка учебных или тестовых проектов;
- подготовка изменений с dry-run, классификацией риска и точным read-back;
- отдельные подтверждаемые сценарии для интеграций, BPMS, пересчётов и других
  runtime-действий;
- браузерная проверка результата, когда одного ответа API недостаточно.

Рекомендуемый первый этап всегда работает только на чтение. Изменения не
следуют автоматически из результатов аудита.

### Работа с диаграммами и резервными копиями

Навык `ks-diagram-roundtrip` выполняет офлайн-часть цикла:

1. Проверяет копию резервной копии KS и отделяет структурные записи от лишних
   или чувствительных данных.
2. Строит привязанную к источнику модель чтения и Diagramm JSON версии 1.2.
3. Показывает классы и связи, сопоставленные атрибуты KS, показатели,
   происхождение формул и количество объектов в каждом классе.
4. Проверяет отредактированную диаграмму относительно исходной структуры.
5. Формирует план поддерживаемых, отложенных и запрещённых изменений.
6. Собирает отдельную клонированную структурную резервную копию и читает её
   обратно для проверки целостности.
7. Останавливается перед живым восстановлением, пока не задан новый тестовый
   проект и не подтверждён отдельный целевой план.

### Безопасность

Защитный слой является частью исполнения, а не только рекомендацией:

1. Адрес стенда и UUID проекта задаются в проверяемом плане и должны точно
   совпасть с окружением во время выполнения.
2. API-адреса приводятся к каноническому виду и классифицируются по пути и по
   фактическому бизнес-эффекту.
3. Чтение, проектные изменения, runtime-действия, разрушительные операции и
   серверные работы разделены разными уровнями допуска.
4. Проектное изменение требует чтения до операции, единственного источника
   payload и непустых машинно-проверяемых условий чтения после операции. UUID
   сущности в плане, payload и read-back должны совпадать.
5. Секреты для runtime-payload разрешены только через специально созданные
   переменные `KS_RUNTIME_PAYLOAD_*` и только для полей подключения или учётных
   данных. Через них нельзя заменить целевой проект, действие или авторизацию
   самого KS-клиента.
6. Из отчётов удаляются Bearer/Basic-заголовки, URI со встроенными учётными
   данными, JWT-подобные строки, закрытые ключи и известные значения секретов.
7. Пути входных и выходных файлов проверяются до обращения к API: обход
   каталогов, абсолютные пути и симлинки блокируются.
8. Преобразование резервной копии выполняется офлайн. Живое восстановление
   остаётся отдельной операцией с точным подтверждением и новым тестовым
   проектом.
9. Весь пакет входных файлов и выходных путей проверяется до авторизации и
   первого API-эффекта. Неопределённый сетевой результат помечается как
   `effect_unknown`, не повторяется автоматически и требует контрольного
   чтения.

Подробная модель угроз и границы подтверждений описаны в
[SECURITY.md](SECURITY.md).

### Текущая граница обратной записи

Режим чтения намеренно богаче режима записи. В диаграмме можно отображать
структуру классов, смысловые связи, сопоставленные поля и атрибуты KS,
показатели, происхождение формул и количество объектов.

Текущий профиль `structural-v0.1` умеет добавлять новые классы и новые
смысловые связи в клонированную резервную копию. Изменение и удаление
существующих сущностей, запись атрибутов, показателей и формул, изменение
объектов и живое восстановление не выводятся из диаграммы автоматически. Для
них требуется отдельный контракт сопоставления и подтверждения.

### Требования

- Codex с поддержкой плагинов;
- Python 3.10 или новее;
- `requests` для API-сценариев KS;
- `zstd` для упакованных резервных копий KS;
- Node.js только для необязательной фиксации браузерных API-вызовов.

```bash
python3 -m pip install -r plugins/knowledge-space-codex/requirements.txt
python3 plugins/knowledge-space-codex/skills/ks-codex/scripts/ks_environment_preflight.py
```

### Установка

Репозиторий открыт на GitHub, но плагин пока не входит в общий каталог
плагинов OpenAI. Другие пользователи устанавливают его из этого GitHub-
marketplace:

```bash
codex plugin marketplace add seroja01ajores/knowledge-space-codex-toolkit --ref main
codex plugin add knowledge-space-codex@ks-agent-local
```

После обновления нужно обновить marketplace, переустановить плагин и открыть
новую задачу Codex, чтобы новые версии навыков были загружены:

```bash
codex plugin marketplace upgrade ks-agent-local
codex plugin add knowledge-space-codex@ks-agent-local
```

### Подключение к проекту KS

Целевой стенд и проект передаются только во время запуска. Можно использовать
логин и пароль либо токен:

```text
KS_BASE_URL=https://<host>/api
KS_PROJECT_UUID=<project uuid>
KS_LOGIN=<login>
KS_PASSWORD=<password>
# или: KS_TOKEN=<token>
```

Значения следует хранить в переменных окружения, Keychain или другом
разрешённом хранилище секретов. Их, пароли внешних систем, исходные резервные
копии, снимки и браузерные captures нельзя коммитить в репозиторий.

Рекомендуемый первый запрос:

```text
Используй $ks-codex. Выполни проверку окружения, проверь выбранный стенд и UUID
проекта, затем проведи аудит проекта только на чтение. Ничего не изменяй.
```

Для работы с резервной копией и диаграммой:

```text
Используй $ks-diagram-roundtrip. Работай только с копией этого бекапа, создай
ограниченную модель чтения и Diagramm JSON, проверь все артефакты и остановись
до живого восстановления.
```

### Публичное ядро и приватное дополнение

Публичный плагин применим к разным установкам KS. Профили конкретной
организации, адреса стендов, учётные данные, реальные доказательства, клиентские
резервные копии и изученные локальные шаблоны должны храниться отдельно в
приватном дополнении. Оно может ссылаться на зафиксированный коммит публичного
ядра, но никогда не включается в публичную сборку.

Так сохраняется механизм самообучения и повторного использования подтверждённых
шаблонов без публикации приватных данных. Подробнее:
[docs/private-overlay.md](docs/private-overlay.md) и
[docs/self-learning.md](docs/self-learning.md).

### Структура репозитория

- `plugins/knowledge-space-codex/` — устанавливаемый плагин;
- `plugins/knowledge-space-codex/skills/ks-codex/` — навык работы с API,
  курсами и проектами KS;
- `plugins/knowledge-space-codex/skills/ks-diagram-roundtrip/` — навык офлайн-
  преобразования диаграммы и клонированной резервной копии;
- `tools/build_portable_plugin.py` — воспроизводимый сборщик обезличенного
  релиза;
- `docs/` — описание архитектуры, приватного дополнения и самообучения.

### Проверка и выпуск релиза

```bash
python3 tools/run_plugin_tests.py
python3 tools/test_build_portable_plugin.py
python3 tools/build_portable_plugin.py --output-dir dist
```

Сборщик включает только канонический плагин, блокирует чувствительные и
привязанные к конкретному стенду материалы и создаёт воспроизводимый ZIP,
контрольную сумму SHA-256 и JSON-отчёт сборки.

### Статус

Плагин ориентирован на рабочее применение, но по умолчанию останавливается при
неопределённости. Успешная офлайн-проверка сама по себе не разрешает изменения
в KS, запуск интеграций, восстановление резервной копии или серверные работы.
Для этого нужны соответствующий проверенный план, точная привязка к цели и
нужный уровень подтверждения.

---

## English version

A portable, stand-agnostic Codex plugin for working with Knowledge Space (KS)
projects through the official API and for reviewing project architecture in an
editable diagram.

The toolkit combines two complementary workflows:

- **KS project engineering** — discovery, read-only audits, course and scratch
  project reconstruction, models, classes, indicators, formulas, objects,
  tables, dashboards, publications, Gantt, integrations, BPMS, safe writes and
  browser-assisted verification.
- **KS ↔ Diagramm round-trip** — bounded backup inspection, Diagramm schema
  1.2, all mapped indicators and attributes, per-class object counts,
  formula/indicator aggregates, source-bound change plans, cloned structural
  backup generation and isolated restore preflight.

The repository contains no fixed KS host, project UUID, customer data,
credential, token, cookie or real project backup.

### Why it is useful

| Task | Toolkit support |
| --- | --- |
| Understand an unfamiliar KS project | Read-only API snapshot plus structural and UI artifact audits |
| Recreate a training or reference project | Isolated scratch-project workflow with explicit verification |
| Repair classes, models, dashboards or publications | Dry-run plan, exact project binding, narrow writes and machine read-back |
| Work with integrations or BPMS | Separate exact-approved runtime gate; no blanket feature ban |
| See a large project as a diagram | Enriched Diagramm JSON with classes, relations, KS fields, indicators, formulas and object counts |
| Return diagram edits to KS | Source-hash-bound structural diff and cloned-backup build; no in-place overwrite |
| Learn an undocumented UI action | Redacted capture → compare → normalize → test → promote workflow |

### Safety by design

The safety layer is part of the product, not an optional checklist:

1. The stand URL and project UUID are declared in the reviewed plan and must
   exactly match the runtime environment.
2. Endpoints are canonicalized and classified by both API path and declared
   business effect.
3. Project writes, runtime actions, destructive actions and server work use
   different capability gates.
4. Project writes require read-before, one unambiguous payload source and
   non-empty machine-readable read-back checks. The reviewed `entityUuid`,
   mutation payload UUID and get-by-id verification UUID must be identical.
5. Runtime payload secrets may only come from purpose-created
   `KS_RUNTIME_PAYLOAD_*` variables and only into credential/source-connection
   fields; KS login credentials and target/action fields cannot be injected.
6. Reports redact embedded Bearer/Basic auth, credentialed URIs, JWT-like
   strings, private keys and configured secret values.
7. Local payload and output paths reject traversal, absolute paths and
   symlinks before any API side effect.
8. Backup conversion is offline. Live restore remains a separate
   exact-approved operation into a new scratch project.
9. All executable local inputs and output targets are preflighted as one batch
   before login. An uncertain network result stops the batch as
   `effect_unknown`, forbids automatic retry and triggers best-effort read-back.

See [SECURITY.md](SECURITY.md) for the threat model and approval boundaries.

### Current round-trip boundary

The read view is intentionally richer than the write profile. Diagramm can
display class structure, semantic relations, mapped KS fields/attributes,
indicators, formula provenance and object counts. The current
`structural-v0.1` write profile creates new classes and new semantic
relationships in a cloned backup.

Updates or deletes of existing entities, attribute/indicator/formula writes,
object mutations and live restore are not silently inferred from the diagram;
they remain deferred until a dedicated mapping and approval contract exists.

### Requirements

- Codex with plugin support;
- Python 3.10 or newer;
- `requests` for KS API scripts;
- `zstd` for packed KS backups;
- Node.js only for optional browser API capture.

```bash
python3 -m pip install -r plugins/knowledge-space-codex/requirements.txt
python3 plugins/knowledge-space-codex/skills/ks-codex/scripts/ks_environment_preflight.py
```

### Install

The repository is public on GitHub, but the plugin is not currently part of
the global OpenAI plugin catalog. Other users install it from this GitHub
marketplace:

```bash
codex plugin marketplace add seroja01ajores/knowledge-space-codex-toolkit --ref main
codex plugin add knowledge-space-codex@ks-agent-local
```

After an update, refresh the marketplace entry, reinstall the plugin and start
a new Codex task so the refreshed skills are loaded:

```bash
codex plugin marketplace upgrade ks-agent-local
codex plugin add knowledge-space-codex@ks-agent-local
```

### Connect to a KS project

Supply the target only at runtime. Use either login/password or a token:

```text
KS_BASE_URL=https://<host>/api
KS_PROJECT_UUID=<project uuid>
KS_LOGIN=<login>
KS_PASSWORD=<password>
# or: KS_TOKEN=<token>
```

Keep values in the environment, Keychain or another approved secret manager.
Never commit them, source-system passwords, raw backups, snapshots or captures.

Recommended first prompt:

```text
Use $ks-codex. Run the environment preflight, verify the selected stand and
project UUID, then perform a read-only project audit. Do not write anything.
```

For a backup/diagram workflow:

```text
Use $ks-diagram-roundtrip. Work only on a copy of this backup, create a bounded
read model and Diagramm JSON, validate all artifacts and stop before live
restore.
```

### Public core and private overlay

The public plugin is reusable across KS installations. Organization-specific
stand profiles, credentials, real evidence, customer backups and learned local
patterns belong in a separate private overlay. The overlay may reference a
pinned public-core commit, but public builds never package the overlay.

This preserves the reusable capture/learning mechanism without publishing the
private material it learns from. See
[docs/private-overlay.md](docs/private-overlay.md) and
[docs/self-learning.md](docs/self-learning.md).

### Repository layout

- `plugins/knowledge-space-codex/` — canonical installable plugin;
- `plugins/knowledge-space-codex/skills/ks-codex/` — KS API/course/project skill;
- `plugins/knowledge-space-codex/skills/ks-diagram-roundtrip/` — offline diagram
  and cloned-backup skill;
- `tools/build_portable_plugin.py` — deterministic sanitized release builder;
- `docs/` — architecture, private-overlay and learning guidance.

### Validation and release

```bash
python3 tools/run_plugin_tests.py
python3 tools/test_build_portable_plugin.py
python3 tools/build_portable_plugin.py --output-dir dist
```

The release builder packages only the canonical plugin, rejects sensitive or
stand-specific artifacts and writes a deterministic ZIP, SHA-256 checksum and
JSON build report.

### Status

This toolkit is production-oriented but deliberately fail-closed. A successful
offline validation does not by itself authorize KS writes, integration runs,
backup restore or server maintenance. Those actions require the corresponding
reviewed plan, target binding and approval gate.
