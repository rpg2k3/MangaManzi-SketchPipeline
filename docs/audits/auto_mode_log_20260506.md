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

---

## STATE WHEN USER RETURNS

(populated at session end)
