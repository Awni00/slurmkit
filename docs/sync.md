# Cross-Cluster Sync

`slurmkit sync` writes derived per-host snapshots under `.slurmkit/sync/` so repositories can share collection status across clusters.

## Purpose

Collections are the local source of truth. Sync files are exports for cross-host visibility and git transport.

That means:

- collections live in `.slurmkit/collections/`
- sync snapshots live in `.slurmkit/sync/`
- sync does not replace or own collection history

## Layout

```text
.slurmkit/sync/
├── cluster-a.yaml
├── cluster-b.yaml
└── workstation.yaml
```

Each file contains the latest summarized collection state for one host.

## Basic usage

Write the local host snapshot:

```bash
slurmkit sync
```

Restrict to one collection:

```bash
slurmkit sync --collection exp1
```

Write the snapshot and push it through git:

```bash
slurmkit sync --push
```

## Typical workflow

On cluster A:

```bash
slurmkit submit exp1
slurmkit sync --push
```

On cluster B:

```bash
git pull
slurmkit collections show exp1
```

## Git usage

If you do not use `--push`, you can commit sync files manually:

```bash
git add .slurmkit/sync/
git commit -m "Sync slurmkit status"
git push
```

## Conflict handling

Conflicts are usually limited to one host-owned file:

```text
.slurmkit/sync/<hostname>.yaml
```

If that happens, keep the version from the machine that owns the file and re-run `slurmkit sync` there if needed.
