# 9LivesK9 Base Pose Library — Application Specification

**Version:** 1.0
**Target platform:** Linux (Kubuntu primary), Windows/macOS later
**Audience:** Claude Code (build agent)

---

## 1. Purpose

A desktop application that generates a 62-image set of anatomically refined base mannequin templates for a single character archetype, in one click, using the OpenAI Image API.

The user has a validated manual workflow: paste a prompt + 3 reference images into ChatGPT, save the result, repeat 62 times per archetype, repeat for ~14 archetypes. The app automates that loop.

**Output of one full run:** 62 light-blue-pencil construction-drawing PNGs in A4 portrait or landscape ratio, named per a strict convention, ready to print and overlay on a light-box for character drawing.

---

## 2. Goals

1. User selects an archetype from a dropdown, clicks "Generate All 62 Images," and walks away.
2. User can create custom archetypes (any gender + age tier + style tag combination) with their own CSP turnaround references.
3. Built-in and custom archetypes use the same code path — no special-casing.
4. Output filenames match the existing convention exactly.
5. Reference selection automatically swaps in the locked archetype anchor after prompt #1, per the existing logic.
6. App tracks cost and shows progress in real time.
7. Failed generations can be retried individually without re-running the whole batch.

## 3. Non-Goals (v1)

- No image editing inside the app (output PNGs go straight to disk).
- No cloud sync. Everything is local.
- No multi-user / collaboration features.
- No drawing tools, light-box overlay, or other downstream workflow.
- No batch generation of multiple archetypes in one queue (one archetype at a time).

---

## 4. Tech Stack

### Phase 1 — Validation (Python, throwaway)
A 30–50 line Python script using the `openai` SDK to confirm the API produces output matching the user's existing AAA-validated quality bar. Not part of the shipped app. **Must be completed and approved before Phase 2 begins.**

### Phase 2 — Production app (Qt C++)
- **Language:** C++17 or later
- **UI framework:** Qt 6 (Widgets, not QML — Widgets is a better fit for this dense desktop UI)
- **HTTP client:** Qt Network (`QNetworkAccessManager`) — no external dependency needed
- **JSON:** Qt's built-in `QJsonDocument`
- **Image handling:** `QImage` / `QPixmap`
- **Build system:** CMake
- **PDF parsing (one-time, build-time):** pdftotext or qpdf to extract the 62 prompts from `F_adult_lora_base_set.pdf` into a JSON template file. This step runs once during development, not at runtime.

### Why Qt C++ over PyQt
User preference (single executable, no Python runtime to ship, more polished installer experience for eventual commercial release). Validation in Python first because iterating on API request shape is faster in a dynamic language; once the request shape is locked, the C++ port is mechanical.

---

## 5. Archetype Data Model

All archetypes — built-in and user-created — use the same JSON schema. Stored as `archetypes/<archetype_id>/archetype.json`.

```json
{
  "archetype_id": "F_yadult_curvy",
  "display_name": "Young Adult Female (Curvy)",
  "gender": "F",
  "age_tier": "young_adult",
  "head_heights": 7.5,
  "head_heights_range": [7.0, 7.5],
  "style_tag": "curvy",
  "style_notes": "Hourglass silhouette, fuller hips and bust, soft waist taper accentuated, otherwise young-adult proportions.",
  "is_builtin": false,
  "csp_references": {
    "front": "csp_references/front.png",
    "side_L": "csp_references/side_L.png",
    "side_R": "csp_references/side_R.png",
    "back": "csp_references/back.png",
    "3q_front_L": "csp_references/3q_front_L.png",
    "3q_front_R": "csp_references/3q_front_R.png"
  },
  "locked_anchors": {
    "front_contrapposto_classic": "locked_anchors/F_yadult_curvy_front_contrapposto_classic_01.png"
  },
  "anatomy_block": "ANATOMY (female young adult, 7.5 heads):\n- 7.5 total head-heights from crown to sole (range 7.0–7.5)\n- Shoulders 1.75–2 head-widths across\n- Hip width slightly exceeds shoulder width (female emphasis)\n- ...\n- Hourglass silhouette, fuller hips and bust, soft waist taper accentuated\n- Maintain stylized anime construction throughout — do NOT drift toward realistic anatomy or Western comic proportions"
}
```

