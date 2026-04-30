# 9LivesK9 Base Pose Library — Project Specification

> **Purpose of this document:** Reference data for the Claude Haiku prompt-assembly engine. This document defines the project's vocabulary — archetypes, views, poses, proportions, naming conventions. When assembling a per-pose prompt, look up the relevant section here for ground-truth values. Do not memorize; reference.

---

## 1. Project Purpose

A reusable, printable library of anatomically refined base mannequin templates across gender, age, and pose category. Each template is designed for a light-box underdrawing workflow: print the base on A4, overlay on light-box, draw the character on top with full control over details (hair, face, outfit, accessories).

Every template follows a locked construction language for visual consistency across the entire library.

---

## 2. Master Style Guide (Locked Conventions)

These rules apply to every generation, without exception.

### 2.1 Art Style

- Light blue pencil construction drawing
- Wireframe contour bands wrapping around form (Atari lines)
- Cross-section ovals at all major joints (shoulder, elbow, wrist, hip, knee, ankle)
- Soft pencil line quality, no heavy ink
- Clean white background
- A4 ratio (portrait default, landscape only when pose demands it)

### 2.2 Figure Conventions

- Bald, faceless head with center cross guideline
- No hair, no clothing, no accessories, no facial features
- No horns, cat ears, tails, or fantasy accessories in the base itself (those are layered during character work)
- Ribcage as egg-shaped volume, pelvis as bucket volume, defined waist taper for adults
- Visible iliac crest, joint articulation, hand fingers fully drawn, feet with arch/heel/toe

### 2.3 Line of Action

- Always overlaid in **red** on every generation
- Traces the spine rhythm from crown of head through weight-bearing support to floor
- Build the figure along the curve from the start

### 2.4 Head-Height Grid

- Numbered horizontal guidelines on the **left margin**
- Numbered from 0 (ground plane, dashed line) to the archetype's head count
- Match the archetype's head count exactly — never default to a single value

---

## 3. Archetype Matrix

### 3.1 Female / Male Archetypes

Same head ratios apply to both genders — body shape emphasis differs (hips vs shoulders).

| Code | Label | Age | Head Heights | Notes |
|---|---|---|---|---|
| `F_adult` / `M_adult` | Adult | 25+ | 8 (range 7.5–8) | Fully developed, longer legs, balanced torso. Push to 8.5 for heroic/stylized. |
| `F_yadult` / `M_yadult` | Young Adult | 18+ | 7.5 (range 7–7.5) | Slightly softer than adults, head subtly larger. Ideal for main characters. |
| `F_teenM` / `M_teenM` | Teen Mature | 16+ | 7 (range 6.5–7) | Near-adult proportions, slightly shorter limbs. Standard shōnen/shōjo range. |
| `F_teenY` / `M_teenY` | Teen Young | 14+ | 6.5 (range 6–6.5) | Noticeably larger head, shorter limbs, more energetic proportions. |
| `F_preteen` / `M_preteen` | Pre-Teen | 12+ | 6 (range 5.5–6) | Big head relative to body, shorter legs, softer less angular anatomy. |

### 3.2 Androgynous Child Archetypes

No gender prefix in filenames — minimal gender distinction at these ages.

| Code | Label | Age | Head Heights | Notes |
|---|---|---|---|---|
| `child` | Child | 8–11 | 5.5 (range 5–5.5) | Neutral silhouette, short limbs, wider torso, minimal gender distinction. |
| `toddler` | Toddler | 2–4 | 4.5 (range 4–4.5) | Very large head, very short legs, slight belly protrusion. |
| `baby` | Baby | 0–1 | 3.5 (range 3–3.5) | Head dominates body, limbs short and soft, minimal joint definition. |

### 3.3 Quick Reference Scale

```
Adult        → 8 heads
Young Adult  → 7.5 heads
Teen Mature  → 7 heads
Teen Young   → 6.5 heads
Pre-Teen     → 6 heads
Child        → 5.5 heads
Toddler      → 4.5 heads
Baby         → 3.5 heads
```

### 3.4 Reference Folder Architecture

