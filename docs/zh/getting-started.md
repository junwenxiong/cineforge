# 开工指南

所有命令都在仓库根目录执行。安装 Python 3.10+、ffmpeg/ffprobe（含字幕支持）及 Noto Sans CJK 等中文字体。模型权重只放 Colab，不下载到本机。

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 tools/smoke_test.py
python3 tools/new_film.py starcore --example starcore
python3 tools/validate_film.py --film starcore
```

冒烟测试仅需标准库。requirements 包含生图、抽检和浏览器可选依赖；云端推理依赖由各适配器安装。Windows 激活 `.venv/Scripts/activate`；剪辑和 POSIX 文件锁建议在 WSL 运行，Box 队列目前需要 Windows Python 的 msvcrt。

`films/<name>/` 放可编辑剧本，`assets/<name>/refs/` 放图，`assets/<name>/music/` 放已授权音乐，`renders/<shot_id>/` 放原片和回执，`videos/<name>/` 放成片。示例只有文字，缺媒体正常。片名和镜号只用安全路径字符，各片 render_prefix 不重复。`--film` 优先于 FILM 环境变量，默认 starcore。

新片运行 `python3 tools/new_film.py myfilm`，告诉助手：“按 skills/cineforge/SKILL.md，把我的创意写成电影，先给我看故事和三条试拍再全片开工。”空模板不会自动生图或开拍。

参考图可自行准备，或在进程环境设置 OPENAI_API_KEY 后运行 `python3 tools/film/gpt_images.py --film starcore`。兼容中转的地址用 CINEFORGE_IMAGE_BASE_URL（不带 /v1）。令牌不要放进版本文件或 shell 历史。gemini_images.py 实际依赖 Antigravity 的 agy，不是装了 Gemini CLI 就能用；它继承的无限制工具模式需使用者先审查。

购买算力前先读[模型](models.md)与[农场](render-farm.md)，先验收三镜再扩大规模。
