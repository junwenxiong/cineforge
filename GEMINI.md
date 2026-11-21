# CineForge agent instructions

This file mirrors AGENTS.md, the canonical copy; keep both in sync. Follow the Secrets section below (also in AGENTS.md).

Read skills/cineforge/SKILL.md and follow its sequence: story → references → three-shot pilot → render → QA/retakes → edit/master → drain/shutdown. Start with `python3 tools/setup.py doctor` (fix FAIL lines first; `--offline` skips network checks) and `python3 tools/smoke_test.py`. Use the documented scripts and --film configuration. Do not download model weights locally, expose credentials, operate paid resources or publish without user authorization. The small MediaPipe hand model from `python3 tools/setup.py init --hand-model` is the only local model download. Preserve human review and report unverified GPU paths honestly.

## Secrets

- Secrets live only in the gitignored `.env` at the repository root; `.env.example` lists the keys. The user stores the Hugging Face token once with `python3 tools/setup.py init`, typing it into a hidden prompt, never into chat. To change it: `python3 tools/setup.py init --reset-hf`.
- Tools read `.env` themselves. For a tool that only reads environment variables, run it as `python3 tools/setup.py run -- COMMAND ...`. Values already set in the shell win over `.env`.
- Never print, log, commit or paste a token or the contents of `.env`: not in commands, arguments, notebooks, issues, reports or other files. Do not `cat`, `source` or `echo` `.env`. Refer to a token by its name (`HF_TOKEN`) or as `hf_…` plus its length.
- If a token may have leaked, tell the user to revoke it at the provider, then run `python3 tools/setup.py init --reset-hf`.
