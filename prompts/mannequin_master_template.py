MANNEQUIN_MASTER_TEMPLATE = r"""Generate a base mannequin template for an art reference library. Match this construction language exactly:

ARCHETYPE: {archetype_label}
VIEW: {view_description}
POSE CATEGORY: {category}
SPECIFIC POSE: {pose_description}
ORIENTATION: A4 {orientation}

LOCKED STYLE CONVENTIONS:
- Light blue pencil construction drawing
- Wireframe contour bands wrapping around form (Atari lines)
- Cross-section ovals at shoulder, elbow, wrist, hip, knee, ankle joints
- Bald, faceless head with center cross guideline
- No hair, clothing, accessories, or fantasy features
- Hands fully articulated with visible fingers
- Soft pencil line quality
- Clean white background

ANATOMY (per archetype):
- {head_count} total head-heights
- {anatomy_specs}
- Rebuild proportions for this archetype — do NOT just shrink an adult figure

POSE RHYTHM:
{pose_rhythm}

LINE OF ACTION:
- Draw the S-curve or primary rhythm line in red overlaid on the figure
- Curve runs from crown of head through spine and weight-bearing support to ground

HEAD-HEIGHT GRID:
- Numbered horizontal guidelines on left margin, 1 through {head_count}, dashed line at ground plane
- Grid must match the archetype's head count exactly

OUTPUT: Single full-body {view_description} mannequin in A4 {orientation} ratio, light blue pencil construction style, line of action overlaid in red."""
