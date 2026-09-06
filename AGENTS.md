# SHSMU timetable synchronizer

- Read README.md, PROJECT_STATUS.md and VERIFICATION.md before continuing.
- Authenticated structured school responses are the source of truth. Do not invent endpoints, fields, semester boundaries or stable IDs.
- Preserve normal human login in existing Chrome. Never read browser credentials or change Chrome, extensions or network settings.
- The daily collector is a manually installed bookmark with sequential bounded same-origin GETs and one sanitized JSON download. Start 同步课表.cmd before clicking the bookmark.
- Incomplete fetches must preserve the last complete version. Keep normalized snapshots, stable UIDs and field-level changes.
- Keep personal data, machine configuration, credentials and evidence in ignored directories. Fresh clones intentionally have no personal history.
- Live validation needs a short-range check before the full semester, at least 10 page cross-checks, and a repeat sync without false changes. Report synthetic tests separately.
- Limit changes to the requested scope and keep dependencies small. Do not deploy or alter an existing server unless that server operation is authorized.
- WebCal is optional and represents one private calendar per backend instance. Published service files are deployment references, not a hosted multi-user service.

- Run 检查项目.cmd or python -X utf8 check.py to discover all Python and JavaScript tests, including workflow, usability and WakeUp tests. Bookmark revision 2026-09-06.8 must be manually reinstalled after this update.
- Preserve CRLF bytes in CMD repository blobs for ZIP downloads. Already downloaded files can be selected with 导入已下载课表.cmd or dragged onto 同步课表.cmd; never silently import older files at startup.
- --new-term cannot switch accounts and must preserve history when the scope is unchanged. Optional WakeUp times live in ignored local/wakeup-slots.json and must match every actual event endpoint.


## Student desktop application

- The student entry is `desktop.py`, packaged by `build_desktop.py` as `医学院课表助手.exe`; the desktop UI uses `desktop_service.py` and does not upload to WebCal. Existing CLI upload behavior is preserved.
- Desktop resource files and personal data have separate roots. Frozen resources are read-only; the default user data root is `%LOCALAPPDATA%/SHSMUScheduleAssistant`. Existing histories are reused only through explicit directory selection, never silently migrated or reset.
- Call `import_capture_unlocked` / `export_current_unlocked` only while holding one `exclusive_sync` lock. Cancellation ends before commit; after commit begins, finish it and its export. Do not expose an old CSV as a successful new export.
- Maintain truthful stage labels: browser collection, local save/export, and user-confirmed iPhone import are separate. The GUI cannot detect phone state or verify a bookmark merely because the user acknowledged its instructions.
- Desktop tests run through `check.py`. The bundled `--self-test REPORT` uses isolated synthetic data; it is not school, phone, or clean-machine acceptance. Track candidate release gates in `STUDENT_ACCEPTANCE.md`.

- The first-run student flow asks for the semester only. The verified 2026-27 autumn desktop range includes winter break through 2027-02-21, based on the published spring start of 2027-02-22. Do not infer another term or internship range from this one. Existing ranges change only after the semester action; explicit custom ranges remain unchanged.
- A complete same-account, same-semester superset capture preserves UID aliases, revisions and cancellation history. Do not reset history when extending coverage. WakeUp week count and displayed last class date come from the currently captured courses, not the query cutoff; newly published courses need another sync.
