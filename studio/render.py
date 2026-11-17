"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, roman
from .media import NO_WINDOW, run

W, H = config.OUT_W, config.OUT_H

from .captions import (FONT_FILES, FONT_PATHS, STYLES, _clean, _groups, _key, bgr,  # noqa: E402,F401
                       build_ass, install_fonts)
from . import captions  # noqa: E402

LAYOUTS = {"track": "Follow the speaker (face tracking)", "split": "Facecam on top, gameplay below",
           "blur": "Full frame + blurred fill", "zoom": "Zoomed in + blurred fill", "crop": "Fill the screen (centre crop)"}


def geometry(src_w, src_h, layout):
    """Where the video sits in the 1080x1920 frame, and where hook and captions go."""
    if src_h >= src_w and layout != "crop":
        layout = "crop"  # already vertical or square: nothing to gain from a blurred fill
    if layout == "blur":
        fg_h = min(H, int(round(W * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = 1000
    else:
        fg_h = H
    top = (H - fg_h) // 2
    if layout == "crop":
        return layout, fg_h, 300, 1380
    return layout, fg_h, max(230, top - 190), min(1640, top + fg_h + 180)


def _filter(layout, fg_h):
    if layout == "crop":
        return f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[v0];"
    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,"
            f"scale={W}:{H},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={W}:{fg_h}:force_original_aspect_ratio=increase,crop={W}:{fg_h}[fg];"
            f"[bg][fg]overlay=0:(H-h)/2,setsar=1[v0];")


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on

FILLERS = {"um", "uh", "uhm", "umm", "uhh", "erm", "er", "hmm", "hm", "mm", "mhm", "uh-huh"}


# ---------------------------------------------------------------- tight edit: cut the dead air and the ums
def clip_audio(src: Path, start: float, end: float):
    """The clip's sound as 16 kHz mono numbers, for finding the quiet parts."""
    import numpy as np
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src),
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True,
                       creationflags=NO_WINDOW, timeout=300)
    if p.returncode != 0:
        return None
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def tighten(words, start, end, audio=None, cut_fillers=True, min_gap=0.45):
    """The parts of the clip to keep: talking and anything loud (a laugh, a scream, an explosion) stays; stretches
    that are both wordless and quiet for longer than `min_gap`, and filler sounds (um, uh), are taken out.
    Returns [(from, to)] in the source's seconds."""
    import numpy as np
    dur = end - start
    keep = np.zeros(int(dur * 100) + 1, dtype=bool)               # one slot per 10 ms
    fill = np.zeros_like(keep)

    def mark(arr, a, b):
        i, j = max(0, int((a - start) * 100)), min(len(arr), int((b - start) * 100) + 1)
        if j > i:
            arr[i:j] = True

    for w in words:
        k = re.sub(r"[^a-z\-]", "", w["w"].lower())
        if cut_fillers and k in FILLERS and w["e"] - w["s"] < 1.2:
            mark(fill, w["s"], w["e"])
        else:
            mark(keep, w["s"] - 0.1, w["e"] + 0.14)
    if audio is not None and len(audio) > 1600:
        hop = 160                                                   # 10 ms at 16 kHz
        n = len(audio) // hop
        rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
        db = 20 * np.log10(rms)
        speechy = np.percentile(db, 70)
        loud = db > max(-38.0, speechy - 14)                        # clearly above the room's quiet
        loud = np.convolve(loud.astype(float), np.ones(15) / 15, mode="same") > 0.5
        m = min(len(keep), len(loud))
        keep[:m] |= loud[:m] & ~fill[:m]
    keep &= ~fill
    segs, i, n = [], 0, len(keep)
    while i < n:
        if keep[i]:
            j = i
            while j < n and keep[j]:
                j += 1
            segs.append([i / 100, j / 100])
            i = j
        else:
            i += 1
    merged = []                                  # a pause shorter than min_gap stays: a breath keeps the speech natural
    for a, b in segs:
        bridge = fill[int(merged[-1][1] * 100):int(a * 100)].any() if merged else False   # never bridge over an um
        if merged and a - merged[-1][1] < min_gap and not bridge:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    merged = [(start + max(0.0, a - 0.04), start + min(dur, b + 0.06)) for a, b in merged if b - a >= 0.12]
    if not merged:
        return [(start, end)]
    if dur - sum(b - a for a, b in merged) < 0.4:
        return [(start, end)]
    return merged


