---
name: rednote-skills
description: "Use this skill for Xiaohongshu workflows via a shared real Chrome profile: login, draft save, note search/export, profile note listing, and note interactions."
---

# rednote-skill

## Directory structure

```
rednote-skills/
├── scripts/
│   ├── _bootstrap_env.py            # Venv bootstrap helper
│   ├── action_delay.py              # Delay/cooldown management
│   ├── batch_context_comments.py    # Batch comment sending with context
│   ├── batch_dump_notes.py          # Batch export note data (JSON+XLSX) from URL list
│   ├── batch_generate_comment_materials.py  # Generate comment materials from search
│   ├── batch_search_keywords.py     # Batch keyword search
│   ├── browser_profile.py           # Chrome profile management
│   ├── collect_note.py              # Collect/bookmark notes
│   ├── comment_note.py              # Send comments to notes
│   ├── convert_notes_to_xlsx.py     # Convert JSON notes to styled Excel (no browser)
│   ├── dedupe_utils.py              # Shared deduplication utilities
│   ├── dedup_urls.py                # Deduplicate URLs against index (no browser)
│   ├── dump_note.py                 # Export single note (markdown or JSON)
│   ├── export_profile_note_comments.py  # Export profile note comments to Excel/JSON
│   ├── follow_user.py               # Follow users
│   ├── interact_helpers.py          # Helper functions for interactions
│   ├── like_note.py                 # Like notes
│   ├── list_profile_notes.py        # List notes from a user profile
│   ├── manual_login.py              # Manual login helper
│   ├── note_content.py              # Note content extraction utilities
│   ├── official_risk_guard.py       # Risk detection and guard
│   ├── publish_note.py              # Save notes as drafts
│   ├── search_note_by_key_word.py   # Search notes by keyword
│   └── validate_cookies.py          # Cookie/login validation
├── deliveries/                      # Final deliverables
├── logs/rednote/                    # Runtime logs and dedupe indexes
├── tmp/rednote/                     # Temporary or debug files
├── SKILL.md                         # This file
├── README.md                        # Project documentation
└── requirements.txt                 # Python dependencies
```

## Script naming conventions

- `batch_<action>_<target>.py` — Batch operations that process multiple items (e.g., `batch_dump_notes.py`, `batch_search_keywords.py`)
- `<action>_<target>.py` — Single-item operations (e.g., `dump_note.py`, `like_note.py`, `search_note_by_key_word.py`)
- `<descriptor>_utils.py` — Shared utility modules (e.g., `dedupe_utils.py`)
- `<action>_<target>_to_<format>.py` — Format conversion scripts (e.g., `convert_notes_to_xlsx.py`)

Browser scripts launch Chrome; pure data scripts (dedup_urls, convert_notes_to_xlsx) do not.

## Core rules

- Use the shared real Chrome profile through Patchright. Do not switch to a temporary cookie browser.
- Start with the target business script. Do not force `validate_cookies.py` first.
- If a script says `未登录小红书` or asks for `python3 scripts/manual_login.py`, complete manual login and rerun the same script.
- Search, dump, publish, like, collect, follow, and comment must all reuse the same Chrome profile.
- For comment or reply workflows, read the note first, then let AI write the final article-specific text, then send it.
- Never ask Python to rewrite or generate comments. `comment_note.py` only sends the final text you pass in.

## Browser config

Default values:
- Chrome executable: auto-detected
- Chrome source user data dir: `~/Library/Application Support/Google/Chrome`
- Chrome runtime user data dir: `workspace tmp/rednote/chrome-user-data`
- Chrome profile directory: `Profile 2`

Optional overrides:
- `REDNOTE_CHROME_PATH`
- `REDNOTE_CHROME_USER_DATA_DIR`
- `REDNOTE_CHROME_RUNTIME_USER_DATA_DIR`
- `REDNOTE_CHROME_PROFILE_DIRECTORY`

## File creation rules

Directory rules:
- Put final deliverables under `deliveries/`
- Put runtime logs under `logs/rednote/`
- Put temporary or debug files under `tmp/rednote/`
- Do not create business output files under `skills/` or `scripts/`

File type rules:
- Use `.json` for structured machine-readable input or output
- Use `.jsonl` for append-only process logs
- Use `.csv` or `.xlsx` for human review and spreadsheet delivery
- Use `.md` for summaries, handoff notes, or run instructions