Each archetype has TWO reference folders, serving complementary roles:

**Anatomical Truth (`/bases/csp_tvd/[ARCHETYPE]/`)**
- Locked proportions, joint positions, structural skeleton
- The "what" — canonical anatomy for the archetype
- Source: Clip Studio Paint mannequin renders or hand-drawn anatomical references

**Style Ideal (`/bases/gpt_tvd/[ARCHETYPE]/`)**
- Contrapposto application, line of action, floating volume construction
- The "how" — target aesthetic and doctrine application
- Source: AI-generated reference at the doctrine target

Both folders contain the same 6 standard views: `front.png`, `back.png`, `side_L.png`, `side_R.png`, `3q_front_L.png`, `3q_front_R.png`.

Both must be populated with all 6 views for an archetype to be "ready" for generation. Image generation calls attach both matching views with explicit role labels so the AI synthesizes them complementarily — applying GPT style to CSP anatomy.

**Output destination:** Generated mannequins are saved to `/output/[ARCHETYPE]/`, separate from the input reference folders. The `bases/` folder is read-only from the app's perspective.

Archetype folder naming: `[ARCHETYPE]-(AGE)/` — e.g., `F_adult-(25+)/`, `M_adult-(25+)/`, `child-(8-11)/`.

---

## 4. Proportion Adjustment Rules per Archetype

When writing the anatomy section of any prompt, scale these specifications by archetype.

### Adult (8 heads)
- Shoulders 2 head-widths across (female) / 2.5 (male athletic)
- Defined waist taper, clear iliac crest
- Legs roughly 4 heads long (half total height)
- Sharp joint articulation

### Young Adult / Teen Mature (7–7.5 heads)
- Shoulders 1.75–2 head-widths
- Slightly less pronounced waist
- Legs slightly shorter relative to torso
- Joints articulated but softer than adult

### Teen Young / Pre-Teen (6–6.5 heads)
- Head visibly larger relative to body
- Shoulders 1.5–1.75 head-widths
- Torso less tapered, more cylindrical
- Limbs shorter, joints softer

### Child (5.5 heads)
- Head dominant, ~1/5 of total height
- Torso wider relative to hips
- Legs shorter than torso
- Minimal joint definition, soft transitions

### Toddler (4.5 heads)
- Head ~1/4 of total height
- Belly protrusion visible
- Very short legs (~1.5 heads)
- Pudgy limbs, no muscle definition

### Baby (3.5 heads)
- Head ~1/3 of total height
- Limbs short and rounded
- No visible joint articulation
- Soft rounded silhouette throughout

### Stylization Notes (Optional)
- Adults → can push to 8–8.5 heads for elegance / heroic look
- Teens → slightly larger heads for appeal
- Kids → exaggerated head size for readability

---

## 5. View Matrix

| View Code | Description |
|---|---|
| `front` | Straight-on front view |
| `back` | Straight-on back view |
| `side_L` | Left profile |
| `side_R` | Right profile |
| `3q_front_L` | Three-quarter front, turned left |
| `3q_front_R` | Three-quarter front, turned right |
| `3q_back_L` | Three-quarter back, turned left |
| `3q_back_R` | Three-quarter back, turned right |

---

## 6. Pose Category Taxonomy

### 6.1 Standing & Contrapposto

| Pose ID | Description |
|---|---|
| `contrapposto_classic` | Hand on hip, weight shift |
| `contrapposto_relaxed` | Both arms down, subtle weight shift |
| `power_stance` | Feet wide, shoulders squared, hands on hips |
| `idle_casual` | Asymmetric relaxed standing |
| `resting_lean` | Leaning against an implied surface |
| `crossed_arms` | Arms folded across chest |
| `glute_reveal` | Back view classical stance |

### 6.2 Walking / Running / Sprinting

| Pose ID | Description |
|---|---|
| `walk_neutral` | Mid-stride casual walk |
| `walk_confident` | Strong stride with attitude |
| `run_jog` | Jogging pace |
| `run_sprint` | Full sprint with extended stride |
| `walk_stealth` | Crouched cautious walk |

