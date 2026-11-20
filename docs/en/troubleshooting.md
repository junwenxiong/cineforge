# Troubleshooting

Rewritten from the source production lessons (2026-11-20). Hardware, limits and performance are observations, not guarantees.

## Session limits

Four sessions were observed on one Pro+ account, including Box and lab sessions. Closed GPU runtimes may leave tabs/session slots; close those too. Check current account limits rather than assuming four.

## Runtime resources

Observed G4: 96 GB GPU, ~176 GB RAM, ~236 GB free disk, Python 3.13; none guaranteed. Check free disk before 94–163 GB downloads. Use a dedicated uv environment when Python 3.12 is required.

## Matplotlib crashes

Set MPLBACKEND=Agg in child processes; notebook inline backends leak into subprocess environments.

## Preparing is not failed

vm_service can report ok:false while phase is preparing. Only ok is True or an error field is terminal; do not duplicate work.

## Safe shutdown

Drain first, wait for final saved receipts/uploads, then delete the runtime. Never stop a Box-owned GPU solely because farm progress stopped.

## Official weights

Mirrored LTX text encoders differed in checksum. Download from official repos and verify hashes/revisions.

## Long shots

H3 cost grows sharply with frame count. Prefer 5–6 seconds, one action per shot.

## Retries

Check job.json, claim.json and farm.log before retrying; a completed, decodable clip with SHA256 is the evidence.

## Heartbeat without work

The heartbeat thread can survive a stalled main loop. Watch saved events; after rerun require a fresh claim within a minute. farm_watch alerts after a long delivery gap.

## Orphan claims

A hot restart can lose claimed-but-not-persisted jobs for the 25-minute lease. Release only claims absent from every live worker current list after confirming ownership.

## Truncated transfers

Retry/cache reference downloads; full-decode raw uploads. Large lab uploads need 2 MB parts plus parts/size/output_sha256 metadata and vsr_assemble verification. A partial lab file is not success.

## Bandwidth

Measure first: source notes observed ~0.5 MB/s HF downloads locally and ~0.2 MB/s tunnel return (52 MB/250 s), not the much faster cloud download. Keep large data in cloud; return final outputs. A private dataset relay needs a separately authorized write token.

## Keep the GPU busy

Upload in background and process the next clip. Intermediate CRF 17 was sufficient in the source workflow; CRF 14 doubled size without visible benefit there.

## Batch failures

Catch errors per item, log and continue; skip verified receipts on resume. Simulate upload errors/timeouts locally before expensive GPU restarts. Model reloads cost minutes.

## Module collisions

Do not name helper scripts dl.py or after common libraries. Use _hf_fetch.py and inspect old outputs before a rerun so stale receipts do not skip unfinished work.

## Tunnel disconnect

QUIC failed behind a local proxy in the source setup; HTTP/2 helped. Keep the tunnel process alive. If the URL changes, update private cells and reconnect workers. A stuck Colab UI may need page reload before reboot, then verify a claim.

## Speech and subtitles

Use speech-aware actual-duration cuts; do not use requested duration × 0.92. Accumulate actual segment durations to prevent subtitle drift. See editing.md.

## Soft images

Most softness was generated, not introduced in editing (source measured only 2–3% editing loss). Use deep focus and detailed skin/fabric, distant haze only; RelayVSR can help without fixing bad anatomy.

## Back views and duplicates

Use partially_preserved for hidden faces. One subject once per ref; no inset views or animals in prop sheets. Rename replacement refs to defeat caches. Prompt-only retries cannot fix duplicate-subject reference art.

## Missing refs and rate limits

Image-service 429 errors left entire scenes waiting. Check missing refs and image logs, reduce concurrency, regenerate missing files and revalidate.

## Box stalled queue

A disconnected Box can leave jobs in_progress forever. Coordinate stopping its queue before archiving stuck receipts and handing shots to the farm.

## LTX allocation

Old forward/reverse queues used ltx_prune. Current index-sharded workers need one fixed list; do not mix these strategies or change worker count mid-run.

## LTX rescue

Source QA reported 15 persistent H3 failures fixed with new keyframes + LTX, and only two errors in a 262-shot LTX review, both bad keyframes. These are observations, not a quality guarantee.

## Worker names and process matching

Use distinct names, not x/xB; target notebook titles exactly before stopping. pgrep patterns appearing in their own command line can match themselves forever.

## Slow workers

Drain slower GPUs first near completion; source A100 shots were ~100 s versus G4 ~42 s. Verify uploads before kill_when_drained.sh or any browser action.

## Sudden close-ups

If a face suddenly fills the screen after a cut, compare the neighboring shots' planned sizes. Use the [shot-size ladder](glossary.md#shot-size-how-much-you-see) to decide how much of the person and surroundings should stay visible. The current LTX picture instructions favor MS/MCU unless shot_size explicitly requests CU/ECU. The LTX video instructions also remove unwanted push-ins and ask for a steady camera. These instructions help, but do not automatically match framing between clips: inspect the starting pictures and watch the cut before accepting it.

**The face grows during the shot.** Most "slams" are not camera moves: in LTX close-ups the person walks or leans toward the lens, and a CU often ends as an extreme close-up. This happens most when the prompt describes a tighter shot than the starting picture shows, or says things like "the shot ends holding on her eyes". What fixed it for us (echo, 2026-11-20):

1. Rewrite the prompt with `tools/film/static_cam.py`: camera lock and "everyone stays the same distance from the camera" go first, push-in phrases are removed, and the size words match the starting picture. Shots converted from H3 first go through `tools/film/h3_to_ltx.py`.
2. Measure every take with `tools/film/zoom_check.py` (face growth, background zoom, hidden cuts inside the clip).
3. Render a second seed for shots that still grow, then let `tools/film/pick_takes.py` keep the best take per shot.
4. In the edit, `tools/film/push_trim.py` cuts away before the face starts growing, but never before a line of dialogue has finished.

Result on echo: shots whose face grew more than 2x went from 20 to 2. Do not anchor the last frame to the same keyframe: the model jumps to a close-up mid-shot and back.
