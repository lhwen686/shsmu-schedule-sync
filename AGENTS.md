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

- Run 检查项目.cmd or python -X utf8 check.py to discover all Python and JavaScript tests, including workflow and WakeUp tests. Bookmark revision 2026-09-06.5 must be manually reinstalled after this update.
