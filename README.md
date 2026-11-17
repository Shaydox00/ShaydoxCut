# ShaydoxCut

Turn long videos and live streams into finished vertical clips. The AI finds the best moments, a smart camera
follows whoever is talking, dead air is cut, and every clip comes out with captions, a hook, emojis, sound effects
and your logo. Post it straight to YouTube, Instagram or TikTok, or export a kit and finish it in CapCut.

Everything runs on your own computer. It is free: there are no credits, you only pay your AI service for what you use
(Gemini's API has a free tier).

## Start it

You need Python 3.10 or newer and `ffmpeg` (on Windows: `winget install Gyan.FFmpeg`).

```bash
pip install -r requirements.txt
```

```bash
python -m studio.server
```

Then open http://127.0.0.1:8766 (the port is set in `.env`). The first start downloads the speech model (about
480 MB, once) and a small face finder (once).

## What it does

**Finding the moments**
- The AI reads the transcript, the loudness and the chat, and looks for sudden action in the picture.
- Before a clip is made, the AI looks at frames from it, so its score and hook account for what happens on screen.
- Every clip gets a virality score with a breakdown: hook, payoff, emotion, shareable and on screen.
- **Moments to include**: tell the AI what you want ("all the funny fails").
- **Learning**: 👍 and 👎 on clips, and the views of posted clips, teach it what works on each channel.

**Editing**
- **Reframe**: Follow speaker (face tracking that cuts to whoever is talking), Facecam + game (finds a streamer's
  webcam by itself), Blurred fill, Zoomed in, Fill screen.
- **23 caption styles** (word pop, highlight box, karaoke fill, one word at a time, spotlight, glow, underline,
  typewriter and more) and **5 hook looks**, each shown as a real preview when you choose.
- **Speech cleanup**: cuts pauses and "um"/"uh" (laughs and screams stay).
- **Enhance audio**, **sound effects**, **background music** that dips when someone talks.
- **Auto zoom** on key words, **auto transitions** on jump cuts, **auto color correction**.
- **AI emojis**: 3D emojis that pop in on the big moments.
- **Auto B-roll**: short stock videos over what is described (free Pexels key, in Settings, Brand kit).
- **Progress bar**, **brand kit** (logo, fonts, colours, saved caption styles), **captions in 20 languages**.

Every effect can be switched on or off per video (Options), per creator (their Setup) and per clip (open it,
change it, **Save and re-make clip**).

**Finishing**
- **Export for CapCut**: the finished clip, a clean copy with no text to edit on, captions as .srt, the emojis,
  sounds, logo and music with their times, the post text, and a timeline for Premiere Pro and DaVinci Resolve.
- **Posting**: connect YouTube, Instagram and TikTok in Settings, Connected apps, then post or queue clips.
- **Live streams**: add a creator, and ShaydoxCut records their stream and clips it while it is live.

## Choosing an AI

Settings, AI: pick a service, paste your key, press **Find models**, then **Save and test**. Gemini, OpenAI and
Claude can all look at pictures; others (Grok, Groq, OpenRouter, a local model through Ollama) work on the words.
Chat subscriptions (ChatGPT Plus, Claude Pro, Gemini Advanced) do not include API access: the key comes from the
service's developer site.

## Settings

Most things are set in the dashboard. A few can go in `.env`; `.env.example` lists every one with an explanation.

| Setting | What it is for |
|---|---|
| `SHAYDOX_PORT` | The port it runs on |
| `SHAYDOX_DATA` | Where videos, clips and settings are kept (or move it in Settings, Storage) |
| `SHAYDOX_AI_PROVIDER`, `SHAYDOX_AI_MODELS`, `SHAYDOX_AI_KEY` | The AI, if you prefer a file to the dashboard |
| `SHAYDOX_ACCOUNTS` | `1` makes everyone sign in. Use it on any server other people can reach |
| `SHAYDOX_UPDATE_REPO` | Your own GitHub repository ("you/shaydoxcut") to be told about new versions |

[DEPLOY.md](DEPLOY.md) explains running it on a server with Docker.

## How it is built

| File | What it does |
|---|---|
| `studio/server.py` | Every web route |
| `studio/jobs.py` | The video pipeline and the queue |
| `studio/brain.py` | The prompts: finding clips, looking at frames, captions |
| `studio/ai.py` | The only code that talks to an AI service |
| `studio/camera.py` | Faces, who is talking, facecam detection, drawing every frame |
| `studio/render.py` | The tight edit, and the final picture and sound with every effect |
| `studio/captions.py` | Caption styles, hook looks and their previews |
| `studio/effects.py` | Emojis, sound effects, music, B-roll |
| `studio/brand.py`, `studio/learn.py`, `studio/export.py` | Brand kit, learning, the CapCut kit |
| `web/index.html` | The whole dashboard, one file, no build step |

## Tests

```bash
python tests/run.py
```

## Licence

MIT (see [LICENSE](LICENSE)). Caption fonts in `studio/fonts/` are under the SIL Open Font License. The 3D emojis are
Microsoft's Fluent Emoji (MIT). Only use videos, music and fonts you have the rights to.
