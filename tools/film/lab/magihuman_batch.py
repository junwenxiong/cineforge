# daVinci-MagiHuman 批量推理（Colab 端，由 magihuman.py 经 /lab/file/ 取回后用 torchrun 单卡启动）。
# 基础模型（distill，8 步无 CFG）+ 1080p 超分 + 编码器只加载一次，逐个镜头生成；每镜写 <id>.mp4 和 <id>.json。
# 用法：MAGI_BATCH=batch.json torchrun --standalone --nproc_per_node=1 magihuman_batch.py --config-load-path config.json
#       （PYTHONPATH 需包含 daVinci-MagiHuman 仓库根目录和 MagiCompiler 仓库根目录）
import importlib.machinery, json, os, sys, time, traceback, types
from pathlib import Path

import torch
import torch.nn.functional as F


def install_flash_attn_shim():
    """官方代码在注意力里 import flash_attn（FA2）。torch 2.9 没有官方 FA2 轮子，就用 SDPA 顶上。
    只提供 flash_attn.flash_attn_interface.flash_attn_func；不提供顶层 flash_attn_interface，FA3 分支保持关闭。"""
    try:
        import flash_attn.flash_attn_interface  # noqa: F401
        return "flash_attn"
    except Exception:
        pass
    from torch.nn.attention import SDPBackend, sdpa_kernel
    fused = [SDPBackend.FLASH_ATTENTION, SDPBackend.CUDNN_ATTENTION, SDPBackend.EFFICIENT_ATTENTION]  # 不许退回 O(S²) 的 math 内核
    state = {"lse": "flash"}

    def bhsd(q, k, v):
        q, k, v = (x.transpose(1, 2) for x in (q, k, v))      # [B,S,H,D] -> [B,H,S,D]
        if k.shape[1] != q.shape[1]:                            # GQA：40 个 q 头 / 8 组 kv
            r = q.shape[1] // k.shape[1]
            k, v = k.repeat_interleave(r, dim=1), v.repeat_interleave(r, dim=1)
        return q, k, v

    def attn_with_lse(q, k, v, scale, causal):
        if state["lse"] == "flash":
            try:
                o = torch.ops.aten._scaled_dot_product_flash_attention(q, k, v, 0.0, causal, False, scale=scale)
                return o[0], o[1]
            except Exception as e:
                print(f"[fa-shim] aten flash+lse unavailable ({str(e)[:160]}); trying efficient attention", flush=True)
                state["lse"] = "efficient"
        if state["lse"] == "efficient":
            try:
                o = torch.ops.aten._scaled_dot_product_efficient_attention(q, k, v, None, True, 0.0, causal, scale=scale)
                return o[0], o[1][..., :q.shape[2]]
            except Exception as e:
                print(f"[fa-shim] efficient+lse unavailable ({str(e)[:160]}); falling back to chunked math", flush=True)
                state["lse"] = "math"
        scale = scale or q.shape[-1] ** -0.5
        rows = max(16, int(2e9 // (k.shape[2] * q.shape[1] * 4)))
        outs, lses = [], []
        for i in range(0, q.shape[2], rows):
            s = torch.matmul(q[:, :, i:i + rows].float(), k.float().transpose(-1, -2)) * scale
            lse = torch.logsumexp(s, dim=-1)
            outs.append(torch.matmul(torch.exp(s - lse[..., None]).to(v.dtype), v))
            lses.append(lse)
        return torch.cat(outs, 2), torch.cat(lses, 2)

    def flash_attn_func(q, k, v, dropout_p=0.0, softmax_scale=None, causal=False, return_attn_probs=False, **kw):
        qq, kk, vv = bhsd(q, k, v)
        if return_attn_probs:                                   # 1080p 超分的局部注意力需要 softmax_lse [B,H,Sq]
            out, lse = attn_with_lse(qq, kk, vv, softmax_scale, causal)
            return out.transpose(1, 2), lse, None
        with sdpa_kernel(fused):
            out = F.scaled_dot_product_attention(qq, kk, vv, is_causal=causal, scale=softmax_scale)
        return out.transpose(1, 2)

    pkg = types.ModuleType("flash_attn")
    pkg.__spec__ = importlib.machinery.ModuleSpec("flash_attn", None, is_package=True)
    pkg.__path__ = []
    mod = types.ModuleType("flash_attn.flash_attn_interface")
    mod.__spec__ = importlib.machinery.ModuleSpec("flash_attn.flash_attn_interface", None)
    mod.flash_attn_func = pkg.flash_attn_func = flash_attn_func
    pkg.flash_attn_interface = mod
    sys.modules["flash_attn"] = pkg
    sys.modules["flash_attn.flash_attn_interface"] = mod
    return "sdpa-shim"


ATTN = install_flash_attn_shim()

from inference.common import parse_config                # noqa: E402
from inference.infra import initialize_infra               # noqa: E402
from inference.model.dit import get_dit                    # noqa: E402
from inference.pipeline import MagiPipeline                # noqa: E402
from inference.utils import timer as timer_mod             # noqa: E402

STEPS = {}
_orig_record = timer_mod.EventPathTimer.synced_record


def _record(self, message, *a, **kw):                      # 记下官方计时器的分段耗时（编码/基础/超分/解码）
    prev_msg, prev_t = self.prev_message, self.prev_time
    _orig_record(self, message, *a, **kw)
    if prev_msg is not None:
        STEPS[prev_msg] = round((self.prev_time - prev_t).total_seconds(), 2)


timer_mod.EventPathTimer.synced_record = _record


def main():
    jobs = json.loads(Path(os.environ["MAGI_BATCH"]).read_text(encoding="utf-8"))
    initialize_infra()
    cfg = parse_config()
    t0 = time.time()
    model = get_dit(cfg.arch_config, cfg.engine_config)
    pipe = MagiPipeline(model, cfg.evaluation_config)
    load_s = time.time() - t0
    env = {"gpu": torch.cuda.get_device_name(), "torch": torch.__version__, "attn": ATTN,
           "compile_mode": os.environ.get("MAGI_COMPILE_COMPILE_MODE", "MAGI_COMPILE"),
           "cpu_offload": os.environ.get("CPU_OFFLOAD"), "sr2_1080": os.environ.get("SR2_1080"),
           "load_seconds": round(load_s, 1), "load_peak_allocated_gib": round(torch.cuda.max_memory_allocated() / 2**30, 1)}
    print(f"[batch] pipeline ready {json.dumps(env)}", flush=True)
    for i, job in enumerate(jobs):
        out = Path(job["output"])
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        STEPS.clear()
        t = time.time()
        meta = {"id": job["id"], "model": "GAIR/daVinci-MagiHuman distill+1080p_sr", "seconds": job["seconds"],
                "seed": job["seed"], "base": [job["br_width"], job["br_height"]], "sr": [job["sr_width"], job["sr_height"]],
                "first_job_includes_warmup": i == 0, **env}
        print(f"[batch] start {job['id']} ({i + 1}/{len(jobs)})", flush=True)
        try:
            p = pipe.run_offline(prompt=job["prompt"], image=job["image"], audio=None,
                                 save_path_prefix=str(out.with_name(out.stem + "_raw")), seed=job["seed"],
                                 seconds=job["seconds"], br_width=job["br_width"], br_height=job["br_height"],
                                 sr_width=job["sr_width"], sr_height=job["sr_height"])
            Path(p).replace(out)
            meta["ok"] = True
        except Exception as e:
            traceback.print_exc()
            meta.update(ok=False, error=repr(e)[:2000])
            torch.cuda.empty_cache()
        meta.update(wall_seconds=round(time.time() - t, 1), steps=dict(STEPS),
                    peak_allocated_gib=round(torch.cuda.max_memory_allocated() / 2**30, 2),
                    peak_reserved_gib=round(torch.cuda.max_memory_reserved() / 2**30, 2))
        out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[batch] {'done' if meta['ok'] else 'FAIL'} {job['id']} wall={meta['wall_seconds']}s "
              f"peak={meta['peak_allocated_gib']}GiB steps={meta['steps']}", flush=True)
    if torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()


if __name__ == "__main__":
    main()
