# BPMS Patterns

Use this reference when a KS project contains `Бизнес процессы`, process tasks, process-triggered integrations, or dashboard buttons that start/advance a process.

## Safety

- Treat every process start, task completion, model recalculation, integration run, history cleanup, variable write, and file upload as a mutating action.
- Do not click process start buttons, task execution buttons, `Очистить историю`, `Создать диаграмму`, or dashboard buttons that look like `Загрузить`, `Рассчитать`, `Утвердить`, `Передать`, `Очистить`, `Экспорт`, or `Импорт` unless the user explicitly approves that exact run.
- Opening a process, reading history, opening the diagram tab, and inspecting task settings are read-only. Still expect the UI to fetch process/history data automatically.
- If a process task points to an integration, apply integration safety too: confirm source, target project, dataset/model targets, and expected writes before running anything.
- When the user intentionally asks to start/complete a process task, use the approved-runtime flow with `scripts/ks_approved_runtime_execute.py --execute`; record exact operation id/endpoint, process/task UUIDs, expected effect, target project, and read-back/verification or waiver.

## Core Read Areas

The BPMS tree is usually opened from:

```http
POST /processes/tree-get-down
```

Common read endpoints observed in KS projects:

```text
POST /processes/get-list
POST /processes/get-by-ids
POST /processes/get-elements-list
POST /tasks/get-list
POST /tasks/get-by-ids
POST /processes/get-instances-list
POST /processes/get-variables-list
```

Payloads vary by KS version; prefer reading the existing process and task back before updating.


## Offline Snapshot Audit

After creating a local snapshot, use the bundled offline tool before touching process settings:

```bash
python3 scripts/ks_bpms_audit.py /path/to/snapshot.json --output bpms_audit.md
```

The tool never calls KS. It reports process/task counts, `run_integration` tasks, unresolved process/integration/model references, unvalidated dataset UUIDs when the snapshot lacks a dataset registry, and run-safety warnings. Treat warnings as a reason to inspect more, not as approval to run anything.

## Process Screen

The process page usually has:

- a process enable toggle `Включить бизнес-процесс`;
- tabs `История запусков` and `Диаграмма`;
- a history table with instance status/current element;
- a variables table;
- sometimes `Очистить историю`.

Do not use the enable toggle as proof that the process is safe to run. It only means the process can be available.

## Diagram Tab

The diagram tab can show:

- `Синхронизировано` / `Не синхронизировано`;
- sync options for process elements and extra figures;
- `Создать диаграмму` when the diagram does not exist.

Creating/synchronizing a diagram changes the process visualization. It is not a data integration run, but still requires approval when working read-only.

## Task Patterns

Common task settings visible in the UI:

- execution type: one executor, joint execution, or parallel execution;
- next element type and next element;
- completion criterion;
- model and dataset selectors;
- integration selector for integration-triggering tasks;
- files tab for file-bound tasks.

Integration-course task pattern:

```text
completionCriteria = run_integration
integrationSettings.integrationUuid = <integration_uuid>
modelUuid = <model_uuid>
datasetUuids = [<dataset_uuid>]
```

If a BPMS task must choose model/dataset at runtime, leave model/dataset unset in the integration itself and bind them in the task or runtime variable settings instead.

Observed task/action families in larger demo projects include:

- `run_integration`: launch an integration from a task;
- `autocomplete_data`: fill or enrich values automatically;
- `set_interface_event`: drive an interface event from the process;
- model tag or object tag based tasks;
- gates/branches based on variables or task outcomes;
- file variables and collection variables.

Preserve existing task shape when updating. A task can look correct in the tree while `completionCriteria` or nested `integrationSettings` remain at defaults.

## Updating Tasks Safely

Before a task update:

1. Read the process, elements, and task by UUID.
2. Record task UUID, process UUID, current criterion, next element, model/dataset, integration, variables, and file bindings.
3. Prepare a dry-run summary of exact changed fields.
4. Update only the target task.
5. Read back and compare the full task shape.

Course-specific note: on some stands, creating a task node leaves `completionCriteria` and integration settings empty. Update the task after creation with the casing accepted by the current stand, then verify.

## Dashboard Buttons And Processes

Buttons on dashboards may start or continue BPMS flows even when the label is business-friendly. Treat labels like these as unsafe to click during QA without approval:

```text
Загрузить факт
Очистка от ...
Рассчитать
Утвердить
Передача данных
Экспорт данных
Импорт
```

Navigation labels such as `Вход в личный кабинет ...` or menu placement buttons are usually safe to inspect, but confirm by checking dashboard events when possible.

## Browser QA Checklist

- Open the process list/tree and record process names.
- Open process pages read-only and inspect enable state, history tab, diagram tab, and task tree.
- Do not clear history, create diagrams, or start processes.
- For each dashboard that contains process buttons, classify every button as navigation, modal, process/integration run, export/import, or unknown.
- If the UI is slow or screenshots time out, use DOM/console inspection before concluding the screen is blank.
