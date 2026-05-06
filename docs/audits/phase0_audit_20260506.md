# Phase 0 — pixAI pipeline baseline audit

| Field | Value |
|---|---|
| Date | 2026-05-06 |
| Branch | `pixAI` |
| Commit hash at audit | `5526380` (pre-audit baseline checkpoint) |
| Auditor | Claude Code (Opus 4.7, 1M context) |
| Status | Baseline frozen — do not modify after commit |

This file is a permanent reference. Future phases diff against it.

---

## 1. Pipeline source map

| Layer | File(s) | Role |
|---|---|---|
| Orchestrator | `app/pipeline/orchestrator.py` | Sequential `run_pipeline(req)`, stages 1→4, single `PixAIClient` per run |
| Stages | `app/pipeline/stages.py` | Stage 1 (txt2img + 9k9base), Stage 2 (img2img + sketch_lora), Stage 3 (img2img + character LoRA), Stage 4 (Claude critique) |
| PixAI HTTP | `app/pixai/client.py`, `models.py`, `defaults.py`, `polling.py`, `concurrency.py`, `credits.py`, `errors.py`, `debug_log.py` | GraphQL client, dataclasses, polling/back-off, in-flight slot guard |
| Booru rewriter | `app/pixai/prompt_rewriter.py` | Whitelist normalizer (~13 tokens) |
| LoRA registry | `app/loras/registry.py` | Single registered LoRA: `9k9base` (locked) |
| Prompt builder | `app/claude/prompts.py` (Stage 3 only) | Claude Opus tool-use call → `{prompts, negative_prompts, rationale}` |
| Critique | `app/critique/{engine,history,learning,regenerate}.py`, `app/claude/critique.py` | Vision critique via Opus → `drifts/successes/suggestedPromptDeltas` |
| Sheet schema | `app/sheets/{schema,storage,migration}.py` | JSON-backed sheets; `linkedLoraId / triggerWords / loraWeight` are the LoRA hooks |
| UI | `app/ui/{generate_tab,sheets_tab,loras_tab,taxonomy}.py` | Generate / Sheets / LoRAs tabs |
| Worker | `app/workers/pipeline_worker.py` | Qt thread for the orchestrator |

---

## 2. LoRA architecture verification status

| LoRA | PixAI model id | Trigger words (in code) | Architecture | Default weight | Verification status |
|---|---|---|---|---|---|
| `9k9base` | `2006655610114208859` | `9k9base, light blue pencil construction, atari bands, joint ovals, faceless bald head, head height grid` | Illustrious-XL-v1.0 (SDXL family) per registry comment + reference task ids `2006991601815684685` / `2006996847850078063` | `1.0` | **Confirmed via code+reference-task only.** Live PixAI metadata fetch attempted; PixAI's Apollo server disables GraphQL introspection in production and the codebase exposes no `model(id:)` / `getModel(id:)` query. Treating registry comment as authoritative; `1844843519625072849` is the API-callable base-checkpoint id (the URL-form id `1844843518698131638` is NOT — returned 403 "Invalid modelId"). |
| `sketch_lora` | **n/a — never trained** | — | — | — | **Confirmed by user: this LoRA does not exist.** Stage 2 must be restructured to pure img2img refinement. `loras.get("sketch_lora")` to be removed from `stages.py` in Phase 1. |
| Faye-Lyn character LoRA | **TBD — to be supplied** | — | DiT.2 per project notes | `0.75` (default `loraWeight` per Phase 1 spec) | **Not yet registered.** Will live on the character sheet's `linkedLoraId`. Stage 3 must fail-fast with a clear error if `linkedLoraId is None`. DiT.2 caveat: negative prompts unsupported on this architecture — drift correction must happen via positive re-specification only. |

**Production-call note**: the existing `PixAIClient` only defines `createGenerationTask`, `getTaskById`, `getMediaById`, `cancelGenerationTask`, and `uploadMedia`. There is no model-metadata query in the codebase. If Phase 1+ needs to verify a LoRA's architecture programmatically, it must add a query to the client — guessing at PixAI's schema against the live endpoint without introspection is not safe.

