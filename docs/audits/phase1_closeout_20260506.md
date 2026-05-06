# Phase 1 closeout — pixAI pipeline upgrade log

| Field | Value |
|---|---|
| Date | 2026-05-06 |
| Branch | `pixAI` |
| Phase 1A commit | `658cd7c` — schema migration, faye_lyn sheet stub, sketch_lora removal |
| Phase 1B commit | `a1604e0` — faye_lyn content, per-stage parameter baselines, Stage 2 restructure, ControlNet weight taper |
| Phase 1C commit | `92aacea` — negative prompt hardening, DiT.2 vs SDXL handling, dead code removal |
| Auditor | Claude Code (Opus 4.7, 1M context) |
| Status | Permanent reference — do not modify after commit |

This file is a permanent reference. Phase 2+ diffs against it.

---

## 1. What shipped

### Phase 1A — schema + B1 unblock + Faye-Lyn stub

- `LoRA.architecture` enum (`sdxl, illustrious, dit1, dit2, unknown`); 9k9base set to `illustrious`; `loras.get()` emits a one-shot warning when fetching a LoRA whose architecture is `unknown`.
- Sheet schema: `triggerWords` default `None → []`, `loraWeight` default `1.0 → 0.75`, new `referenceAnchors []`. `upgrade_sheet` remains idempotent.
- B1 unblocked: `loras.get("sketch_lora")` removed from `stage_2_sketch_pass`. Placeholder pass-through bridged Phase 1A → 1B.
- B2 unblocked: `data/sheets/faye_lyn.json` stub with the four pre-seeded `learnedDrifts` (`sourceRunIds: ["pre-audit"]`).
- `.gitignore` exception added for the canonical Faye-Lyn sheet (other sheets stay local).

### Phase 1B — Faye-Lyn content + per-stage parameter baselines

Faye-Lyn sheet content populated:

- `designNotes`: full canonical description (kemonomimi cat-girl, dark skin, magenta afro, 7.5 head heights, punk-arcade glitch aesthetic).
- `continuityRules`: 10 entries locking hair color / cat ear shape / tail shape / skin tone / eye color / face style / boot silhouette / belt accessories / fishnet density / garter strap policy.
- `outfitVariants`: 1 default — `Design_A_default`, with 15 booru tags for the canonical street outfit.

Per-stage parameter baselines applied (verified via `scripts/preview_phase1b_params.py` — no PixAI calls):

| Field | Stage 1 | Stage 2 | Stage 3 |
|---|---|---|---|
| Mode | txt2img | img2img | img2img |
| Width × Height | 832×1216 | 832×1216 | 832×1216 |
| Sampler | DPM++ 2M Karras | DPM++ 2M Karras | DPM++ 2M Karras |
| Steps | 26 | 24 | 28 |
| CFG | 6.0 | 5.5 | 6.5 |
| `clipSkip` | 2 | 2 | 2 |
| Strength (denoise) | – | 0.40 | 0.60 |
| LoRA stack | 9k9base @ 0.9 | (none) | char LoRA @ sheet.loraWeight |
| ControlNet | optional skeleton/depth | openpose @ 0.85, depth @ 0.55 (from S1) | openpose @ 0.7, depth @ 0.5 (from S2) |
| `qualityTag` | omitted | omitted | omitted |
| `priority` | omitted unless `high_priority=True` | same | same |

Plus:

- `9k9base.weight` `1.0 → 0.9` in the registry.
- `loras.find_by_pixai_id()` helper added for Stage 3's reverse lookup from `sheet.linkedLoraId`.
- Stage 3 fail-fast on missing/unregistered `linkedLoraId` with a clear error pointing the user at `loras.register()`.
- `scripts/preview_phase1b_params.py` for re-running parameter inspection any time.

### Phase 1C — negative-prompt hardening + DiT.2 / SDXL fork + dead-code removal

Stage 1 negative — **14-token underscored** form (replaces 12-token space-separated):

```
nsfw, worst_quality, bad_quality, low_quality, lowres, bad_anatomy,
multiple_figures, clothing, hair, face_features, shading,
finished_illustration, color, photo_realistic
```