### Age tier → proportion rules table

This table is the single source of truth for age-based proportion adjustment. When the user picks an age tier in the wizard, the app auto-fills `head_heights`, `head_heights_range`, and the base anatomy bullets.

| age_tier      | label          | head_heights | range       | shoulders         | leg ratio       | joint def    |
|---------------|----------------|--------------|-------------|-------------------|-----------------|--------------|
| `adult`       | Adult (25+)    | 8            | 7.5–8       | 2 head-widths (F) / 2.5 (M) | ~4 heads (1/2 body) | sharp        |
| `yadult`      | Young Adult (18+) | 7.5       | 7.0–7.5     | 1.75–2            | slightly shorter | softer       |
| `teenM`       | Teen Mature (16+) | 7         | 6.5–7       | 1.75–2            | slightly shorter | softer       |
| `teenY`       | Teen Young (14+) | 6.5        | 6.0–6.5     | 1.5–1.75          | shorter          | soft         |
| `preteen`     | Pre-Teen (12+) | 6            | 5.5–6.0     | 1.5–1.75          | shorter          | soft         |
| `child`       | Child (8–11)   | 5.5          | 5.0–5.5     | head-dominant     | shorter than torso | minimal    |
| `toddler`     | Toddler (2–4)  | 4.5          | 4.0–4.5     | head ~1/4 height  | ~1.5 heads        | none         |
| `baby`        | Baby (0–1)     | 3.5          | 3.0–3.5     | head ~1/3 height  | rounded short     | none         |

The full anatomy bullet list per age tier is hardcoded in `proportion_rules.json` (committed with the app).

### Built-in archetypes (shipped with app)

```
F_adult, M_adult,
F_yadult, M_yadult,
F_teenM, M_teenM,
F_teenY, M_teenY,
F_preteen, M_preteen,
child, toddler, baby
```

Built-in archetypes have `is_builtin: true` and ship without CSP references — user must upload their own for each one before generating. (User has stated they will produce these in CSP themselves.)

### Filename rules

- Gendered: `[gender]_[age_tier][_style_tag]_[view]_[pose]_[variant].png`
  - With style tag: `F_yadult_curvy_front_contrapposto_classic_01.png`
  - Without: `F_adult_front_contrapposto_classic_01.png`
- Androgynous (`child`, `toddler`, `baby`): omit gender prefix — `child_front_idle_casual_01.png`

---

## 6. The 62-Prompt Structure

### Source of truth

The user's existing `F_adult_lora_base_set.pdf` contains 62 fully-written prompts that produced the validated output. These are the **gold standard** — the app's prompts must match this structure exactly.

**Build-time task:** Parse `F_adult_lora_base_set.pdf` once, extract each prompt's text body, and emit `prompt_templates.json` with placeholders where archetype-specific content goes.

### Prompt structure (every prompt has the same skeleton)

```
I'm attaching 3 reference templates from my 9LivesK9 Base Pose Library — treat them as the primary style anchor.

ARCHETYPE: {ARCHETYPE_LABEL}
VIEW: {VIEW_DESCRIPTION}
POSE CATEGORY: {POSE_CATEGORY}
SPECIFIC POSE: {POSE_SPECIFIC_DESCRIPTION}
ORIENTATION: {ORIENTATION}

LOCKED STYLE CONVENTIONS (match my references exactly):
{LOCKED_STYLE_BLOCK}   // identical for all 62 prompts

{ANATOMY_BLOCK}        // archetype-specific — injected from archetype.json

POSE RHYTHM:
{POSE_RHYTHM_BLOCK}    // pose+view specific, same across archetypes

LINE OF ACTION:
{LINE_OF_ACTION_BLOCK} // pose+view specific

HEAD-HEIGHT GRID:
- Numbered horizontal guidelines 1 through {HEAD_COUNT} along the left margin
- Dashed line at the bottom marking the ground plane (marker 0)
- Crown of head sits at marker {HEAD_COUNT}, soles touch marker 0
- Grid must match the {HEAD_COUNT}-head {age_label} count exactly — no drift

OUTPUT: {OUTPUT_LINE}
```

### Substitution variables