Naming rules:
- Prefer lowercase snake_case for stable filenames
- Prefer `YYYYMMDDTHHMMSS` for run-level timestamps, for example `20260403T153000.json`
- Prefer `batch_01_<keyword>.json`, `combined_50.json`, `summary.json` for task outputs when a batch structure exists
- Keep names ASCII when practical; if a Chinese keyword is business-critical, keep it short and stable

Creation rules:
- Default to creating a new timestamped file instead of overwriting an old result
- Only append to log files such as `logs/rednote/*.jsonl`
- Only overwrite an existing file when the command explicitly targets that path and replacement is intentional
- When a task creates a delivery folder, add a short `README.md` if the folder contains multiple result files

Path rules:
- Prefer absolute paths for `--input`, `--output`, and `--output-dir`
- Reuse script default output paths unless the task needs a dedicated delivery folder
- Preserve note URLs exactly when saving records, including `xsec_token` and `xsec_source`

Recommended patterns:
- Batch materials: `logs/rednote/generated_comment_materials/<run_id>.json|csv|xlsx`
- Batch logs: `logs/rednote/batch_search_keywords.jsonl` and `logs/rednote/batch_context_comments.jsonl`
- Profile exports: `deliveries/rednote_profile_comment_sheets/<run_id>.json|xlsx`
- Ad hoc note lists or debug data: `tmp/rednote/<topic>_<date>.json`

## Note dedupe rules

Goal:
- Avoid repeated note capture across runs
- Avoid collecting multiple notes from the same author in the same dedupe scope
- Keep dedupe state persistent and machine-readable

Default storage:
- Use `logs/rednote/note_dedupe_index.json` as the default persistent dedupe index
- If a task needs an isolated dedupe scope, pass a dedicated path with `--dedupe-path`
- Recommended isolated naming: `logs/rednote/note_dedupe_index_<topic>.json`

How to save:
- Save dedupe state as JSON, not JSONL
- Keep one persistent index file per dedupe scope
- Write the dedupe index after a batch run finishes
- Do not mix unrelated campaigns into the same dedupe file unless cross-campaign dedupe is intended

Index shape:
- Top-level fields: `version`, `items`, `authors`
- `items` is keyed by `note_id`
- `authors` is keyed by normalized `author_key`

Recommended item fields:
- `note_id`
- `author_name`
- `author_key`
- `first_seen_at`
- `last_seen_at`
- `source_keyword`
- `last_run_id`
- `status`
- `dedupe_reason`

Recommended author fields:
- `author_key`
- `author_name`
- `first_seen_at`
- `last_seen_at`
- `first_note_id`
- `last_note_id`
- `source_keyword`
- `last_run_id`

How to validate:
1. Parse `note_id` from the candidate note URL before opening the detail page
2. If `note_id` already exists in the persistent index or current-run memory set, skip early as a note duplicate
3. After reading note content, extract the authoritative `note_id` from note data and check again
4. Normalize author name into `author_key` and check author-level duplication
5. Only keep the note when both `note_id` and `author_key` pass validation

Author normalization:
- Build `author_key` from cleaned author nickname
- Normalize with NFKC
- Remove whitespace differences
- Compare case-insensitively
- Treat the normalized `author_key` as the stable author dedupe key

How to dedupe:
- First priority: `note_id`
- Second priority: `author_key`
- If `note_id` is duplicated, skip directly
- If `note_id` is new but `author_key` already exists, skip as `author_duplicate`
- Default policy is strict: one author contributes at most one captured note within one dedupe scope

How to record results:
- Captured notes: write to batch output and update dedupe index with `status: captured`
- Author duplicates found after content read: update dedupe index with `status: skipped` and `dedupe_reason: author_duplicate`
- Note duplicates detected before capture: count as skipped in run summary even if no new item is written
- Run summary should expose at least:
  - `deduped_skipped`
  - `note_id_skipped`
  - `author_skipped`
  - `captured`

Operational rules:
- Never treat note title as a dedupe key
- Never treat keyword as a dedupe key
- Do not save records without a valid `note_id` into the persistent dedupe index
- Preserve the original note URL in exported records, including `xsec_token` and `xsec_source`
- If the business goal requires multiple notes from the same author, use a separate `--dedupe-path` for that task instead of reusing the default global index

## Login flow

