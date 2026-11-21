# Getting started

Run all commands from the repository root. Install Python 3.10+, ffmpeg (including ffprobe and subtitle/font support), and a CJK font such as Noto Sans CJK. GPU weights stay on Colab, not your laptop.

```sh
python3 tools/setup.py init --venv
python3 tools/setup.py doctor
python3 tools/smoke_test.py
python3 tools/new_film.py starcore --example starcore
python3 tools/validate_film.py --film starcore
```

`init` copies `.env.example` to a private `.env` file, asks once for your Hugging Face token with hidden typing, checks it with Hugging Face, and with `--venv` creates `.venv` and installs `requirements.txt` into it. Running it again keeps what you already set. `doctor` checks Python, ffmpeg, fonts, packages, your token, LTX-2.5 license access, the helper programs and your assistant setup, and prints a `fix:` line for each problem. Only `FAIL` lines make it exit with an error. Use `doctor --offline` to skip the Hugging Face checks and `doctor --json` for machine-readable output. Prefer to install packages by hand? Run `python3 -m venv .venv`, `. .venv/bin/activate`, `pip install -r requirements.txt`.

`init --hand-model` also downloads the small MediaPipe hand model (about 8 MB) to `~/.cache/mp/hand_landmarker.task` for hand checks; nothing else is downloaded to your computer.

The smoke test uses only the standard library. Requirements cover optional image, QA and browser tools; inference dependencies are installed by each cloud adapter. On Windows activate `.venv/Scripts/activate`; use WSL for editing and POSIX file locks. Box queue tools currently require Windows Python (`msvcrt`).

`films/<name>/` holds editable story JSON, `assets/<name>/refs/` images, `assets/<name>/music/` licensed music, `renders/<shot_id>/` receipts and raw clips, `videos/<name>/` final exports. Examples are text only. Missing media is expected until you create it. Film and shot names must be safe path components; use a unique render_prefix per film. `--film` overrides `FILM`; default is starcore.

For a new story: `python3 tools/new_film.py myfilm`. Tell your agent: “Follow skills/cineforge/SKILL.md; turn this premise into a film, show me the story and three pilot shots before launching the full render.” Empty templates do not generate anything automatically.

## Your tokens and the .env file

Every secret lives in one private file, `.env`, in the repository root. Git ignores it, and on Linux it is readable only by you. You type the Hugging Face token once; after that the tools and your assistant (Claude Code, Codex or Gemini CLI) read it from `.env`, so you never paste it into chat. To replace it, run `python3 tools/setup.py init --reset-hf`. To add other keys, such as OPENAI_API_KEY, open `.env` in a text editor; `.env.example` explains each one. A value already set in your shell wins over `.env`.

Some tools only read environment variables. Run them through `python3 tools/setup.py run -- COMMAND`, which starts the command with `.env` loaded and prints nothing secret. On WSL, a repository under `/mnt/c` or `/mnt/d` cannot keep `.env` private (Windows drives ignore `chmod`); `doctor` warns about this. Cloning into your Linux home folder avoids it.

Your assistant also finds the CineForge skill and instructions on its own: Claude Code reads `CLAUDE.md` and `.claude/skills/`, Codex reads `AGENTS.md` and `.agents/skills/`, Gemini CLI reads `GEMINI.md` and `.agents/skills/`. These small files are part of the repository; `init` restores them if they are missing.

## Pictures

Images: place your own files at the refs paths, or add OPENAI_API_KEY to `.env` and run `python3 tools/setup.py run -- python3 tools/film/gpt_images.py --film starcore`. CINEFORGE_IMAGE_BASE_URL is an optional compatible server origin (without /v1). Never paste keys into tracked files, chat or commands saved in shell history. `gemini_images.py` is an optional Antigravity `agy` integration; merely installing Gemini CLI is not enough. Its inherited unrestricted tool mode needs explicit operator review before use.

Read [models](models.md) and [render farm](render-farm.md) before buying compute. First validate three shots, then scale up.