Per-prompt fixed (extracted from PDF):
- `VIEW_DESCRIPTION`, `POSE_CATEGORY`, `POSE_SPECIFIC_DESCRIPTION`
- `ORIENTATION` (portrait or landscape)
- `POSE_RHYTHM_BLOCK`, `LINE_OF_ACTION_BLOCK`, `OUTPUT_LINE`

Per-archetype injected at runtime:
- `ARCHETYPE_LABEL` — e.g. "female young adult, 7.5 head-heights"
- `ANATOMY_BLOCK` — built from age tier + style notes
- `HEAD_COUNT` — integer from age tier

Constant across all prompts:
- `LOCKED_STYLE_BLOCK` — 10 hardcoded bullet points (light blue pencil, Atari lines, cross-section ovals, bald faceless head, no hair/clothing, hands articulated, soft pencil, white background, etc.)

### Pose substitution for younger archetypes

Some poses don't apply to younger archetypes and must be substituted. Substitution rules per the user's existing system:

| Original pose      | child / toddler / baby substitute |
|--------------------|-----------------------------------|
| `contrapposto_classic` | toddler/baby → `idle_casual` |
| `sit_chair_neutral` | toddler/baby → `sit_floor_crossed` |
| `run_jog`           | baby → `idle_casual` variant |
| `combat_ready`      | child/toddler/baby → `reach_up` |
| `recline_prop`      | baby → `recline_flat` |
| `jump_air`          | toddler/baby → `reach_up` variant |
| `combat_kick_high`  | child/toddler/baby → `lean_forward` or `wave` |
| `power_stance` (camera one-offs) | preteen and younger → `idle_casual` |

### Limited view set for toddler/baby

Per the existing build order: toddler and baby use only 3 views (`front`, `side_L`, `back`) instead of 6. Total prompts for toddler/baby = 3 views × 6 poses = 18 prompts (not 62).

App must detect this case and adjust the generation queue accordingly.

---

## 7. Reference Selection Algorithm

For each of the 62 prompts, the app must select exactly **3** reference images to attach to the API call. Maximum is 3 — more causes averaging and quality loss.

### Reference pool

For a given archetype, the reference pool is:
- 6 CSP turnarounds (`csp_front`, `csp_side_L`, etc.) — uploaded by user
- 0–N locked anchors (populated as the app generates them)

### Selection rules

```
function select_references(archetype, prompt):
    pose = prompt.pose                  # e.g. "contrapposto_classic"
    view = prompt.view                  # e.g. "front"
    pose_category = prompt.category     # standing / walking / sitting / etc.

    # 1. The closest-three CSP views per the user's existing logic
    closest_csp = closest_three_csps(view)
    # Examples:
    #   view=front       → [csp_front, csp_3q_front_L, csp_3q_front_R]
    #   view=side_L      → [csp_side_L, csp_front, csp_3q_front_L]
    #   view=side_R      → [csp_side_R, csp_front, csp_3q_front_R]
    #   view=back        → [csp_back, csp_side_L, csp_side_R]
    #   view=3q_front_L  → [csp_3q_front_L, csp_front, csp_side_L]
    #   view=3q_front_R  → [csp_3q_front_R, csp_front, csp_side_R]

    # 2. After the archetype anchor (prompt #1) is generated and locked,
    #    swap it in for csp_front on standing/walking/sitting/kneeling/combat
    #    prompts. Keep the other two CSP views.
    if archetype.has_anchor("front_contrapposto_classic")
       and pose_category in ["standing", "walking", "sitting", "kneeling", "combat"]
       and "csp_front" in closest_csp:
        closest_csp.replace("csp_front", archetype.anchor("front_contrapposto_classic"))

    # 3. For non-standard views — recline_prop, jump_air, foreshortening_reach,
    #    and the camera-angle one-offs — keep all three CSP turnarounds.
    #    CSP outperforms the locked anchor on these.
    if pose in ["recline_prop", "jump_air", "foreshortening_reach",
                "low_angle_hero", "high_angle_vulnerable"]:
        return closest_csp_unmodified(view)

    return closest_csp
```

### Closest-three lookup table (hardcode this)

