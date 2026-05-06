# Auto-mode log — 2026-05-06

| Field | Value |
|---|---|
| Branch | `pixAI` |
| Session start | 2026-05-06T08:02:00Z |
| Mode | Auto (no confirmation gates between sub-tasks) |
| Scope | Phase 2 + Phase 3 + Kero email draft |
| Hard guardrails | No PixAI generation calls. No invented API fields. No force pushes. Push after each phase commit. Log all blocks; continue past them. |
| Phase 1 closeout | `1d705bd` (origin/pixAI) |
| Phase 0 audit | `78a6a3c` (origin/pixAI) |

---

## Work log

### 2026-05-06T08:02:00Z — auto-mode session started
- Empty log shell committed at `d92bf0d`, pushed to `origin/pixAI`.
- Tree clean. Phase 1 closeout `1d705bd` is the predecessor commit.

### 2026-05-06T08:05:00Z — Phase 2.1 — Outfit consistency check (started)
- Reading existing critique infrastructure: `app/claude/critique.py`, `app/critique/engine.py`, `app/critique/learning.py`, `app/critique/history.py`. `learning.promote_recurring_drifts()` already exists for cross-scene drift escalation; will add a sibling for consecutive in-scene drifts in 2.2.
- Plan: extend `critique_image()` with optional `reference_image_path` (carries the canonical Design_A image as a second Claude vision block) and add the structured `outfit_consistency` field to the tool schema (boots/hosiery/belt/skirt/arm-coverage/added-elements). Engine wrapper resolves the reference path from `sheet.referenceAnchors[0].path` against the repo root.

