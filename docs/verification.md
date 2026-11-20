# Local export verification — 2026-11-20

Verified without a GPU, external model download, live production service or browser control:

- `PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_test.py`: compiles every repository Python file to a temporary directory; validates Starcore (363 shots / 2272 planned seconds), Catfilm (331 / 2014) and Echo (320 / 1926); tests safe creation/no overwrite; starts an isolated loopback farm on a random port; verifies authenticated status, rejects missing/wrong credentials, confirms no token file, and stops its own child.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/film/check_multifilm.py`: priority/reverse dispatch, exhaustion, film filter, reference serving and traversal rejection using temporary fixtures and a random port.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/film/check_ltx.py`: staging/fallback prompt, missing-reference blocking, corrupt/wrong-resolution/no-audio rejection using synthetic ffmpeg clips, receipt preservation, SHA256 and repeat collection, worker sharding, H3 exclusion and HTTP keyframe access controls.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/film/test_farm_supervisor.py`: eight isolated supervisor tests.
- Private-source `automation/film/export_oss.py --target ../cineforge`: allowlist export and full worktree secret scan. Two consecutive exports compared by paths and SHA256; identical bytes. `.git` is excluded from scanning.
- Scanner negative checks use synthetic token prefixes, tunnel/canvas addresses, private IPs, email, random prose and random Python comment/docstring strings. No real credentials used. Known public function names and explicitly reviewed music stems/model URL are not treated as secrets.

The inherited LTX test originally expected an unmodified prompt and a keyframe spec despite missing references. Export transformations update those assertions to match the current static-camera prompt and missing-reference blocking behavior. Multi-film regression now uses a random port instead of a fixed local port.

Missing-media counts in the smoke test are expected: 27 Starcore, 139 Catfilm, 215 Echo. The repository contains text only. Planned seconds are source shot sums, not final film duration or rendering elapsed time.

Not verified here: Colab account availability, GPU adapters, image-provider APIs, Windows Box/browser control, regenerated references/music, full-film render or final master. The H3 worker still requires the user's separately licensed Box runtime. The farm is intended for trusted workers, not untrusted public hosting. Public repository name availability, publication settings and rights to any future uploaded media remain release-review tasks.