Run the business script first. Only login when needed.

```bash
cd rednote-skills
python3 scripts/manual_login.py
```

Optional check:

```bash
cd rednote-skills
python3 scripts/validate_cookies.py
```

- `True`: already logged in
- `False`: run `python3 scripts/manual_login.py`

## Common commands

```bash
cd rednote-skills

# Draft save only
python3 scripts/publish_note.py
python3 scripts/publish_note.py "测试标题" "正文内容" --delay-seconds 5
python3 scripts/publish_note.py "测试｜图文混排" $'第一段\n\n[[image:/absolute/path/to/a.jpg]]\n\n第二段' --delay-seconds 5

# Search / export
python3 scripts/search_note_by_key_word.py "关键词" --top_n 5 --delay-seconds 3
python3 scripts/search_note_by_key_word.py "关键词" --start-index 21 --end-index 40 --filter '{"sort_by":"最新","note_type":"图文"}' --delay-seconds 3
python3 scripts/batch_search_keywords.py --input /absolute/path/to/keywords.json --top-n 5 --delay-seconds 3
python3 scripts/batch_generate_comment_materials.py --input /absolute/path/to/keywords.json --top-n 5 --delay-seconds 3 --dedupe-path logs/rednote/note_dedupe_index.json
python3 scripts/list_profile_notes.py --profile-url "https://www.xiaohongshu.com/user/profile/<user_id>" --output /absolute/path/to/profile_notes.json
python3 scripts/list_profile_notes.py --user-id "<user_id>" --limit 0 --delay-seconds 3
python3 scripts/dump_note.py "<note_url>"
python3 scripts/dump_note.py "<note_url>" --format json
python3 scripts/dump_note.py "<note_url>" --format json --output /absolute/path/to/note.json

# Deduplicate URLs (pure data, no browser)
python3 scripts/dedup_urls.py --input /absolute/path/to/urls.json --output /absolute/path/to/unique_urls.json
python3 scripts/dedup_urls.py --input /absolute/path/to/urls.json --dedupe-path logs/rednote/note_dedupe_index_<topic>.json --update-index
python3 scripts/dedup_urls.py --input /absolute/path/to/urls.json --dry-run

# Batch export notes (browser required)
python3 scripts/batch_dump_notes.py --input /absolute/path/to/urls.json --output-dir deliveries/bid_notes --dedupe-path logs/rednote/note_dedupe_index.json --limit 30 --delay-seconds 3
python3 scripts/batch_dump_notes.py --input /absolute/path/to/urls.json --dry-run

# Convert JSON notes to Excel (pure data, no browser)
python3 scripts/convert_notes_to_xlsx.py --input /absolute/path/to/notes.json --output /absolute/path/to/summary.xlsx
python3 scripts/convert_notes_to_xlsx.py --input /absolute/path/to/notes.json --output /absolute/path/to/summary.xlsx --columns "title,nickname,note_url,tags,desc,publish_time,liked_count"

# Export profile note comments
python3 scripts/export_profile_note_comments.py --profile-url "https://www.xiaohongshu.com/user/profile/<user_id>" --output-dir deliveries/rednote_profile_comment_sheets
python3 scripts/export_profile_note_comments.py --input /absolute/path/to/profile_notes.json --limit 10

# Interactions
python3 scripts/like_note.py "<note_url>" --delay-seconds 5
python3 scripts/collect_note.py "<note_url>" --delay-seconds 5
python3 scripts/follow_user.py "<note_url>" --delay-seconds 5
python3 scripts/comment_note.py "<note_url>" "<final_comment>" --delay-seconds 5 --like-probability 0.35
python3 scripts/batch_context_comments.py --input /absolute/path/to/comments.json --delay-seconds 5 --like-probability 0.35
```

## Publish rules

- `publish_note.py` saves to drafts only. It does not publish.
- Body supports inline image placeholders: `[[image:/absolute/path/to/file]]`
- Keep image paths absolute for reliability.
- The browser stays open after draft save for manual review.

## Search rules

