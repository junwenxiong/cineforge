# CineForge · 影铸

[中文](README.zh-CN.md) · [Start here](docs/en/getting-started.md) · Apache-2.0

Turn a paragraph into a plan for a roughly 30-minute AI film with dialogue, music and subtitles. CineForge gives your coding agent the scripts and production playbook to write shots, prepare reference images, send video jobs to your Colab GPUs, review mistakes and assemble a film. You still choose images, listen to dialogue and approve retakes. This is an early toolkit, not a finished one-click movie app.

You need Python 3.10+, ffmpeg/ffprobe, a Colab Pro/Pro+ account with available GPU credit, and Claude Code, Codex or Gemini CLI. Linux/WSL is the main local environment. Optional Box/browser controls require Windows Python and a separate Chrome profile. Reference images need your own image service or manually created images; that service can have additional charges.

## Five-step quick start

1. Open this repository in your agent CLI. Read [getting started](docs/en/getting-started.md), then run `python3 tools/smoke_test.py` (no GPU or internet needed).
2. Run `python3 tools/new_film.py starcore --example starcore`. This copies the text example into `films/starcore`. For your own story use `python3 tools/new_film.py myfilm`, then ask the agent to follow [the playbook](skills/cineforge/SKILL.md).
3. Fill in the story, scenes, shots and reference images. Run `python3 tools/validate_film.py --film starcore`. Missing media is expected initially; add `--require-media` before rendering. Review three difficult pilot shots first.
4. Follow [render farm](docs/en/render-farm.md) to configure a backend and launch your own Colab workers. H3's fast worker requires your separately licensed Box installation. The LTX adapter uses official inference code and is still an experimental workflow.
5. Review [QA and retakes](docs/en/qa-and-retakes.md), then [edit and master](docs/en/editing.md). Drain workers, delete their runtimes and check billing after completion.

## Time, cost and current limits

Project measurements dated 2026-11-20: warm Box H3 around 40 seconds per shot on a G4; LTX distilled around 40 seconds; Pika batch around 360 seconds. These are selected shot measurements, not an end-to-end film benchmark. No verified total elapsed time, dollar bill or CU total is available for a 331-shot film on four G4s. Downloads, image creation, retakes, uploads and editing add time. Set a budget in your Colab account and start with three shots. Session limits and GPU availability vary; four simultaneous sessions were observed on the author's account, not promised to everyone.

Working source features: per-film configuration, claim leases, resume receipts, upload decode checks, multi-film rendering, contact sheets, speech-aware cut estimates, music mixing and subtitles. Not yet verified from a fresh public install: a fully automatic paragraph-to-film run, GPU adapters or end-to-end mastering with regenerated assets. No bundled weights, images, music, public notebook or universal CLI. VLM review is agent-assisted, not an automatic pass/fail service. See [models](docs/en/models.md) for adapter status.

## Licenses and privacy

CineForge code is Apache-2.0; models and media have separate terms. MiniMax-H3's community license excludes the US, EU, UK and South Korea and requires AI-generated labelling. Read [the official H3 license](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE) before using or distributing outputs. LTX-2.5 is gated: accept its [model license](https://huggingface.co/Lightricks/LTX-2.5) and any required upscaler license on Hugging Face. Open weights do not mean unrestricted use.

HF/API tokens stay in process memory when entered using the documented route. Enter the tunnel address and farm credential only in your private notebook cell; never share that notebook with credentials present. Legacy browser automation reads ignored local URL/token files and is optional. The farm's default mode writes a local token file; use `--token-env` for memory-only authentication. See [SECURITY](SECURITY.md).

## Example films

- [Starcore Dawn / 星核黎明](examples/starcore/README.md) — main text example; film link coming soon.
- [Calico Signal / 三花信号](examples/catfilm/README.md) — film link coming soon.
- [Echo / 残响](examples/echo/README.md) — film link coming soon.

[Writing](docs/en/writing-a-script.md) · [Troubleshooting](docs/en/troubleshooting.md) · [FAQ](docs/en/faq.md) · [Contributing](CONTRIBUTING.md)
