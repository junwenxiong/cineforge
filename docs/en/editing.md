# Editing, music and master

Install ffmpeg with libass/subtitle support and CJK fonts. Supply licensed tracks under assets/<film>/music and fill music_cues.json and film.json credits. Example cue filenames and attribution are historical references, not bundled music or proof of your license. Verify each source and keep its license/attribution record. Do not invent a soundtrack when files are missing.

```sh
python3 tools/film/speech_cut.py --film starcore --dry-run
python3 tools/film/speech_cut.py --film starcore
python3 tools/film/rough_cut.py --film starcore --name final
python3 tools/film/score_mix.py --film starcore --name final
python3 tools/film/master.py --film starcore --name final
```

Review speech_cut's proposed cuts before the second command. It estimates the last audible sound with ffmpeg silence detection, not semantic ASR/VAD; music/foley can keep the tail open. Override per shot in films/<film>/cut.json using in/out/drop. A useful human-reviewed out-point is min(actual duration − 0.05, speech end + 0.25). The source project found delayed speech (~2.4 seconds) and clips ~0.6 seconds longer than requested; cutting at requested duration × 0.92 clipped 32 of 59 lines.

The editor accumulates actual segment durations. Per-segment frame rounding previously produced 6.9 seconds of subtitle drift over 354 shots. Check subtitles near both start and end; do not rebuild the timeline from requested shot lengths. Listen to transitions and duck music under speech. Mix LTX's louder audio against H3 deliberately.

Optional HD: vsr_stage.py --films starcore --name final prepares enhancement tasks; lab/relayvsr_film.py runs on Colab, vsr_assemble.py verifies chunked returns. Confirm every desired shot has an enhanced result before adding --hd to rough_cut, score_mix and master. Missing HD clips fall back to scaled originals; that is not full-film enhancement. Outputs appear under videos/<film>/, including final_master.mp4 or final_hd_master.mp4. Decode the whole master, review dialogue/subtitles/credits and label AI-generated content before publishing.
