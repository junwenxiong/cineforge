"""Colab-only H3 A/B lab; exec with B,T,W on an otherwise unused runtime.
Reuse /boot.py definitions without invoking its farm claim loop. Box code stays
unmodified. a/b/c/d isolate steps and sparse attention; e changes engine + LoRA
and steps together, retaining CK, sparse, sampler, CFG=1 and the int8 video VAE.
Eight steps are accepted by BasicScheduler; this is not an 8-step-trained LoRA.
Metadata includes the graph embedded by ComfyUI in the actual output MP4.
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

MODEL = "h3ab"
B = globals().get("B") or os.environ.get("FARM_B")
T = globals().get("T") or os.environ.get("FARM_T")
W = globals().get("W") or os.environ.get("FARM_W", "h3ab")
ROOT = Path("/content/h3ab")
VARIANTS = {
    "baseline": {},
    "steps8": {"steps": 8},
    "dense": {"sparse": False},
    "steps8_dense": {"steps": 8, "sparse": False},
    "bf16_30": {"engine": "refbf16", "lora": "none", "steps": 30},
}


def request(path, data=None, **query):
    query.update(t=T, w=W)
    u = B.rstrip("/") + path + "?" + urllib.parse.urlencode(query)
    for attempt in range(4):
        try:
            req = urllib.request.Request(u, data=data, headers={"Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=600) as f:
                return f.read()
        except Exception:
            if attempt == 3:
                # urllib errors may contain credential-bearing URLs.
                raise RuntimeError("farm request failed: " + path) from None
            time.sleep(5 * (attempt + 1))


def log(message):
    print(message, flush=True)
    request("/lab/log", (MODEL + ": " + message).encode())


def spec_for(job, variant):
    return dict(batch=MODEL, id=job["id"] + "_" + variant, mode="ref",
                engine="ref", lora="ref4", steps=4, sampler="res_multistep",
                scheduler="simple", sparse={"tau": 1.3, "start": 0.2}, attn="ck",
                images=[r["name"] for r in job["refs"]], prompt=job["prompt"],
                w=job["w"], h=job["h"], frames=job["frames"], seed=job["seed"]) | VARIANTS[variant]


def load_definitions(source, filename, namespace):
    tree = ast.parse(source, filename)
    # farm_worker.py ends in an unconditional main(); never claim film jobs.
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id == "main")]
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


def graph_supported(vm, spec):
    """Fail closed when the served version silently ignores a requested knob."""
    graph = vm.build(spec)
    def inputs(kind):
        return [v["inputs"] for v in graph.values() if v["class_type"] == kind]
    assert inputs("BasicScheduler")[0]["steps"] == spec["steps"]
    assert inputs("UNETLoader")[0]["unet_name"] == vm.local_path("engine_" + spec["engine"]).name
    assert bool(inputs("BlockSparseAttention")) == bool(spec["sparse"])
    assert bool(inputs("LoraLoaderModelOnly")) == (spec["lora"] != "none")
    if spec["lora"] != "none":
        assert inputs("LoraLoaderModelOnly")[0]["lora_name"] == vm.local_path("lora_" + spec["lora"]).name
    return graph


def probe_graph(mp4):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=prompt",
                             "-of", "json", str(mp4)], check=True, capture_output=True, text=True)
    return json.loads(json.loads(result.stdout)["format"]["tags"]["prompt"])


def verify_graph(expected, actual):
    for key, node in expected.items():
        got = actual[key]
        assert got["class_type"] == node["class_type"], key
        assert all(got["inputs"].get(k) == v for k, v in node["inputs"].items()), key
    assert not (set(actual) - set(expected)), "unexpected workflow nodes"


def run_one(worker, vm, job, variant, hashes):
    spec = spec_for(job, variant)
    sid = spec["id"]
    receipt = ROOT / (sid + ".json")
    mp4 = worker["OUT"] / MODEL / (sid + ".mp4")
    meta = dict(id=job["id"], variant=variant, requested_config=spec,
                source_sha256=hashes, film_config=job["film_config"], wall_seconds=None)
    try:
        expected = graph_supported(vm, spec)
    except (KeyError, AssertionError, ValueError, IndexError) as ex:
        meta.update(status="skipped", reason="unsupported served graph: " + type(ex).__name__)
        request(f"/lab/upload/{MODEL}/{sid}.json", json.dumps(meta).encode())
        log(sid + " skipped: unsupported served graph")
        return
    if receipt.exists():
        meta = json.loads(receipt.read_text())
        if meta["requested_config"] != spec or meta["source_sha256"] != hashes:
            raise RuntimeError("existing receipt has different config: " + sid)
    else:
        for ref in job["refs"]:
            data = request(ref["url"])
            if hashlib.sha256(data).hexdigest() != ref["sha256"]:
                raise RuntimeError("reference changed: " + ref["name"])
            (worker["INPUT"] / ref["name"]).write_bytes(data)
        queued = worker["JOBS"] / (sid + ".json")
        existing = [queued, queued.with_suffix(".json.run"), worker["JOBS"] / "done" / queued.name]
        rec = worker["read_status"]().get("jobs", {}).get(MODEL + "/" + sid)
        if not rec and not any(p.exists() for p in existing):
            tmp = queued.with_suffix(".tmp")
            tmp.write_text(json.dumps(spec, ensure_ascii=False))
            tmp.rename(queued)
        for p in existing:
            if p.exists() and json.loads(p.read_text()) != spec:
                raise RuntimeError("existing job has different config: " + sid)
        started = time.monotonic()
        while True:
            st = worker["read_status"]()
            rec = st.get("jobs", {}).get(MODEL + "/" + sid)
            if worker["final"](rec) and st.get("current") != MODEL + "/" + sid:
                break
            if not worker["service_alive"]() or st.get("state") == "error":
                raise RuntimeError("service stopped; inspect Colab service log (no automatic resubmit)")
            if time.monotonic() - started > 7200:
                raise RuntimeError("job wait timed out; inspect existing task before rerunning")
            log(sid + " waiting: " + str(st.get("state")))
            time.sleep(30)
        meta.update(status="completed" if rec.get("ok") else "failed", service_record=rec,
                    wall_seconds=rec.get("wall_sec"), wait_seconds=time.monotonic() - started)
        if rec.get("ok"):
            actual = probe_graph(mp4)
            verify_graph(expected, actual)
            subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(mp4),
                            "-f", "null", "-"], check=True, capture_output=True)
            meta.update(applied_graph=actual, applied_config=spec, graph_verified=True,
                        sha256=hashlib.sha256(mp4.read_bytes()).hexdigest())
        receipt.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    if meta["status"] == "completed":
        if hashlib.sha256(mp4.read_bytes()).hexdigest() != meta["sha256"]:
            raise RuntimeError("output changed after verification: " + sid)
        request(f"/lab/upload/{MODEL}/{sid}.mp4", mp4.read_bytes())
    request(f"/lab/upload/{MODEL}/{sid}.json", receipt.read_bytes())
    log(sid + " " + meta["status"])


def main():
    if not B or not T or not Path("/content").is_dir():
        raise RuntimeError("Run in a dedicated Colab runtime with B,T,W defined")
    os.environ.update(MPLBACKEND="Agg", HF_HOME="/content/hf", HF_XET_HIGH_PERFORMANCE="1")
    ROOT.mkdir(exist_ok=True)
    worker_src = request("/boot.py")
    worker = load_definitions(worker_src, "farm_worker.py", {"B": B, "T": T, "W": W, "__name__": "h3ab_worker"})
    owner = ROOT / "service_owner"
    if worker["service_alive"]() and not owner.exists():
        raise RuntimeError("Existing service is not owned by this lab; use an unused runtime")
    for p in worker["JOBS"].glob("*.json*"):
        if json.loads(p.read_text()).get("batch") != MODEL:
            raise RuntimeError("Foreign queued task; use an unused runtime")
    current = worker["read_status"]().get("current")
    if current and not current.startswith((MODEL + "/", "_warm/")):
        raise RuntimeError("Foreign running task; use an unused runtime")
    hashes = {"farm_worker.py": hashlib.sha256(worker_src).hexdigest()}
    for name in ("vm_service.py", "prompting.py", "h3kf_node.py"):
        data = request("/vm/" + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
        path = Path("/content") / name
        if worker["service_alive"]() and path.read_bytes() != data:
            raise RuntimeError("Served source changed while lab service is running")
        path.write_bytes(data)
    sys.path.insert(0, "/content")
    module_spec = importlib.util.spec_from_file_location("h3ab_vm", "/content/vm_service.py")
    vm = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(vm)  # guarded main; build() itself uses no GPU
    jobs = json.loads(request("/lab/jobs", m=MODEL))
    if not worker["service_alive"]():
        if shutil.disk_usage("/content").free < 120 * 10**9:
            raise RuntimeError("Need 120 GB free before setup (includes full BF16 weights)")
        if not shutil.which("uv"):
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
        owner.write_text(MODEL)
        worker["start_service"]()
        time.sleep(5)
    # Variant-major order: reuse weights, defer the much larger BF16 load to last.
    for variant in VARIANTS:
        for job in jobs:
            run_one(worker, vm, job, variant, hashes)
    log("finished; results in renders/lab/h3ab; runtime still needs manual shutdown")


if __name__ in ("__main__", "builtins"):
    main()
