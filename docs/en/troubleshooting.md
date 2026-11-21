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

## Animal recasts: human hands instead of paws

When you restage real footage with animal characters (people → cats with `tools/film/lab/ltx_v2v.py`), faces, ears and fur come out right but the hands stay human: five fingers, pink fingertips, nails, sometimes "furry human hands". Three causes stack up:

1. **The control video carries the finger outlines.** The depth (or edge) map from the source shows every finger, and the model follows it.
2. **The wording invites it.** "Paw-hands" or "five short fingers" in reference, keyframe or video prompts reads as a furry human hand.
3. **The hand detector drops frames.** Clasped or overlapping hands, motion blur and film grain hide hands from MediaPipe for a second or more; unmasked frames keep the full finger outline.

What fixes it:

1. Find the hands in the source: `python3 tools/film/hand_mask.py source.mp4 --start S --dur D [--crop w:h:x:y] --out hands.json`. It merges a tracking pass and a low-confidence per-frame pass, pads and holds each box, and bridges gaps up to 1 s. Black-and-white footage works. It needs `mediapipe` and `opencv-python-headless` (in `requirements.txt`) and the MediaPipe hand model: `mkdir -p ~/.cache/mp && curl -L -o ~/.cache/mp/hand_landmarker.task https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task` (or set `HAND_MODEL`).
2. Put the result in the job as `"hands": {...}`. `ltx_v2v.py` then melts the control inside soft ellipses (heavily blurred depth: the arm and hand stay one smooth shape, fingers vanish; edges are erased) and lowers control attention there with `--conditioning-attention-mask` (`hand_attn`, default 0.1). Do not dilate inside the box with a hand-sized kernel: it leaves a hard bright rectangle that the model paints as a sheet of paper.
3. Describe real paws everywhere: "round furry paws, pink toe beans, same fur as the arm, NO separate fingers, NO fingernails, NO bare skin, never human hands; to hold something the paw curls around it". Review every keyframe's paws before rendering.
4. In long takes, give a cat keyframe as a mid-shot guide (`guides`) whenever a new character enters the frame or hands come into close-up (hand-holding, covering the face). A character who walks in without a guide is drawn as a human.
5. Check the result: `python3 tools/film/hand_check.py clip.mp4 --sheet hands.jpg`. MediaPipe only recognizes human hands, so it rarely fires on a real paw; each hit is scored for bare-skin likeness and put on a contact sheet. White or cream fur also scores high, so always look at the sheet.

**A character stays human mid-shot.** Only the first frame is drawn as cats, so any face that is not clearly visible in it has no cat version to follow and is copied from the source. Watch for:

- people who **enter** mid-shot;
- people who **turn toward the camera or lift their head** after starting turned away or face down (these often come out as cat ears on a human face or a human mouth);
- **blurred foreground heads or shoulders at the frame edge** that the image model left human in the first frame itself; the video then keeps them human throughout.

Fix: extract the source frame where the face appears, have the image model redraw that frame with the cat version (same composition; reuse the same description for a recurring extra), and pass it as a `guides` entry at strength 0.8. Mention the entrance in the video prompt too ("a grey tabby maid cat walks in from the left"). If the first frame already kept a human, redraw the first frame and name the edge figure in the prompt. Review the **whole reel as a 2 fps contact sheet**, then zoom into suspect faces; checking one frame per shot misses these.

**Garbled subtitles at the bottom of the frame.** Measured causes, most important first:

1. **Never mention text in the video prompt.** Any of "subtitles", "captions", "text", even "no subtitles", makes the distilled pipeline paint captions: it has no CFG, so negations add the concept instead of removing it. Same two shots, same controls: 67 and 40 frames with text → 0 and 0 after deleting that sentence, with the original dialogue still conditioning the audio (lip sync kept).
2. Subtitles burned into the source leave glyph dots at the bottom of the depth map. `ltx_v2v.py` inpaints white subtitle strokes and their outline in the bottom 22% of the source before computing the control (default; `clean_band: false` turns it off).
3. "TV drama" leans toward captions; say "period feature film, shot on 35mm".
4. Control videos are cached per shot ID; change the cache name when you change the control code.

Check with `python3 tools/film/desub.py clip.mp4 --check` (count only frames inside the shot length). `--out` patches small captions, but thin text on bright fur does not clean well, so re-render instead. `no_audio: true` drops the dialogue as audio conditioning (loses lip sync); you should rarely need it.
