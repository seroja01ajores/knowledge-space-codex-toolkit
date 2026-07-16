# Safe Restore and Read-back

This document begins where the offline round-trip CLI ends. The CLI has no
upload or restore command, and every offline plan, manifest, bundle-validation
report, and packed backup remains `liveRestoreBlocked: true`. A separate live
executor may proceed only after a fresh read-only preflight and exact
`approved_destructive` approval for the specific operation below.

## Risk Classification

- Local unpack, slice, bundle validation, conversion, diff, build, structural
  validation, and pack: offline/read-only with respect to KS.
- Creating/downloading a backup through KS: `approved_runtime`.
- Uploading and restoring a backup: `approved_destructive`.
- Access changes, overwrite, cleanup, or delete: separate exact destructive
  approval; never implied by approval to restore a new project.

## Preflight

Run a fresh read-only discovery and record before requesting upload approval:

- exact stand origin and authenticated user identity;
- source project origin and UUID;
- intended new scratch project name;
- packed backup absolute path, size, and SHA-256;
- pack-report path and SHA-256 with successful packed read-back;
- final bundle-validation report path and SHA-256 with zero hard errors;
- source, plan, clean-output, and packed-output SHA-256 values;
- exact accepted deferred paths from the bound build report;
- restore options fixed to new project, current user only, and recalculation off;
- confirmation that no existing project UUID is a restore target;
- the exact requested action, approval identity, approval timestamp, and the
  artifact/option snapshot covered by that approval.

Never infer the target from the currently visible browser tab. Never restore over
an existing project in this workflow. A project name containing “scratch” is not
proof that a project is disposable.

The offline `liveRestoreBlocked` state cannot be cleared by editing a manifest,
bridge, plan, or report. The separate executor must compare the approved snapshot
byte-for-byte/field-for-field immediately before upload and stop on any drift.

## Restore Profile

After exact approval, the separate live executor may use the normal KS backup
UI/API flow:

1. upload the validated file;
2. create a restore operation;
3. load it as a new project;
4. restore access only for the current user;
5. disable automatic model recalculation;
6. wait for terminal restore history status;
7. stop on failure; do not retry with broader options.

Do not create an empty project first. New-project restore creates the project and
remaps UUIDs.

Approval covers only this one upload/restore attempt using the approved packed
SHA-256 and options. It does not authorize overwrite, access broadening,
recalculation, retry with changed inputs, cleanup, or deletion.

## Read-back Checklist

After success, collect server-assigned values rather than assuming backup UUIDs:

- new project name and UUID;
- owner/current-user access;
- restore history success status;
- ordinary class entity and tree UUIDs;
- semantic relationship entity and tree UUIDs;
- source and destination class names/UUIDs;
- class/relationship descriptions;
- helper relation closure where API exposes it;
- absence of writes to the source and other work projects;
- browser tree/detail visibility.

Write a separate read-back binding artifact if another offline round-trip needs
to recognize the restored scratch project. Preserve the original offline bridge,
manifest, exact approval snapshot, and all reports for audit. The read-back
binding is identity evidence, not standing authorization for future writes or
restores.

## Failure Handling

On HTTP error, JSON `error`, failed restore history, missing entity, wrong
endpoint, access mismatch, or browser mismatch:

- stop immediately;
- keep the failed artifact and reports locally;
- treat the approval as consumed for that attempt and obtain a new exact
  approval before any retry;
- do not patch server storage or databases;
- do not restore over another project;
- classify whether the defect is converter, packaging, restore configuration,
  UUID rebinding, or frontend cache;
- fix and rerun offline validation before another approved attempt.
