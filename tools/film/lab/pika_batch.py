#!/usr/bin/env python3
"""Pika-H3-Flex（ref2va）批量推理：每个模型阶段整批只加载一次。

用法（Colab G4，在 pika_flex.py 建好的 venv 里运行，仓库已在 /content/pika/repo 执行过 pip install -e .）：
    /content/pika/venv/bin/python pika_batch.py jobs.json

jobs.json 是任务列表，每项字段：
    {"id": "s01", "prompt": "...", "seconds": 5, "resolution": "768p", "seed": 42,
     "refs": ["/content/pika/in/a.png", ...], "cpu_offload": false, "output": "/content/pika/out/s01.mp4"}
可选字段 "aspect"，默认 "16:9"。refs 默认按图片处理，也可以写 "video:路径" 或 "audio:路径"。

流程和官方 pika_h3.pipeline.generate() 一致，只是按阶段分批：
  A 条件编码：Qwen3-VL 加载一次，编码全部文本后释放；再加载 VAE 编码全部参考图后释放。条件张量留在 CPU。
  B 采样：Transformer 和 LoRA 只建一次，常驻显卡的任务先跑，需要 CPU offload 的任务后跑；
    后一组开始前把模型移回 CPU，再启用 group offload。常驻模式下 OOM 的任务会放进 offload 组重试一次。
  C 解码：解码器加载一次，逐个解码、写 mp4、校验，并把 json 元数据写在 mp4 旁边。
需要 offload 的任务：cpu_offload=true，或 768p 且图片参考不少于 4 张，或设置环境变量 PIKA_OFFLOAD=1（全部任务）。
已存在的 mp4 会跳过，不会覆盖。单个任务失败时把错误写进它的 json，整批继续；有任何失败时退出码为 1。
"""
import gc, importlib.metadata, json, os, sys, time, traceback
from argparse import Namespace
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("HF_HOME", "/content/hf")
MODEL_REPO, REVISION = "Pika-Labs/Pika-H3-Flex", "0ddf55ad7067ca1e76812253bd7b4600df87f759"
KINDS = ("image", "video", "audio")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(jobs_path):
    import pika_h3.pipeline as P
    from pika_h3.runtime import validate_runtime
    validate_runtime()
    import av, numpy as np, torch, yaml
    from pika_h3.core import geometry as G
    from pika_h3.core.conditioning import H3ConditionEncoder, Reference, Request, normalize_references, resolve_geometry
    from pika_h3.core.evaluation import EVAL_NOISE_VERSION, sample_evaluation_ladder
    from pika_h3.core.loader import apply_lora, build_transformer, load_lora_weights
    from pika_h3.core.media import preflight_reference_specs
    from pika_h3.core.numerics import configure_numerics_backend, prepare_conditioning
    from pika_h3.core.schedules import H3SigmaSchedule
    from pika_h3.core.vae import H3Decoders, write_mp4
    from pika_h3.core.wrapper import H3DiffusionWrapper
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for model generation")
    OOM = getattr(torch, "OutOfMemoryError", torch.cuda.OutOfMemoryError)
    bucket_file = Path(P.__file__).parent / "core" / "buckets.yaml"
    table = yaml.safe_load(bucket_file.read_text())
    batch_t0, batch = time.monotonic(), {}
    common = {}

    def meta(job):
        geom = job.get("geom")
        return {"id": job["id"], "task": "ref2va", "prompt": job.get("prompt"), "seed": job["seed"],
                "resolution": job.get("resolution"), "aspect": job["aspect"], "requested_seconds": job["seconds"],
                "geometry": asdict(geom) if geom else None, **common,
                "transformer_cpu_offload": job.get("offload_used", False), "timings": job["timings"],
                "sampling_peak_allocated_bytes": job.get("peak"), "reference_order": job.get("kinds"),
                "input_sha256": job.get("input_sha256"), "batch_timings": dict(batch), "error": job.get("error"),
                "traceback": job.get("traceback")}

    def write_meta(job):
        job["output"].parent.mkdir(parents=True, exist_ok=True)
        job["output"].with_suffix(".json").write_text(json.dumps(meta(job), indent=2, ensure_ascii=False) + "\n")

    def fail(job, stage, exc):
        job["error"], job["traceback"] = f"{stage}: {type(exc).__name__}: {exc}", traceback.format_exc()
        for key in ("request", "embeds", "cond", "latents", "normalized"):
            job.pop(key, None)
        log(f"[{stage}] {job['id']} FAILED {job['error']}")
        write_meta(job)

    def live():
        return [j for j in jobs if not j.get("error") and not j.get("skip")]

    def cleanup():
        gc.collect()
        torch.cuda.empty_cache()

    # ---- inputs: the same checks as cli.main() + generate() before any model loads
    jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8"))
    for i, job in enumerate(jobs):
        job.update(id=str(job.get("id", i)), output=Path(job["output"]), seed=int(job.get("seed", 42)),
                   seconds=int(job.get("seconds", 5)), resolution=job.get("resolution", "768p"),
                   prompt=job.get("prompt", ""), aspect=job.get("aspect", "16:9"), timings={})
        if job["output"].exists():
            job["skip"] = True
            log(f"[in] {job['id']} skip: {job['output']} exists")
            continue
        try:
            specs = [r if r.split(":", 1)[0] in KINDS else f"image:{r}" for r in job.get("refs", [])]
            if not job["prompt"].strip() or len(job["prompt"]) > 8000 or not 0 <= job["seed"] < 2**63:
                raise ValueError("prompt must have 1-8000 characters and seed must be in [0, 2**63-1]")
            if job["output"].suffix.lower() != ".mp4" or job["seconds"] not in range(5, 16) or not specs:
                raise ValueError("need .mp4 output, seconds in 5..15, and at least one reference")
            width, height = table["tiers"]["p" + job["resolution"][:-1]][table["aspects"].index(job["aspect"])]
            frames = G.align_num_frames(job["seconds"] * G.FPS)
            preflight_reference_specs(specs)
            refs = [Reference.from_spec(s) for s in specs]
            if not any(r.kind in ("image", "video") for r in refs):
                raise ValueError("ref2va requires an image or video reference")
            job.update(frames=frames, width=width, height=height, kinds=[r.kind for r in refs],
                       request=Request(task="ref2va", prompt=job["prompt"], references=refs, height=height, width=width,
                                       num_frames=frames, reference_rule="tiered", keyframe_fit="crop"),
                       input_sha256={"first_image": None, "last_image": None,
                                     "references": [P.file_sha256(s.partition(":")[2]) for s in specs]})
        except Exception as exc:
            fail(job, "in", exc)
    if not live():
        log("nothing to run")
        return 1 if any(j.get("error") for j in jobs) else 0

    t = time.monotonic()
    args = Namespace(task="ref2va", adapter_path=None, model_repo=MODEL_REPO, revision=REVISION, base_path=None)
    base, adapter, manifest = P.resolve_assets(args)
    batch["assets_seconds"] = time.monotonic() - t
    policy = manifest["numerics_policy"]
    configure_numerics_backend(policy, runtime="inference")
    common.update(adapter_sha256=manifest["sha256"], adapter_revision=REVISION, base=manifest["base"],
                  local_base_override=False, local_conditioner_override=False,
                  bucket_sha256=P.file_sha256(bucket_file), noise_version=EVAL_NOISE_VERSION,
                  numerics_policy=policy, sampling=manifest["sampling"], torch=torch.__version__,
                  gpu=torch.cuda.get_device_name(), dependencies={n: importlib.metadata.version(n)
                  for n in ("diffusers", "transformers", "peft", "av", "safetensors")})

    # ---- Stage A: H3ConditionEncoder.encode() split into a text pass then a VAE pass (same calls, same order per job)
    t = time.monotonic()
    encoder = H3ConditionEncoder(str(base), device="cuda")
    for job in live():
        t1 = time.monotonic()
        try:
            req = job.pop("request")
            job["geom"] = resolve_geometry(req)
            job["normalized"], job["ref_sizes"] = normalize_references(req, job["geom"])
            job["embeds"] = encoder.encode_text(req, [], [], references=job["normalized"])
        except Exception as exc:
            fail(job, "A-text", exc); cleanup()
        job["timings"]["conditioning_seconds"] = time.monotonic() - t1
    encoder.free("text")
    batch["text_stage_seconds"] = time.monotonic() - t
    t = time.monotonic()
    for job in live():
        t1 = time.monotonic()
        try:
            refs = []
            for ref in job.pop("normalized"):
                entry = {"kind": ref.kind}
                if ref.kind == "image":
                    entry["video_latents"] = encoder.encode_image_latent(ref.image)
                elif ref.kind == "video":
                    entry["video_latents"] = encoder.encode_video_latent(ref.frames)
                if ref.has_audio:
                    entry["audio_latents"] = encoder.encode_audio_latent(ref.audio)
                refs.append({k: v.cpu() if torch.is_tensor(v) else v for k, v in entry.items()})
            embeds, tags = job.pop("embeds")
            geom = job["geom"]
            job["cond"] = {"prompt_embeds": embeds.unsqueeze(0).cpu(), "text_token_tags": tags.cpu(), "keyframes": [],
                           "references": refs, "geometry": geom, "reference_images": job["ref_sizes"],
                           "packed_tokens": G.packed_token_count(num_text_tokens=int(tags.numel()),
                               num_latent_frames=geom.num_latent_frames, latent_height=geom.latent_height,
                               latent_width=geom.latent_width, num_audio_latents=geom.num_audio_latents, num_keyframes=0,
                               reference_video_rows=sum(int(r["video_latents"].shape[1] * (r["video_latents"].shape[3] // 2)
                                   * (r["video_latents"].shape[4] // 2)) for r in refs if "video_latents" in r),
                               reference_audio_rows=sum(int(r["audio_latents"].shape[1] * G.AUDIO_CHANNELS)
                                   for r in refs if "audio_latents" in r)).total}
            job["timings"]["conditioning_seconds"] += time.monotonic() - t1
            log(f"[A] {job['id']} cond {job['timings']['conditioning_seconds']:.1f}s tokens={job['cond']['packed_tokens']}")
        except Exception as exc:
            fail(job, "A-vae", exc); cleanup()
    encoder.free()
    del encoder
    cleanup()
    batch["vae_stage_seconds"] = time.monotonic() - t

    # ---- Stage B: one transformer + LoRA; resident jobs first, then group-offload jobs (+ OOM retries)
    def load_model():
        t1 = time.monotonic()
        m = build_transformer(str(base), dtype=torch.bfloat16, device="cpu", subfolder=manifest["trunk"])
        apply_lora(m, rank=manifest["rank"], alpha=manifest["alpha"], target_modules=manifest.get("target_modules"),
                   master_dtype=torch.bfloat16)
        load_lora_weights(m, str(adapter))
        m.requires_grad_(False).eval()
        batch["transformer_load_seconds"] = time.monotonic() - t1
        return m
    model = None
    schedule = H3SigmaSchedule({"denoising_step_list": P.KNOTS, "video_score_sigma_shift": 12,
                                "audio_score_sigma_shift": 3}, device="cuda")
    force = os.environ.get("PIKA_OFFLOAD") == "1"
    needs = lambda j: force or bool(j.get("cpu_offload")) or (j["resolution"] == "768p" and j["kinds"].count("image") >= 4)
    queues = {"resident": [j for j in live() if not needs(j)], "offload": [j for j in live() if needs(j)]}
    t = time.monotonic()
    for mode in ("resident", "offload"):
        if not queues[mode]:
            continue
        if model is None:
            model = load_model()
        t1 = time.monotonic()
        if mode == "resident":
            model.to("cuda")
        else:  # back to the CPU state generate() offloads from, then the CLI's --cpu-offload hooks
            model.to("cpu"); cleanup()
            model.enable_group_offload(onload_device=torch.device("cuda"), offload_device=torch.device("cpu"),
                offload_type="block_level", num_blocks_per_group=1, use_stream=True, record_stream=False)
        batch[f"{mode}_setup_seconds"] = time.monotonic() - t1
        for job in queues[mode]:
            geom, oom = job["geom"], False
            t1 = time.monotonic()
            torch.cuda.reset_peak_memory_stats()
            try:
                wrapper = H3DiffusionWrapper(model).eval()  # fresh per job: no layout cache carried across requests
                with torch.inference_mode():
                    video, audio = sample_evaluation_ladder(wrapper,
                        conditional_dict=prepare_conditioning(job["cond"], "cuda", policy=policy),
                        video_shape=[1, geom.num_latent_frames, G.VIDEO_LATENT_CHANNELS, geom.latent_height, geom.latent_width],
                        audio_shape=[1, geom.num_audio_latents, G.AUDIO_EXTERNAL_DIM],
                        sigmas_v=schedule.video_ladder, sigmas_a=schedule.audio_ladder, seed=job["seed"], device="cuda")
                job["latents"] = (video[0].cpu(), audio[0].cpu())
                torch.cuda.synchronize()
                job.update(peak=torch.cuda.max_memory_allocated(), offload_used=mode == "offload")
                job.pop("cond")
                job["timings"]["sampling_seconds"] = time.monotonic() - t1
                log(f"[B:{mode}] {job['id']} sample {job['timings']['sampling_seconds']:.1f}s peak={job['peak'] / 2**30:.1f}GiB")
            except OOM as exc:
                if mode == "offload":
                    fail(job, "B", exc)
                else:
                    oom = True
            except Exception as exc:
                fail(job, f"B:{mode}", exc)
            wrapper = video = audio = None
            cleanup()
            if oom:
                log(f"[B] {job['id']} OOM resident -> retry once with group offload")
                job["timings"]["oom_resident_seconds"] = time.monotonic() - t1
                queues["offload"].append(job)
    model = None
    cleanup()
    batch["sampling_stage_seconds"] = time.monotonic() - t

    # ---- Stage C: decoders once; decode, write, validate exactly like generate()
    t = time.monotonic()
    decoders = H3Decoders(str(base), device="cuda") if any("latents" in j for j in live()) else None
    for job in [j for j in live() if "latents" in j]:
        t1, out, frames = time.monotonic(), job["output"], job["frames"]
        try:
            video, audio = job.pop("latents")
            with torch.inference_mode():
                pixels = decoders.decode_video(video)
                wave = decoders.decode_audio(audio)
            if pixels.shape[:3] != (frames, job["height"], job["width"]):
                raise RuntimeError(f"decoded geometry mismatch: {pixels.shape}")
            if not np.isfinite(wave).all():
                raise RuntimeError("decoded audio is not finite")
            wave = wave[:, :round(frames / G.FPS * G.AUDIO_SAMPLE_RATE)]
            out.parent.mkdir(parents=True, exist_ok=True)
            write_mp4(str(out), pixels, audio=wave)
            with av.open(str(out)) as enc:
                vs = enc.streams.video[0]
                if (vs.width, vs.height) != (job["width"], job["height"]) or not enc.streams.audio:
                    raise RuntimeError("encoded video/audio validation failed")
                ac = enc.streams.audio[0].codec_context
                if vs.average_rate != G.FPS or ac.sample_rate != G.AUDIO_SAMPLE_RATE or ac.channels != 2:
                    raise RuntimeError("encoded frame rate or stereo audio format mismatch")
                if sum(1 for _ in enc.decode(video=0)) != frames:
                    raise RuntimeError("encoded frame count mismatch")
            job["timings"]["decode_encode_seconds"] = time.monotonic() - t1
            write_meta(job)
            log(f"[C] {job['id']} saved {out} decode {job['timings']['decode_encode_seconds']:.1f}s")
        except Exception as exc:
            if out.exists():  # keep the invalid file for inspection, but free the name for a rerun
                out.replace(out.with_suffix(".invalid.mp4"))
            fail(job, "C", exc)
        pixels = wave = None
        cleanup()
    batch["decode_stage_seconds"] = time.monotonic() - t
    batch["total_seconds"] = time.monotonic() - batch_t0
    log("stages " + " ".join(f"{k}={v:.1f}" for k, v in batch.items()))
    done = sum(1 for j in jobs if not j.get("error") and not j.get("skip"))
    failed = [j["id"] for j in jobs if j.get("error")]
    log(f"done={done} skipped={sum(1 for j in jobs if j.get('skip'))} failed={len(failed)} {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