(`face_features` replaces ambiguous `face`; `finished_illustration`, `color`, and `photo_realistic` keep the LoRA's flat-pencil aesthetic.)

Stage 2 negative — **6-token short template** via `_STAGE_2_NEGATIVE` in `stages.py`:

```
worst_quality, bad_quality, photo_realistic, finished_illustration, color, multiple_figures
```

(Stage 2 no longer leaks the Stage 1 negative — construction-style suppression is irrelevant once we already have a clean Stage 1 mannequin.)

Stage 3 negative — **architecture-forked builder** in `app/claude/prompts.py:_apply_architecture_handling()`:

- `architecture == "dit2"` — negative cleared to `""`; `learnedDrifts.correction` fields appended to the positive prompt as re-specifications.
- `architecture in {"sdxl", "illustrious"}` — Claude's negative is discarded and replaced with the deterministic SDXL template (`worst_quality, bad_quality, very_displeasing, displeasing, oldest, artistic_error, lowres, jpeg_artifacts, censor, watermark, bad_hands, bad_anatomy`) plus `learnedDrifts.drift` fields appended as comma-separated absences.
- `architecture == "unknown"` — one-shot warning, fall back to SDXL behavior (safer than DiT.2 positive-only since it adds a negative prompt rather than relying on positive re-specification only).

Stage 3 in `stages.py` reads `char_lora.architecture` and forwards it into `generate_prompt`. The post-processor runs only for `stage >= 3`.

Dead code removed:

- `_POS_9K9BASE` constant in `registry.py` — Stage 1 prompt assembly never used it; "blueprint style / technical drawing" tokens were pulling toward architectural diagrams. Stage 1 docstring updated to drop the stale `positive_append` step.
- `sketch_lora_registered` test fixture — last consumer (`test_stage_2_requires_sketch_lora`) deleted in this commit.

### Tests

- 47 collected, **46 passed, 0 skipped, 2 expected warnings** (`architecture=unknown` warnings firing as designed in tests that intentionally don't set it).
- The three Phase-1A skips are all resolved:
  - `test_stage_2_attaches_controlnet_from_base_media_id` → renamed and rewritten as `test_stage_2_pure_img2img_with_tapered_controlnet`. Asserts no LoRA, openpose @ 0.85, depth @ 0.55, CFG 5.5, steps 24, strength 0.40, and the new short Stage 2 negative.
  - `test_stage_2_requires_sketch_lora` → **deleted** (sketch_lora is gone for good).
  - `test_full_pipeline_end_to_end_mocked` → unskipped and rewritten against the Phase 1B/1C contract: 3 `createGenerationTask` calls, Stage 2 tapered ControlNet, Stage 3 SDXL template (the `char_lora_registered` fixture uses `architecture="illustrious"`).
- New `char_lora_registered` fixture for any test exercising Stage 3.

---

## 2. Deferred items

| # | Item | Where flagged | Owner |
|---|---|---|---|
| D1 | ControlNet end-timing (`end at 0.85` guidance-end) — no field exposed in PixAI's GraphQL schema | `stages.py` Stage 3 docstring | Phase 2 discovery + Kero follow-up email |
| D2 | Reference-image conditioning (IP-Adapter Plus @ 0.55 / Reference-Only ControlNet @ 0.5) — neither type string documented in `ControlNetSpec.type`'s accepted set; `sheet.referenceAnchors` is carried through but not read by any API call yet | `stages.py` Stage 3 docstring | Phase 2 discovery + Kero follow-up email |
| D3 | Stage 2 with 9k9base @ 0.5 fallback if construction-style drift appears at Stage 2 — per-Phase-1B clarification this is conditional on Phase 4 benchmark observations; not implemented | conversation record | Phase 4 |
| D4 | Faye-Lyn character LoRA `linkedLoraId` is still `null` on the sheet — Stage 3 will fail-fast until the user supplies the PixAI id and registers the LoRA via `loras.register(...)` | `data/sheets/faye_lyn.json` | user-supplied (out-of-band) |
| D5 | Token-weight ordering (`(token:1.2)` etc.) and prompt-assembler logging (`runs/<run_id>/assembled_request.json`) | Phase 0 gap analysis Q6 / Q12 | Phase 3 |
| D6 | Critique → regenerate auto-loop in the orchestrator | Phase 0 gap analysis Q10 — `regenerate.py` exists but no caller | Phase 2 |
| D7 | Booru whitelist expansion + Danbooru tag-list cache (`data/danbooru_tags.csv` top 100k by post count) + tag-validity check | Phase 0 gap analysis Q5 | Phase 3 |
| D8 | PixAI metadata-fetch GraphQL query — no `model(id:)` exposed in current client; introspection disabled on PixAI's Apollo server | Phase 0 audit (§2 verification status) | Phase 4 if needed |

### External signals on file

- **PixAI tech response (Kero, 2026-05-06)** — investigating processing-step differences between web UI and API. No timeline, no parameter fix yet, no integration work needed. Recorded in `phase0_audit_20260506.md` §7.
- **Kero follow-up email pending**: ask explicitly which ControlNet type strings expose IP-Adapter / Reference-Only / FaceID, and whether `controlEnd` / `controlStart` timing fields are accepted. Both D1 and D2 unblock from one email.

---

## 3. Phase 2 priorities (ranked)

1. **D2 + D6 paired — reference-image conditioning AND auto-regenerate loop.** These are the two structural gaps that explain "recognizable but drifts." Picking them as a pair lets us measure improvement after each turn of the wrench. D6 is implementable today (`regenerate.py` exists, just needs orchestrator wiring); D2 needs PixAI API discovery first.
2. **Send the Kero follow-up email** to unblock D1 + D2 simultaneously.
3. **D5 — token-weight ordering** for Stage 3 so outfit/accessory tokens out-rank style boosters. Code-only change; cheap. Could land before D2 if Kero's reply is slow.

---

## 4. State at end of Phase 1

- Branch tip: `92aacea`, pushed to `origin/pixAI`.
- Repo + working tree clean at closeout commit time.
- Pipeline is **not yet runnable end-to-end against live PixAI** because of D4 (Faye-Lyn LoRA id missing). All other code-path blockers are resolved: B1 (sketch_lora removed), B2 (sheet stub present), B3 (fail-fast on `linkedLoraId is None` with a clear error). Once the user supplies the Faye-Lyn LoRA id and registers it, Stage 3 will assemble valid params.
- Test suite green: 46 passed, 0 skipped, 2 expected warnings.
- Two unimplementable spec items (D1, D2) are reflected only in docstrings — no invented GraphQL fields, no speculative API surface.
- No PixAI generation calls were made during Phase 1. Phase 4 is the benchmark phase.
