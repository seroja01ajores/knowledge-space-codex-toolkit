# KS Integration Course Build Spec

Use this course-specific reference only when recreating the KS DB integration course from scratch or comparing against its final demo backup. It is not a generic integration template. Replace all UUIDs and external source details with values from the target project and stand.

## Prerequisites

- Model: `Планирование работ`
- Datasets: `План`, `Факт`, `common`
- Dictionaries: `Тип работы`, `Тип ремонта`
- Classes: `Работы`, `Оборудование`, `Персонал`, `Технический`, `Консолидирующий`
- Relation classes:
  - `Назначено оборудование`: `Оборудование -> Работы`
  - `Назначен персонал`: `Персонал -> Работы`
- DB source display name: `Источник 1`
- DB source: use the stand/course-provided database type, host, database name, login, and password. Do not run or check the source without confirmed safe credentials.
- System time dimension: discover its UUID from the target stand or the target
  project's own table/formula configuration before building mappings. Never
  reuse a UUID copied from a course backup or another stand.

## Integrations And Operations

### Получение элементов справочников

Direction: `input`; model/datasets empty.

1. Operation `Получить элементы справочника`, route `get_dictionary_elements`, target dictionary `Тип работы`.
   - `public.type_work.name_type -> name`
   - `public.type_work.id_type -> primaryKey`
2. Operation `Получить элементы справочника`, route `get_dictionary_elements`, target dictionary `Тип ремонта`, previous operation 1.
   - `public.type_repair.name_repair -> name`
   - `public.type_repair.id_repair -> primaryKey`

### Работы (План)

Direction: `input`; model `Планирование работ`; dataset `План`.

1. `Cоздать объект`, route `create_object`, class `Работы`.
   - `public.work.name_work -> name`
   - `public.work.id_work -> primaryKey`
2. Empty-name operation, route `update_data`, class `Работы`.
   - SQL: `SELECT iwp.id_work, iwp.start, iwp.finish, iwp.limit, tw.name_type FROM info_work_plan AS iwp JOIN type_work AS tw ON iwp.id_type = tw.id_type`
   - `public.type_work.name_type -> indicator Работы.Тип работы`, dictionary element by name
   - `public.info_work_plan.id_work -> primaryKey`
   - `public.info_work_plan.limit -> indicator Работы.Лимит затрат`
   - `public.info_work_plan.finish -> indicator Работы.Окончание`
   - `public.info_work_plan.start -> indicator Работы.Начало`

### Работы (Факт)

Direction: `input`; model `Планирование работ`; dataset `Факт`.

1. `Обновить данные`, route `update_data`, class `Работы`.
   - `public.info_work_fact.start -> indicator Работы.Начало`
   - `public.info_work_fact.id_work -> primaryKey`
   - `public.info_work_fact.finish -> indicator Работы.Окончание`

### Оборудование

Direction: `input`; model `Планирование работ`; dataset `План`.

1. `Cоздать объект`, route `create_object`, class `Оборудование`.
   - `public.equipment.name_equipment -> name`
   - `public.equipment.id_equipment -> primaryKey`
2. `Создать cвязи объектов`, route `create_objects_relations`, class `Оборудование`, relation `Назначено оборудование`, previous operation 1.
   - `public.link_equipment_work.id_link -> primaryKey`
   - `public.link_equipment_work.id_equipment -> relatedSourceId`
   - `public.link_equipment_work.id_work -> relatedDestinationId`
3. `Обновить данные`, route `update_data`, class `Оборудование`, previous operation 2.
   - `public.equipment.id_equipment -> primaryKey`
   - `public.equipment.price -> indicator Оборудование.Цена`

### Персонал

Direction: `input`; model `Планирование работ`; dataset `План`.

1. `Cоздать объект`, route `create_object`, class `Персонал`.
   - `public.staff.id_staff -> primaryKey`
   - `public.staff.name_staff -> name`
2. `Создать cвязи объектов`, route `create_objects_relations`, class `Персонал`, relation `Назначен персонал`, previous operation 1.
   - `public.link_staff_work.id_link -> primaryKey`
   - `public.link_staff_work.id_staff -> relatedSourceId`
   - `public.link_staff_work.id_work -> relatedDestinationId`
3. `Обновить данные`, route `update_data`, class `Персонал`, previous operation 2.
   - `public.staff.rate -> indicator Персонал.Ставка`
   - `public.staff.id_staff -> primaryKey`

### Суточное количество часов на выполнение работы (Назначен персонал)

Direction: `input`; model `Планирование работ`; dataset `План`.

1. `Обновить данные`, route `update_data`, class `Назначен персонал`.
   - `public.staff_hours.id_staff_hours -> indicator Назначен персонал.Суточное количество часов на выполнение работы`
   - `public.staff_hours.id_staff_hours -> primaryKey`