---

## 3. Per-stage parameter inventory

Pulled from `app/pixai/defaults.py`, `app/pixai/models.py`, and each stage's call site in `app/pipeline/stages.py`. Defaults shown in italics where the call site does not override them.

| Field | Stage 1 (base) | Stage 2 (sketch) | Stage 3 (character) |
|---|---|---|---|
| Pipeline mode | txt2img | img2img | img2img |
| `model_id` (base ckpt) | `9k9base.base_model_id` = `1844843519625072849` (Illustrious-XL-v1.0) | `sketch_lora.base_model_id` (unregistered → fails) | `sketch_lora.base_model_id` (unregistered → fails) |
| Sampler | *DPM++ 2M Karras* | *DPM++ 2M Karras* | *DPM++ 2M Karras* |
| Steps | *28* | *28* | *28* |
| CFG | *7.1* | *7.1* | *7.1* |
| Width × Height | *768 × 1280* | *768 × 1280* | *768 × 1280* |
| `clip_skip` | *2* | *2* | *2* |
| Seed | optional `req.seed` | none | none |
| Priority | `1000` if `high_priority` else `None` | same | same |
| `mediaId` (img2img source) | – | Stage 1 output | Stage 2 output |
| `strength` (denoise) | – | **0.6** | **0.55** |
| LoRAs | `9k9base @ 1.0` | `sketch_lora @ sketch.weight` | `linkedLoraId @ loraWeight` (from sheet) |
| ControlNets | optional skeleton (openpose) + depth, both `weight=1.0` | **openpose + depth, both derived from Stage 1 output, `weight=1.0`** | **openpose + depth, both derived from Stage 2 output, `weight=1.0`** |
| `qualityTag` (Booster) | **explicitly `None`** (P18 — Booster fights 9k9base) | not set → `None` | not set → `None` |
| Positive prompt | hard-coded 6-tag list (see §4) | `sketch.trigger_words + sketch.positive_append` | Claude-generated (sheet + scene + prior_critiques) |
| Negative prompt | `_NEG_9K9BASE` (10-ish tokens) | `sketch.default_negative` | Claude-generated |
| Booru rewrite | `to_booru()` whitelist applied | not applied | not applied |
| Reference-image conditioning | none beyond optional ControlNet | – | – (no IP-Adapter or per-image guidance) |

---

## 4. Stage 1 prompt — exactly what is sent

**Positive (after `to_booru()` normalization):**

```
1girl, solo, full_body, female adult, contrapposto, 9k9base, faceless bald head, head height grid, light blue pencil, construction lines, white background
```

**Negative** (`_NEG_9K9BASE` from `app/loras/registry.py`):

```
nsfw, worst quality, bad quality, low quality, lowres, bad anatomy, multiple figures, clothing, hair, face, shading, finished anime
```

**Note on dead code** (Q11): `_POS_9K9BASE` is defined in the registry as `flat line drawing, pencil sketch, construction lines visible, no shading, no rendering, blueprint style, technical drawing` but is **not appended** in Stage 1 prompt assembly. The accompanying comment in `stages.py` says blueprint/technical-drawing tokens previously pulled the model toward architectural diagrams. To be removed in Phase 1 cleanup.

---

## 5. Critique loop — current shape

- `app/claude/critique.py` (Opus, vision tool-use) → returns `{drifts:[{aspect, expected, observed, severity}], successes:[…], suggestedPromptDeltas:[…]}`.
- `app/critique/engine.py` adds `origin: "auto"` / `origin: "manual"` and merges manual feedback as a top-priority drift.
- `app/critique/regenerate.py` reads the last *N* iterations from `history` and feeds them to `app/claude/prompts.py:generate_prompt(prior_critiques=…)` to compose a corrected Stage 3 prompt — but **the orchestrator does not auto-invoke this**. Stage 4 emits the critique JSON; re-roll is opt-in via the UI / a separate caller.
- `learning.py` and `history.py` exist but were not deeply read in this audit.

