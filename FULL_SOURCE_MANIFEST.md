# Full Source Manifest

This manifest makes the public export reproducible and auditable. Counts refer to the production working tree at export time; the production repository itself was not modified.

## Source identity

| Field | Value |
|---|---|
| Source repo path | `[local-workspace]/community-mind-mirror` (absolute user path withheld) |
| Git root | `[local-workspace]` (absolute user path withheld) |
| Export timestamp | `2026-09-19T19:29:21+08:00` |
| Source branch | `main` |
| Source commit SHA | `e7041a200b7cd4ca7d21b3637bd9f13684f0ab3d` |
| Source tracked file count | 158 |
| Source status entries in SignalForge subtree | 702 |
| Modified tracked source files included | 19 |
| Untracked source files included | 390 |
| Source-of-truth paths exported | 548 |
| Total files in final GitHub repository | 556 |
| Files discovered on source disk | 44,822 |
| Files intentionally excluded from disk inventory | 44,274 |
| Git-visible untracked files excluded | 2,597 |

The final repository count is larger than the 548 source-of-truth paths because it also contains the professor-facing README, four portfolio overview documents, this manifest, the untracked-source appendix, the public `.gitignore`, and `dashboard/.npmrc` for reproducible installation across the source tree's existing React peer-dependency range.

## Inclusion policy

- All 158 tracked paths from the SignalForge subtree were represented in the export. The root `README.md` path contains the updated professor-facing README rather than the older production README text.
- The export uses the current working-tree contents, so all 19 modified tracked source files are included as they existed at export time.
- Untracked current source was not dropped merely because Git had not recorded it. The export includes current code from `api/`, `processors/`, `dashboard/`, `scrapers/`, `database/`, `scheduler/`, `config/`, `docs/`, `benchmarks/`, and root run/test/audit scripts.
- The exact 390 untracked files included are listed in [Included Untracked Source](docs/INCLUDED_UNTRACKED_SOURCE.md).
- Two exported scripts were made portable in the mirror only: hard-coded local Windows fallbacks were replaced with repository-relative path discovery. The production working tree was not edited.

## Intentionally excluded paths

The following path classes were intentionally omitted. These are exclusions from the full **source** mirror, not missing application source:

| Path or pattern | Reason |
|---|---|
| `.env`, `.env.*` except `.env.example` | Secrets and machine-local configuration |
| `dashboard/.env` | Machine-local frontend configuration |
| `.radar_runtime/` | Runtime research state and databases |
| `.radar_cache/`, `.radar_backups/` | Cache and rollback data |
| `.signalforge_stage/`, `.signalforge_backups/` | Runtime staging and backups |
| `.signalforge_*` and `.radar_*` root metadata | Installer manifests, failure bundles, and backup metadata |
| `_sf_*/` | WIP/export/install packages |
| `SignalForge_Latest_*/` | Historical packaged snapshot |
| `venv/`, `.venv/`, `node_modules/` | Local dependency installations |
| `dist/`, `build/` | Generated build output |
| `__pycache__/`, `.pytest_cache/`, `*.pyc`, `*.pyo` | Generated caches and bytecode |
| `logs/`, `cache/`, `downloads/`, `*.log` | Runtime logs, caches, and downloads |
| `*.sqlite`, `*.sqlite3`, `*.db` | Runtime databases |
| `*.zip` | Installer, backup, snapshot, and rollback archives |
| `*.bak`, `*.before_*`, `*_backup.*` | Historical rollback copies |
| `artifacts/` | Generated execution artifacts |
| `.spending.json` | Private runtime spending data |
| `SignalForge_Brain_v2_REVIEW_BUNDLE.txt` | Generated review bundle |
| `SignalForge_Brain_v2_Source_Manifest.json` | Generated package manifest |
| `SignalForge_Brain_v2_Source_Snapshot.zip` | Generated source archive |
| `signalforge_golden*_results_*` | Generated benchmark result output |
| `install_*.py` | Historical installer scripts rather than current runtime source |

## Secret scan result

No real secret was found in the 548-file source inclusion set or the final staged Git tree.

Patterns checked included `API_KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `Bearer`, `Authorization`, `sk-`, `ghp_`, `github_pat_`, `BEGIN PRIVATE KEY`, `SERPER`, `OPENAI`, `ANTHROPIC`, `DATABASE_URL`, cloud key formats, embedded URL credentials, and non-empty secret assignments across Python, PowerShell, TypeScript, JavaScript, Markdown, JSON, YAML, TOML, and environment templates.

Reviewed matches were limited to:

- environment-variable names and server-side header construction;
- explicit fake test fixtures such as `x-secret`, `gh-secret`, `secret-brave-key`, and `example.com`;
- `.env.example` placeholders such as `your_password` and empty API-key fields;
- security tests that deliberately reject embedded credentials.

## Private-data scan result

No private customer record, personal email, phone number, session cookie, LINE token, real credential, private certificate, or private URL was found in the inclusion set. Public project/source names, public URLs, synthetic fixtures, and the repository owner's project-level capability labels remain because they are code/configuration context rather than private customer data.

## Entrypoints and dependencies

- Backend entrypoint: `api/main.py`, served as `api.main:app` with Uvicorn.
- Frontend entrypoint: `dashboard/src/main.tsx`, served by Vite.
- Python dependencies: `requirements.txt`, `requirements-signalforge-chatgpt.txt`.
- Frontend dependencies: `dashboard/package.json`, `dashboard/package-lock.json`.
- Infrastructure/config templates: `docker-compose.yml`, `.env.example`, `dashboard/vite.config.ts`, TypeScript configs.
