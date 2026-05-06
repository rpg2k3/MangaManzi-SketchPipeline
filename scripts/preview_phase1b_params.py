"""Phase 1B: print the assembled createGenerationTask payload for each
stage so the spec compliance can be verified before any PixAI call.

Construction logic mirrors `app.pipeline.stages` exactly. No PixAI API
call is issued — this is a pure local print.

Usage:
    .venv/bin/python scripts/preview_phase1b_params.py
"""

import json
import sys
from pathlib import Path

# Make the repo root importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import loras
from app.loras import LoRA
from app.pixai import ControlNetSpec, LoraSpec, TaskParameters
from app.pixai.prompt_rewriter import to_booru
from app.sheets import load
from app.ui.taxonomy import archetype_core, pose_core, subject_anchor


# ─────────────────────────────────────────────────────────────────────
# Synthetic ids — never sent to PixAI; just placeholders for the print.
# ─────────────────────────────────────────────────────────────────────

DEMO_BASE_MEDIA_ID = "demo-stage-1-output-media-id"
DEMO_SKETCH_MEDIA_ID = "demo-stage-2-output-media-id"

# Synthetic Faye-Lyn LoRA registration so Stage 3's registry lookup
# resolves. We register at runtime ONLY for this preview — nothing is
# persisted. Architecture is set to dit2 per project notes; the
# base_model_id is left at the Illustrious id since the DiT.2 base id
# is TBD (Phase 1C / Phase 4 will fork prompt logic by architecture).
DEMO_FAYE_LORA = LoRA(
    name="faye_lyn_demo",
    pixai_model_id="DEMO-FAYE-LYN-PIXAI-ID",
    purpose="character finalization (Faye-Lyn)",
    trigger_words="faye_lyn, magenta_hair, dark_skin, cat_ears",
    weight=0.75,
    base_model="Illustrious-XL-v1.0",  # placeholder until DiT.2 base id supplied
    base_model_id="1844843519625072849",
    used_in_stage=3,
    architecture="dit2",
)


def build_stage_1_params(*, archetype: str, view: str, pose: str) -> TaskParameters:
    base = loras.get("9k9base")
    parts = [
        subject_anchor(archetype),
        archetype_core(archetype),
        pose_core(pose),
        "9k9base, faceless bald head, head height grid",
        "light blue pencil, construction lines",
        "white background",
    ]
    natural_prompts = ", ".join(p for p in parts if p)
    prompts = to_booru(natural_prompts)

    return TaskParameters(
        prompts=prompts,
        negative_prompts=base.default_negative,
        loras=[LoraSpec(model_id=base.pixai_model_id, weight=base.weight)],
        control_nets=[],
        priority=None,
        seed=None,
        model_id=base.base_model_id,
        quality_tag=None,
    )


def build_stage_2_params(*, base_media_id: str) -> TaskParameters:
    base = loras.get("9k9base")
    return TaskParameters(
        prompts="9k9base, refined pencil sketch, clean construction lines",
        negative_prompts=base.default_negative,
        loras=[],
        media_id=base_media_id,
        strength=0.40,
        cfg_scale=5.5,
        sampling_steps=24,
        control_nets=[
            ControlNetSpec(type="openpose", media_id=base_media_id, weight=0.85),
            ControlNetSpec(type="depth", media_id=base_media_id, weight=0.55),
        ],
        priority=None,
        model_id=base.base_model_id,
        quality_tag=None,
    )


def build_stage_3_params(
    *, sketch_media_id: str, sheet: dict, char_lora: LoRA
) -> TaskParameters:
    triggers = sheet.get("triggerWords") or []
    char_triggers = ", ".join(triggers) if isinstance(triggers, list) else str(triggers)
    char_weight = float(sheet.get("loraWeight") or 0.75)

    # Stage 3 normally calls Claude to compose the prompt. For this preview
    # we emit a representative concatenation showing what the assembled
    # call would carry — Phase 1C wires the actual DiT.2/SDXL prompt fork.
    placeholder_positive = (
        f"{char_triggers or '(no_triggers_yet)'}, "
        "1girl, solo, full_body, contrapposto, "
        "[Phase 1C will inject sheet.outfitVariants[0].tags + learnedDrifts here]"
    )
    placeholder_negative = "(empty for DiT.2; SDXL template will be built in Phase 1C)"

    return TaskParameters(
        prompts=placeholder_positive,
        negative_prompts=placeholder_negative,
        loras=[LoraSpec(model_id=char_lora.pixai_model_id, weight=char_weight)],
        media_id=sketch_media_id,
        strength=0.60,
        cfg_scale=6.5,
        sampling_steps=28,
        control_nets=[
            ControlNetSpec(type="openpose", media_id=sketch_media_id, weight=0.7),
            ControlNetSpec(type="depth", media_id=sketch_media_id, weight=0.5),
        ],
        priority=None,
        model_id=char_lora.base_model_id,
        quality_tag=None,
    )


def main() -> None:
    sheet = load("faye_lyn")

    # Register the synthetic Faye-Lyn LoRA so Stage 3 has something to
    # resolve against. Demo only — not persisted.
    if loras.find_by_pixai_id(DEMO_FAYE_LORA.pixai_model_id) is None:
        loras.register(DEMO_FAYE_LORA)

    s1 = build_stage_1_params(archetype="F_yadult", view="front", pose="contrapposto_classic")
    s2 = build_stage_2_params(base_media_id=DEMO_BASE_MEDIA_ID)
    s3 = build_stage_3_params(
        sketch_media_id=DEMO_SKETCH_MEDIA_ID,
        sheet=sheet,
        char_lora=DEMO_FAYE_LORA,
    )

    for label, p in (("STAGE 1 (base mannequin)", s1),
                     ("STAGE 2 (pure img2img refinement, no LoRA)", s2),
                     ("STAGE 3 (character finalization)", s3)):
        print("=" * 78)
        print(label)
        print("=" * 78)
        print(json.dumps(p.to_pixai_dict(), indent=2))
        print()


if __name__ == "__main__":
    main()
