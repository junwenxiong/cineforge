#!/usr/bin/env python3
"""Prototype for cloud-side final-video compaction; never uploads or deletes input.

Keep source until transfer is acknowledged. Output includes a SHA256 sidecar.
Run only on generated videos, before the existing chunked transfer stage.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--crf', type=int, choices=[18, 19, 20], default=20)
    p.add_argument('--threads', type=int, default=2)
    a = p.parse_args()
    manifest = a.output.with_suffix(a.output.suffix + '.json')
    if a.output.exists() or manifest.exists() or a.output.suffix.lower() != '.mp4':
        p.error('output must be a new .mp4 with no existing sidecar')
    if a.threads < 1:
        p.error('threads must be positive')
    before = probe(a.source)
    started = time.monotonic()
    fd, name = tempfile.mkstemp(prefix='.compact-', suffix='.mp4', dir=a.output.parent)
    os.close(fd)
    temp = Path(name)
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads',
                        str(a.threads), '-i', str(a.source), '-map', '0:v:0',
                        '-map', '0:a?', '-c:v', 'libx264', '-threads', str(a.threads),
                        '-preset', 'fast', '-crf', str(a.crf), '-pix_fmt', 'yuv420p',
                        '-c:a', 'copy', '-movflags', '+faststart', str(temp)], check=True)
        after = probe(temp)
        if abs(float(before['format']['duration']) - float(after['format']['duration'])) > .05:
            raise ValueError('duration changed by more than 50 ms')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-threads',
                        str(a.threads), '-i', str(temp), '-f', 'null', '-'], check=True)
        result = dict(crf=a.crf, preset='fast', source_bytes=a.source.stat().st_size,
                      output_bytes=temp.stat().st_size, duration=after['format']['duration'],
                      encode_and_check_seconds=time.monotonic() - started)
        if result['output_bytes'] >= result['source_bytes']:
            result['use_original'] = True
            print(json.dumps(result))
            return
        with temp.open('rb') as f:
            result['sha256'] = hashlib.file_digest(f, 'sha256').hexdigest()
        # Same-filesystem hard link publishes only the fully checked file,
        # atomically and without overwriting another process's output.
        os.link(temp, a.output)
        with manifest.open('x') as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result))
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
