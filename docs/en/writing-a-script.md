# Write shots the model can follow

Start with 故事圣经.md (premise, character arcs, world rules and length), then scenes.json (ordered beats and exact dialogue), visual_locks.json (unchanging identity/design descriptions), refs.json (image prompts and dependencies), and shots/S01.json (arrays of shots). Copy visual locks verbatim into each relevant prompt. Target duration is a plan, not a guarantee; add pauses and reactions when counting seconds.

```json
[{"id":"myfilm_s01_01","scene":"S01","mode":"reference","seconds":6,"resolution":"720p","refs":["assets/myfilm/refs/hero.png"],"prompt":"<Picture 1> shows the hero. Deep focus, crisp skin pores and fabric detail. The hero raises one hand.","summary_zh":"主角举手","dialogue":[]}]
```

For H3 use the full six-section prompt structure in the Starcore examples. `<Picture 1>` means the first refs path, not a character number; use at most five references. Dialogue entries are `{"who":"Hero","text":"Exact line"}` and must match scenes.json. Put `<d>` dialogue early in the action description and request speech within the first second. Plan mostly 5–6 second shots, one action per shot.

Every reference image must show one subject once. No turnarounds, inset views or two poses. Prop images must contain no cat, animal or person. Review a contact sheet before rendering. If replacing an image, change its filename and shot refs because workers cache by URL. The cat example intentionally ships without the owner's real photos: create your own original cat design.

For back views use partially_preserved retention and explicitly say only back of head/shoulders, no visible face. Prefer a three-quarter rear angle. In group shots say “each subject appears exactly once”; do not describe one person as two subjects. Inspect with check_backview.py before changing already rendered shots.

Use “deep focus, crisp skin pores and fabric detail”; avoid soft focus, shallow depth, bokeh and foreground haze. Keep mist in distant backgrounds. A complicated action chain encourages unwanted cuts and blurred close-ups.

Run `python3 tools/validate_film.py --film myfilm --require-media`. Structural validation does not replace dialogue, visual-lock or creative review. Keep the hardest three shots in pilot.json and review motion, identity and audio before queueing the whole film.
