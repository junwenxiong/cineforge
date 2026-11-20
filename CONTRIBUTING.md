# Contributing

Issues and pull requests are welcome. Explain the expected and actual behavior, OS/Python/ffmpeg versions, model adapter and a small sanitized text example. Include exact reproduction commands; do not attach private media, tokens or active notebook/tunnel addresses.

Keep changes focused. Run `python3 tools/smoke_test.py`, compile changed Python, and include relevant offline regression results. Document GPU checks separately with hardware, model revision, shot duration and whether timing includes startup. Do not claim offline tests prove model quality.

Source-imported tools are maintained by an explicit allowlist exporter; coordinate updates to the upstream export transformations when changing portable paths. See docs/export.md. Contributions are provided under Apache-2.0. Retain notices and document third-party dependencies and model licensing separately.