```
front       → [front, 3q_front_L, 3q_front_R]
side_L      → [side_L, front, 3q_front_L]
side_R      → [side_R, front, 3q_front_R]
back        → [back, side_L, side_R]
3q_front_L  → [3q_front_L, front, side_L]
3q_front_R  → [3q_front_R, front, side_R]
```

---

## 8. OpenAI API Integration

### Endpoint

`POST https://api.openai.com/v1/images/edits`

The Edits endpoint (not Generations) is the correct one — it accepts both a prompt and reference images.

### Request shape

Multipart form data:
- `model`: `"gpt-image-2"` (configurable in settings, fallback to `"gpt-image-1.5"` or `"gpt-image-1"` if user prefers)
- `image[]`: 3 PNG files (the selected references)
- `prompt`: full prompt string (~2,000–3,000 chars)
- `size`: `"1024x1536"` for portrait, `"1536x1024"` for landscape (closest available to A4)
- `quality`: `"high"` (configurable; `"medium"` cuts cost ~40%)
- `input_fidelity`: `"high"` (preserves reference image style)
- `n`: 1
- `output_format`: `"png"`

### Response handling

- Response returns base64-encoded PNG in `data[0].b64_json`
- Decode and write to `output/<archetype_id>/<filename>.png`
- Track `usage.total_tokens` for cost calculation

### Error handling

| Error                         | Action                                                                  |
|-------------------------------|-------------------------------------------------------------------------|
| 401 Unauthorized              | Prompt user for valid API key, halt batch                              |
| 429 Rate limit                | Exponential backoff: 5s → 10s → 20s → 40s → fail after 4 retries       |
| 500/502/503/504 Server error  | Retry up to 3× with 10s gap, then mark this prompt failed and continue |
| 400 Bad request               | Log full prompt + reference paths, mark failed, continue               |
| Content policy rejection      | Mark failed, continue, surface in summary                              |
| Network timeout (>120s)       | Retry once, then mark failed                                            |
| Output decode failure         | Save raw response for debugging, mark failed                            |

Failed prompts go to a per-batch `failures.json` and can be re-run individually from the UI.

### Concurrency

**Sequential, not parallel.** OpenAI's image API has tight rate limits and complex prompts can take 60–120s each. Parallel calls invite 429 errors. A 62-image batch takes 30–80 minutes — acceptable for an unattended run.

### API key storage

- Stored in OS-native secure store (`QtKeychain` library) — not in plaintext config.
- User enters key once via Settings dialog.
- Never logged to disk or stdout.

### Cost tracking

After each successful generation:
- Read `usage.total_tokens` from response
- Compute cost using current pricing (configurable in `pricing.json`, user can update if OpenAI changes rates)
- Update running batch total in UI
- Append line to `output/<archetype_id>/cost_log.csv`

Default cost estimate: $0.20/image (high quality, portrait, 3 refs). Show estimated total before user clicks Generate.

---

## 9. File System Layout

```
~/.config/9livesk9/                       # Qt standard config dir
├── config.json                           # output dir, model preference, etc.
└── pricing.json                          # current OpenAI rates

<user_chosen_root>/                       # set on first run, e.g. ~/9LivesK9/
├── archetypes/
│   ├── F_adult/
│   │   ├── archetype.json
│   │   ├── csp_references/
│   │   │   ├── front.png
│   │   │   ├── side_L.png
│   │   │   ├── side_R.png
│   │   │   ├── back.png
│   │   │   ├── 3q_front_L.png
│   │   │   └── 3q_front_R.png
│   │   └── locked_anchors/
│   │       └── F_adult_front_contrapposto_classic_01.png
│   ├── F_yadult_curvy/
│   │   └── ...
│   └── ... (one folder per archetype)
├── output/
│   ├── F_adult/
│   │   ├── F_adult_front_contrapposto_classic_01.png
│   │   ├── F_adult_side_L_contrapposto_classic_01.png
│   │   ├── ... (62 PNGs total)
│   │   ├── cost_log.csv
│   │   └── batch_log.json
│   └── ...
└── templates/
    ├── prompt_templates.json             # parsed from F_adult_lora_base_set.pdf
    ├── proportion_rules.json             # age tier → anatomy bullets
    └── locked_style_block.txt            # the 10 constant style bullets
```