### 2026-05-06T08:30:00Z — Phase 2.1–2.5 — Implementation complete
- `app/claude/critique.py`: added `_OUTFIT_CONSISTENCY_SCHEMA` (boot_silhouette / hosiery / belt / skirt / arm_coverage / added_elements_not_on_reference); `critique_image()` now accepts `reference_image_path`; deep-copies the schema and adds `outfit_consistency` to its `required` list only when a reference image is present (so Claude can't be forced to fill it without seeing the canonical design).
- `app/critique/engine.py`: new `_resolve_reference_path(sheet)` resolves `sheet.referenceAnchors[0].path` against repo root, gracefully returning `None` if the anchor is missing or the file isn't on disk. `run_critique` forwards the resolved path.
- `app/pipeline/stages.py`: `stage_4_critique` now delegates to `app.critique.engine.run_critique` instead of calling `critique_image` directly — single source of truth for reference-path resolution.
- `app/critique/learning.py`: new `promote_consecutive_drifts(sheet_id, scene_id, threshold, *, source_run_ids)` — when the same drift `aspect` recurs in N consecutive iterations of one scene, promotes to `sheet.learnedDrifts` with `promotedAt` ISO timestamp, `sourceRunIds`, last-seen example, and `origin: "consecutive_in_scene"`. Idempotent. Excludes manual-feedback drifts.
- `app/pipeline/orchestrator.py`: PipelineRequest gains `max_iterations: int = 3` and `drift_severity_threshold: str = "high"`. PipelineResult gains `iterations: list[dict]` and `promoted_drifts: list[dict]`. Auto-regen loop after the initial Stage 4: re-runs Stage 3 only (S1+S2 are pose-locked) up to `max_iterations` times with prior critiques bundled, breaking early when no drift hits the threshold. Each iteration writes to `out_dir / "iter_<n>"` and appends to per-scene history. After the loop, calls `promote_consecutive_drifts`. Severity ladder helper (`_normalize_severity`) maps `"high" → "major"` so the user-facing threshold string is friendly.
- New test files: `tests/test_critique_outfit.py` (6 tests covering reference-image plumbing + schema shape).
- Extended `tests/test_critique_history.py` with 4 consecutive-drift tests (basic, all-in-iters, manual-excluded, short-history-no-op).
- Extended `tests/test_pipeline.py` with 4 auto-regen tests (cap, clean-break, max_iterations=1 disabled, threshold below drift skips re-roll). New `stateful_patched_claude` fixture lets tests flip the critique payload mid-run.
- Test suite: **60 passed, 0 failed, 0 skipped, 2 expected warnings**.

### 2026-05-06T08:32:00Z — Phase 2.4 — IP-Adapter / Reference-Only discovery: BLOCKED
- Schema introspection is disabled on PixAI's Apollo server (re-confirmed from Phase 0).
- The codebase exposes no `model(id:)`, `controlNetTypes`, or similar metadata query.
- The only way to probe ControlNet type strings is to send a `createGenerationTask` mutation, which is a generation call and forbidden by the auto-mode guardrails.
- **Confirmed deferred to D2** (already tracked in Phase 1 closeout). Resolution path: Kero email follow-up (drafted in this session) asking explicitly which preprocessor types the API exposes for reference-image content conditioning.
- **No code changes** under Phase 2.4. No invented API fields per guardrail.

### 2026-05-06T08:38:00Z — Phase 2 commit
- `becc8cc` (origin/pixAI). 10 files changed, 904 insertions(+), 42 deletions(-).
- 60 tests passing.

### 2026-05-06T08:40:00Z — Phase 3 — starting
Plan order (independent edges first to keep commits clean):
1. Booster gate in TaskParameters (`allow_booster=True` required to include `qualityTag`).
2. Tag-validator module — best-effort Danbooru download, graceful fallback, cache to data/danbooru_tags.csv.
3. Stage 3 token weight ordering rules in `_SYSTEM` prompt.
4. Assembled-request logging — stages write `runs/<run_id>/stage_<n>_request.json` before each PixAI call; first per-session also goes to stdout.
5. Token budget warnings written into `runs/<run_id>/manifest.json`.
6. Tests for all of the above.

### 2026-05-06T11:14:00Z — Phase 3.3 Danbooru tag cache populated
- Successfully downloaded **100,000 Danbooru tags** (sorted by `post_count` desc) in 44.5s via `app.pixai.tag_validator.download_danbooru_tags()`.
- Cache written to `data/danbooru_tags.csv` (2.0 MB, 100,001 lines including header).
- Cache file is gitignored — regenerable any time via `scripts/download_danbooru_tags.py`.

### 2026-05-06T11:30:00Z — Phase 3 — implementation complete
- `app/pixai/models.py`: `TaskParameters.allow_booster: bool = False` added. `to_pixai_dict()` drops `qualityTag` and emits a `UserWarning` when `quality_tag is not None and allow_booster is False`. The three real stages keep `quality_tag=None` so this is purely a defense against accidental Booster injection.
- `app/pixai/tag_validator.py`: new module — `download_danbooru_tags()`, `load_cache()`, `validate_tokens()`, `seed_cache_for_tests()`. Booru-shape regex (`^[a-z0-9_]+$`) so natural-language clauses and `(token:weight)` syntax are passed through without false alarms. Cache miss returns empty unknown-list (no spurious warnings when offline).
- `scripts/download_danbooru_tags.py`: CLI wrapper for cache rebuild.
- `app/claude/prompts.py`: `_SYSTEM` extended with the Stage 3 token-order-and-weighting rules — trigger words → subject → view → pose → anatomy → hair → face/skin → outfit (main `(token:1.2)`, accessories `(token:1.3)`) → style boosters `(token:0.9)` → quality tags. Plus a DiT.2 architecture note explaining that emitted negatives are discarded post-process.
- `app/pipeline/stages.py`: imports hoisted to the top (was a fragile mid-file second block). `RUNS_ROOT = repo/runs/`. New `_log_assembled_request(run_id, stage, params_dict, extra=None)` helper writes the assembled payload to `runs/<run_id>/stage_<n>_request.json` and a manifest line to `runs/<run_id>/manifest.jsonl` carrying `token_count_positive`, `budget_warnings`, `unknown_booru_tags`, `request_file`. First call per session also prints a one-shot stdout summary so an interactive operator can sanity-check without opening files. `run_id` is plumbed through all three stages and the orchestrator (initial_run_id = scene_id; iter_run_id = `<scene_id>_iter_<n>`).
- Token budgets: Stage 1 hard cap 12, Stage 2 hard cap 20, Stage 3 hard cap 50 (ideal range 30–40). All warnings are SOFT — runs proceed; warning lands in manifest.
- `runs/` dir added to `.gitignore` (per-run debug artifacts, not source).
- `tests/test_phase3.py`: 14 new tests covering booster gate (3), tag validator (5), assembled-request logging + token budgets (6).
- Test suite: **74 passed, 0 failed, 0 skipped, 2 expected warnings**.

---

## STATE WHEN USER RETURNS

(populated at session end)
