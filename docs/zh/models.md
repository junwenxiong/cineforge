# 模型与适配器状态

以下是项目 2026-11-20 的观察，不是可复现的公开基准。当时 G4 为 RTX PRO 6000 Blackwell 96GB；耗时受预热、分辨率、镜长和参考图数量影响。保留全部适配器供研究，但公开导出版尚未做 GPU 验证。

| 适配器 | 单镜实测 | 用途与限制 |
|---|---:|---|
| Box H3，ref 引擎 + 4 步 LoRA | 约 40 秒 | 多参考图机器人身份最好；需另行取得 Box 专有运行时 |
| LTX-2.5 distilled | 约 40 秒 | 单首帧与人像特写好；机器人变形容易改造型 |
| LTX DFR + 细节 LoRA | 约 50 秒 | 更锐，但变形主体会被重新设计 |
| Pika H3 Flex 单镜 CLI | 约 830 秒 | 每镜重新加载权重 |
| Pika batch | 约 360 秒 | 采样约 305 秒、解码 57 秒，首次文本编码 200 秒；慢于 Box H3 |
| Hyperflow H3 Flash | 6 步 270–310 秒；8 步 350–400 秒 | 实验：Blackwell 缺 FA3，丢场景锁，需 H100 复测 |
| RelayVSR X2 | 推理 6–8 秒，含加载 26–53 秒 | 2 倍增强有用，保留原音轨；传输可能更耗时 |
| Open-H3 Regenerate IC | 每 5 秒窗口约 237 秒 | 每片约 8 分钟，脸轻微变化，成本高 |
| MagiHuman | 未成功出片 | G4 的 720p/1080p 超分爆显存，还需其他 gated 编码器 |

Box H3 约 -15～-20 LUFS，LTX distilled -8～-17，DFR -9～-19，Pika -17～-19。混音前听声音并统一响度。公平对比要固定分镜、refs/首帧、seed、镜长与分辨率，包含对白、机体动作和变形镜；用抽帧看身份和动作，再听口型与拟音。区分预热推理和下载加载时间。

同一历史日志里，HunyuanVideo-1.5 因无声音被排除；Wan 2.7 记为 API-only，未接入。这不是当前市场调查。Pika/Hyperflow 为实验适配器，MagiHuman 保留失败尝试供研究，H3 A/B 依赖 Box。lab/enhance.py 含 RelayVSR 与 regenerate，lab/relayvsr_film.py 做批量增强。

代码许可不包含模型权利。阅读 [H3 官方许可](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)：不覆盖美国、欧盟、英国、韩国并要求 AI 标注，衍生模型也需另查许可。[LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) 与[超分模型](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler)需先接受 gated 许可。使用官方仓库并核对 revision/校验和，不擅自替换镜像权重。