---

## 6. Gap analysis

### Blocking (pipeline cannot run end-to-end as-is)

| # | Gap | Where | Phase 1 disposition |
|---|---|---|---|
| B1 | `sketch_lora` not registered → Stage 2 `KeyError` on every run | `app/pipeline/stages.py:165` calls `loras.get("sketch_lora")` | **Confirmed by user: this LoRA does not exist.** Phase 1 restructures Stage 2 to pure img2img refinement, removes the `loras.get("sketch_lora")` call, drops the registry entry expectation. |
| B2 | No character sheets exist (`data/sheets/` empty) → Stage 3 `PipelineError` | orchestrator pre-flight check | Phase 1 ships a Faye-Lyn sheet stub at `data/sheets/faye_lyn.json` populated from canonical Design_A, plus four pre-seeded `learnedDrifts` entries (sourceRunIds: `["pre-audit"]`). |
| B3 | `linkedLoraId` field on the Faye-Lyn sheet is `null` until the user supplies it → Stage 3 still fails | sheet schema | Phase 1: Stage 3 fail-fast on `linkedLoraId is None` with a clear error telling the user to supply the LoRA id on the sheet. Faye-Lyn ID arrives from user separately. |

### Quality gaps (root causes of "recognizable but drifts" symptom)

| # | Gap | Risk | Where | Phase disposition |
|---|---|---|---|---|
| Q1 | All three stages use the same global defaults: 768×1280, CFG 7.1, 28 steps, DPM++ 2M Karras. Anime SDXL/Illustrious workflows tune these per stage (CFG 5–7, steps 24–32, native 1024-bucket sizes 832×1216 / 896×1152). 768×1280 is non-standard for SDXL. | Soft output, off-aspect quality | `app/pixai/defaults.py` | Phase 1 — per-stage parameter overhaul. |
| Q2 | ControlNet weights are uniform `1.0` for both openpose and depth. Best practice tapers (openpose 0.7–0.9, depth 0.5–0.7) on later passes. | Pose rigidity overrides outfit silhouette → wrong boots, missing accessories | `ControlNetSpec.weight = 1.0` | Phase 1 — Stage 2 uses 0.85/0.55, Stage 3 uses 0.7/0.5. |
| Q3 | Stage 2 / Stage 3 `qualityTag` (Booster) is implicit `None`. Stage 1 explicitly disables it (correctly — fights 9k9base). | Stage 3 character output potentially undertuned | `stages.py` (no `quality_tag=…` on S2/S3) | **Decision: keep Booster OFF for Stage 2/3 in Phase 1.** Same "Booster fights LoRA training style" logic likely applies. Re-test in Phase 4 benchmarks; do not change default in Phase 1. |
| Q4 | No reference-image conditioning beyond chained img2img + ControlNet. No IP-Adapter / Reference-Only / FaceID. Character consistency rests entirely on the character LoRA + Stage 2 sketch carryover. | "Recognizable but drifting" — exactly the user's stated symptom | `stages.py` | Phase 1 (Stage 3 reference-image hook) + Phase 2 (`referenceAnchors` schema, `learnedDrifts` injector). |
| Q5 | Booru whitelist is tiny (~13 tokens). Common Illustrious-trained tags (`looking_at_viewer`, `simple_background`, `cowboy_shot`, `dynamic_pose`, `from_above`, `from_below`, `detailed_face`, etc.) pass through with spaces — they don't hit booru attention. | Drift from intended composition / framing | `prompt_rewriter.py:KNOWN_BOORU_TAGS` | Phase 3 — local Danbooru tag list cache (top 100k by post count) + tag-validity check. |
| Q6 | Stage 3 prompt is fully Claude-generated, no priority weighting (`(token:1.2)`, `[token:0.7]`, `(token:1.4)`) and no spec for ordering "high-fidelity outfit terms first vs. style boosters last". | Style tokens out-fight outfit terms → "fishnet over-density, missing straps/belts/boots" | `app/claude/prompts.py` | Phase 3 — token weighting + ordering rules. |
| Q7 | Stage 1 negative still includes `clothing, hair, face, shading, finished anime`. Stage 2 inherits a different sketch_lora negative (unverified). Stage 3 negative is Claude-generated. Three independent negative-prompt sources. | Prompt-level negation incoherence | per-stage | Phase 1 — replace each stage's negative with the explicit templates in the Phase 1 spec. |
| Q8 | DiT.2 vs DiT.1 vs SDXL handling not differentiated. Faye-Lyn LoRA is DiT.2 — negative prompts must be empty for that architecture. Current pipeline always sends a negative. | Architecture-incompatible parameters | `stages.py`, `models.py` | Phase 1 — Stage 3 fork by architecture: empty negative for DiT.2; SDXL fallback template if metadata says SDXL. |
| Q9 | No `model_version` / `architecture` field on the `LoRA` dataclass — registry can't conditionally branch on DiT.1/DiT.2/SDXL. | Can't fix Q8 cleanly | `app/loras/registry.py` | Phase 1 — add `architecture` field to `LoRA` dataclass. |
| Q10 | Critique→regenerate is **manual**: orchestrator calls Stage 4 but doesn't loop. Drift correction lives in `regenerate.py` but no caller wires it back into a re-roll. | "Recognizable but drifts" never auto-corrects | `orchestrator.py` | Phase 2 — auto-loop with `max_iterations` (default 3) + drift severity threshold. |
| Q11 | `_POS_9K9BASE` is dead code (defined, never appended in stages.py). | Maintenance / accidental future re-enable | `stages.py:112-119` vs `registry.py:45-48` | Phase 1 cleanup — remove. |
| Q12 | No system for separating **immutable LoRA vocabulary** (`<lora-trigger>`) from **prompt-style language**. Currently they're concatenated as a comma-list, no precedence weighting. | Prompt priority order undefined → style overrides character (the stated symptom) | `stages.py` Stage 1 + `prompts.py` Stage 3 | Phase 3 — token weighting and prompt assembler logging (`runs/<run_id>/assembled_request.json`). |

