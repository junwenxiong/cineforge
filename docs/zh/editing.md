# 剪辑、音乐与母版

安装带 libass/字幕支持的 ffmpeg 和中文字体。已授权音乐放 assets/<film>/music，在 music_cues.json 和 film.json 填提示与署名。示例曲名、署名只是历史参考，不附音乐，也不能证明你有许可；逐项核对来源并保留授权记录。缺音乐时不要编造音轨。

```sh
python3 tools/film/speech_cut.py --film starcore --dry-run
python3 tools/film/speech_cut.py --film starcore
python3 tools/film/rough_cut.py --film starcore --name final
python3 tools/film/score_mix.py --film starcore --name final
python3 tools/film/master.py --film starcore --name final
```

先审查 dry-run 再写剪点。speech_cut 用 ffmpeg 静音检测估计最后声音，不是语义 ASR/VAD，音乐和拟音可能让尾部保留。films/<film>/cut.json 按镜号写 in/out/drop。人工确认出点可参考 min(实际时长−0.05, 说话结束+0.25)。原项目发现平均约 2.4 秒才开口、成片比标称长约 0.6 秒；按标称时长×0.92 剪曾剪断 59 句中的 32 句。

剪辑器按实际分段时长累计时间线。逐段帧长取整曾在 354 镜中造成 6.9 秒字幕漂移，开头和结尾都要对字幕，不要用标称秒数重建时间线。听转场，压低对白下的配乐，特别注意 LTX 比 H3 响。

可选高清：vsr_stage.py --films starcore --name final 准备任务，Colab 跑 lab/relayvsr_film.py，vsr_assemble.py 校验分块回传。确认所有目标镜头增强完成后，再给 rough_cut、score_mix、master 加 --hd。缺增强片会回退到原片放大，不等于全片增强。成片在 videos/<film>/，如 final_master.mp4 或 final_hd_master.mp4。完整解码，核对对白、字幕、署名和 AI 标注后再发布。
