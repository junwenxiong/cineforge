# 抽检与重拍

运行 `python3 tools/film/anatomy_strips.py`，从所有原片 25%、50%、85% 位置抽帧；或用 `python3 tools/film/qa_sheet.py --film starcore S01 S02`。`continuity_report.py --film starcore` 做技术连续性统计，需要 NumPy/Pillow。抽帧会漏掉中间帧问题，验收必须看完整视频并听台词。

让助手的视觉模型或真人对照 refs 检查主体数量、手脚尾巴、身份、道具、背景、单一动作和构图。VLM 仅作建议，仓库没有自动 VLM 执行器。将问题写成 `[{"id":"myfilm_s01_01","defect":"多尾"}]`，保存到忽略的 renders/qa/flags.json。尾巴、复制修复识别中文关键词，必须审查提示词。

```sh
python3 tools/film/retake.py --film myfilm --flags renders/qa/flags.json --dry-run
```

检查 job.json、claim.json、farm.log，确认没有工作机正在渲染或上传该镜后，才去掉 --dry-run。脚本跳过有效租约，归档旧 take，修提示词并清零尝试数。它主要用于 H3，过期租约和第二入口仍需协调，不要盲删回执强制重拍。

多轮 H3 肢体失败先修参考图：一张图一个主体一次，并换文件名。仍失败时画干净首帧，写 engine=ltx、项目相对 keyframe 路径、连贯英文 ltx_prompt，台词原文加引号并补 Audio:。先排空所属工作机并归档旧回执，再 stage/collect；collect 故意不覆盖已有 job。先运行 ltx_stage.py --dry-run。LTX 也会继承首帧错误。

验收依据是 completed 回执、SHA256、完整音视频解码、主体正确、对白完整和口型可接受，不是页面可打开或心跳正常。重拍后删除该镜对应的旧抽帧缓存再生成，抽帧器默认跳过已有图片。