App-bundled (read-only, ship with installer):
```
<install_dir>/
├── 9livesk9                              # binary
├── templates/                            # default templates (copied to user dir on first run)
│   ├── prompt_templates.json
│   ├── proportion_rules.json
│   └── locked_style_block.txt
└── resources/
    └── icons/
```

---

## 10. GUI Design

Qt Widgets, native look (no custom theming in v1). Three primary screens.

### 10.1 Main Window

```
┌──────────────────────────────────────────────────────────────────┐
│ 9LivesK9 Base Pose Library                          [_] [□] [×]  │
├──────────────────────────────────────────────────────────────────┤
│ File   Edit   Settings   Help                                    │
├────────────────────────┬─────────────────────────────────────────┤
│                        │                                         │
│  ARCHETYPES            │  F_adult                                │
│  ─────────────         │  ──────────────────────                 │
│                        │  Female Adult, 8 head-heights           │
│  ▼ Built-in            │  Style: (default)                       │
│    ● F_adult        ✓  │                                         │
│    ○ M_adult           │  CSP References          [Replace All]  │
│    ○ F_yadult          │  ┌────────┬────────┬────────┐           │
│    ○ M_yadult          │  │ front  │ side_L │ side_R │           │
│    ○ F_teenM           │  │  ✓     │  ✓     │  ✓     │           │
│    ○ M_teenM           │  └────────┴────────┴────────┘           │
│    ○ F_teenY           │  ┌────────┬────────┬────────┐           │
│    ○ M_teenY           │  │  back  │3q_F_L  │3q_F_R  │           │
│    ○ F_preteen         │  │  ✓     │  ✓     │  ✓     │           │
│    ○ M_preteen         │  └────────┴────────┴────────┘           │
│    ○ child             │                                         │
│    ○ toddler           │  Output folder:                         │
│    ○ baby              │  ~/9LivesK9/output/F_adult/      [...]  │
│                        │                                         │
│  ▼ Custom              │  Locked anchors: 0                      │
│    + Create New...     │  Generated images: 0 / 62               │
│                        │                                         │
│                        │  Estimated cost: $11.50 – $13.80        │
│                        │                                         │
│                        │  ┌────────────────────────────────────┐ │
│                        │  │   GENERATE ALL 62 IMAGES           │ │
│                        │  └────────────────────────────────────┘ │
│                        │                                         │
│                        │  [ View Last Batch Log ]                │
│                        │                                         │
├────────────────────────┴─────────────────────────────────────────┤
│ Status: Ready                                  API: connected ●  │
└──────────────────────────────────────────────────────────────────┘
```

**Behaviors:**
- Left panel: scrollable list, two collapsible sections (Built-in, Custom). Right-click custom archetype → Edit / Delete / Duplicate.
- Selecting an archetype loads its detail view on the right.
- Reference thumbnails: click to view full size, right-click to replace single reference.
- "Replace All" opens file picker and expects 6 named files (front.png, side_L.png, etc.) or lets user pick 6 files and assigns them.
- Generate button is disabled if any of the 6 CSP references are missing.
- Estimated cost = images × per-image rate × (1 + retry buffer 0.2). Shows range based on quality setting.

### 10.2 Create New Archetype Wizard (modal, 4 steps)

**Step 1: Identity**
```
┌─ Create New Archetype — Step 1 of 4 ───────────────────────────┐
│                                                                 │
│  Identity                                                       │
│                                                                 │
│  Gender:                                                        │
│    ( ) Female      ( ) Male      ( ) Androgynous                │
│                                                                 │
│  Age Tier:                                                      │
│    [ Young Adult (18+) — 7.5 head-heights         ▼ ]           │
│                                                                 │
│    ℹ Auto-populated proportions for this tier:                  │
│       • 7.5 total head-heights (range 7.0–7.5)                  │
│       • Shoulders 1.75–2 head-widths                            │
│       • Slightly less pronounced waist than adult               │
│       • Joints articulated but softer than adult                │
│                                                                 │
│                                       [ Cancel ]  [ Next > ]    │
└─────────────────────────────────────────────────────────────────┘
```

