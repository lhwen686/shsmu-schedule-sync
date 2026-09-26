# SHSMU timetable synchronizer

Use [PROJECT_STATUS.md](PROJECT_STATUS.md#baseline) for version/source-of-truth questions, the [task map](MAINTENANCE.md#task-map) for affected modules and checks, README for student instructions, and VERIFICATION for specific evidence. Read only what the task needs; dated status and old PASS records are not current runtime evidence.

## Maintenance

- For a product fix or release, use the existing [maintenance workflow](MAINTENANCE.md#fix-workflow); do not introduce another tracking system or a multi-agent framework. Small instruction/document edits need only relevant validation and a recoverable diff.
- Confirm the repository, branch, HEAD and existing changes before editing. Follow the source-of-truth boundary in [PROJECT_STATUS.md](PROJECT_STATUS.md#baseline). Never publish private repository history or overwrite unrelated uncommitted files.
- Complete the requested change, relevant checks and fixes for introduced failures. Select checks using [verification gates](MAINTENANCE.md#verification-gates); safe local fixture tests need no step-by-step approval. Preserve release/school/phone gates and distinguish PASS, FAIL and NOT RUN; synthetic or historical evidence cannot prove current live behavior.
- Preserve CRLF bytes in CMD repository blobs and ZIP downloads. Keep the existing `*.cmd -text` attribute; do not globally normalize line endings.

## Data and browser invariants

- Authenticated structured school responses are the source of truth. Never invent endpoints, fields, semester boundaries or stable event IDs. Prefer explicit source dates over recurrence reconstruction.
- Reuse the user's existing normally logged-in browser; the maintainer uses existing Chrome. Never collect passwords, authentication headers, cookies, session storage or browser credentials, or automate browser/profile/extension changes. Do not change proxy, DNS, VPN, hosts, firewall or TLS validation.
- Collection is a manually installed bookmark with sequential, bounded same-origin GETs and one sanitized JSON download. Start the receiver before clicking it. Browser-module changes require regenerating the installer and the user's manual bookmark replacement; daily use requires no Codex browser backend.
- Incomplete collection, missing details or ambiguous identities must preserve the last complete version. Keep sanitized raw responses, normalized snapshots, field changes, stable UIDs, aliases, revisions and cancellation history.
- `--new-term` cannot switch accounts. Each person needs an independent directory without another person's history or upload configuration. Same-scope imports and complete, explicitly permitted same-account/same-semester superset captures preserve history. Never silently import an old download.
- Personal synchronization and evidence review use the existing personal data directory. Fresh clones/worktrees intentionally lack ignored data, configuration and environments; absence is not a school deletion and must not reset UID history.
- Keep personal data, configuration, credentials and evidence in ignored directories. Public releases use an explicit allowlist and clean history; never copy private settings or raw student files into issues, commits, logs or releases.

## Desktop invariants

- `desktop.py` uses `desktop_service.py` and never uploads to WebCal. Preserve optional CLI uploads; the reference backend stores one private calendar per instance and is not a hosted multi-user service.
- Frozen resources are read-only; default data lives in `%LOCALAPPDATA%/SHSMUScheduleAssistant` on Windows and `~/Library/Application Support/SHSMUScheduleAssistant` on macOS. Startup logs and the desktop share this platform path. Reuse existing history only through explicit directory selection, without silent migration or reset.
- Hold one `exclusive_sync` lock for `import_capture_unlocked` and `export_current_unlocked`. Cancellation stops before commit; once commit begins, finish saving and exporting. Never offer an old CSV as a successful new export.
- WakeUp CSV and Apple ICS have independent readiness, errors and phone confirmations. ICS validates the committed snapshot and exact bytes, independently of WakeUp slots. Confirmations bind to the displayed format's file hash.
- Browser collection, local export and user-confirmed phone import are separate stages. A bookmark acknowledgement is not proof of installation; preview and WebCal subscription do not prove Apple Mail attachment import.
- Without a committed timetable, reopening resumes bookmark setup; acknowledgement permits first collection in the current session, and a complete saved timetable enables the update home. Preserve stored acknowledgements and history.
- First-run setup asks for the semester, not a personal last-class date. Apply only verified term presets after explicit semester action; preserve custom/unknown ranges. Current dates belong in PROJECT_STATUS, not permanent rules.
- WakeUp weeks and the displayed last class date come from captured courses; newly published courses require another capture. Validate every event endpoint against actual slot times; optional `local/wakeup-slots.json` follows `wakeup-slots.example.json`. Do not treat the default template as another person's verified timetable.
