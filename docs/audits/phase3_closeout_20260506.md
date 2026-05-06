# Phase 3 closeout — prompt assembly hardening

| Field | Value |
|---|---|
| Date | 2026-05-06 |
| Branch | `pixAI` |
| Phase 3 commit | `0685380` — prompt logging, token budget, tag validity, weight ordering, booster gate |
| Predecessor | `becc8cc` (Phase 2 closeout) |
| Auditor | Claude Code (Opus 4.7, 1M context) — auto-mode session |
| Status | Permanent reference — do not modify after commit |

---

## 1. What shipped

### 3.1 + 3.2 Assembled-request logging + token-budget warnings

- `app/pipeline/stages.py`:
  - Imports hoisted to the top (was a fragile mid-file second block hidden under prose comments).
  - `RUNS_ROOT = repo_root / "runs"` (gitignored).
  - New `_log_assembled_request(run_id, stage, params_dict, extra=None)` helper writes the assembled `createGenerationTask` payload to `runs/<run_id>/stage_<n>_request.json`, plus a manifest line to `runs/<run_id>/manifest.jsonl` carrying `ts`, `stage`, `token_count_positive`, `budget_warnings`, `unknown_booru_tags`, `request_file`, and any extra metadata (e.g. Stage 3 records the LoRA `architecture`).
  - First call per session also prints a one-shot stdout summary so an interactive operator can sanity-check parameters without opening JSON files.
  - All three `stage_*_*` functions accept `run_id: str | None = None` and call the logger before the PixAI mutation.
- `app/pipeline/orchestrator.py`:
  - Initial run uses `run_id = scene_id`. Auto-regen iterations use `run_id = "<scene_id>_iter_<n>"`. Each iteration's manifest is therefore separate.

Token budget thresholds (soft — runs continue, warning lands in manifest):

| Stage | Hard cap | Ideal range |
|---|---|---|
| 1 | 12 | 1–12 |
| 2 | 20 | 1–20 |
| 3 | 50 | 30–40 |

### 3.3 Tag validity check

- `app/pixai/tag_validator.py` (new): `download_danbooru_tags()`, `load_cache()`, `positive_prompt_tokens()`, `validate_tokens()`, `seed_cache_for_tests()`. Booru-shape regex (`^[a-z0-9_]+$`) so natural-language clauses (`"broader shoulders"`) and `(token:weight)` syntax aren't false-flagged. Empty/missing cache returns empty unknown-list — no spurious warnings when offline.
- `scripts/download_danbooru_tags.py` (new): CLI wrapper. Downloads top-N tags from `danbooru.donmai.us/tags.json` ordered by post_count desc.
- `data/danbooru_tags.csv`: gitignored (regenerable cache). Populated this session: 100,000 tags / 2.0 MB / 44.5s download time.
- Validation results are surfaced into the run manifest's `unknown_booru_tags` list — log-only, never modifies the prompt.

### 3.4 Token weight ordering in Stage 3 prompts

- `app/claude/prompts.py` `_SYSTEM`: appended an explicit STAGE 3 TOKEN ORDER AND WEIGHTING block enforcing:
  1. Trigger words (verbatim, never re-weighted)
  2. Subject anchor
  3. View tag
  4. Pose tag
  5. Anatomy / proportion
  6. Hair tags
  7. Face / skin tags
  8. Outfit — main garments `(token:1.2)`, accessories `(token:1.3)`
  9. Style boosters `(token:0.9)`
  10. Quality tags
- The system prompt explicitly states *why* (outfit fidelity drift is the #1 failure mode for character LoRAs; up-weighting accessories ensures attention concentrates on character identity tokens before style).
- DiT.2 architecture note appended explaining that emitted negatives are discarded by the post-processor.

### 3.5 Booster / qualityTag gate

- `app/pixai/models.py`:
  - `TaskParameters.allow_booster: bool = False` (new field).
  - `to_pixai_dict()` — when `quality_tag is not None and allow_booster is False`, the `qualityTag` is dropped from the request payload and a `UserWarning` is emitted. `qualityTag` only reaches PixAI when the caller explicitly sets `allow_booster=True`.
- All three real stages keep `quality_tag=None` so this is defense-in-depth: never silent send.

### 3.6 Tests

- `tests/test_phase3.py` (new): 14 tests covering booster gate (3), tag validator (5), assembled-request logging + token budgets (6).

**Test suite at end of Phase 3: 74 passed, 0 failed, 0 skipped, 2 expected warnings.**

---

## 2. State at end of Phase 3

- Branch tip: `0685380`, pushed to `origin/pixAI`.
- Auto-mode log committed at `d92bf0d` (initial) — final summary update pending in the closing commit of this session.
- Test suite green: 74/74.
- Phase 4 is **NOT** running in this auto-mode session — it requires real PixAI generation calls and the Faye-Lyn LoRA id (D4) is still unresolved.
- One network call was made during Phase 3: the read-only Danbooru tag list fetch (anonymous, public API, 44.5s, 100k tags). No PixAI generation calls.

---

## 3. Phase 4 readiness

Phase 4 (benchmark suite) requires:

- D4 — Faye-Lyn character LoRA's PixAI model id, registered via `loras.register(...)` so Stage 3 can resolve it.
- Optional: Kero's reply on D2 (IP-Adapter / Reference-Only) — without it, Stage 3 reference-image conditioning is held at "carried in sheet, not sent to API". Phase 4 can run with this constraint and benchmark against current pipeline shape; later iteration after Kero replies will re-benchmark with reference-image conditioning enabled.
- The Phase 4 benchmark suite itself (6 reference generations × old vs new pipeline + structured critique scoring) is **not yet implemented**. It's spec'd in the original prompt but auto-mode session stopped before it per the no-Phase-4 guardrail.

The first thing to do when D4 is supplied: run `scripts/preview_phase1b_params.py` swapping the synthetic Faye-Lyn LoRA for the real registered one, verify the assembled Stage 3 dict, and only then schedule a real benchmark run.