**Step 2: Style**
```
┌─ Create New Archetype — Step 2 of 4 ───────────────────────────┐
│                                                                 │
│  Style                                                          │
│                                                                 │
│  Style Tag:                                                     │
│    [ curvy_____________________ ]                               │
│                                                                 │
│    Used in archetype ID: F_yadult_curvy                         │
│    Used in filenames:    F_yadult_curvy_front_..._01.png        │
│                                                                 │
│  Style Notes (injected into ANATOMY block):                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Hourglass silhouette, fuller hips and bust, soft waist     │ │
│  │ taper accentuated, otherwise young-adult proportions.      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│    Tips: be specific about silhouette, body composition, and    │
│    any departures from the base age-tier proportions.           │
│                                                                 │
│                              [ < Back ]  [ Next > ]   [ Cancel ]│
└─────────────────────────────────────────────────────────────────┘
```

**Step 3: CSP References (6 file pickers)**
```
┌─ Create New Archetype — Step 3 of 4 ───────────────────────────┐
│                                                                 │
│  CSP Turnaround References                                      │
│                                                                 │
│  Upload 6 turnaround images of your CSP base pose model in      │
│  default A-pose. PNG, max 4 MB each, min 1024 px on the         │
│  shorter side.                                                  │
│                                                                 │
│   front:       [ front.png             ]  [ Browse ]  ✓         │
│   side_L:      [ side_L.png            ]  [ Browse ]  ✓         │
│   side_R:      [ side_R.png            ]  [ Browse ]  ✓         │
│   back:        [ back.png              ]  [ Browse ]  ✓         │
│   3q_front_L:  [ 3q_front_L.png        ]  [ Browse ]  ✓         │
│   3q_front_R:  [ (none selected)       ]  [ Browse ]  ⚠         │
│                                                                 │
│   [ Auto-detect from folder ]                                   │
│                                                                 │
│                              [ < Back ]  [ Next > ]   [ Cancel ]│
└─────────────────────────────────────────────────────────────────┘
```

- "Auto-detect from folder" prompts for a directory and matches files by name (`front.png`, `side_L.png`, etc.). Useful since the user is producing these in CSP and exports a known-named set.
- Next is disabled until all 6 are valid.

**Step 4: Confirm**
```
┌─ Create New Archetype — Step 4 of 4 ───────────────────────────┐
│                                                                 │
│  Review & Create                                                │
│                                                                 │
│  Archetype ID:    F_yadult_curvy                                │
│  Display name:    Young Adult Female (Curvy)                    │
│  Gender:          Female                                        │
│  Age Tier:        Young Adult (18+) — 7.5 head-heights          │
│  Style tag:       curvy                                         │
│  References:      6 / 6 ✓                                       │
│                                                                 │
│  Files will be saved to:                                        │
│    ~/9LivesK9/archetypes/F_yadult_curvy/                        │
│                                                                 │
│                          [ < Back ]  [ Create Archetype ]       │
│                                            [ Cancel ]           │
└─────────────────────────────────────────────────────────────────┘
```

### 10.3 Generation Progress (modal, blocks main window)

```
┌─ Generating F_adult ────────────────────────────────────────────┐
│                                                                 │
│  ████████████████████░░░░░░░░░░░░░░░  37 / 62  (59%)            │
│                                                                 │
│  Now generating: F_adult_back_walk_neutral_01.png               │
│  Reference set:  csp_back, csp_side_L, csp_side_R               │
│                                                                 │
│  Elapsed:        24:18                                          │
│  Remaining:      ~17:00                                         │
│  Cost so far:    $7.31 / ~$12.40 estimated                      │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ✓ F_adult_front_contrapposto_classic_01.png       $0.19    │ │
│  │ ✓ F_adult_side_L_contrapposto_classic_01.png      $0.21    │ │
│  │ ✓ F_adult_side_R_contrapposto_classic_01.png      $0.20    │ │
│  │ ✓ ... (33 more)                                            │ │
│  │ ⚠ F_adult_3q_front_L_run_jog_01.png  failed — retry?       │ │
│  │ ⟳ F_adult_back_walk_neutral_01.png   generating (00:42)    │ │
│  │ ⊙ F_adult_3q_front_L_walk_neutral_01.png    queued         │ │
│  │ ⊙ ... (24 more)                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  [ Pause Batch ]   [ Open Output Folder ]   [ Cancel Batch ]    │
└─────────────────────────────────────────────────────────────────┘
```

