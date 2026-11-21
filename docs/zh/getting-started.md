# 开工指南

所有命令都在仓库根目录执行。安装 Python 3.10+、ffmpeg/ffprobe（含字幕支持）及 Noto Sans CJK 等中文字体。模型权重只放 Colab，不下载到本机。

```sh
python3 tools/setup.py init --venv
python3 tools/setup.py doctor
python3 tools/smoke_test.py
python3 tools/new_film.py starcore --example starcore
python3 tools/validate_film.py --film starcore
```

`init` 把 `.env.example` 复制成私密的 `.env`，只问一次 Hugging Face 令牌（输入不显示），并向 Hugging Face 核对；加 `--venv` 会建好 `.venv` 并装入 `requirements.txt`。重复运行会保留已有设置。`doctor` 检查 Python、ffmpeg、字体、依赖、令牌、LTX-2.5 许可权限、辅助程序和助手配置，每个问题下面给一行 `fix:` 修法。只有 `FAIL` 会让它以错误退出。`doctor --offline` 跳过 Hugging Face 联网检查，`doctor --json` 输出机器可读结果。想手动装依赖，可运行 `python3 -m venv .venv`、`. .venv/bin/activate`、`pip install -r requirements.txt`。

`init --hand-model` 还会把很小的 MediaPipe 手部模型（约 8 MB）下载到 `~/.cache/mp/hand_landmarker.task`，用于检查手部；除此之外不往本机下载模型。

冒烟测试仅需标准库。requirements 包含生图、抽检和浏览器可选依赖；云端推理依赖由各适配器安装。Windows 激活 `.venv/Scripts/activate`；剪辑和 POSIX 文件锁建议在 WSL 运行，Box 队列目前需要 Windows Python 的 msvcrt。

`films/<name>/` 放可编辑剧本，`assets/<name>/refs/` 放图，`assets/<name>/music/` 放已授权音乐，`renders/<shot_id>/` 放原片和回执，`videos/<name>/` 放成片。示例只有文字，缺媒体正常。片名和镜号只用安全路径字符，各片 render_prefix 不重复。`--film` 优先于 FILM 环境变量，默认 starcore。

新片运行 `python3 tools/new_film.py myfilm`，告诉助手：“按 skills/cineforge/SKILL.md，把我的创意写成电影，先给我看故事和三条试拍再全片开工。”空模板不会自动生图或开拍。

## 令牌和 .env 文件

所有密钥都放在仓库根目录的一个私密文件 `.env` 里。Git 会忽略它，在 Linux 上只有你自己能读。Hugging Face 令牌只需输入一次，之后工具和助手（Claude Code、Codex 或 Gemini CLI）都从 `.env` 读取，不用再贴进聊天。要更换，运行 `python3 tools/setup.py init --reset-hf`。其他密钥（如 OPENAI_API_KEY）用文本编辑器写进 `.env`，`.env.example` 里有逐项说明。shell 里已设置的同名变量优先于 `.env`。

有些工具只读环境变量，用 `python3 tools/setup.py run -- 命令` 运行即可：它带着 `.env` 启动命令，不会打印密钥。WSL 下如果仓库放在 `/mnt/c`、`/mnt/d` 这类 Windows 盘，`.env` 无法设为私密（Windows 盘不认 `chmod`），`doctor` 会提醒；把仓库克隆到 Linux 主目录即可。

助手也会自动找到 CineForge 技能和说明：Claude Code 读 `CLAUDE.md` 和 `.claude/skills/`，Codex 读 `AGENTS.md` 和 `.agents/skills/`，Gemini CLI 读 `GEMINI.md` 和 `.agents/skills/`。这些小文件随仓库提供，缺失时 `init` 会补回。

## 参考图

参考图可自行准备，或把 OPENAI_API_KEY 写进 `.env` 后运行 `python3 tools/setup.py run -- python3 tools/film/gpt_images.py --film starcore`。兼容中转的地址用 CINEFORGE_IMAGE_BASE_URL（不带 /v1）。令牌不要放进版本文件、聊天窗口或 shell 历史。gemini_images.py 实际依赖 Antigravity 的 agy，不是装了 Gemini CLI 就能用；它继承的无限制工具模式需使用者先审查。

购买算力前先读[模型](models.md)与[农场](render-farm.md)，先验收三镜再扩大规模。
