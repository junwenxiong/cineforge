# Render farm

The local server assigns shots and receives clips; each Colab worker runs one heavy GPU job at a time. H3 claims last 25 minutes and stop after three attempts. Existing job.json receipts prevent redispatch; LTX shots are excluded from H3 claims. Missing refs silently make shots ineligible, so validate media first.

Start locally with a token held in memory:

```sh
read -rs -p 'Farm token (choose a long random value): ' CINEFORGE_FARM_TOKEN; echo
export CINEFORGE_FARM_TOKEN
python3 tools/film/farm_server.py --films starcore --token-env CINEFORGE_FARM_TOKEN --port 8765
```

In another terminal run `cloudflared tunnel --protocol http2 --url http://127.0.0.1:8765`. Keep this terminal alive. Enter its HTTPS address and the same token only in a private Colab cell. Do not publish cell output or share credential-bearing notebooks. This is a single-owner trusted-worker service, not a multi-user hosting platform.

For H3 set CINEFORGE_BOX_VM_DIR to the VM directory in your own licensed Box installation before starting the server. vm_service.py, prompting.py and h3kf_node.py are NOT distributed here. The server supplies them only from that configured directory; check your Box license permits your own remote use.

Colab starter cell (substitute privately):

```python
B = "https://YOUR_TUNNEL_HOST"
T = "YOUR_PRIVATE_FARM_TOKEN"
W = "worker01"
import urllib.request
exec(urllib.request.urlopen(f"{B}/boot.py?t={T}").read().decode())
```

For LTX, create keyframes, mark shots `engine: ltx`, run `python3 tools/film/ltx_stage.py --film starcore`, then use W = "ltx_starcore_0of1", LAB_MODEL = "ltx_starcore", and replace /boot.py with /lab/file/ltx25.py. Run `python3 tools/film/ltx_collect.py --film starcore --watch` locally. For N workers use `_0ofN` through `_(N-1)ofN`; all must read the same fixed job list. Do not run ltx_prune.py or rewrite the list during index-sharded work.

For gated models accept the HF licenses first. Store your read-only token once with `python3 tools/setup.py init`; the farm reads `HF_TOKEN` from the private `.env` at startup and keeps it in memory, so you never paste it again. To change it without restarting, submit it to /lab/setsecret over direct loopback using stdin, authenticated with the farm token. That endpoint refuses tunneled requests. The memory-only route also works with curl: use `--data-binary @-`, never embed the HF token in command history. `/lab/secret` makes it available to authenticated workers, so all workers must be trusted.

Check /status with `?t=` and inspect farm.log for new claim and saved events. `farm_watch.py --film starcore` warns about stalls; heartbeat alone does not prove progress. `farm_supervisor.py --dry-run --once` previews supervision; review its Windows/browser dependencies before enabling actions. Legacy colab_drive.py is optional and reads ignored renders/farm/url and token files.

Stop safely: write worker names separated by spaces to renders/farm/drain; wait for every worker's current list to empty AND final saved receipts/uploads to arrive. Then manually disconnect/delete runtimes (or use the reviewed optional browser control). Box-owned machines must be stopped in Box. Verify Colab has no active sessions and credit usage has stopped, then stop the local server and tunnel. Never kill an active upload.
