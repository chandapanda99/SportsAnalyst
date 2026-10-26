# Local environment settings

Copy `.env.example` to `.env` for development and set your model-provider values.
The application reads `.env` and process environment variables; process values take
precedence. Never commit a populated env file or put credentials in frontend/Vite
variables. Hosting deployment files are intentionally not part of the current setup.

## What you need

- **Azure Foundry:** `MODEL_PROVIDER=azure_foundry`, `MODEL`, `FOUNDRY_ENDPOINT`,
  and `FOUNDRY_API_KEY` (or an explicitly configured supported identity).
  Model calls can still incur provider charges.
- **Message formatting:** optionally set `CHAT_MODEL` for summaries and follow-up
  wording only. Omit it to reuse `MODEL`. `REASONING_EFFORT` controls supported
  model reasoning configuration.
- **Ollama instead:** set `MODEL_PROVIDER=ollama`, `OLLAMA_BASE_URL` and
  `OLLAMA_MODEL`. Foundry credentials are unnecessary for that provider.
- **Data location:** omit `DATA_DIR` for the standard per-user folder, or choose a
  path deliberately. Changing it does not migrate datasets or investigation history.
- **Performance:** `DATASET_CACHE_MB` and `DATASET_SYNC_CONCURRENCY` control cache
  and bounded downloads. Start with the template values and tune when necessary.
- **Optional CFB sources:** review [source terms](cfb-source-terms.md) before setting
  `CFB_NCAA_ENABLED` or `CFB_CFBD_ENABLED`. Either requires
  `CFB_SECONDARY_USAGE_CONFIRMED=true`; template defaults do not acknowledge terms
  on another operator's behalf.
- **Diagnostics:** `LOG_LEVEL` controls logging. `LANGSMITH_*` configures optional
  tracing; tracing is not required.

## Local server versus Windows desktop

The standalone development server uses `PERSISTENCE_BACKEND=local`,
`JOB_BACKEND=local` and `JOB_PROGRESS_TRANSPORT=stream`. No separate worker or
external database is needed.

The Windows launcher configures `JOB_BACKEND=sqlite` and manages its sibling worker
automatically. Do not manually select SQLite for a standalone server without
starting `sports-analyst-worker`, or its jobs will remain queued.

SQL row limits, history limits, checksums, event timeouts, job admission and
worker polling/lease/heartbeat/retry settings already have defaults in
`src/sports_analyst/config.py`. Existing intentional private overrides are retained.
`MAX_ACTIVE_JOBS` limits queued/running work, not worker concurrency.

`SPORTS_ANALYST_DATA_ADMIN_TOKEN` is an optional deletion-protection setting.
It is not required for a trusted local installation and is not general authentication.
Do not expose an unauthenticated development server to the public internet.

## Windows signing

`WINDOWS_SIGNING_*` belongs to installer builds, not analysis or dataset syncing.
The PowerShell build/sign scripts read process environment variables, not `.env`.
Existing private signing settings may be retained for reference, but must be exported
to the build process when used. Never distribute private signing material.

## Retired hosting configuration

No Oracle, Google deployment, Redis, Neon, or external storage credentials are needed
for the local/desktop setup. Optional storage/job compatibility code remains internal;
no deployment is enabled by the template.

Removed private hosting settings and the original environment were archived locally
under `build/retired-cloud-backups/` before removing the extra env files. That archive
contains secrets: protect it like `.env`, do not share it, and keep a secure copy
elsewhere if you need it long-term because build outputs are disposable. It is ignored
by Git and excluded from Docker contexts. Tracked deployment files can also be
recovered from Git history. Removing local deployment files does not stop or delete
already-provisioned provider resources; those must be reviewed separately.
