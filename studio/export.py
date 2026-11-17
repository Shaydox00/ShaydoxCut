"""Export to an editor: everything needed to finish a clip in CapCut (or Premiere Pro, DaVinci Resolve, Final Cut).

CapCut cannot open another app's project files, so the kit gives it what it can use directly:
- the finished clip, and a clean copy (same cut and camera, no text or effects) to build your own edit on,
- captions as .srt files (in phrases, and one word at a time) for CapCut's Import captions,
- the emoji pictures, sound effects, logo and music that were used, with a list of when each one appears,
- the post text,
- an XML timeline (Final Cut Pro 7 XML) that Premiere Pro and DaVinci Resolve open, with markers on every effect.
"""
import json
import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from . import config, ctx, effects, jobs

FPS = 30

HOW_TO = """HOW TO FINISH THIS CLIP IN CAPCUT
=================================

What's in this folder
  {base}_captioned.mp4         The finished clip: captions, hook, emojis, sound effects. Ready to post.
  {base}_clean.mp4             The same cut and camera with NO text or effects. Build your own edit on this one.
  captions.srt                 Captions in short phrases.
  captions_word_by_word.srt    Captions one word at a time (the popular Shorts look).
  cues.txt                     When each emoji, zoom and sound effect happens, in seconds.
  post.txt                     Title, description and hashtags to paste when you post.
  assets/                      The emoji pictures, sound effects{logo_line}{music_line} used in the clip.
  timeline_premiere_davinci.xml  A timeline for Premiere Pro or DaVinci Resolve (not for CapCut).

CapCut on a computer (Windows or Mac)
  1. Open CapCut and press "New project" (or "Create project").
  2. Press Import and choose {base}_clean.mp4. Drag it onto the timeline. CapCut sets the project to 9:16 to match.
  3. Captions, either way:
       a) Your captions: in the Captions (or Text) panel choose "Import captions" / "Local captions", pick
          captions_word_by_word.srt (or captions.srt), then choose a caption template for the look.
       b) CapCut's own: press "Auto captions" and choose the language. CapCut writes them from the sound.
  4. Emojis and sounds: import the files in assets/ and place them at the times listed in cues.txt.
     (Or drag in CapCut's own stickers and sound effects at those times.)
  5. Export at 1080p, 30 fps.

CapCut on a phone
  Phone CapCut can't import .srt files. Import {base}_clean.mp4, then use Text > Auto captions.
  Or simply post {base}_captioned.mp4, which is already finished.

Premiere Pro / DaVinci Resolve
  File > Import > choose timeline_premiere_davinci.xml. If asked where the video is, point it at
  {base}_clean.mp4 in this folder. Markers on the timeline show each emoji, zoom and sound effect.
"""


def _slug(s, fallback):
    s = re.sub(r"[^\w\- ]+", "", str(s or "")).strip()[:50].strip()
    return re.sub(r"\s+", "_", s) or fallback


def _fcp_xml(base: str, clean_name: str, dur: float, cues: dict) -> str:
    n = max(1, int(round(dur * FPS)))
    rate = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"
    file_el = (f'<file id="file-1"><name>{escape(clean_name)}</name><pathurl>{escape(clean_name)}</pathurl>{rate}'
               f"<duration>{n}</duration><media><video><samplecharacteristics><width>1080</width><height>1920</height>"
               f"</samplecharacteristics></video><audio><samplecharacteristics><depth>16</depth><samplerate>48000"
               f"</samplerate></samplecharacteristics><channelcount>2</channelcount></audio></media></file>")
    markers = []
    for e in cues.get("emojis", []):
        markers.append((e["time"], f"Emoji {e['emoji']}", "emoji"))
    for a, _b in cues.get("punches", []):
        markers.append((a, "Zoom in", "punch-in on a key word"))
    for s in cues.get("sounds", []):
        if s["sound"] != "pop":
            markers.append((s["time"], f"Sound: {s['sound']}", "sound effect"))
    mk = "".join(f"<marker><name>{escape(nm)}</name><comment>{escape(c)}</comment><in>{int(round(t * FPS))}</in>"
                 f"<out>-1</out></marker>" for t, nm, c in sorted(markers))
    clip_v = (f'<clipitem id="clip-v"><name>{escape(clean_name)}</name><duration>{n}</duration>{rate}<start>0</start>'
              f"<end>{n}</end><in>0</in><out>{n}</out>{file_el}</clipitem>")
    clip_a = (f'<clipitem id="clip-a"><name>{escape(clean_name)}</name><duration>{n}</duration>{rate}<start>0</start>'
              f'<end>{n}</end><in>0</in><out>{n}</out><file id="file-1"/><sourcetrack><mediatype>audio</mediatype>'
              f"<trackindex>1</trackindex></sourcetrack></clipitem>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="seq-1">'
            f"<name>{escape(base)}</name><duration>{n}</duration>{rate}<media><video><format><samplecharacteristics>"
            f"{rate}<width>1080</width><height>1920</height><pixelaspectratio>square</pixelaspectratio>"
            f"</samplecharacteristics></format><track>{clip_v}</track></video><audio><track>{clip_a}</track></audio>"
            f"</media>{mk}</sequence></xmeml>\n")


