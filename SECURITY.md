# Security model / Модель безопасности

[Русский](#русская-версия) · [English](#english-version)

## Русская версия

### Область действия

Плагин предназначен для работы в пределах выбранного проекта Knowledge Space
через официальный HTTP API и для офлайн-обработки экспортированных резервных
копий проекта. Он не даёт разрешения изменять развёртывание KS, базу данных,
контейнеры, пользователей, глобальные роли или посторонние проекты.

### Уровни допуска

- `dry_run`: чтение, классификация и подготовка планов без побочных эффектов.
- `execute_project_writes`: точно подтверждённые изменения в пределах проекта
  с чтением до операции и машинно-проверяемым чтением результата.
- `approved_runtime`: точно подтверждённые запуски интеграций, действия BPMS,
  пересчёты, экспорты, загрузки и аналогичные runtime-эффекты.
- `approved_destructive`: точно подтверждённая разрушительная или глобальная
  операция, например удаление, изменение доступа или изолированное
  восстановление резервной копии. Универсальные исполнители этот уровень
  допуска не реализуют.
- `server_maintenance`: явно отделённые серверные работы. Они никогда не
  выводятся автоматически из задачи по работе с проектом KS.

Неизвестные или неоднозначные операции блокируются по принципу fail-closed.

### Работа с учётными данными

- `KS_BASE_URL`, `KS_PROJECT_UUID` и либо `KS_TOKEN`, либо
  `KS_LOGIN`/`KS_PASSWORD` настраиваются вне Git.
- Секреты интеграций для runtime-операций передаются через специальные
  переменные `KS_RUNTIME_PAYLOAD_*`. Они могут подставляться только в заранее
  проверенные поля учётных данных или подключения к источнику. Поля
  идентификации, проекта, действия и управления нельзя передавать через
  `payloadEnv`; основные учётные данные KS блокируются, даже если скопированы в
  переменную с разрешённым именем.
- Нельзя помещать cookie, значения CSRF, закрытые ключи, учётные данные
  источников или резервные копии продуктивных проектов в планы или задачи
  GitHub (issues).
- В сгенерированных отчётах маскируются чувствительные ключи и встроенные
  шаблоны учётных данных.
- Все дефекты исполняемого пакета, которые можно определить локально,
  проверяются до первой авторизации или первого API-вызова проекта. Потерянный
  ответ на изменение или runtime-действие отмечается как `effect_unknown`;
  пакет останавливается, автоматический повтор запрещается, а заявленное
  контрольное чтение выполняется, когда это возможно.

### Безопасность резервных копий и диаграмм

- Исходные резервные копии являются неизменяемыми входными данными и должны
  оставаться приватными.
- Большие резервные копии обрабатываются ограниченными по объёму zstd-срезами;
  значения бизнес-объектов не помещаются в модель чтения Diagramm.
- Каждый редактируемый артефакт привязывается к SHA-256 исходника и самого
  артефакта.
- Профиль записи создаёт клонированную структурную резервную копию и никогда не
  изменяет оригинал на месте.
- Живое восстановление не входит в офлайн CLI и должно выполняться только в
  новый, отдельно подтверждённый тестовый проект с собственной
  предварительной проверкой разрушительной операции и контрольным чтением.

### Сообщение об уязвимости

Не создавайте публичный issue, содержащий учётные данные, клиентские данные,
реальные UUID проектов, фрагменты резервных копий или внутренние имена хостов.
Свяжитесь с владельцем репозитория приватно и приложите только минимальное
синтетическое воспроизведение проблемы.

---

## English version

### Scope

The plugin is designed for project-scoped Knowledge Space work through the
official HTTP API and for offline processing of exported project backups. It
does not grant permission to change a KS deployment, database, containers,
users, global roles or unrelated projects.

### Capability gates

- `dry_run`: read, classify and prepare plans; no side effects.
- `execute_project_writes`: exact approved project-scoped changes with
  read-before and machine read-back checks.
- `approved_runtime`: exact approved integration, BPMS, recalculation, export,
  upload and similar runtime effects.
- `approved_destructive`: exact destructive/global operation such as delete,
  access change or isolated backup restore. The generic executors do not
  implement this gate.
- `server_maintenance`: explicitly separate server work. It is never inferred
  from a KS project task.

Unknown or ambiguous operations fail closed.

### Credential handling

- Configure `KS_BASE_URL`, `KS_PROJECT_UUID` and either `KS_TOKEN` or
  `KS_LOGIN`/`KS_PASSWORD` outside Git.
- Runtime integration secrets use dedicated `KS_RUNTIME_PAYLOAD_*` variables.
  They may target only reviewed credential/source-connection fields. Identity,
  project, action and control fields cannot be supplied through `payloadEnv`,
  and core KS credentials are rejected even if copied into an allowed variable.
- Do not paste cookies, CSRF values, private keys, source credentials or
  production backups into plans or issues.
- Generated reports redact sensitive keys and embedded credential patterns.
- Every locally knowable defect in an executable batch is checked before the
  first login or project API call. A lost mutation/runtime response is reported
  as `effect_unknown`; the batch stops, automatic retry is forbidden, and the
  declared read-back is attempted when possible.

### Backup and diagram safety

- Source backups are immutable inputs and must remain private.
- Large backups use bounded zstd slicing; business object values are not placed
  in the Diagramm read model.
- Every editable artifact is bound to source and artifact SHA-256 values.
- The write profile builds a cloned structural backup and never edits the
  original in place.
- Live restore is outside the offline CLI and must target a newly approved
  scratch project with its own destructive preflight and read-back.

### Reporting a vulnerability

Do not open a public issue containing credentials, customer data, real project
UUIDs, backup fragments or internal hostnames. Contact the repository owner
privately and include only a minimal synthetic reproduction.
