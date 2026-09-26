# Historical Source Export Manifest

This file records the **2026-09-19 source export snapshot** that was used to create the GitHub mirror.

It is historical provenance, not a description of the current repository head.

## Snapshot identity

- Export date: 2026-09-19
- Source branch at export: `main`
- Source commit at export: `e7041a200b7cd4ca7d21b3637bd9f13684f0ab3d`
- Export intent: preserve full SignalForge source while excluding secrets, private runtime data, caches and rollback packages

## Excluded classes

The export intentionally excluded:

- real `.env` and credentials
- runtime databases
- `.radar_runtime/`
- caches and logs
- rollback backups
- generated build output
- local dependency folders
- generated zip / installer packages
- private user / customer data

## Current status

The repository has continued to evolve after this snapshot.

For current architecture and setup, use:

- [README](README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Demo Guide](docs/DEMO.md)
- [Limitations](docs/LIMITATIONS.md)

Do not use the historical counts from the original export as current repository statistics.
