# Getting started

Run all commands from the repository root. Install Python 3.10+, ffmpeg (including ffprobe and subtitle/font support), and a CJK font such as Noto Sans CJK. GPU weights stay on Colab, not your laptop.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 tools/smoke_test.py
python3 tools/new_film.py starcore --example starcore
python3 tools/validate_film.py --film starcore
```

The smoke test uses only the standard library. Requirements cover optional image, QA and browser tools; inference dependencies are installed by each cloud adapter. On Windows activate `.venv/Scripts/activate`; use WSL for editing and POSIX file locks. Box queue tools currently require Windows Python (`msvcrt`).

`films/<name>/` holds editable story JSON, `assets/<name>/refs/` images, `assets/<name>/music/` licensed music, `renders/<shot_id>/` receipts and raw clips, `videos/<name>/` final exports. Examples are text only. Missing media is expected until you create it. Film and shot names must be safe path components; use a unique render_prefix per film. `--film` overrides `FILM`; default is starcore.

For a new story: `python3 tools/new_film.py myfilm`. Tell your agent: “Follow skills/cineforge/SKILL.md; turn this premise into a film, show me the story and three pilot shots before launching the full render.” Empty templates do not generate anything automatically.

Images: place your own files at the refs paths, or run `python3 tools/film/gpt_images.py --film starcore` after setting OPENAI_API_KEY in the process environment. CINEFORGE_IMAGE_BASE_URL is an optional compatible server origin (without /v1). Never paste keys into tracked files or commands saved in shell history. `gemini_images.py` is an optional Antigravity `agy` integration; merely installing Gemini CLI is not enough. Its inherited unrestricted tool mode needs explicit operator review before use.

Read [models](models.md) and [render farm](render-farm.md) before buying compute. First validate three shots, then scale up.
