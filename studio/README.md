# CineForge Studio（影铸 · AI 视频可视化工作流看板平台）

将底层 CineForge 短剧与 V2V 换角流水线封装为面向非技术创作者的电影级可视化工作流看板，融合 EasyColab 表单化一键接入与零安装外部访客体验，纯 Python 3.14 标准库 + FFmpeg 驱动，零第三方依赖。

## 快速启动

```bash
# 本机启动（默认 http://127.0.0.1:8866）
bash studio/start.sh

# 办公室局域网共享给同事体验
bash studio/start.sh --lan --port 8866

# 外部零门槛公网评测（推荐：访客模式 + cloudflared 临时隧道，无口令直达）
bash studio/start.sh --public --guest --port 8866

# 可选：为写操作加上临时邀请口令（只读画廊/样片仍零门槛浏览）
bash studio/start.sh --public --guest --invite-code TEAM2026
```

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
