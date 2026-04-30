# MangaManzi Sketch Pipeline

AI-orchestrated character pose library generator for manga and anime production. Built for the light-box underdrawing workflow — generates anatomically refined base mannequin templates and character sketches that hand-trace cleanly onto paper.

Originally built for the **9LivesK9** IP universe, designed to scale to any manga/anime character production pipeline.

## What It Does

Take a character reference sheet (PixAI, manual scan, etc.) → generate dozens of anatomically consistent pose sketches that align with a fixed library of mannequin templates. Print, light-box, hand-trace. The pipeline handles the proportional and pose construction work so the artist focuses on character details, expression, and inking.

## Architecture

| Lane | Provider | Role |
|---|---|---|
| Mannequin base generation | OpenAI gpt-image-1 | Creates 100+ pose templates per archetype with grid + line of action |
| Character sketch overlay | Google Gemini gemini-2.5-flash-image | Draws the character onto each mannequin, preserving design |
| Character extraction & prompt assembly | Anthropic Claude Haiku | Reads character sheets into JSON, assembles per-pose prompts |

Three providers, three independent jobs. Each chosen empirically based on production testing.

## Status

**Alpha — closed testing as of April 2026.**

Built solo. Architecture stabilized. F_adult archetype complete. Beta access by invitation.

## Setup

Requires:
- Python 3.13+
- Linux desktop (tested on Kubuntu 25.10)
- API keys from OpenAI, Anthropic, and Google
- API credit on each provider (~$5–10 each is plenty for testing)

```bash
git clone https://github.com/rpg2k3/MangaManzi-SketchPipeline.git
cd MangaManzi-SketchPipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

On first launch, you'll be prompted to enter your three API keys. They're validated immediately and stored in OS-native secure storage (Keychain/Credential Manager/Secret Service) — never in plaintext on disk.

## Project Structure

```
bases/csp_tvd/         Anatomy reference mannequins (CSP renders) per archetype
bases/gpt_tvd/         Style ideal mannequins (doctrine + contrapposto)
output/                Generated mannequin pose library [gitignored]
characters/            Character sheets + extracted JSON + sketches [gitignored]
prompts/main_prompts/  Master prompt knowledge files (style guide + behavior)
config/                App settings + per-archetype proportion overrides
```

## Cost Reality

Approximate cost for one full character build (mannequins already exist):

- Character extraction (Claude Haiku): ~$0.01
- Per-pose prompt assembly × 100: ~$0.50
- Sketch generation × 100 (Gemini): ~$2.00
- **Total per character: ~$2.50**

Mannequin base generation is one-time per archetype, ~$2.50 for F_adult.

## License

[See LICENSE file]

## Contributing

Currently in closed alpha. Bug reports welcome via [GitHub Issues](https://github.com/rpg2k3/MangaManzi-SketchPipeline/issues). Feature requests deferred until beta opens.

---

**MangaManzi** — manga production tools for the indie studio.
Built with Claude Code and a lot of stubbornness.
