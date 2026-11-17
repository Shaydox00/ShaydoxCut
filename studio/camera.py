"""The smart camera: finds the faces in a clip, follows whoever is talking, finds a streamer's facecam, and draws
every frame of the vertical video (follow-the-speaker, facecam over gameplay, blurred fill, punch-in zooms).

How it works, in plain words:
1. A few times a second it looks at the picture and finds every face (a small face-finding model from OpenCV).
2. Faces seen in a row at nearly the same place are treated as the same person ("tracks").
3. Whoever's mouth area moves the most is taken as the one talking. The camera only changes person when someone
   else has clearly been talking for a moment, so it never flickers between two people.
4. A face that stays still in one corner for most of the clip is a streamer's facecam.
5. Then every frame is cut and scaled by hand and written into a plain video, which render.py finishes
   (captions, emojis, logo, sound).
"""
import bisect
import math
import subprocess
import threading
from pathlib import Path

import numpy as np

from . import config
from .media import NO_WINDOW

try:
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)      # no technical notices in the server window
    except Exception:  # noqa: BLE001
        pass
except Exception:  # noqa: BLE001 - without OpenCV the old fixed layouts are used
    cv2 = None

BASE_W, BASE_H = 720, 1280          # frames are drawn at this size; ffmpeg scales them to 1080x1920 with a sharp filter
SAMPLE_EVERY = 0.2                  # seconds between face checks
DETECT_W = 640                      # the picture is shrunk to this width before looking for faces
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
SPLIT_TOP = 0.36                    # facecam over gameplay: the facecam's share of the height

_det_lock = threading.Lock()
_model_tried = [False]


def available() -> bool:
    return cv2 is not None


# ---------------------------------------------------------------- finding faces
def _yunet_file() -> Path:
    """The face-finding model (about 230 KB), fetched once. Without it a simpler built-in finder is used."""
    f = config.MODELS_DIR / "face_detection_yunet_2023mar.onnx"
    if f.is_file() and f.stat().st_size > 100_000:
        return f
    if not _model_tried[0]:
        _model_tried[0] = True
        try:
            import httpx
            r = httpx.get(YUNET_URL, follow_redirects=True, timeout=60)
            if r.status_code == 200 and len(r.content) > 100_000:
                tmp = f.with_suffix(".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(f)
                return f
        except Exception:  # noqa: BLE001
            pass
    return f


class _Finder:
    """One face finder per thread (they are not safe to share)."""
    _local = threading.local()

    @classmethod
    def get(cls):
        d = getattr(cls._local, "d", None)
        if d is None:
            with _det_lock:
                f = _yunet_file()
            if f.is_file() and hasattr(cv2, "FaceDetectorYN"):
                try:
                    d = ("yunet", cv2.FaceDetectorYN.create(str(f), "", (320, 320), 0.62, 0.3, 50))
                except Exception:  # noqa: BLE001
                    d = None
            if d is None:
                d = ("haar", cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"))
            cls._local.d = d
        return d


def find_faces(img) -> list:
    """Faces in a (small) BGR picture: [(x, y, w, h, confidence)] in that picture's pixels."""
    kind, d = _Finder.get()
    h, w = img.shape[:2]
    if kind == "yunet":
        d.setInputSize((w, h))
        _, faces = d.detect(img)
        if faces is None:
            return []
        return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])) for f in faces if f[2] > 8 and f[3] > 8]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found = d.detectMultiScale(gray, 1.15, 5, minSize=(16, 16))
    return [(float(x), float(y), float(fw), float(fh), 0.7) for (x, y, fw, fh) in found]