### 6.3 Sitting / Kneeling / Reclining

| Pose ID | Description |
|---|---|
| `sit_chair_neutral` | Seated upright on implied chair |
| `sit_chair_relaxed` | Leaning back, legs crossed |
| `sit_floor_crossed` | Cross-legged on ground |
| `sit_floor_side` | Side-seated with legs tucked |
| `kneel_one` | One knee down, one up (proposal/sword) |
| `kneel_both` | Both knees down |
| `recline_prop` | Reclining propped on one elbow |
| `recline_flat` | Lying flat on back or stomach |

### 6.4 Combat & Action

| Pose ID | Description |
|---|---|
| `combat_ready` | Fighting stance, guard up |
| `combat_punch_right` | Mid-punch extension |
| `combat_kick_high` | High kick in motion |
| `combat_block` | Defensive guard |
| `combat_sword_idle` | Sword held ready |
| `combat_sword_swing` | Mid-swing |
| `cast_spell` | Arms raised casting |
| `throw_object` | Mid-throw extension |

### 6.5 Dynamic Gestures

| Pose ID | Description |
|---|---|
| `reach_up` | Arm extended upward |
| `reach_forward` | Arm extended forward |
| `point` | Arm pointing at implied target |
| `lean_forward` | Torso leaning forward |
| `lean_back` | Torso leaning back |
| `turn_look` | Mid-turn looking over shoulder |
| `shrug` | Shoulders raised |
| `wave` | Hand raised in greeting |

### 6.6 Camera Angles

| Pose ID | Description |
|---|---|
| `low_angle_hero` | Upward camera, heroic proportions emphasized |
| `high_angle_vulnerable` | Downward camera, figure smaller/lower |
| `foreshortening_reach` | Limb extended toward camera |
| `foreshortening_lying` | Reclining with feet or head toward camera |
| `dutch_angle` | Tilted camera |

---

## 7. File Naming Convention

### 7.1 Pattern

```
[gender]_[archetype]_[view]_[pose]_[variant].png
```

For androgynous archetypes (child, toddler, baby), omit the gender prefix:

```
[archetype]_[view]_[pose]_[variant].png
```

### 7.2 Examples

- `F_adult_front_contrapposto_classic_01.png`
- `M_yadult_3q_front_L_combat_ready_01.png`
- `F_teenM_side_L_walk_neutral_01.png`
- `M_preteen_back_idle_casual_01.png`
- `child_front_idle_casual_01.png`
- `toddler_side_L_sit_floor_crossed_01.png`

### 7.3 Variants

Use `_01`, `_02`, etc. for multiple versions of the same pose/view combo when slight attitude variations are wanted.

---

## 8. Build Order Priority

When generating archetype foundations:

1. **Phase 1:** F_adult across all 8 views with `contrapposto_classic` — anchors the entire library's style
2. **Phase 2:** M_adult across all 8 views with `contrapposto_classic` — establishes male proportions
3. **Phase 3:** Core pose expansion on adult archetypes — walk, run, sit, kneel, combat_ready, reach, lean
4. **Phase 4:** Young Adult & Teen archetypes — `contrapposto_classic` across 4 views each
5. **Phase 5:** Pre-Teen & Child — most readable poses (idle_casual, walk_neutral, sit_floor_crossed)
6. **Phase 6:** Toddler & Baby — front, side_L, back only; limited pose set
7. **Phase 7:** Extended pose library — combat variations, camera angles, foreshortening, dynamic gestures

---

## 9. Reference Anchoring Strategy

For app-driven generation, the canonical references come from `/csp_tvd/[ARCHETYPE]/`. Always attach the view-matching reference image alongside the generation prompt.

When generating an archetype that doesn't yet have a CSP reference folder populated, fall back to the closest age-adjacent archetype's references (e.g., for `F_teenM` use `F_yadult-(18+)` references if `F_teenM-(16+)` is not yet populated).

Maximum 3 reference images attached per generation — more causes averaging and loss of clarity. The matched view is mandatory; secondary references are optional.
