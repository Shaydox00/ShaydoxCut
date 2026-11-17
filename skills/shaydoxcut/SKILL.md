---
name: shaydoxcut
description: Install, start, update or fix ShaydoxCut, the free AI clipping studio that turns long videos and live streams into finished vertical clips (Shorts, TikTok, Reels) on the user's own computer. Use when the user asks to install, set up, run, open, start, update, upgrade, move or troubleshoot ShaydoxCut, or asks how to make clips with it.
---

# ShaydoxCut

ShaydoxCut is a local web app (Python + ffmpeg). It runs on the user's computer and opens in their browser at
http://127.0.0.1:8765. Repository: https://github.com/Shaydox00/ShaydoxCut

Speak to the user in plain words: they may not be a programmer. Say what you are about to do before each step that
installs software, and ask before anything that installs system-wide software or deletes files.

## Install

1. **Ask where to put it.** Suggest a short, permanent folder: `C:\shaydoxcut` on Windows, `~/shaydoxcut` on a Mac or
   Linux. Never install into a temporary folder or this assistant's own workspace or scratch folder: those get
   cleaned up, and on Windows a long path (over about 100 characters) stops the speech model from loading.
   If ShaydoxCut is already there, go to **Update** instead.

2. **Check the tools.** Run these and look at the answers:
   - `git --version`
   - Python 3.10 or newer: `python --version` (on a Mac or Linux also try `python3 --version`)
   - `ffmpeg -version`

   For anything missing, tell the user what it is for and ask before installing it:
   - Windows: `winget install Git.Git`, `winget install Python.Python.3.12`, `winget install Gyan.FFmpeg`
     (a new terminal may be needed afterwards so the new programs are found)
   - Mac (with Homebrew): `brew install git python ffmpeg`
   - Linux (Debian/Ubuntu): `sudo apt install git python3 python3-venv ffmpeg`

3. **Download it** into the chosen folder:
   ```
   git clone https://github.com/Shaydox00/ShaydoxCut <folder>
   ```
   If git asks to sign in, the repository may be private: the user needs the owner to invite them on GitHub first.

4. **Install its packages** in a private Python environment inside that folder (this takes a few minutes):
   - Windows:
     ```
     cd <folder>
     python -m venv .venv
     .venv\Scripts\python -m pip install -r requirements.txt
     ```
   - Mac / Linux:
     ```
     cd <folder>
     python3 -m venv .venv
     .venv/bin/python -m pip install -r requirements.txt
     ```

5. **Start it** (see **Start**) and open http://127.0.0.1:8765. The first start downloads the speech model (about
   480 MB, once), so the first video waits for that.

6. **Tell the user** where it is installed, how to start it next time, and the next step below.

## First steps for the user

- **Add an AI key:** in ShaydoxCut, Settings, AI. Gemini has a free tier: a key from https://aistudio.google.com/apikey
  works. Claude or OpenAI keys work too (paid per use). Chat subscriptions (ChatGPT Plus, Claude Pro, Gemini
  Advanced) do not include these keys. Without a key, clips are picked by loudness only.
- **Make clips:** paste a YouTube, Twitch or Kick link (or upload a video) on Home, press Make clips. Options sets the
  number and length of clips, caption style, hook, layout and effects.
- **Optional:** a free Pexels key (Settings, Brand kit) turns on Auto B-roll. A logo, fonts and music go in the
  Brand kit too.

## Start

ShaydoxCut runs only while its window is open. Start it in its own terminal so it keeps running:

- Windows: `cd <folder>` then `.venv\Scripts\python -m studio.server`
- Mac / Linux: `cd <folder>` then `.venv/bin/python -m studio.server`

It prints `ShaydoxCut is running: http://127.0.0.1:8765`. Open that address. To stop it, press Ctrl+C in its window.
If port 8765 is taken, put `SHAYDOX_PORT=8766` in a file called `.env` in the folder and start it again.

## Update

1. Stop ShaydoxCut if it is running (Ctrl+C in its window).
2. In its folder: `git pull`
3. Install any new packages: `.venv\Scripts\python -m pip install -r requirements.txt` (Mac/Linux: `.venv/bin/python ...`)
4. Start it again. The user's videos, clips, keys and settings (the `data` folder and `.env`) are not touched.

If the folder is in a temporary or very deep location, offer to move it: clone into the new short folder, copy over
`.env`, `storage.json` and the `data` folder, install the packages, start it there and check the clips are there.
Only then offer to delete the old folder, and only if the user says yes.

## Fixing problems

- **"ffmpeg is missing"** in the dashboard: install ffmpeg (step 2), open a new terminal, start again.
- **"DLL load failed ... The filename or extension is too long"** (Windows): the folder path is too long. Move it to a
  short folder like `C:\shaydoxcut` (see Update).
- **Clips picked "by loudness" or the hook is missing:** the AI did not answer. Settings, AI shows why (no key, quota
  used up, or the service overloaded). Adding a second model after a comma there lets it switch when one is busy.
- **A YouTube video fails to download:** try again later or upload the file instead; YouTube sometimes refuses.
- **Tests** (for checking an install): `.venv\Scripts\python tests/run.py` (Mac/Linux: `.venv/bin/python tests/run.py`).

Read `README.md` and `AGENTS.md` in the ShaydoxCut folder for everything else.