- `search_note_by_key_word.py` returns a Python list of note URLs.
- Use `--top_n` for the first N results.
- Use `--start-index` and `--end-index` for waterfall ranges.
- Use `--max-scroll-rounds` and `--max-idle-scroll-rounds` when you need a deeper range.
- `--filter '<json>'` supports:
  - `sort_by`: `综合` / `最新` / `最多点赞` / `最多评论` / `最多收藏`
  - `note_type`: `不限` / `视频` / `图文`
  - `publish_time`: `不限` / `一天内` / `一周内` / `半年内`
  - `search_scope`: `不限` / `已看过` / `未看过` / `已关注`
  - `position_distance`: `不限` / `同城` / `附近`
- Filter aliases also work: `sort`, `location_distance`, `location`, `排序方式`, `笔记类型`, `发布时间`, `搜索范围`, `位置距离`
- Preserve `xsec_token` and `xsec_source` in note URLs for follow-up scripts.

## Profile note listing

- `list_profile_notes.py` accepts either `--profile-url` or `--user-id`
- `--limit 0` means collect as many notes as the page exposes
- Output JSON includes `profile_url`, `count`, and `notes`
- Each note includes `id`, `xsec_token`, `xsec_source`, `note_url`, `title`, `cover`

## Batch search input

`batch_search_keywords.py` supports:
- JSON array of keywords: `["关键词A", "关键词B"]`
- JSON array of objects: `[{"keyword": "关键词A", "top_n": 5}]`
- JSON object with `items`: `{"items": [{"keyword": "关键词A", "top_n": 5}]}`
- JSON mapping: `{"关键词A": 5, "关键词B": {"top_n": 8}}`

Per item fields:
- `keyword`
- `top_n`
- `start_index`
- `end_index`
- `max_scroll_rounds`
- `max_idle_scroll_rounds`
- `delay_seconds`
- `filter`
- `meta`

Rules:
- CLI `--filter` is supported
- Root-level `filter` is supported for `{"items": [...]}` input
- Merge order: CLI `--filter` < root `filter` < item `filter`
- Use `--dry-run` to validate input without launching searches
- Logs default to `logs/rednote/batch_search_keywords.jsonl`

## Comment workflow

Required order:
1. Run `python3 scripts/dump_note.py "<note_url>"`
2. Let AI write the final comment based on the actual note content
3. Run `python3 scripts/comment_note.py "<note_url>" "<final_comment>" --delay-seconds 5`

Hard rules:
- Never send generic template comments.
- Comments must be grounded in the current note's title,正文细节、标签、表达方式、情绪或观点.
- Reply comments must also be article-specific and consistent with the original comment context.
- `comment_note.py` only sends the final comment text it receives.
- `--like-probability <0-1>` or `REDNOTE_COMMENT_AUTO_LIKE_PROBABILITY` controls optional pre-like behavior. Default: `0.35`

## Batch comment workflow

Required order:
1. Run `python3 scripts/batch_generate_comment_materials.py ...`
2. Let AI read the exported materials and prepare `/absolute/path/to/comments.json`
3. Run `python3 scripts/batch_context_comments.py --input /absolute/path/to/comments.json --delay-seconds 5 --like-probability 0.35`

Rules:
- `batch_generate_comment_materials.py` only exports materials. It does not send comments.
- Exported files default to `logs/rednote/generated_comment_materials/<run_id>.json|csv|xlsx`
- `comment_info` and `reply_comment_info` are placeholders for later AI-written drafts
- `batch_context_comments.py` does not search notes or generate copy
- Each record must map one `note_url` to one final `comment_text`
- Do not batch-send generic praise or filler copy
- Use `--dry-run` to validate input without posting
- Logs default to `logs/rednote/batch_context_comments.jsonl`

Supported `comments.json` forms:
- JSON array: `[{"note_url": "...", "comment_text": "..."}]`
- JSON object with `items`: `{"items": [{"note_url": "...", "comment_text": "..."}]}`
- JSON mapping: `{"https://.../explore/...": "评论内容"}`

Optional per-row fields:
- `delay_seconds`
- `like_probability`
- `meta`

## Delay rules

- Sensitive scripts accept `--delay-seconds <seconds>`
- Shared default delay can be set with `REDNOTE_ACTION_DELAY_SECONDS`
- Random delay range can be adjusted with:
  - `REDNOTE_RANDOM_DELAY_MIN_SECONDS`
  - `REDNOTE_RANDOM_DELAY_MAX_SECONDS`

## Notes

- The search script can bootstrap the skill-local virtualenv automatically.
- If a note needs candidate images, use the sibling skill `skills/rednote-image-search` first.