# ---------------------------------------------------------------- reading the clip
def _frames(src: Path, segments):
    """Every frame inside the kept parts of the clip, in the order they play: yields (which part, time in the
    source, BGR frame). Parts may jump back in time (a cold open teaser plays a later line first)."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError("The video file couldn't be opened for the smart camera.")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if not 5 <= fps <= 240:
            fps = 30.0
        for k, (a, b) in enumerate(segments):
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, a - 0.05) * 1000)
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if t < a - 0.02:
                    continue
                if t >= b:
                    break
                yield k, t, frame
    finally:
        cap.release()


def source_fps(src: Path) -> float:
    cap = cv2.VideoCapture(str(src))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    finally:
        cap.release()
    return fps if 5 <= fps <= 240 else 30.0


# ---------------------------------------------------------------- looking at the clip
def analyse(src: Path, segments, want_motion=False) -> dict:
    """Looks at the clip a few times a second. Returns the face samples, the tracks (one per person), the source
    size, and (if asked) how much the picture moves per sample, for spotting action."""
    samples, prev_gray, nxt = [], None, None
    size = None
    seg_now = None
    for k, t, frame in _frames(src, segments):
        if k != seg_now:                       # a new part: sample it from its own start
            seg_now, nxt, prev_gray = k, None, None
        if nxt is not None and t < nxt:
            continue
        nxt = t + SAMPLE_EVERY
        H, W = frame.shape[:2]
        size = (W, H)
        k = DETECT_W / W if W > DETECT_W else 1.0
        small = cv2.resize(frame, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = []
        for (x, y, w, h, c) in find_faces(small):
            mouth = 0.0
            if prev_gray is not None:
                y0, y1 = int(y + h * 0.55), int(y + h * 1.05)
                x0, x1 = int(x + w * 0.2), int(x + w * 0.8)
                y0, x0 = max(0, y0), max(0, x0)
                y1, x1 = min(gray.shape[0], y1), min(gray.shape[1], x1)
                if y1 - y0 > 3 and x1 - x0 > 3:
                    a = cv2.resize(gray[y0:y1, x0:x1], (24, 12)).astype(np.float32)
                    b = cv2.resize(prev_gray[y0:y1, x0:x1], (24, 12)).astype(np.float32)
                    mouth = float(np.mean(np.abs(a - b))) / (float(np.mean(a)) + 20.0) * 100
            faces.append({"x": x / k, "y": y / k, "w": w / k, "h": h / k, "c": c, "mouth": mouth})
        motion = 0.0
        if want_motion and prev_gray is not None:
            motion = float(np.mean(cv2.absdiff(cv2.resize(gray, (64, 36)), cv2.resize(prev_gray, (64, 36)))))
        samples.append({"t": t, "faces": faces, "motion": motion, "k": k})
        prev_gray = gray
    if size is None:
        raise RuntimeError("No pictures could be read from this part of the video.")
    tracks = _tracks(samples)
    return {"samples": samples, "tracks": tracks, "size": size}


def _tracks(samples) -> list:
    """Joins faces from sample to sample into people. A face belongs to the track whose last face is nearest,
    if it is close enough for the size of the face and was seen less than 1.2 s ago."""
    tracks = []
    for i, s in enumerate(samples):
        used = set()
        for f in sorted(s["faces"], key=lambda f: -f["w"]):
            cx, cy = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
            best, bd = None, None
            for tr in tracks:
                if tr["id"] in used or s["t"] - tr["last_t"] > 1.2:
                    continue
                lf = tr["faces"][-1][1]
                d = math.hypot(cx - (lf["x"] + lf["w"] / 2), cy - (lf["y"] + lf["h"] / 2))
                if d < max(lf["w"], f["w"]) * 0.9 and 0.5 < f["w"] / max(1, lf["w"]) < 2.0 and (bd is None or d < bd):
                    best, bd = tr, d
            if best is None:
                best = {"id": len(tracks), "faces": [], "last_t": s["t"]}
                tracks.append(best)
            best["faces"].append((i, f))
            best["last_t"] = s["t"]
            used.add(best["id"])
    n = max(1, len(samples))
    for tr in tracks:
        xs = np.array([f["x"] + f["w"] / 2 for _, f in tr["faces"]])
        ys = np.array([f["y"] + f["h"] / 2 for _, f in tr["faces"]])
        tr["share"] = len(tr["faces"]) / n
        tr["cx"], tr["cy"] = float(np.median(xs)), float(np.median(ys))
        tr["w"] = float(np.median([f["w"] for _, f in tr["faces"]]))
        tr["h"] = float(np.median([f["h"] for _, f in tr["faces"]]))
        tr["wobble"] = float(np.std(xs) + np.std(ys))
        tr["talk"] = float(np.mean([f["mouth"] for _, f in tr["faces"]]))
    return [t for t in tracks if len(t["faces"]) >= 3]


def find_facecams(a: dict) -> list:
    """Tracks that look like a streamer's webcam overlay: a face that hardly moves, near an edge of a wide
    picture, seen for a good part of the clip. Several are possible (the overlay can change size mid-stream)."""
    W, H = a["size"]
    if W < H * 1.2:
        return []
    out = []
    for tr in a["tracks"]:
        near_edge = tr["cx"] < W * 0.34 or tr["cx"] > W * 0.66 or tr["cy"] > H * 0.62 or tr["cy"] < H * 0.3
        small = tr["w"] < W * 0.2
        still = tr["wobble"] < max(14.0, tr["w"] * 0.9)       # a head moves inside a webcam; the overlay doesn't
        if tr["share"] >= 0.18 and near_edge and small and still:
            out.append(tr)
    return out


# ---------------------------------------------------------------- deciding where the camera points
def _speaker_plan(a: dict, tracks=None, hold=2.5) -> list:
    """For every sample: (centre x, centre y, face width, track id) of the person to show, or None."""
    tracks = tracks if tracks is not None else a["tracks"]
    by_sample = {}
    for tr in tracks:
        for i, f in tr["faces"]:
            by_sample.setdefault(i, []).append((tr, f))
    act = {tr["id"]: 0.0 for tr in tracks}
    cur, cur_since, rival_since, plan, seen = None, -9.0, {}, [], -99.0
    for i, s in enumerate(a["samples"]):
        here = by_sample.get(i, [])
        for tr in tracks:                          # talking, smoothed over about a second
            m = next((f["mouth"] for t2, f in here if t2 is tr), 0.0)
            act[tr["id"]] = act[tr["id"]] * 0.78 + m * 0.22
        if not here:                               # nobody seen: stay where we were for a moment
            plan.append(plan[-1] if plan and plan[-1] and s["t"] - seen < hold else None)
            continue
        seen = s["t"]
        size = {t2["id"]: f["w"] for t2, f in here}
        big = max(size.values())
        def weight(tid):           # someone tiny in the background is rarely the one to show
            return act[tid] * (0.35 + 0.65 * min(1.0, size.get(tid, 0) / big))
        best = max(here, key=lambda p: weight(p[0]["id"]))[0]
        if cur is None or cur not in size:
            cur, cur_since = best["id"], s["t"]
        elif best["id"] != cur and weight(best["id"]) > weight(cur) * 1.45 + 0.4:
            rival_since.setdefault(best["id"], s["t"])
            if s["t"] - rival_since[best["id"]] >= 0.8 and s["t"] - cur_since >= 1.6:
                cur, cur_since = best["id"], s["t"]
                rival_since.clear()
        else:
            rival_since.clear()
        f = next(f for t2, f in here if t2["id"] == cur)
        plan.append((f["x"] + f["w"] / 2, f["y"] + f["h"] * 0.55, f["w"], cur))
    return plan


def _follow(times, plan, frame_times, width, default):
    """The camera's centre for every frame. It cuts straight to a new person, and otherwise glides after the
    face, ignoring small movements so the picture stays calm."""
    xs, ys, ws, ids = [], [], [], []
    last = default
    for p in plan:
        last = p if p else last
        xs.append(last[0])
        ys.append(last[1])
        ws.append(last[2])
        ids.append(last[3])
    out, j = [], 0
    pos = None
    prev_t = None
    for t in frame_times:
        while j + 1 < len(times) and times[j + 1] <= t:
            j += 1
        if not times:
            out.append(default[:3])
            continue
        if j + 1 < len(times) and ids[j] == ids[j + 1] and times[j + 1] > times[j]:
            u = (t - times[j]) / (times[j + 1] - times[j])
            tx, ty, tw = xs[j] + (xs[j + 1] - xs[j]) * u, ys[j] + (ys[j + 1] - ys[j]) * u, ws[j]
        else:
            tx, ty, tw = xs[j], ys[j], ws[j]
        if pos is None or pos[3] != ids[j] or prev_t is None or t - prev_t > 0.5:
            pos = [tx, ty, tw, ids[j]]                         # a new person (or a new part of the clip): cut to them
        else:
            dt = t - prev_t
            k = 1 - math.exp(-dt / 0.45)
            dead = width * 0.06
            for n, tv in ((0, tx), (1, ty)):
                gap = tv - pos[n]
                if abs(gap) > dead:
                    pos[n] += (gap - math.copysign(dead, gap)) * k
            pos[2] += (tw - pos[2]) * k
        prev_t = t
        out.append((pos[0], pos[1], pos[2]))
    return out


# ---------------------------------------------------------------- drawing the frames
def _cover(img, w, h):
    """Scale to fill w x h exactly, cutting what sticks out evenly."""
    ih, iw = img.shape[:2]
    k = max(w / iw, h / ih)
    r = cv2.resize(img, (max(w, int(round(iw * k))), max(h, int(round(ih * k)))), interpolation=cv2.INTER_LINEAR)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def _window(frame, cx, cy, w, h):
    """A w x h piece of the frame centred as near (cx, cy) as the frame allows."""
    H, W = frame.shape[:2]
    w, h = min(W, int(round(w))), min(H, int(round(h)))
    x0 = int(round(min(max(0, cx - w / 2), W - w)))
    y0 = int(round(min(max(0, cy - h / 2), H - h)))
    return frame[y0:y0 + h, x0:x0 + w]


def _blur_bg(frame, w, h):
    small = _cover(frame, max(8, w // 6), max(8, h // 6))
    small = cv2.GaussianBlur(small, (0, 0), 3)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.convertScaleAbs(big, alpha=0.8, beta=-6)


def _zoomed(img, z, fx=0.5, fy=0.42):
    """Push in by z (1.0 = none), around a point given as a share of the width and height."""
    if z <= 1.003:
        return img
    h, w = img.shape[:2]
    cw, ch = w / z, h / z
    x0 = min(max(0, fx * w - cw / 2), w - cw)
    y0 = min(max(0, fy * h - ch / 2), h - ch)
    m = np.float32([[z, 0, -x0 * z], [0, z, -y0 * z]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def zoom_curve(events, dur, fps):
    """How far the camera is pushed in at each output frame. events: [(start, end)] seconds on the output
    timeline. Eases in fast (a punch), holds, and eases out slowly."""
    n = max(1, int(math.ceil(dur * fps)))
    z = np.ones(n, dtype=np.float32)
    for a, b in events:
        for i in range(max(0, int((a - 0.05) * fps)), min(n, int((b + 0.45) * fps) + 1)):
            t = i / fps
            if t < a:
                v = 0.0
            elif t < a + 0.12:
                v = (t - a) / 0.12
                v = 1 - (1 - v) ** 3
            elif t <= b:
                v = 1.0
            else:
                v = max(0.0, 1 - (t - b) / 0.4)
                v = v * v * (3 - 2 * v)
            z[i] = max(z[i], 1.0 + 0.13 * v)
    return z


def layout_geometry(layout: str):
    """Where the hook and the captions sit (in 1080x1920 pixels) for each layout drawn here."""
    if layout == "split":
        top = int(config.OUT_H * SPLIT_TOP)
        return top, top + int((config.OUT_H - top) * 0.62)
    if layout in ("track", "crop"):
        return 300, 1380
    return None


def plan_clip(src: Path, segments, layout: str) -> dict:
    """Looks at the clip and decides what the camera does. Returns the plan and what was found, in words."""
    a = analyse(src, segments)
    W, H = a["size"]
    cams = find_facecams(a) if layout == "split" else []
    note = ""
    used = layout
    if layout == "split" and not cams:
        used, note = "track", "No facecam was found, so the camera follows the speaker instead."
    times = [s["t"] for s in a["samples"]]
    if used == "split":
        others = [t for t in a["tracks"] if t not in cams]
        plan = _speaker_plan(a, cams, hold=1e9)        # a facecam overlay stays put even when the face looks away
        content = _speaker_plan(a, others) if others else [None] * len(times)
    else:
        plan, content = _speaker_plan(a), None
    if used in ("track", "split") and not any(plan):
        note = note or "No faces were found, so the camera stays in the middle."
    return {"layout": used, "size": (W, H), "times": times, "plan": plan, "content": content, "cams": cams,
            "sk": [s_["k"] for s_ in a["samples"]],
            "note": note, "faces": len(a["tracks"])}


def draw(src: Path, segments, cam: dict, out: Path, zoom_events=(), fps=None, cut_zoom=False):
    """Writes the vertical video (no sound, no captions yet) for the kept parts of the clip, following the plan.
    Returns the number of frames written and the frame rate."""
    W, H = cam["size"]
    fps = fps or source_fps(src)
    if fps > 45:
        fps = fps / 2                      # 60 fps sources are drawn at 30: half the work, and Shorts play at 30 anyway
    dur = sum(b - a for a, b in segments)
    zc = zoom_curve(zoom_events, dur + 1.0, fps)
    layout = cam["layout"]
    default = (W / 2, H * 0.42, H * 0.2, -1)
    sk = cam.get("sk") or [0] * len(cam["times"])
    parts = {}                                    # each kept part gets its own camera path (parts may jump in time)
    for k, (a, b) in enumerate(segments):
        ft, t = [], a
        while t < b:
            ft.append(t)
            t += 1 / fps
        idx = [i for i, x in enumerate(sk) if x == k]
        times_k = [cam["times"][i] for i in idx]
        pk = _follow(times_k, [cam["plan"][i] for i in idx], ft, BASE_W, default) \
            if layout in ("track", "split", "zoom") else None
        gk = _follow(times_k, [cam["content"][i] for i in idx], ft, BASE_W, (W / 2, H / 2, H * 0.2, -1)) \
            if layout == "split" and cam.get("content") else None
        parts[k] = (ft, pk, gk)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{BASE_W}x{BASE_H}",
         "-r", f"{fps:.4f}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "15",
         "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    n = 0
    top_h = int(BASE_H * SPLIT_TOP)
    try:
        due, seg_of = None, None
        for seg, t, frame in _frames(src, segments):
            frame_times, path, gpath = parts[seg]
            if seg != seg_of:
                seg_of, due = seg, t
            if t < due - 0.3 / fps:
                continue                   # a frame between two we keep (a faster source than the output)
            due += 1 / fps
            if frame.shape[1] != W or frame.shape[0] != H:
                frame = cv2.resize(frame, (W, H))
            i = max(0, min(len(frame_times) - 1, bisect.bisect_right(frame_times, t + 0.5 / fps) - 1)) if frame_times else 0
            z = float(zc[min(n, len(zc) - 1)])
            if cut_zoom and len(segments) > 1 and seg_of is not None and seg_of % 2:
                z *= 1.08                  # every other part after a cut sits a little closer: jump cuts look deliberate
            if layout == "track" or layout == "crop":
                cx, cy, fw = path[i] if path else (W / 2, H / 2, 0)
                ch = H / z
                cw = ch * BASE_W / BASE_H
                if cw > W:
                    cw, ch = W, W * BASE_H / BASE_W
                cyy = cy + ch * 0.08 if z > 1.003 else H / 2           # pushed in: keep the face a little above centre
                img = cv2.resize(_window(frame, cx, cyy, cw, ch), (BASE_W, BASE_H), interpolation=cv2.INTER_LINEAR)
            elif layout == "split":
                fcx, fcy, fw = path[i]
                ph = fw * 2.6 / z
                pw = ph * BASE_W / top_h
                top = cv2.resize(_window(frame, fcx, fcy + fw * 0.15, pw, ph), (BASE_W, top_h), interpolation=cv2.INTER_LINEAR)
                bh = BASE_H - top_h
                gcx = gpath[i][0] if gpath else W / 2
                gw = H * BASE_W / bh
                if gw > W:
                    gw = W
                if not gpath:
                    gcx = W * 0.42 if fcx > W / 2 else W * 0.58
                # keep the facecam out of the gameplay picture: a webcam overlay is about 6 face-widths wide
                if fcx > W / 2:
                    gcx = min(gcx, max(gw / 2, fcx - 3.1 * fw - gw / 2))
                else:
                    gcx = max(gcx, min(W - gw / 2, fcx + 3.1 * fw + gw / 2))
                bottom = cv2.resize(_window(frame, gcx, H / 2, gw, gw * bh / BASE_W), (BASE_W, bh), interpolation=cv2.INTER_LINEAR)
                img = np.vstack([top, bottom])
                cv2.rectangle(img, (0, top_h - 3), (BASE_W, top_h + 2), (20, 16, 14), -1)
            elif layout == "zoom":
                fg_h = int(BASE_H * 1000 / config.OUT_H) // 2 * 2
                img = _blur_bg(frame, BASE_W, BASE_H)
                cx = path[i][0] if path and path[i][2] > 0 and cam["faces"] else W / 2
                fg = _window(frame, cx, H / 2, H * BASE_W / fg_h, H)
                fg = cv2.resize(fg, (BASE_W, fg_h), interpolation=cv2.INTER_LINEAR)
                y0 = (BASE_H - fg_h) // 2
                img[y0:y0 + fg_h] = _zoomed(fg, z)
            else:                                                       # blur: the whole picture over a blurred copy
                img = _blur_bg(frame, BASE_W, BASE_H)
                fg_h = min(BASE_H, int(round(BASE_W * H / W / 2)) * 2)
                fg = cv2.resize(frame, (BASE_W, fg_h), interpolation=cv2.INTER_AREA if W > BASE_W else cv2.INTER_LINEAR)
                y0 = (BASE_H - fg_h) // 2
                img[y0:y0 + fg_h] = _zoomed(fg, z)
            proc.stdin.write(np.ascontiguousarray(img).tobytes())
            n += 1
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait(timeout=600) != 0:
            raise RuntimeError(f"Drawing the frames failed: {err[-400:]}")
    except BaseException:
        proc.kill()
        raise
    if n == 0:
        raise RuntimeError("No frames could be read from this part of the video.")
    return n, fps


def motion_per_second(src: Path, start: float, end: float) -> list:
    """How much the picture changes each second, from tiny grey frames (fast even for long videos)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(src),
                        "-vf", "fps=2,scale=64:36,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, creationflags=NO_WINDOW, timeout=3600)
    if p.returncode != 0 or not p.stdout:
        return []
    fr = np.frombuffer(p.stdout, dtype=np.uint8)
    fr = fr[: len(fr) // (64 * 36) * 64 * 36].reshape(-1, 36, 64).astype(np.int16)
    if len(fr) < 3:
        return []
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    per_sec = [float(d[i:i + 2].mean()) for i in range(0, len(d), 2)]
    return per_sec


def still_frames(src: Path, start: float, end: float, n=6, width=512) -> list:
    """n JPEG pictures spread over the clip, small enough to show an AI cheaply."""
    out = []
    for k in range(n):
        t = start + (end - start) * (k + 0.5) / n
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, creationflags=NO_WINDOW, timeout=60)
        if p.returncode == 0 and p.stdout:
            out.append(p.stdout)
    return out
