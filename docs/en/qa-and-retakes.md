# QA and retakes

Run `python3 tools/film/anatomy_strips.py` for 25%, 50%, 85% frame strips across rendered shots, or `python3 tools/film/qa_sheet.py --film starcore S01 S02`. Use `continuity_report.py --film starcore` for technical continuity metrics (requires NumPy and Pillow). A strip can miss a defect between frames: watch full clips and listen to dialogue before acceptance.

Ask your agent's vision model or a human to check subject count, limbs/tails, identity, props, background, one-action completion and readable framing against the refs. VLM review is advisory; there is no bundled automatic VLM runner. Save a JSON list like `[{"id":"myfilm_s01_01","defect":"extra tail / 多尾"}]` in ignored renders/qa/flags.json. Tail/duplication prompt repairs recognize Chinese defect keywords; inspect the dry-run and resulting prompt.

```sh
python3 tools/film/retake.py --film myfilm --flags renders/qa/flags.json --dry-run
```

Only rerun without --dry-run after checking job.json, claim.json and farm.log and confirming no worker is rendering/uploading that shot. The tool skips active leases, archives the previous take, adjusts prompts and resets attempts. It is intended for H3; stale leases or a second queue still require operator coordination. Never merely delete receipts to force work blindly.

Repeated H3 anatomy failures often originate in the reference image. Replace duplicate-subject refs first, using new filenames. If H3 still fails, make a clean single-subject keyframe, set engine to ltx, keyframe to its project-relative path, and ltx_prompt to one continuous English description with exact quoted dialogue and an Audio: section. Stop/drain owners and archive old receipts before stage/collect; collect intentionally does not overwrite existing jobs. Use ltx_stage.py --dry-run to inspect first. LTX output inherits mistakes in its keyframe.

Acceptance means a completed receipt, SHA256, successful full audio/video decode, correct subjects, complete speech and acceptable lipsync. A reachable page or a heartbeat is not acceptance. Regenerate anatomy strips after retakes: remove only the corresponding cached QA image, because the extractor skips existing strips.
