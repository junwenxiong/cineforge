# 写出模型能执行的分镜

按顺序写 故事圣经.md（创意、人物弧光、世界规则、时长）、scenes.json（有序节拍与准确台词）、visual_locks.json（固定外观）、refs.json（参考图及依赖）、shots/S01.json（镜头数组）。每镜原样复用相关视觉锁。目标时长只是计划，累计时要留反应镜和停顿。

```json
[{"id":"myfilm_s01_01","scene":"S01","mode":"reference","seconds":6,"resolution":"720p","refs":["assets/myfilm/refs/hero.png"],"prompt":"<Picture 1> shows the hero. Deep focus, crisp skin pores and fabric detail. The hero raises one hand.","summary_zh":"主角举手","dialogue":[]}]
```

H3 的六段式完整提示词参考星核示例。`<Picture 1>` 指 refs 第一张图，不是角色编号，每镜最多五张。对白格式 `{"who":"主角","text":"准确台词"}`，必须与 scenes.json 一致。把 `<d>` 台词提前，要求第一秒开始说话。一般每镜 5–6 秒，只写一个动作。

每张参考图只画一个主体一次：不要三视图、小窗、第二姿态。道具图明确没有人、猫或其他动物。开拍前先看总览图；替换图必须换文件名并更新 refs，因为工作机按 URL 缓存。猫片不附原主人的真实照片，请自行设计新猫形象。

背影用 partially_preserved，明确只见后脑和肩、不见脸，优先 3/4 后侧。多人镜写 each subject appears exactly once；同一人不要描述成两个主体。用 check_backview.py 检查，修改已拍镜头前先确认状态。

写 deep focus, crisp skin pores and fabric detail，避免 soft focus / shallow depth / bokeh，雾只放远景。连续复杂动作容易触发自切镜和虚焦特写。

运行 `python3 tools/validate_film.py --film myfilm --require-media`。结构校验不能替代台词、视觉锁和创作审查。pilot.json 先放最难三镜，人物、动作与声音都通过后再全片开拍。
