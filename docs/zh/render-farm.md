# 多机农场

本地服务派镜头并收回成片，每台 Colab 同时只运行一个重型 GPU 任务。H3 租约 25 分钟，最多尝试三次；已有 job.json 不重复派片，engine=ltx 的镜头由 LTX 流程处理。缺 refs 的镜头会被跳过，先检查媒体。

令牌只放内存的启动方式：

```sh
read -rs -p '输入随机长农场令牌: ' CINEFORGE_FARM_TOKEN; echo
export CINEFORGE_FARM_TOKEN
python3 tools/film/farm_server.py --films starcore --token-env CINEFORGE_FARM_TOKEN --port 8765
```

另开终端运行 `cloudflared tunnel --protocol http2 --url http://127.0.0.1:8765` 并保持终端运行。HTTPS 地址和同一个令牌只填私人 Colab 单元，不分享带凭据的 notebook 或输出。此服务面向单个所有者和可信工作机，不适合多租户托管。

H3：启动服务前设置 CINEFORGE_BOX_VM_DIR，指向自己已获许可的 Box VM 目录。仓库不分发 vm_service.py、prompting.py、h3kf_node.py；服务仅从该目录加载，远程自用也需符合 Box 许可。

Colab 启动单元（私下替换）：

```python
B = "https://YOUR_TUNNEL_HOST"
T = "YOUR_PRIVATE_FARM_TOKEN"
W = "worker01"
import urllib.request
exec(urllib.request.urlopen(f"{B}/boot.py?t={T}").read().decode())
```

LTX：准备首帧，镜头写 engine: ltx，运行 `python3 tools/film/ltx_stage.py --film starcore`。单元用 W = "ltx_starcore_0of1"、LAB_MODEL = "ltx_starcore"，把 /boot.py 换为 /lab/file/ltx25.py。本地运行 `python3 tools/film/ltx_collect.py --film starcore --watch`。N 台机器从 `_0ofN` 到 `_(N-1)ofN`，使用同一固定任务表；按索引分片时不能运行 ltx_prune.py 或重写任务表。

HF gated 模型先接受许可，再从本机直连 /lab/setsecret，以 stdin 提交只读令牌并带农场鉴权。该接口拒绝隧道请求，服务重启后令牌消失。curl 用 --data-binary @-，不要把 HF 令牌写进命令历史。已认证工作机可以读取 /lab/secret，因此必须信任所有工作机。

/status 带 ?t= 查询，结合 farm.log 的 claim、saved 判断进度。`farm_watch.py --film starcore` 查停滞，心跳不代表主循环正常。先用 `farm_supervisor.py --dry-run --once` 预览，启用动作前审查 Windows/浏览器依赖。colab_drive.py 是可选旧工具，会读取忽略目录中的 URL/token 文件。

收工把机器名空格分隔写入 renders/farm/drain，等每台 current 为空且最后回执与上传保存完成，再手动断开并删除运行时，或使用已审查的浏览器工具。Box 自己的机器从 Box 关闭。核实 Colab 无活动会话且额度不再下降，再停止本地服务和隧道。上传未完成时不能杀进程。