def _cues_text(cues: dict) -> str:
    rows = [f"Clip length: {cues.get('duration', 0):.2f} s" +
            (f"  (dead air and filler words cut: {cues.get('cut', 0):.1f} s)" if cues.get("cut") else ""), ""]
    for e in cues.get("emojis", []):
        rows.append(f"{e['time']:7.2f} s   emoji {e['emoji']}   (assets/emoji_{e['time']:.2f}s.png)")
    for a, b in cues.get("punches", []):
        rows.append(f"{a:7.2f} s   zoom in until {b:.2f} s")
    for s in cues.get("sounds", []):
        rows.append(f"{s['time']:7.2f} s   sound effect: {s['sound']} (assets/{s['sound']}.wav)")
    if cues.get("music"):
        rows.append(f"   0.00 s   music under the whole clip, quieter while someone talks: {cues['music']}")
    return "\n".join(rows[:2] + sorted(rows[2:])) + "\n"


def _add_clip(z: zipfile.ZipFile, job: dict, clip: dict, folder: str, used: set):
    d = Path(job["dir"]) / "clips"
    cid = clip["id"]
    finished = d / Path(str(clip.get("file") or "")).name
    if not finished.is_file():
        return False
    base = _slug(clip.get("title") or clip.get("hook"), cid)
    while base.lower() in used:
        base += "_2"
    used.add(base.lower())
    root = f"{folder}{base}/" if folder is not None else ""
    z.write(finished, root + f"{base}_captioned.mp4")
    clean = d / Path(str(clip.get("clean") or f"{cid}_clean.mp4")).name
    if clean.is_file():
        z.write(clean, root + f"{base}_clean.mp4")
    for src, name in ((d / f"{cid}.srt", "captions.srt"), (d / f"{cid}.words.srt", "captions_word_by_word.srt")):
        if src.is_file():
            z.write(src, root + name)
    try:
        cues = json.loads((d / f"{cid}.cues.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cues = {"duration": clip["end"] - clip["start"], "emojis": [], "punches": [], "sounds": []}
    z.writestr(root + "cues.txt", _cues_text(cues))
    tags = " ".join("#" + t for t in clip.get("hashtags") or [])
    z.writestr(root + "post.txt", f"HOOK: {clip.get('hook', '')}\n\nTITLE: {clip.get('title', '')}\n\n"
                                  f"DESCRIPTION:\n{clip.get('description', '')}\n\n{tags}\n")
    for e in cues.get("emojis", []):
        png = effects.emoji_png(e["emoji"])
        if png:
            z.write(png, root + f"assets/emoji_{e['time']:.2f}s.png")
    for name in sorted({s["sound"] for s in cues.get("sounds", [])}):
        f = effects.sound(name)
        z.write(f, root + f"assets/{name}.wav")
    from . import brand
    logo = brand.logo_path(job["user"]) if clip.get("brand", True) else None
    if logo:
        z.write(logo, root + "assets/logo.png")
    music = cues.get("music")
    if music:
        mf = effects.music_dir(job["user"]) / Path(music).name
        if mf.is_file():
            z.write(mf, root + f"assets/music{mf.suffix}")
    z.writestr(root + "timeline_premiere_davinci.xml", _fcp_xml(base, f"{base}_clean.mp4", cues.get("duration", 0), cues))
    z.writestr(root + "HOW TO OPEN IN CAPCUT.txt", HOW_TO.format(
        base=base, logo_line=", logo" if logo else "", music_line=", music" if music else ""))
    return True


def build(pairs: list) -> tuple:
    """A .zip with an editor kit for each (video id, clip id). Returns (file, name for the download)."""
    tmp = config.user_dir(ctx.uid()) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("export-*.zip"):
        old.unlink(missing_ok=True)
    import secrets
    out = tmp / f"export-{secrets.token_hex(6)}.zip"
    made, used, single = 0, set(), len(pairs) == 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for jid, cid in dict.fromkeys(pairs):
            job = jobs.get(jid)
            clip = next((c for c in (job or {}).get("clips", []) if c["id"] == cid and c.get("status") == "done"), None)
            if clip and _add_clip(z, job, clip, None if single else "", used):
                made += 1
                name = _slug(clip.get("title") or clip.get("hook"), cid)
    if not made:
        out.unlink(missing_ok=True)
        raise ValueError("None of those clips are ready to export.")
    return out, (f"{name}_capcut_kit.zip" if single else f"shaydoxcut-{made}-clips-capcut-kit.zip")


def cleanup(f: Path):
    shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