**Behaviors:**
- Live log scrolls automatically; user can scroll up to inspect.
- Failed items show a "retry" link inline. Failures are also queued at the end of the batch for one auto-retry.
- Pause: finishes current request, halts queue, button changes to Resume.
- Cancel: confirms, then aborts after current request finishes.
- After completion: dialog summarizes successes/failures and offers "Open Output Folder."
- After prompt #1 succeeds, the app saves it as the archetype's locked anchor and the log shows: `🔒 Locked as anchor: F_adult_front_contrapposto_classic_01.png`.

### 10.4 Settings Dialog

```
┌─ Settings ──────────────────────────────────────────────────────┐
│                                                                 │
│  API                                                            │
│    OpenAI API Key:    [ ••••••••••••••••••••• ]   [ Update ]    │
│    Connection:        ● Connected (last checked 2m ago)         │
│                                                                 │
│  Generation                                                     │
│    Model:             [ gpt-image-2          ▼ ]                │
│    Quality:           ( ) low  ( ) medium  (●) high             │
│    Input fidelity:    ( ) low  (●) high                         │
│                                                                 │
│  Storage                                                        │
│    Root folder:       [ ~/9LivesK9/                  ] [...]    │
│    Output organized by archetype: [✓]                           │
│                                                                 │
│  Cost                                                           │
│    Per-image estimate (high quality, portrait): $0.20           │
│    [ Edit pricing ]                                             │
│                                                                 │
│  Advanced                                                       │
│    Max parallel requests: [ 1 ▼ ] (sequential is recommended)   │
│    Retry on failure:      [✓]                                   │
│    Save raw API responses for debugging: [ ]                    │
│                                                                 │
│                                          [ Cancel ]  [ Save ]   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 11. Build Phases

### Phase 1 — API parity validation (Python, ~1 evening)

**Deliverable:** `validate_api.py` — standalone script.

**What it does:**
1. Reads `OPENAI_API_KEY` from environment.
2. Loads 3 hardcoded reference paths and the prompt #1 text from `F_adult_lora_base_set.pdf`.
3. Calls `client.images.edit(...)` with `gpt-image-2`, high quality, 1024×1536.
4. Saves output as `validation_output_<timestamp>.png`.
5. Prints token count and estimated cost.
6. Repeats 3 times with same inputs for variance check.

**Success criteria (user's call):** output is at or near the visual quality of the user's existing `F_adult_front_contrapposto_classic_01.png`. If yes, proceed to Phase 2. If no, iterate on the prompt prefix or model parameters before continuing.

### Phase 2 — Build-time PDF parsing (Python, one-off)

**Deliverable:** `parse_prompts.py` + generated `prompt_templates.json`.

**What it does:**
1. Parses `F_adult_lora_base_set.pdf` page by page.
2. Extracts each prompt's body, reference attachment list, filename, and orientation.
3. Identifies which lines are archetype-specific (ANATOMY block, ARCHETYPE label, HEAD-HEIGHT GRID line) and replaces with `{{PLACEHOLDER}}` tokens.
4. Emits structured JSON: array of 62 entries with `{ filename, view, pose, category, orientation, reference_keys, prompt_template }`.

This JSON ships with the app — the parser script isn't included in the binary.

### Phase 3 — Qt C++ skeleton (1–2 days)

**Deliverable:** Compilable, runnable empty app with:
- Main window with archetype list (empty), detail panel
- Settings dialog (UI only, doesn't save yet)
- Create Archetype wizard (UI only, doesn't write files)
- "Generate" button that prints "TODO" to a log

Goal: lock the UI layout before wiring logic.

### Phase 4 — Archetype management (1–2 days)

- Load/save `archetype.json`
- Built-in archetypes seeded on first run
- Wizard creates custom archetypes and writes files
- Reference upload, validation, and storage
- Edit/delete/duplicate custom archetypes

### Phase 5 — Generation engine (2–3 days)

- Load `prompt_templates.json`
- Build full prompts per archetype
- Reference selection algorithm
- OpenAI API client (Qt Network)
- Sequential batch loop with progress signaling
- Error handling, retries, failure queue
- Cost tracking
- Locked anchor save + reuse

### Phase 6 — Generation UI (1–2 days)

- Progress dialog wired to engine
- Live log
- Pause/resume/cancel
- Per-item retry
- Completion summary

### Phase 7 — Polish (1 day)

- About dialog
- Help links
- Crash log capture
- App icon
- Installer (deb + AppImage for Kubuntu)

**Total:** ~8–12 working days for a solo dev with Claude Code as the primary writer.

---

## 12. Error Handling Summary

| Failure mode | UI response | Log behavior |
|---|---|---|
| API key invalid | Modal, halt, redirect to Settings | `errors.log` |
| Rate limit (429) | Inline notice, auto-retry with backoff | `batch_log.json` |
| Server error (5xx) | Inline notice, auto-retry | `batch_log.json` |
| Bad prompt (400) | Mark item failed, continue, surface in summary | full prompt in `failures.json` |
| Content policy | Mark failed, continue | `failures.json` |
| Network timeout | Auto-retry once, then mark failed | `batch_log.json` |
| Missing reference file | Pre-flight check before batch starts; refuse to begin | n/a |
| Disk full | Halt batch, modal | `errors.log` |
| User cancel | Save state, allow resume from same point | `batch_log.json` |

All logs are plaintext or JSON, stored in `output/<archetype_id>/logs/`. No external telemetry.

---

## 13. Cost Tracking

- Per-image cost computed from `usage.total_tokens` × `pricing.json` rates.
- `pricing.json` is user-editable in case OpenAI changes rates between app updates.
- Per-batch CSV: `output/<archetype_id>/cost_log.csv` with columns: `timestamp, filename, input_tokens, output_tokens, cost_usd, status`.
- Lifetime spend visible in Settings → Cost panel.
- Pre-flight estimate shown before user clicks Generate; updated continuously during batch.

---

## 14. Future Extensions (out of scope for v1, document for later)

- Batch generate multiple archetypes overnight
- Custom pose definitions (currently 10 hardcoded poses)
- Custom view definitions (currently 6 hardcoded views)
- Image post-processing (auto-crop to A4 print bleed, watermark removal, etc.)
- Cloud sync for archetypes across machines
- Sharing custom archetypes between users (export/import bundle)
- Direct print integration (skip the file-saving step)
- Alternative providers (Stable Diffusion local, Midjourney via Discord bot, etc.)

---

## 15. Acceptance Criteria for v1

- [ ] User can install on Kubuntu via .deb or AppImage in under 2 minutes.
- [ ] User can enter API key once and it persists across launches.
- [ ] User can select F_adult, click Generate, and 62 PNGs land in the output folder within 90 minutes.
- [ ] Output PNGs match the existing manual workflow's visual quality (validated in Phase 1).
- [ ] User can create `F_yadult_curvy` from scratch in under 5 minutes (excluding CSP file production).
- [ ] User can run `F_yadult_curvy` end-to-end without the app needing any code changes.
- [ ] Failed prompts can be re-run individually without re-running the whole batch.
- [ ] Cost shown post-batch is within ±10% of the actual OpenAI bill.
- [ ] Toddler/baby archetypes correctly generate 18 images instead of 62.
- [ ] App does not lose data if killed mid-batch (resume from last completed prompt).

---

## 16. Notes for Claude Code

- This spec is the source of truth. If you disagree with a decision here, raise it with the user before changing it.
- Where the spec is ambiguous, ask the user. Do not invent.
- `F_adult_lora_base_set.pdf` is in the project — the user will provide it when you reach Phase 2. Treat it as the gold standard for prompt structure.
- The user's existing `Updated_Base_Pose_Library_Setup_v2.docx` documents the design system in plain English. Read it for context.
- Phase 1 (Python validation) **must complete and be approved by the user** before any C++ code is written. Do not skip this.
- After each phase, stop, summarize what's built, and wait for user approval before starting the next phase.
- Prefer Qt's built-in classes over external dependencies. Only pull in `QtKeychain` (for secure API key storage); everything else should be Qt-native.
- All user-facing strings go through `tr()` for future localization — even in v1.
- Code style: Qt's standard (camelCase methods, four-space indent, header guards, no `using namespace` in headers).
- Commit small, commit often. Each phase = one or more commits.
