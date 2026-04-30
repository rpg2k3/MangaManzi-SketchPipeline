# main_prompt/

Knowledge base for the 9LivesK9 Sketch Pipeline app's prompt-assembly engine.

## Files

| File | Purpose | Loaded by |
|---|---|---|
| `9LK9_PROJECT_SPEC.md` | Reference data: archetypes, views, poses, proportions, naming convention | Claude Haiku as background context |
| `9LK9_PROMPT_INSTRUCTIONS.md` | Behavioral system prompt: how Claude assembles per-pose prompts | Claude Haiku as system prompt for every call |

## Updating

These files are user-editable. After changes:
- Restart the app to reload the prompt knowledge.
- Run a single-pose test before triggering a full 62-pose batch.
- The next archetype's first generation is the verification point — compare against the CSP reference for that archetype.

## DO NOT

- Do not edit these files while a generation batch is in progress — changes won't apply mid-batch.
- Do not delete either file — the app will fail to load.
- Do not merge them into one file — the app loads them with different roles (background vs system prompt).
