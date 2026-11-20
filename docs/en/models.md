# Models and adapter status

These are project observations from 2026-11-20, not reproducible public benchmarks. G4 in those runs was an RTX PRO 6000 Blackwell 96 GB. Timings depend on warm weights, resolution, shot length and reference count. All adapters are retained for research; none has been GPU-tested in this exported repository.

| Adapter | Observed time per shot | Best use / limitation |
|---|---:|---|
| Box H3, ref engine + 4-step LoRA | ~40 s | Best multi-reference robot identity; separate proprietary Box runtime required |
| LTX-2.5 distilled | ~40 s | Strong human close-ups and single keyframe; robot transformations can drift |
| LTX DFR + detail LoRA | ~50 s | Sharper; can redesign transforming subjects |
| Pika H3 Flex single CLI | ~830 s | Reloads weights every shot |
| Pika batch | ~360 s | Sampling ~305 s + decode ~57 s; first text encoding ~200 s; slower than Box H3 |
| Hyperflow H3 Flash | 270–310 s at 6 steps; 350–400 s at 8 | Experimental; missing FA3 on Blackwell, scene-lock drift; H100 retest needed |
| RelayVSR X2 | 6–8 s inference, 26–53 s including loading | Useful 2× enhancement; preserve original audio; transfer can dominate |
| Open-H3 Regenerate IC | ~237 s per 5 s window | Experimental, ~8 minutes per clip; slight face changes, expensive |
| MagiHuman | No successful clip | G4 720p/1080p enhancement ran out of memory; additional gated encoders |

Box H3 measured around -15 to -20 LUFS; LTX distilled around -8 to -17; DFR -9 to -19; Pika -17 to -19. Listen and normalize during mixing rather than assuming equal loudness. For fair comparison keep shots, references/keyframe, seed, duration and resolution fixed; include speech, body motion and a transformation. Compare identity and action using frame strips, then listen to lipsync and foley. Distinguish warm inference from startup/download time.

Candidate notes from the same source log: HunyuanVideo-1.5 was excluded because it did not produce sound; Wan 2.7 was listed as API-only and was not integrated. These historical notes are not a current market survey. Pika and Hyperflow remain experimental adapters; MagiHuman is a failed experiment retained for future work. H3 A/B is a Box-dependent tuning adapter. RelayVSR and regenerate live in lab/enhance.py; lab/relayvsr_film.py handles batch enhancement.

Code license does not grant model rights. Review [MiniMax-H3's license](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE): territory exclusions include US, EU, UK and South Korea, and AI labelling is required. Review derivative licenses too. Accept the gated licenses for [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) and [its upscaler](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler) before using their weights. Use official repositories and verify revisions/checksums; do not substitute third-party weight mirrors.
