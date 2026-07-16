# KS Backup Unpacking With zstdcat

Use this when the user provides an exported KS project backup or a zstd-compressed JSON file that must be inspected locally.

## Safety Rules

- Unpack backups locally into a dedicated working directory.
- Do not restore or load a backup into any KS server unless the user explicitly asks for restore/load and confirms the target project/server.
- Treat backup contents as sensitive: project data, users, object names, files, and configuration may be present.
- Do not edit the compressed source file. Write decompressed output to a new file.
- Prefer read-only inspection of unpacked JSON before any API writes.

## Check Tool Availability
Install tools on a local workstation or disposable analysis environment. Do not install packages on a production KS server unless the user explicitly requested server maintenance.


```bash
which zstdcat
```

If missing on macOS:

```bash
brew install zstd
```

If missing on Ubuntu / Debian:

```bash
sudo apt update
sudo apt install zstd
```

If missing on Fedora / RHEL / CentOS:

```bash
sudo dnf install zstd
```

If missing on Arch / Manjaro:

```bash
sudo pacman -S zstd
```

On Windows, use Windows Subsystem for Linux (WSL) or the Windows binaries from:

```text
https://github.com/facebook/zstd/releases
```

## Unpack Command

General form:

```bash
zstdcat /path/to/zstdunpack.json > /path/to/output/zstdunpacked2.json
```

Example with a dedicated output directory:

```bash
mkdir -p /tmp/ks-backup-unpacked
zstdcat /path/to/zstdunpack.json > /tmp/ks-backup-unpacked/zstdunpacked2.json
```

The input filename may still end with `.json` even when its contents are zstd-compressed. Trust the compression format, not only the extension.

## Validate The Result

Check the output exists and has content:

```bash
ls -lh /tmp/ks-backup-unpacked/zstdunpacked2.json
head -c 200 /tmp/ks-backup-unpacked/zstdunpacked2.json
```

If `jq` is available, validate JSON:

```bash
jq type /tmp/ks-backup-unpacked/zstdunpacked2.json
```

For a large file, inspect top-level keys without printing sensitive data:

```bash
jq 'if type == "object" then keys else type end' /tmp/ks-backup-unpacked/zstdunpacked2.json
```

## KS Backup Metadata Tail

Some KS backup exports decompress to a JSON array followed by a small service tail:

```text
%backup_metadata_size=104%<base64 metadata>
```

That tail is useful as backup metadata, but it makes tools such as `jq` report a parse error after reading the array. For analysis, keep the original unpacked file and create a clean JSON copy by cutting the file before `%backup_metadata_size=`.

Chunk-safe Python helper for large files:

```bash
python3 - <<'PY'
from pathlib import Path
marker = b'%backup_metadata_size='
src = Path('/tmp/ks-backup-unpacked/zstdunpacked2.json')
out = Path('/tmp/ks-backup-unpacked/zstdunpacked2.clean.json')
meta = Path('/tmp/ks-backup-unpacked/zstdunpacked2.metadata.txt')
tail = b''
with src.open('rb') as f, out.open('wb') as g:
    while True:
        chunk = f.read(1024 * 1024)
        if not chunk:
            if tail:
                g.write(tail)
            break
        data = tail + chunk
        idx = data.find(marker)
        if idx != -1:
            g.write(data[:idx])
            meta.write_bytes(data[idx:] + f.read())
            break
        keep = len(marker) + 128
        if len(data) > keep:
            g.write(data[:-keep])
            tail = data[-keep:]
        else:
            tail = data
PY
```

Then validate the clean copy:

```bash
jq type /tmp/ks-backup-unpacked/zstdunpacked2.clean.json
jq 'length' /tmp/ks-backup-unpacked/zstdunpacked2.clean.json
```

## When zstdcat Fails

Common causes:

- file is not zstd-compressed;
- file path contains spaces and was not quoted;
- output directory does not exist;
- `zstdcat` is not installed;
- file is truncated or corrupted.

Retry with quoted paths:

```bash
zstdcat "/path/with spaces/zstdunpack.json" > "/tmp/ks-backup-unpacked/zstdunpacked2.json"
```

Check compression:

```bash
file "/path/to/zstdunpack.json"
```

## Suggested Workflow For Codex

1. Check `which zstdcat`.
2. Create a local output directory.
3. Run `zstdcat "<input>" > "<output>"`.
4. Validate that the output is JSON.
5. Summarize top-level structure.
6. Use the unpacked JSON only as read-only source material unless the user explicitly asks to build/restore something from it.

## Large Backup Inspection

For large or production-like backups, do not print raw objects, data rows,
files, source connection records, or user records. Inspect aggregates first:

```bash
jq 'length' backup.clean.json
jq -r '.[].type? // .[].entityType? // empty' backup.clean.json | sort | uniq -c
```

When the export format is an array of typed records, collect only names and counts:

```bash
jq -r '.[] | select(.name? or .l10n?.name?) | [.type, (.name // .l10n.name)] | @tsv' backup.clean.json
```

Recommended safe outputs:

- project name and export metadata;
- counts by entity type;
- model, dashboard, publication, integration, integration-table, and process names;
- dashboard tree paths;
- integration direction and route names;
- process/task names and completion criteria;
- source type/product only, with host/login/password/database/API URL redacted.

If a backup contains demo business data, use only tiny structural samples and mark any domain examples as demo-only. Portable skill docs should describe patterns, not copy customer data or source schemas.