### Количество часов на ремонт (ВИ+ПИ)

Direction: `input`; model/datasets empty.

1. Empty-name operation, route `update_data`, class `Оборудование`.
   - SQL: `SELECT e.id_equipment, er.name_equipment, er.hours_repair, er.quarter_repair, tr.name_repair FROM public.equipment_repair AS er JOIN public.equipment AS e ON er.name_equipment = e.name_equipment JOIN public.type_repair AS tr ON er.type_repair = tr.id_repair ORDER BY quarter_repair ASC`
   - `public.equipment.id_equipment -> primaryKey`
   - `public.type_repair.name_repair -> dimension Тип ремонта`
   - `public.equipment_repair.hours_repair -> indicator Оборудование.Количество часов на ремонт`
   - `public.equipment_repair.quarter_repair -> system time dimension`

### Суммарное количество часов на ремонт (ПИ)

Direction: `input`; model/datasets empty. The demo backup had a leading-space artifact in this integration name; prefer the trimmed name in new projects unless exact backup parity is required.

1. `Обновить данные`, route `update_data`, class `Оборудование`.
   - SQL: `SELECT e.id_equipment, er.name_equipment, SUM(er.hours_repair) AS hours_repair, tr.name_repair FROM public.equipment_repair AS er JOIN public.equipment AS e ON er.name_equipment = e.name_equipment JOIN public.type_repair AS tr ON er.type_repair = tr.id_repair GROUP BY e.id_equipment, tr.name_repair, er.name_equipment ORDER BY hours_repair DESC`
   - `public.type_repair.name_repair -> dimension Тип ремонта`
   - `public.equipment_repair.hours_repair -> indicator Оборудование.Суммарное количество часов на ремонт`
   - `public.equipment.id_equipment -> primaryKey`

### Передача данных (Работы)

Direction: `output`; model `Планирование работ`; dataset `Факт`.

1. `Передать данные`, route `send_data`, class `Работы`.
   - `public.x06_user.quarter -> system time dimension`
   - `public.x06_user.name_work -> name`
   - `public.x06_user.cost -> indicator Работы.Общие затраты`
   - `public.x06_user.id_work -> primaryKey`
   - Output sampling conditions on `Работы.Общие затраты`:
     - `IS NOT NULL` constant numeric `0`
     - `!=` constant numeric `0`

### Общие затраты на работы в первом полугодии

Direction: `input`; model/datasets empty.

1. Empty-name operation, route `create_object`, class `Работы`.
   - SQL: `SELECT x.name_work AS "Название работы", x.cost AS "Общие затраты", x.quarter_number AS "Квартал" FROM ( SELECT name_work, cost, EXTRACT(QUARTER FROM quarter) AS quarter_number FROM x06_user WHERE quarter < '2026-07-01 00:00:00' ) AS x ORDER BY x.quarter_number ASC;`
   - `public.x06_user.id_work -> primaryKey`
   - Create integration table with the same name. Visible columns:
     - `<operation_uuid>~~~~Название работы`
     - `<operation_uuid>~~~~Общие затраты`
     - `<operation_uuid>~~~~Квартал`


## Read-Only Parity Checklist

When comparing a recreated integration-course project with the final demo, do not run any integrations or BPMS processes just to prove parity. Use read-back structure first:

- Integration names and directions: 10 integrations matching this spec.
- Operation routes and order: compare each integration by `routename`, previous-operation links, disabled flags, and custom SQL presence.
- Field mappings: filter field rules by the operation UUIDs of that integration before counting or comparing.
- Output integration: `Передача данных (Работы)` should have exactly two relevant output sampling conditions after operation filtering: `IS NOT NULL` and `!= 0` for the total-cost indicator.
- BPMS: task `Задача` should have `completionCriteria: run_integration` and point to the output integration, model `Планирование работ`, dataset `Факт`. Separately verify `process.enabled`; do not enable/start it without explicit approval.
- Final UI/data parity requires the non-integration layer too: course objects, 12 data tables, 5 dashboards, and the publication/application tree.

## Business Process Pattern

The demo contains one process `Передача данных (Работы)`:

- Start event `Старт`
- Task `Задача`
  - `completionCriteria`: `run_integration`
  - `integrationSettings.integrationUuid`: integration `Передача данных (Работы)`
  - model: `Планирование работ`
  - dataset: `Факт`
- End event `Финиш`

Do not start this process until the source is confirmed safe; the task can run the output integration.

Implementation note observed on a 2026 KS stand: creating a BPMS task through `/processes/create-node` may create the task but leave `completionCriteria` and `integrationSettings` at defaults. After the task exists, call `/tasks/update` with `UUID`, `ProcessUUID`, `CompletionCriteria: "run_integration"`, and uppercase `IntegrationSettings.IntegrationUUID`, `ModelUUID`, `DatasetUUIDs`.