def remap(words, segments):
    """Words moved onto the clip's own timeline after cuts. Words inside a cut part are dropped."""
    out, offset = [], 0.0
    for a, b in segments:
        for w in words:
            mid = (w["s"] + w["e"]) / 2
            if a <= mid < b:
                out.append(dict(w, s=round(max(0.0, w["s"] - a) + offset, 3), e=round(min(b, w["e"]) - a + offset, 3)))
        offset += b - a
    return out


# ---------------------------------------------------------------- subtitles for editors (CapCut, Premiere...)
def _srt_ts(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(words, per=4, one_word=False) -> str:
    groups = [[w] for w in words] if one_word else _groups(words, per)
    rows = []
    for i, g in enumerate(groups):
        a, b = g[0]["s"], g[-1]["e"]
        if b - a < 0.05:
            b = a + 0.3
        rows.append(f"{i + 1}\n{_srt_ts(a)} --> {_srt_ts(b)}\n{' '.join(_clean(w['w']) for w in g)}\n")
    return "\n".join(rows)


# ---------------------------------------------------------------- the clip
def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int, kit=None,
                music=None) -> dict:
    """Writes <name>.mp4 (finished), <name>_clean.mp4 (same cut and camera, no text or effects: for editing in
    CapCut), <name>.jpg, <name>.ass, <name>.srt, <name>.words.srt and <name>.cues.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    kit = kit or {}
    for fname, f in (kit.get("font_files") or {}).items():
        FONT_PATHS[fname] = f["path"]
    start, end = clip["start"], clip["end"]
    inside = sorted((w for w in words if w["s"] >= start - 0.05 and w["s"] < end), key=lambda w: w["s"])
    # The clip is made in a short work folder and moved into place afterwards. The caption step of ffmpeg cannot
    # open files whose full path is longer than 260 characters on Windows, which a data folder deep inside other
    # folders easily reaches. Inside the work folder every name is short and relative (a drive colon would also
    # break the filter syntax).
    work = Path(tempfile.mkdtemp(prefix="sx"))
    try:
        return _render_in(work, src, out_dir, name, clip, inside, src_w, src_h, kit, music)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _render_in(work, src, out_dir, name, clip, inside, src_w, src_h, kit, music):
    global _qsv_ok
    import json
    from . import camera, effects
    start, end = clip["start"], clip["end"]
    want = clip.get("layout", "track")
    if src_h >= src_w and want in ("blur", "zoom", "split"):
        want = "track"                             # already vertical: nothing to fill, just follow the face
    notes = []
    segments = [(start, end)]
    smart = camera.available()
    if smart and clip.get("tight", True):
        try:
            segments = tighten(inside, start, end, clip_audio(src, start, end), cut_fillers=clip.get("fillers", True))
        except Exception as e:  # noqa: BLE001 - the clip is still made, uncut
            notes.append(f"Tight edit skipped: {str(e)[:120]}")
    words_out = remap(inside, segments)
    dur = sum(b - a for a, b in segments)
    hl_keys = {_key(h) for h in clip.get("highlight_words") or [] if _key(h)}
    punches = []
    if clip.get("punch", True):
        for w in words_out:                                  # push in on the punch words, never two too close together
            if _key(w["w"]) in hl_keys and w["s"] > 0.8 and all(w["s"] - p[0] > 2.6 for p in punches):
                punches.append((w["s"], min(dur, w["e"] + 0.3)))
        punches = punches[:6]
    cam_info = {}
    layout = want
    if smart:
        try:
            cam = camera.plan_clip(src, segments, want)
            camera.draw(src, segments, cam, work / "base.mp4", zoom_events=punches,
                        cut_zoom=clip.get("transitions", True))
            layout = cam["layout"]
            cam_info = {"faces": cam["faces"], "note": cam["note"], "facecam": bool(cam["cams"])}
            if cam["note"]:
                notes.append(cam["note"])
        except Exception as e:  # noqa: BLE001 - the plain layouts below still work
            smart = False
            notes.append(f"Smart camera unavailable ({str(e)[:120]}); used a fixed layout.")
            segments, punches = [(start, end)], []
            words_out, dur = remap(inside, segments), end - start
    if not smart:
        layout = want if want in ("blur", "zoom", "crop") else "crop"
    geo = camera.layout_geometry(layout) if smart else None
    fg_h = None
    if geo:
        hook_y, cap_y = geo
    else:
        layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, layout)
    st = captions.style(clip.get("style", "bounce"), kit)
    hook_look = captions.hook_look(clip.get("hook_style") or "classic", kit)
    ass = build_ass(words_out, 0.0, dur, clip.get("hook", ""), clip.get("style", "bounce"),
                    clip.get("highlight_words", []), hook_y, cap_y, st=st, hook_look=hook_look)
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in set(config.FONTS_DIR.glob("*.ttf")) | set((Path(__file__).resolve().parent / "fonts").glob("*.ttf")):
        if not (work / "f" / f.name).exists():
            shutil.copyfile(f, work / "f" / f.name)
    for f in (kit.get("font_files") or {}).values():
        if Path(f["path"]).is_file():
            shutil.copyfile(f["path"], work / "f" / Path(f["path"]).name)

    # ---- inputs
    inputs, count = [], [0]

    def add(*args):
        inputs.extend(args)
        count[0] += 1
        return count[0] - 1

    if smart:
        v_in = add("-i", "base.mp4")
    else:
        v_in = add("-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(src))
    seek0 = max(0.0, segments[0][0] - 1.0)
    a_in = add("-ss", f"{seek0:.3f}", "-t", f"{segments[-1][1] - seek0 + 0.5:.3f}", "-i", str(src))
    fc = []
    grade = ",normalize=smoothing=30:independence=0.5:strength=0.55,eq=saturation=1.16:contrast=1.04" \
        if clip.get("color") else ""
    if smart:
        fc.append(f"[{v_in}:v]scale={W}:{H}:flags=lanczos,setsar=1,fps={config.OUT_FPS}{grade}[v0]")
    else:
        fc.append(_filter(layout, fg_h).rstrip(";").replace("[0:v]", f"[{v_in}:v]").replace("[v0]", f"{grade}[v0]" if grade else "[v0]"))
    fc.append("[v0]split=2[vclean][vfx]")
    cur = "vfx"
    broll_used = []
    if clip.get("broll") and kit.get("pexels_key"):
        taken = []
        for item in clip.get("broll_cues") or []:            # stock video over the talking, while the word is said
            hit = next((w for w in words_out if _key(w["w"]) == _key(item.get("word", "")) and w["s"] > 1.5
                        and all(abs(w["s"] - t) > 4 for t in taken)), None)
            if not hit:
                continue
            f = effects.broll_clip(item.get("query", ""), kit["pexels_key"], seed=name + item.get("query", ""))
            if not f:
                continue
            t0, d = max(0.0, hit["s"] - 0.3), min(2.4, max(1.0, dur - hit["s"] - 0.5))
            bi = add("-ss", "0.5", "-t", f"{d:.2f}", "-i", str(f))
            k = len(taken)
            fc.append(f"[{bi}:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                      f"setsar=1,format=yuva420p,fade=t=in:st=0:d=0.18:alpha=1,fade=t=out:st={d - 0.2:.2f}:d=0.2:alpha=1,"
                      f"setpts=PTS-STARTPTS+{t0:.3f}/TB[br{k}]")
            fc.append(f"[{cur}][br{k}]overlay=0:0:eof_action=pass[vb{k}]")
            cur = f"vb{k}"
            taken.append(hit["s"])
            broll_used.append({"query": item.get("query", ""), "time": round(t0, 2), "seconds": round(d, 2), "file": f.name})
    cues = {"segments": segments, "emojis": [], "punches": punches, "sounds": [], "broll": []}
    sounds = []                                                    # (file, time, volume)
    if clip.get("sfx", True):
        sounds.append((effects.sound("whoosh"), 0.0, 0.32))
        for a, _b in punches:
            sounds.append((effects.sound("thump"), max(0.0, a - 0.02), 0.45))
    if clip.get("emoji", True):
        shown = effects.pick(words_out, clip.get("highlight_words"), clip.get("emojis"))
        ey = cap_y - 250 if cap_y > 700 else cap_y + 260          # just above the captions
        spots = (W // 2, W // 2 - 190, W // 2 + 190)
        for k, (e, t) in enumerate(shown):
            frames = effects.emoji_frames(e)
            if not frames:
                continue
            ei = add("-framerate", str(effects.ANIM_FPS), "-start_number", "0", "-i", str(frames / "%03d.png"))
            t0 = min(t, max(0.0, dur - effects.ANIM_SECONDS))
            # the animation is a short clip of its own, moved to start on the word
            fc.append(f"[{ei}:v]format=rgba,setpts=PTS-STARTPTS+{t0:.3f}/TB[em{k}]")
            fc.append(f"[{cur}][em{k}]overlay=x={spots[k % 3]}-w/2:y={ey}-h/2:eof_action=pass:format=auto[ve{k}]")
            cur = f"ve{k}"
            cues["emojis"].append({"emoji": e, "time": round(t, 2)})
            if clip.get("sfx", True):
                sounds.append((effects.sound("pop"), t0, 0.5))
    logo = kit.get("logo_path") if clip.get("brand", True) else ""
    if logo and Path(logo).is_file():
        from PIL import Image
        im = Image.open(logo).convert("RGBA")
        lw = max(40, int(W * kit.get("logo_size", 16) / 100))
        im = im.resize((lw, max(1, int(im.height * lw / im.width))), Image.LANCZOS)
        op = kit.get("logo_opacity", 85)
        if op < 100:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * op / 100)))
        im.save(work / "logo.png")
        li = add("-i", "logo.png")
        pos = kit.get("logo_pos", "tr")
        lx = "40" if pos[1] == "l" else "W-w-40"
        ly = "60" if pos[0] == "t" else "H-h-150"
        fc.append(f"[{cur}][{li}:v]overlay=x={lx}:y={ly}[vlogo]")
        cur = "vlogo"
    if clip.get("progress", True):
        col = (kit.get("bar_color") if kit else None) or "C8F542"
        bh = 12
        # A full-width bar that slides in from the left as the clip plays: it reaches the right edge on the last
        # frame. (drawbox can't do this: it works its size out once, at the start.)
        bi = add("-f", "lavfi", "-i", f"color=c=0x{col}:s={W}x{bh}:r={config.OUT_FPS}:d={dur + 1:.2f}")
        fc.append(f"[{cur}]drawbox=x=0:y={H - bh}:w={W}:h={bh}:color=black@0.35:t=fill[vtrack]")
        fc.append(f"[vtrack][{bi}:v]overlay=x='-w+w*t/{max(dur, 0.1):.3f}':y={H - bh}:eof_action=pass[vbar]")
        cur = "vbar"
    fc.append(f"[{cur}]ass={name}.ass:fontsdir=f[v]")
    # ---- sound: the kept parts joined, then effects and music mixed under the voice
    parts = []
    for k, (a, b) in enumerate(segments):
        fc.append(f"[{a_in}:a]atrim={a - seek0:.3f}:{b - seek0:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(0.0, b - a - 0.015):.3f}:d=0.015[p{k}]")
        parts.append(f"[p{k}]")
    clean_up = ("highpass=f=75,afftdn=nf=-28:tn=1,acompressor=threshold=-21dB:ratio=3:attack=8:release=160:makeup=2,"
                if clip.get("enhance", True) else "")      # rumble out, hiss down, levels evened: a cleaner voice
    fc.append(f"{''.join(parts)}concat=n={len(parts)}:v=0:a=1,{clean_up}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[voice]")
    music_file = Path(music) if music and Path(music).is_file() else None
    fc.append("[voice]asplit=" + ("3[vmain][vclean_a][vkey]" if music_file else "2[vmain][vclean_a]"))
    mix = ["[vmain]"]
    for k, (f, t, vol) in enumerate(sounds):
        shutil.copyfile(f, work / f"s{k}.wav")
        si = add("-i", f"s{k}.wav")
        ms = int(t * 1000)
        fc.append(f"[{si}:a]aresample=48000,volume={vol},adelay={ms}|{ms}[sx{k}]")
        mix.append(f"[sx{k}]")
        cues["sounds"].append({"sound": f.stem, "time": round(t, 2)})
    if music_file:
        shutil.copyfile(music_file, work / ("m" + music_file.suffix))
        mi = add("-stream_loop", "-1", "-i", "m" + music_file.suffix)
        fc.append(f"[{mi}:a]atrim=0:{dur + 0.5:.2f},asetpts=PTS-STARTPTS,aresample=48000,volume=0.22,"
                  f"afade=t=out:st={max(0.0, dur - 1.2):.2f}:d=1.2[mus]")
        fc.append("[mus][vkey]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=350[mduck]")
        mix.append("[mduck]")
        cues["music"] = music_file.name
    if len(mix) > 1:
        fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        fc.append("[vmain]anull[a]")
    fc.append("[vclean_a]anull[aclean]")
    graph = ";".join(fc)
    common = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{dur:.3f}", "-pix_fmt"]
    encoders = []
    if _qsv_ok is not False:
        encoders.append(("qsv", ["nv12", "-c:v", "h264_qsv", "-global_quality", "23", "-preset", "fast"]))
    encoders.append(("x264", ["yuv420p", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]))
    err = None
    for label, enc in encoders:
        cmd = (["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", graph,
               "-map", "[v]", "-map", "[a]"] + common + enc + [f"{name}.mp4",
               "-map", "[vclean]", "-map", "[aclean]"] + common + enc + [f"{name}_clean.mp4"])
        p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0:
            if label == "qsv":
                _qsv_ok = True
            break
        err = p.stderr[-1500:]
        if label == "qsv":
            _qsv_ok = False
    else:
        raise RuntimeError(f"Render failed: {err}")
    cover_t = min(1.2, dur / 2)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cover_t:.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-q:v", "3", f"{name}.jpg"], cwd=work)
    (work / f"{name}.srt").write_text(srt(words_out, st.get("per", 3) + 1), encoding="utf-8")
    (work / f"{name}.words.srt").write_text(srt(words_out, one_word=True), encoding="utf-8")
    cues["broll"] = broll_used
    cues.update(duration=round(dur, 3), layout=layout, hook=clip.get("hook", ""), cut=round(end - start - dur, 2),
                words=[{"w": w["w"], "s": w["s"], "e": w["e"]} for w in words_out])
    (work / f"{name}.cues.json").write_text(json.dumps(cues), encoding="utf-8")
    for f in (f"{name}.mp4", f"{name}_clean.mp4", f"{name}.jpg", f"{name}.ass", f"{name}.srt", f"{name}.words.srt",
              f"{name}.cues.json"):
        shutil.move(str(work / f), str(out_dir / f))
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "clean": f"{name}_clean.mp4", "layout": layout,
            "duration_out": round(dur, 2), "cut_seconds": round(end - start - dur, 2), "camera": cam_info,
            "render_note": " ".join(notes)[:300]}
