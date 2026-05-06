# Phase 2 closeout — drift suppression and reference anchoring

| Field | Value |
|---|---|
| Date | 2026-05-06 |
| Branch | `pixAI` |
| Phase 2 commit | `becc8cc` — outfit critique, drift escalation, auto-regenerate loop, IP-Adapter discovery |
| Predecessor | `1d705bd` (Phase 1 closeout) |
| Auditor | Claude Code (Opus 4.7, 1M context) — auto-mode session |
| Status | Permanent reference — do not modify after commit |

---

## 1. What shipped

### 2.1 Outfit consistency check in Stage 4 critique

- `app/claude/critique.py`:
  - New `_OUTFIT_CONSISTENCY_SCHEMA` covering boot_silhouette (height/sole/closure/matches_reference), hosiery (type/matches_reference), belt (chain_present/charm_shape/charm_position/matches_reference), skirt (cut/length/matches_reference), arm_coverage (type/matches_reference), and `added_elements_not_on_reference` (free-text array for things present on the generation but absent from the canonical reference).
  - `critique_image()` accepts an optional `reference_image_path`. When supplied, Claude receives a second image block ("Image 1 — canonical reference") alongside the generated image ("Image 2 — generated output"). The tool schema is deep-copied per call and `outfit_consistency` is added to its `required` list — Claude must fill it when a reference is present, but cannot be forced to fill it without seeing the canonical design.
- `app/critique/engine.py`:
  - New `_resolve_reference_path(sheet)` reads `sheet.referenceAnchors[0].path`, resolves repo-root-relative, and returns `None` if the anchor is missing or the file is not on disk. Half-configured sheets cannot raise mid-run.
  - `run_critique()` forwards the resolved path into `critique_image`.
- `app/pipeline/stages.py`:
  - `stage_4_critique` now delegates to `app.critique.engine.run_critique` so reference-path resolution lives in one place.

The structured `outfit_consistency` field is automatically carried into the auto-regen loop's `prior_critiques` bundle (passed through `app/pipeline/orchestrator._build_prior_critiques_bundle`), so Claude sees previous outfit-mismatch reports when composing the corrected positive prompt.

### 2.2 Drift escalation (consecutive in-scene)

- `app/critique/learning.py`:
  - New `promote_consecutive_drifts(sheet_id, scene_id, threshold, *, source_run_ids)`. When the same drift `aspect` appears in `threshold` consecutive iterations of one scene, promotes to `sheet.learnedDrifts` with `promotedAt` ISO timestamp, `sourceRunIds` list, last-seen example, and `origin: "consecutive_in_scene"`. Idempotent (doesn't re-promote already-learned aspects). Excludes `origin == "manual"` drifts (those carry user-specific guidance, not a model-failure signal).
- `app/critique/__init__.py`:
  - Added export.

This complements the existing cross-scene `promote_recurring_drifts` (which fires when a drift recurs in `threshold` distinct scenes). Both feed the same `learnedDrifts` field with the same idempotency contract.

### 2.3 Auto-regenerate loop

- `app/pipeline/orchestrator.py`:
  - `PipelineRequest` gains `max_iterations: int = 3` and `drift_severity_threshold: str = "high"`.
  - `PipelineResult` gains `iterations: list[dict]` and `promoted_drifts: list[dict]`.
  - After the initial Stage 4, if drifts at or above the threshold remain, Stage 3 is re-rolled (S1+S2 are pose-locked and stable) up to `max_iterations` total times. Each re-roll uses prior critiques (from per-scene history) bundled into `generate_prompt(prior_critiques=...)`. Iterations write to `out_dir / "iter_<n>" /` and append to `app.critique.history` — so Phase 3's logging and the `promote_consecutive_drifts` call see them.
  - Severity ladder helper `_normalize_severity()` maps user-facing strings (`"high"`, `"low"`, etc.) to the schema's enum (`major`, `minor`).
  - After the loop, `promote_consecutive_drifts` runs with `threshold=max_iterations` so a stubborn drift inside one regen loop bubbles into the sheet for future scenes.

### 2.4 IP-Adapter / Reference-Only discovery — BLOCKED

Schema introspection is disabled on PixAI's Apollo server (re-confirmed from Phase 0). The codebase exposes no `model(id:)`, `controlNetTypes`, or similar metadata query. The only path to probe ControlNet type strings runtime-style would be a `createGenerationTask` mutation, which is forbidden by auto-mode guardrails.

**Confirmed deferred to D2.** Resolution path: Kero email follow-up drafted in this session (see `docs/correspondence/kero_phase2_followup_20260506.md`).

### 2.5 Tests

- `tests/test_critique_outfit.py` (new): 6 tests covering optional vs required `outfit_consistency`, two-image-block plumbing, missing-reference fallback, engine path resolution, and schema shape lock.
- `tests/test_critique_history.py` (extended): 4 new tests for `promote_consecutive_drifts` (basic, all-in-iterations, manual-excluded, short-history no-op).
- `tests/test_pipeline.py` (extended): 4 new auto-regen tests (cap, clean-critique-breaks-loop, max_iterations=1 disables loop, threshold-below-drift skips re-roll). New `stateful_patched_claude` fixture lets tests flip the critique payload mid-run.

**Test suite at end of Phase 2: 60 passed, 0 failed, 0 skipped, 2 expected warnings.**

---

## 2. What did NOT ship in Phase 2

| Deferred | Why | Owner |
|---|---|---|
| IP-Adapter / Reference-Only ControlNet integration | API surface unknown; no probe path without generation calls (forbidden) | D2 — Kero email |
| Stage 3 reference-image conditioning at weight 0.55/0.5 | Same — no API surface to send the reference into | D2 — Kero email |
| ControlNet end-timing (`controlEnd: 0.85`) | No field exposed in current GraphQL schema | D1 — separate Kero email later |

---

## 3. State at end of Phase 2

- Branch tip: `becc8cc`, pushed to `origin/pixAI`.
- Test suite green: 60/60.
- Pipeline runnable end-to-end against live PixAI is still gated on D4 (Faye-Lyn LoRA id supply) — unchanged from end of Phase 1.
- Auto-regen loop is exercised in tests via the mock harness; the live behavior is verified only when D4 lands.
- No PixAI generation calls were made during Phase 2 implementation or testing.