---

## 7. External signals

- **PixAI tech response (Kero, 2026-05-06)**: PixAI technical team is investigating processing-step differences between web UI and API. Hypothesis confirmed plausible. **No timeline, no parameter fix yet, no integration work needed.** Note for context — does not block any Phase 1+ decision.

---

## 8. Closeout

The pipeline at commit `5526380` is **non-runnable end-to-end**: Stage 2 throws on the missing `sketch_lora` registry entry (B1), and even with that bypassed Stage 3 has no character sheet to bind to (B2) and no `linkedLoraId` to point to a real LoRA (B3). All three blockers are scoped to Phase 1.

The "recognizable but drifts" symptom the user reported is **structurally explained** by the combination of three independent quality gaps:

- **Q4** — no reference-image conditioning beyond chained img2img + ControlNet, so character consistency rests entirely on the character LoRA;
- **Q6 / Q12** — no token-weight ordering or priority structure in the Stage 3 prompt, so style tokens out-rank outfit/accessory tokens;
- **Q10** — no auto-regenerate loop, so drift never corrects even when the critique surface already names it.

Phase 1 will fix the three blockers AND apply the empirically-validated parameter baseline in one pass: restructure Stage 2 to pure img2img refinement (no sketch_lora), update per-stage sampler/CFG/steps/resolution, taper ControlNet weights, swap to native 1024-bucket sizes (832×1216), add the `architecture` field to the LoRA dataclass for DiT.2 vs SDXL forking, draft the Faye-Lyn sheet stub with the four pre-seeded `learnedDrifts` corrections, remove the `_POS_9K9BASE` dead code, and harden the negative-prompt templates per stage. Booster (`qualityTag`) stays OFF for Stage 2/3 — to be re-tested in Phase 4 benchmarks. Phase 2 will wire the critique→regenerate loop and add `referenceAnchors` to the sheet schema. PixAI's processing-step investigation (per Kero, today) is informational only and does not affect Phase 1 scope.
