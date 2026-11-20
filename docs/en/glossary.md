# CineForge glossary

New to filmmaking or cloud computers? Start here. [Back to the README](../../README.md) · [中文](../zh/glossary.md)

## Shot

One continuous piece of video before a cut to another view. In CineForge, it is usually a short generated clip, often 5–6 seconds. A scene can contain many shots: a room, a speaker, then the listener's reaction.

## Shot size: how much you see

Shot size means how much of the subject fills the picture. It is not the video's pixel resolution. This ladder goes from the widest view to the closest:

| Short name | Name | What you see |
|---|---|---|
| EWS / ELS | Extreme wide / extreme long shot | A large landscape; a person may look tiny |
| WS / LS | Wide / long shot | The whole person and plenty of surroundings |
| FS | Full shot | The person from head to feet |
| MLS | Medium long shot | Roughly knees up |
| MS | Medium shot | Roughly waist up |
| MCU | Medium close-up | Roughly chest up |
| CU | Close-up | Mostly the face |
| ECU | Extreme close-up | A small detail, such as an eye or fingertip |

These are filmmaking conventions, not exact crop measurements or a promise that every model obeys them. Going closer can emphasize emotion; changing size suddenly can feel jarring. Plan the change rather than letting every shot become a face filling the screen. The current LTX picture instructions favor MS/MCU unless a shot explicitly requests CU/ECU. Other sizes still need your written instructions and visual review.

## Reference image

A picture showing what a person, animal, prop or place should look like. It helps keep the design recognizable between shots. Make each reference picture show one subject once: two views of a cat can accidentally become two cats in the video.

## Keyframe

For this project's LTX workflow, the picture used as the video's starting frame. Unlike a general reference image, it sets the opening pose and composition. A wrong extra hand in this picture can remain wrong in the video, so inspect it first.

## H3

MiniMax-H3, an AI model that generates video with sound. This project's fast H3 route uses the user's separately licensed DramaPie Box installation and can use several reference pictures. Box's implementation is not included. H3 also has its own model license and territory limits; see [models](models.md).

## LTX

LTX-2.5, another AI video-and-sound model. CineForge uses a starting picture to guide it. “Distilled” names its faster version in this workflow. It offers a route without Box, but you still need to configure Colab and accept the required Hugging Face licenses. See [models](models.md).

## Colab runtime

The temporary remote computer connected to your Google Colab notebook. The notebook is the web page with code; the runtime is the computer executing it. Disconnect and delete the runtime after work and uploads finish, then check that usage has stopped. Closing a browser tab alone is not a reliable shutdown procedure.

## GPU

Graphics processing unit: a chip that can perform many calculations at once. It does the heavy work of generating video. CineForge's intended setup rents this chip through Colab, so you do not need a powerful GPU in your own computer. “G4” is the GPU option name reported in the project's measurements; availability varies.

## Tunnel

A temporary internet connection that lets your Colab computer reach the film service on your own computer. Keep its address and access token private. The address can change after a restart, and interrupted transfers may need another attempt. See [render farm](render-farm.md).

## Render farm

Several computers making video shots for the same film. “Rendering” here means generating the video. CineForge's local service hands out work and receives finished clips; each cloud computer runs one heavy video job at a time. More computers also consume more paid credit.

## Retake

Another attempt at a shot that failed review. Fix the cause first—a bad picture, unclear action or wrong framing—then generate it again. Save the earlier version and make sure no computer is still working on that shot. See [QA and retakes](qa-and-retakes.md).

## LUFS

Loudness Units relative to Full Scale: a way to measure how loud audio sounds to a listener. A value closer to zero is louder: −10 LUFS is louder than −20 LUFS. Different video models can produce very different volumes, so match them during editing and listen for abrupt changes. LUFS does not measure whether dialogue is correct or music is good.
