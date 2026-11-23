# CineForge Studio（影铸 · AI 视频可视化工作流看板平台）

将底层 CineForge 短剧与 V2V 换角流水线封装为面向创作者的本地可视化工作流看板 + Google Colab 云端多模型算力节点，支持 **MiniMax-H3（开源 ComfyUI 4 步免 Box）**、**LTX-2.5**、**LTX-2.5 V2V** 与 **RelayVSR X2**，纯 Python 3.10+ 标准库 + FFmpeg 驱动，零本地 GPU 要求。

## 快速启动

```bash
# 推荐：一条命令同时启动本地 Web (8866) + 派片服务 (8765) + Colab 隧道，并打印接入信息
bash studio/start.sh --with-farm --port 8866

# 仅启动本机 Web 界面（默认 http://127.0.0.1:8866）
bash studio/start.sh

# 办公室局域网共享给同事体验
bash studio/start.sh --lan --port 8866

# 外部零门槛公网评测（访客模式 + cloudflared 临时隧道，无口令直达）
bash studio/start.sh --public --guest --port 8866
```

云端算力一键打开：[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/junwenxiong/cineforge/blob/main/colab/CineForge_Colab_Worker.ipynb)

> 端口 `8765` 保留给现有 `tools/film/farm_server.py`，Studio 默认监听 `8866`。

## 核心能力与接口

| 路由 | 说明 |
| --- | --- |
| `GET /api/health` | 服务健康状态与绑定端口 |
| `GET /api/showcase` | 灵感广场样片与实拍统计（自动提取并缓存 16:9 JPG 海报） |
| `GET /api/templates` | 电影画风卡、一句话短剧预设与 V2V 名场面预设 |
| `GET /api/projects` | 自动发现已有工作区影片与用户新建的 `studio_*` 项目 |
| `POST /api/projects` | 一键生成 `films/studio_<slug>/` 标准分镜工程并入库 |
| `GET /api/projects/{id}` | 项目 6 步流水线、DAG 节点拓扑、角色视觉锁、场次与逐镜列表 |
| `PATCH /api/projects/{id}/shots/{shot_id}` | 镜头状态、文案、提示词、剪点与备注更新（写入 SQLite 叠加层） |
| `POST /api/projects/{id}/shots/{shot_id}/retake` | 标记单镜打回重拍并记录导演意见 |
| `POST /api/projects/{id}/advance-stage` | 推进 6 步工作流阶段状态 |
| `POST /api/projects/{id}/render-preview` | 后台 FFmpeg 实时合成 H.264 + AAC 可播预演片并推送 SSE 进度 |
| `POST /api/projects/{id}/dispatch-cloud` | 生成 `studio/data/dispatch/{id}_jobs.json` 派片清单与脱敏 Colab 模板 |
| `GET /api/workflows/presets` | 获取内置简版 ComfyUI 工作流模板列表（H3 4步 R2V/T2V、LTX-2.5、V2V、多模型混拍流） |
| `GET / PUT /api/projects/{id}/workflow` | 读取或保存项目的 Lite ComfyUI 节点流（节点坐标、参数与旁路状态） |
| `GET /api/projects/{id}/workflow/export` | 导出标准 ComfyUI API `.json` 或 CineForge 节点流 JSON |
| `POST /api/projects/{id}/workflow/import` | 导入外部 ComfyUI API / UI JSON 或 CineForge 节点流 JSON |
| `POST /api/projects/{id}/workflow/run` | 按当前 ComfyUI 节点流参数（模型/步数/种子/分辨率）一键 Queue Prompt 派发至 Colab |
| `POST /api/uploads` | 上传图片/视频素材至 `studio/data/uploads/`（视频自动抽帧） |
| `GET /api/jobs` / `GET /api/jobs/{job_id}` | 查询预演合成与派片任务进度 |
| `GET /api/farm/status` | 脱敏算力池状态、16 点实时算力折线图 `telemetry`、闲置释放守护 `idle_guard`、Google Drive 缓存与成本对比 |
| `GET /api/farm/colab-notebook` | 动态下载标准 `nbformat 4.5` 的 `CineForge_Colab_Worker.ipynb`（内置 `#@param` 表单、Drive 30GB 缓存与闲置 `runtime.unassign()`） |
| `GET /api/share/info` | 外部端访客模式信息、LAN/公网一键命令与微信/飞书白领评测邀请文案 |
| `GET / POST /api/evaluations` | 白领 3 分钟评测任务、四维星级评分汇总与评价墙 |
| `GET /api/events` | SSE 实时状态广播通道 |
| `GET /api/media?path=<relpath>` | 严格白名单媒体流，完整支持 HTTP `Range` (`206 Partial Content`) |

## Docker 打包与一键启动

镜像不内置密钥（`.env` / `renders/farm/token`）或外部大素材，仅打包代码、FFmpeg、中文字体与可选的 `cloudflared`，运行时通过挂载项目工作区目录读取成片与写入任务数据：

```bash
# 本地构建并启动零门槛访客模式（自动协同宿主机 8765 派片服务）
bash docker/run.sh --guest --port 8866

# 启动并附带临时 Cloudflare 公网分享链接
bash docker/run.sh --guest --public --port 8866
```

## 安全与密钥边界

- 绝不读取、打印或暴露 `.env`、`HF_TOKEN`、`renders/farm/token`、本地 Box 画布地址或真实隧道 URL。
- `/api/farm/colab-notebook` 与 `/api/share/info` 严禁写入任何真实令牌、隧道链接或个人本地路径。
- `/api/media` 采用 `Path.resolve()` 严格目录白名单与扩展名白名单（仅 `.mp4/.jpg/.jpeg/.png/.webp`），坚决拦截 `renders/farm/`、`.env`、`..` 与任意脚本/日志/JSON 文件。
- 已有工作区项目（`starcore`、`catfilm`、`echo`、`classics`、`streetangel`、`starlight_arm`）保持只读，所有看板修改仅持久化在 `studio/data/studio.db`。
