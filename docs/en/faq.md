# FAQ

**Is it one click?** No. Your agent follows a playbook and runs existing scripts; story, reference images, pilot approval and final QA still require decisions. A universal CLI and automatic VLM reviewer are future work.

**Do I need a local GPU?** No for the intended Colab flow. Cloud weights and environments stay under /content. Local editing needs CPU, disk and ffmpeg.

**Can I use it without Box?** LTX and other lab adapters use external official inference repos. The fast H3 farm worker requires your own Box installation. No Box implementation is shipped. The exported GPU workflow has not been end-to-end revalidated.

**Can any agent run it?** Claude Code, Codex and Gemini CLI can read the same playbook. Image-generation tooling has separate requirements; gemini_images.py uses agy, not Gemini CLI itself.

**Why are images and music missing?** Examples share scripts, not personal photos or licensed assets. Create references and obtain music rights yourself. The original cat photos are deliberately absent.

**Can I sell the result?** Apache-2.0 covers this code only. Check every model, reference image and music license and distribution territory; label AI outputs where required. Read models.md before choosing a backend.

**What does it cost?** No verified full-film bill is published. Budget for GPU time, image generation, failed attempts and transfers. Monitor your own account and verify runtimes really stop after draining.

**Can I resume?** Keep receipts and claims in ignored renders/. Check ownership before retries. H3 and LTX must not own the same shot concurrently. Changing shot content should use versioned IDs or reviewed retakes.

**Where do I report problems?** Use issues for reproducible, sanitized bugs and PRs for fixes. Never attach credentials, notebook cells containing tokens or personal media. See CONTRIBUTING.md and SECURITY.md.
