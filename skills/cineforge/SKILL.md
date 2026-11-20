---
name: cineforge
description: Plan, render, review and edit an AI film with CineForge scripts and the user's own compute.
---
# CineForge production playbook

Work from the repository root. Read README.md and docs/en/getting-started.md. Follow the user's budget, chosen backend, account limits and permission boundaries. Never launch paid GPU/image work, control a browser, publish, or stop somebody else's runtime without task authorization. Keep weights on Colab and credentials out of files/logs/notebook sharing. Do not use the user's daily browser or clipboard.

1. Run `python3 tools/smoke_test.py`. Create a film with `python3 tools/new_film.py NAME` (or `--example starcore`). Write the story bible, ordered scenes, exact dialogue, visual locks, refs and shot arrays. Follow docs/en/writing-a-script.md. Validate with `python3 tools/validate_film.py --film NAME`.
2. Prepare original references manually or via the documented image adapters. One subject once per image; no private photos without consent. Run the validator with `--require-media`. Have a human inspect references.
3. Select the three hardest pilot shots. Confirm model license and budget; show the pilot before opening the whole queue. H3 requires CINEFORGE_BOX_VM_DIR; LTX requires accepted HF gates and a keyframe. Do not claim an untested backend is working.
4. Follow docs/en/render-farm.md. Start farm_server.py with --films and --token-env. User-owned workers run one heavy task each. Inspect claims, saved events and missing refs; heartbeat alone is insufficient. Keep LTX indexed task lists fixed. Preview supervisor actions with --dry-run --once.
5. Run anatomy_strips.py and qa_sheet.py --film NAME SCENE. Review full clips and sound with human/VLM assistance; no automatic VLM runner is bundled. Use retake.py --dry-run first, preserve previous takes, and coordinate ownership before mutations. Persistent H3 anatomy failures: clean keyframe, engine=ltx, ltx_stage.py --dry-run, then stage/collect after authorized cloud work.
6. Run speech_cut.py --film NAME --dry-run, review then apply. Run rough_cut.py, score_mix.py, master.py each with --film NAME --name final. Supply licensed music and accurate credits; verify subtitles at both ends and fully decode the master. Optional RelayVSR requires verified enhanced clips before --hd.
7. Drain all owned workers, verify final uploads, then disconnect/delete their runtimes and verify billing stopped. Stop the local farm and tunnel. Report output paths, QA findings, measured costs/times and remaining defects. Publish only when explicitly authorized.

Use concrete scripts in tools/film; no fictional cineforge render CLI exists. Read docs/en/troubleshooting.md before retries. Cross-platform limits and adapter status are documented in docs/en/models.md and getting-started.md.
