# Maintainer export

The original private project's automation/film/export_oss.py is the explicit allowlist exporter. It reads only named tools and the four named example trees, transforms automation paths into tools, workflows into films, injects CINEFORGE_BOX_VM_DIR and environment-based image credentials, then scans the entire destination (excluding .git). It never reads runtime/media trees or Box implementation files. It preserves hand-authored target docs and utilities; re-export overwrites imported tools/examples. Review upstream changes before rerunning.

Run from the private source project:

```sh
python3 automation/film/export_oss.py --target ../cineforge
python3 automation/film/export_oss.py --target ../cineforge --scan-only
```

Exit zero means no detected hits; nonzero prints locations/categories without secret values. It scans untracked text too, so clean local generated state before a release scan. The git object database is outside that scan: review staged changes and never commit a failed export. Destination symlinks are rejected. No automatic deletion of target files occurs; obsolete files require explicit review/removal.

Excluded: all media, real cat photos, generated receipts/logs, notebook identities, budgets, backups, caches, research clones, archives, Box implementation and one-off benchmark output. The legacy rough_loop and network-recovery shell scripts depend on the original operator's process setup and are omitted; invoke the documented per-film editor explicitly. Lab inference adapters remain with status notes in models.md. No media source license is inferred from example credits.
