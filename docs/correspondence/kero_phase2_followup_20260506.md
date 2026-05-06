# Kero — PixAI follow-up: reference-image preprocessors

**Status:** draft, awaiting user review before send
**Date drafted:** 2026-05-06
**Recipient:** Kero (PixAI)
**Subject:** Re: web UI vs API processing — quick follow-up on reference-image preprocessors
**In reply to:** his earlier message today (PixAI tech team investigating processing-step diff)

---

Hey Kero,

Thanks for the reply this morning — appreciate the team taking a look at the web-UI vs API processing-step diff. No timeline pressure on our side; we'll sit on it. The screen recording reproducing the diff is being prepped separately and I'll send that over once it's clean.

Quick technical question while we're at it, on a different thread:

**Does the PixAI API expose IP-Adapter or Reference-Only ControlNet, or any preprocessor that does reference-image *content* conditioning** (as opposed to edge / pose / depth extraction)?

The set of `controlNets[].type` strings I have documented from the JS client + experimentation is:

`dwpose, canny, depth, hed, mlsd, openpose, seg, normal, scribble`

All nine are extraction-style preprocessors — they pull lines/pose/depth out of the source and feed it back as a structural constraint. None of them do what IP-Adapter or Reference-Only ControlNet do (broadcast the reference image's content/style into the latent so a character LoRA can match design fidelity).

**Why we're asking:** in our three-stage pipeline (base mannequin → sketch refinement → character finalization with character LoRA + img2img), the character-stage output is "recognizable but drifts" — the character LoRA gets the basics right but outfit details, accessories, and proportions drift across runs. Standard SD/SDXL workflows lean hard on IP-Adapter Plus or Reference-Only ControlNet at this exact stage, weighted ~0.5–0.6, with the canonical character sheet as the reference image. We can't replicate that on the API today because none of the documented preprocessors carry content.

If the API exposes a `type` string for this — even something internal/undocumented — that'd unblock a major chunk of our outfit-fidelity work. If not, knowing definitively would let us close the question and pick a different path (e.g. heavier reliance on per-character LoRA training, or a polling-based two-pass approach).

A simple yes/no with the right type string is enough; happy to do all the integration work from there.

Cheers,
[user]

---

## Notes for sender

- Tone matches Kero's informal/technical register from the prior thread.
- Singular focus per instruction: just the IP-Adapter / Reference-Only question. The ControlNet end-timing question (deferred item D1) is held back for a separate later email so this one stays easy to scan.
- Mentions the screen recording without committing to a delivery date — keeps that thread open without crowding this email.
- The "type string" framing makes it easy for Kero to answer with a single word (e.g., "yes — use `ip_adapter`").
