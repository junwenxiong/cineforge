# Security

This is a single-owner research farm with trusted workers, not a hardened public hosting service. Bind it to loopback and authenticate every request. A tunnel exposes that service; protect its address and shared token. Authenticated workers can fetch the in-memory HF token. Treat notebook code, cell output and account sharing as secret exposure risks.

Use --token-env for memory-only farm authentication. The legacy default writes renders/farm/token; legacy colab_drive reads renders/farm/url too. Both are ignored and must never be committed. Enter the tunnel URL only in the private notebook cell when using the manual flow. HF credentials live only in the gitignored `.env` (created by `tools/setup.py init`, mode 600); the farm loads them into memory at startup. To swap a token at runtime, submit it through stdin to the direct-loopback /lab/setsecret endpoint, never through a tunnel. Never commit, print or paste `.env` contents. API image keys come from the environment. Restart the farm to clear HF secrets and rotate exposed credentials at their provider.

Do not post active secrets or exploit details publicly. Before a private reporting channel is configured, open an issue requesting private contact without sensitive details. Maintainers should configure repository private vulnerability reporting before public release.

The exporter scans text for known token formats, personal paths, emails, private IPs and suspicious high-entropy prose. Heuristic scanning cannot prove absence of every secret; review diffs before publishing. No model weights, Box implementation or private media are distributed.
