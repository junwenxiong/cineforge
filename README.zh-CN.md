# CineForge · 影铸

[English](README.md) · [从这里开始](docs/zh/getting-started.md) · Apache-2.0

把一段话变成一部约 30 分钟 AI 电影的制作计划，再由你的编程助手配合脚本完成分镜、参考图、云端拍摄、抽检、对白剪辑、音乐和字幕。你仍需选图、听对白和决定重拍。现在交付的是制作工具箱，还不是输入一句话就能保证出成片的软件。

需要 Python 3.10+、ffmpeg/ffprobe、有 GPU 额度的 Colab Pro/Pro+，以及 Claude Code、Codex 或 Gemini CLI。主要本地环境为 Linux/WSL；可选 Box 与浏览器控制使用 Windows Python 和独立 Chrome。参考图可自行制作，或使用另付费的生图服务。

## 五步开始

1. 在助手中打开仓库，阅读[开工指南](docs/zh/getting-started.md)，运行 `python3 tools/smoke_test.py`，不需要联网或 GPU。
2. 运行 `python3 tools/new_film.py starcore --example starcore`，把文字示例复制到 `films/starcore`。新故事用 `python3 tools/new_film.py myfilm`，让助手按[制作手册](skills/cineforge/SKILL.md)推进。
3. 写好故事、场次、分镜并准备参考图。运行 `python3 tools/validate_film.py --film starcore`；准备开拍时加 `--require-media`。先验收最难的三镜。
4. 按[农场指南](docs/zh/render-farm.md)配置后端和自己的 Colab。快速 H3 工作机依赖用户另行取得许可的 Box；官方 LTX 推理适配器仍属于实验流程。
5. [抽检与重拍](docs/zh/qa-and-retakes.md)，再[剪辑出母版](docs/zh/editing.md)。结束后排空工作机、删除运行时并确认停止计费。

## 时间、费用与边界

2026-11-20 的项目单镜记录：G4 上预热后的 Box H3 约 40 秒，LTX distilled 约 40 秒，Pika 批量约 360 秒。这不是整片计时。没有核实过的“331 镜、四台 G4 共几小时/多少钱/CU”的总账，因此不承诺整片价格。下载、参考图、重拍、上传和剪辑都要额外时间。先设置预算并试拍；四会话只是原账号实测，不代表所有账号固定权益。

已有功能：多片配置、租约去重、回执续跑、回传解码验证、抽帧、语音剪点估计、配乐与字幕。尚未在公开版全新环境验证完整 GPU 流程；没有通用一键 CLI、权重、图片、音乐或公开 notebook。VLM 抽检仍需助手或真人判断。各适配器状态见[模型](docs/zh/models.md)。

## 许可与隐私

代码采用 Apache-2.0。模型、配乐和图片另有许可。MiniMax-H3 社区许可不覆盖美国、欧盟、英国、韩国，并要求标注 AI 生成；使用与发布输出前阅读[官方许可](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)。LTX-2.5 为 gated 模型，先在 HF 接受[模型许可](https://huggingface.co/Lightricks/LTX-2.5)及所需超分模型许可。开放权重不代表无使用限制。

按文档操作时 HF/API 令牌只放进程内存；隧道地址和农场凭据只填进自己的 notebook 单元，不提交或分享。可选旧浏览器工具读取本地忽略的 URL/token 文件；服务默认也会写本地 token，使用 `--token-env` 可避免落盘。见 [SECURITY](SECURITY.md)。

## 示例电影

- [《星核黎明》](examples/starcore/README.md)：主文字示例；成片链接 coming soon。
- [《三花信号》](examples/catfilm/README.md)：成片链接 coming soon。
- [《残响》](examples/echo/README.md)：成片链接 coming soon。

[写分镜](docs/zh/writing-a-script.md) · [排障](docs/zh/troubleshooting.md) · [常见问题](docs/zh/faq.md) · [参与贡献](CONTRIBUTING.md)
