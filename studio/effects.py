"""Extras drawn on a clip: emoji pictures, sound effects, and the picks of which emoji goes with which word.

Sound effects are made here in code (no files to download, no licences to worry about): a whoosh when the clip
opens, a pop when an emoji appears, and a soft thump when the camera punches in.
Emojis are Microsoft's 3D Fluent Emoji (MIT licence), fetched once and kept; without internet the computer's own
colour emoji font is used."""
import re
import threading
import wave
from pathlib import Path

import numpy as np

from . import config

FX_DIR = config.DATA_DIR / "fx"
EMOJI_PX = 230                   # how big an emoji is on the 1080x1920 clip
ANIM_FPS = 30
ANIM_SECONDS = 1.35
_lock = threading.Lock()

EMOJI_FONTS = [r"C:\Windows\Fonts\seguiemj.ttf", "/System/Library/Fonts/Apple Color Emoji.ttc",
               "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/noto/NotoColorEmoji.ttf",
               "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"]

# The emojis a clip may use: Microsoft's 3D Fluent Emoji (MIT licence), fetched once each and kept. Limiting the AI
# to this list keeps every emoji looking the same, polished way.
FLUENT = {
    "🔥": "Fire", "😂": "Face with tears of joy", "🤣": "Rolling on the floor laughing", "💀": "Skull",
    "💰": "Money bag", "💵": "Dollar banknote", "🏆": "Trophy", "👑": "Crown", "😱": "Face screaming in fear",
    "😡": "Pouting face", "😤": "Face with steam from nose", "❤️": "Red heart", "👀": "Eyes", "🚨": "Police car light",
    "😭": "Loudly crying face", "🥺": "Pleading face", "🤔": "Thinking face", "🧐": "Face with monocle",
    "💯": "Hundred points", "⚡": "High voltage", "🎯": "Bullseye", "🥶": "Cold face", "🥵": "Hot face",
    "🤯": "Exploding head", "🚀": "Rocket", "🎉": "Party popper", "🤩": "Star-struck", "😎": "Smiling face with sunglasses",
    "🧠": "Brain", "💣": "Bomb", "💥": "Collision", "😲": "Astonished face", "😧": "Anguished face", "😳": "Flushed face",
    "🙄": "Face with rolling eyes", "🫠": "Melting face", "🤡": "Clown face", "👻": "Ghost", "💎": "Gem stone",
    "✅": "Check mark button", "❌": "Cross mark", "⚠️": "Warning", "💡": "Light bulb", "📈": "Chart increasing",
    "🎮": "Video game", "✨": "Sparkles", "🤭": "Face with hand over mouth", "🤢": "Nauseated face",
    "😈": "Smiling face with horns", "🐐": "Goat", "⏱️": "Stopwatch", "📢": "Megaphone", "🤪": "Zany face",
    "💦": "Sweat droplets", "🤫": "Shushing face", "🫡": "Saluting face", "🍕": "Pizza", "🦁": "Lion",
    "😬": "Grimacing face", "👏": "Clapping hands", "💪": "Flexed biceps", "👍": "Thumbs up", "👎": "Thumbs down",
    "🙏": "Folded hands", "🤌": "Pinched fingers", "🙌": "Raising hands",
}
FLUENT_CDN = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets/"

# When the AI gives no emoji, a strong word can still bring one. Only words that really carry a feeling: a wrong
# emoji on an everyday word looks worse than none.
KEYWORDS = {
    "😂": "hilarious lmao lol laughing", "💀": "dead died bruh rip", "🔥": "fire insane lit incredible",
    "🤯": "unbelievable impossible mindblowing", "💰": "money cash dollars million millions rich", "🏆": "won winner champion victory",
    "😱": "scared terrifying horror screaming", "😡": "furious rage pissed", "❤️": "love", "🚨": "emergency danger alert",
    "😭": "crying tears", "💯": "facts exactly", "⚡": "instantly lightning", "🎯": "headshot bullseye", "🥶": "freezing",
    "🍕": "pizza", "🎮": "gaming controller", "🐐": "goat", "🤡": "clown", "👻": "ghost", "🚀": "rocket", "🧠": "brain genius",
    "💣": "bomb", "💥": "explosion boom", "👑": "king queen", "🤢": "disgusting gross", "😈": "evil devil",
}
_WORD_EMOJI = {w: e for e, ws in KEYWORDS.items() for w in ws.split()}


def _key(w):
    return re.sub(r"[^a-z0-9']", "", str(w).lower())


def is_emoji(s: str) -> bool:
    s = str(s or "").strip()
    return 0 < len(s) <= 8 and any(ord(ch) >= 0x2190 for ch in s) and not re.search(r"[A-Za-z0-9<>]", s)


def pick(words_out: list, highlight: list, ai_emojis: list, limit=5, gap=2.2) -> list:
    """Which emojis to show and when: [(emoji, time on the clip)]. The AI's choices first, then said keywords."""
    want = []
    for item in ai_emojis or []:
        e = str((item or {}).get("emoji", "")).strip() if isinstance(item, dict) else ""
        e = e if e in FLUENT else e.replace("\ufe0f", "") if e.replace("\ufe0f", "") in FLUENT else e + "\ufe0f"
        if e in FLUENT and _key(item.get("word")):
            want.append((_key(item["word"]), e))
    for h in highlight or []:
        k = _key(h)
        if k in _WORD_EMOJI and k not in {w for w, _ in want}:
            want.append((k, _WORD_EMOJI[k]))
    for w in words_out:
        k = _key(w["w"])
        if k in _WORD_EMOJI and k not in {x for x, _ in want}:
            want.append((k, _WORD_EMOJI[k]))
    out = []
    for k, e in want:
        hit = next((w for w in words_out if _key(w["w"]) == k and w["s"] > 0.6
                    and all(abs(w["s"] - t) >= gap for _, t in out)), None)
        if hit is not None:
            out.append((e, hit["s"]))
        if len(out) >= limit:
            break
    return sorted(out, key=lambda x: x[1])


def _fluent(e: str):
    """The 3D picture of this emoji, fetched once and kept. None when it is not in the set or cannot be fetched."""
    import urllib.parse
    name = FLUENT.get(e) or FLUENT.get(e.replace("\ufe0f", ""))
    if not name:
        return None
    d = FX_DIR / "emoji3d"
    d.mkdir(parents=True, exist_ok=True)
    f = d / ("-".join(f"{ord(c):x}" for c in e) + ".png")
    if f.is_file() and f.stat().st_size > 2000:
        return f
    import httpx
    stem = name.lower().replace(" ", "_")
    base = FLUENT_CDN + urllib.parse.quote(name)
    for path in (f"/3D/{stem}_3d.png", f"/Default/3D/{stem}_3d_default.png"):
        try:
            r = httpx.get(base + path, timeout=20, follow_redirects=True)
        except Exception:  # noqa: BLE001
            return None
        if r.status_code == 200 and len(r.content) > 2000:
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(f)
            return f
    return None


def _system_emoji(e: str):
    from PIL import Image, ImageDraw, ImageFont
    for path in EMOJI_FONTS:
        if not Path(path).is_file():
            continue
        try:
            size = 109 if "Noto" in path else 136                  # Noto's colour emoji only comes in one size
            font = ImageFont.truetype(path, size)
            im = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((110, 110), e, font=font, embedded_color=True, anchor="mm")
            box = im.getbbox()
            if box:
                return im.crop(box)
        except Exception:  # noqa: BLE001
            continue
    return None


def emoji_png(e: str) -> Path | None:
    """The emoji as a transparent picture: the 3D one, or the system's own emoji if that cannot be had."""
    f = _fluent(e)
    if f:
        return f
    FX_DIR.mkdir(parents=True, exist_ok=True)
    f = FX_DIR / ("e_" + "-".join(f"{ord(c):x}" for c in e) + ".png")
    if f.is_file():
        return f
    im = _system_emoji(e)
    if im is None:
        return None
    from PIL import Image
    k = 256 / max(im.size)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    with _lock:
        im.save(f)
    return f


def _ease_back(u):
    """0 to 1 with a little overshoot, like something springing into place."""
    c1, c3 = 1.9, 2.9
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


def emoji_frames(e: str) -> Path | None:
    """A folder of pictures (000.png, 001.png...) that play the emoji's pop: it springs in with a small turn,
    floats gently, then shrinks away. Made once per emoji and reused by every clip."""
    src = emoji_png(e)
    if not src:
        return None
    import math
    from PIL import Image, ImageFilter
    d = FX_DIR / "anim" / (src.stem + "-v2")
    n = int(ANIM_SECONDS * ANIM_FPS)
    if d.is_dir() and len(list(d.glob("*.png"))) == n:
        return d
    tmp = d.with_name(d.name + ".tmp")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    base = Image.open(src).convert("RGBA")
    k = EMOJI_PX / max(base.size)
    base = base.resize((int(base.width * k), int(base.height * k)), Image.LANCZOS)
    canvas = int(EMOJI_PX * 1.6)
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.putalpha(base.getchannel("A").point(lambda v: int(v * 0.45)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    for i in range(n):
        t = i / ANIM_FPS
        if t < 0.28:                                     # springs in
            u = t / 0.28
            sc, rot, alpha = max(0.05, _ease_back(u)), -16 * (1 - u), min(1.0, u * 2.5)
        elif t > ANIM_SECONDS - 0.22:                    # shrinks away
            u = (t - (ANIM_SECONDS - 0.22)) / 0.22
            sc, rot, alpha = 1 - 0.55 * u * u, 4 * u, 1 - u
        else:                                            # floats
            sc, rot, alpha = 1 + 0.025 * math.sin(t * 7), 3.5 * math.sin(t * 4.2), 1.0
        bob = -6 * math.sin(t * 5.0) if 0.28 <= t <= ANIM_SECONDS - 0.22 else 0
        frame = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        size = (max(1, int(base.width * sc)), max(1, int(base.height * sc)))
        for img, dx, dy in ((shadow, 6, 14), (base, 0, 0)):
            im = img.resize(size, Image.LANCZOS).rotate(rot, resample=Image.BICUBIC, expand=True)
            if alpha < 1:
                im.putalpha(im.getchannel("A").point(lambda v, a=alpha: int(v * a)))
            frame.alpha_composite(im, ((canvas - im.width) // 2 + dx, (canvas - im.height) // 2 + dy + int(bob)))
        frame.save(tmp / f"{i:03d}.png", optimize=False, compress_level=1)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d


# ---------------------------------------------------------------- sound effects, made in code
RATE = 48000


def _write(path: Path, x: np.ndarray):
    x = np.clip(x / (np.max(np.abs(x)) + 1e-9) * 0.9, -1, 1)
    data = (x * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())


def _whoosh():
    n = int(RATE * 0.55)
    t = np.arange(n) / RATE
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    out, lp = np.zeros(n), 0.0
    for i in range(n):                                             # a filter that opens and closes: air rushing past
        a = 0.02 + 0.5 * np.sin(np.pi * t[i] / t[-1]) ** 2
        lp += a * (noise[i] - lp)
        out[i] = lp
    env = np.sin(np.pi * np.clip(t / t[-1], 0, 1)) ** 1.6
    return out * env


def _pop():
    n = int(RATE * 0.12)
    t = np.arange(n) / RATE
    f = 900 * np.exp(-t * 28) + 260
    ph = 2 * np.pi * np.cumsum(f) / RATE
    return np.sin(ph) * np.exp(-t * 38)


def _thump():
    n = int(RATE * 0.3)
    t = np.arange(n) / RATE
    f = 120 * np.exp(-t * 9) + 45
    ph = 2 * np.pi * np.cumsum(f) / RATE
    click = np.random.default_rng(3).standard_normal(n) * np.exp(-t * 400) * 0.3
    return np.sin(ph) * np.exp(-t * 11) + click


SOUNDS = {"whoosh": _whoosh, "pop": _pop, "thump": _thump}


def sound(name: str) -> Path:
    FX_DIR.mkdir(parents=True, exist_ok=True)
    f = FX_DIR / f"{name}.wav"
    if not f.is_file():
        with _lock:
            if not f.is_file():
                tmp = f.with_suffix(".tmp.wav")
                _write(tmp, SOUNDS[name]())
                tmp.replace(f)
    return f


# ---------------------------------------------------------------- music the user added
MUSIC_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac")


def music_dir(uid: str) -> Path:
    d = config.user_dir(uid) / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d


def music_list(uid: str) -> list:
    return sorted(f.name for f in music_dir(uid).iterdir() if f.suffix.lower() in MUSIC_EXT)


def music_file(uid: str, choice: str, seed: str = "") -> Path | None:
    """The track to play under a clip: a named one, or for "auto" one picked from the list (the same one each time
    the same clip is re-made)."""
    names = music_list(uid)
    if not names or not choice:
        return None
    if choice == "auto":
        import hashlib
        return music_dir(uid) / names[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(names)]
    return music_dir(uid) / choice if choice in names else None


# ---------------------------------------------------------------- B-roll: short stock clips over the talking
PEXELS = "https://api.pexels.com/videos/search"


def broll_clip(query: str, key: str, seed: str = "") -> Path | None:
    """A short vertical stock video for `query` from Pexels (free; needs your own key), fetched once and kept.
    None when there is no key, nothing fits, or Pexels can't be reached."""
    import hashlib
    import httpx
    query = re.sub(r"[^\w\s\-]", " ", str(query or "")).strip()[:60]
    if not key or not query:
        return None
    d = FX_DIR / "broll"
    d.mkdir(parents=True, exist_ok=True)
    f = d / (hashlib.md5((query.lower() + "|" + seed).encode()).hexdigest()[:16] + ".mp4")
    if f.is_file() and f.stat().st_size > 50_000:
        return f
    try:
        r = httpx.get(PEXELS, params={"query": query, "orientation": "portrait", "per_page": 8, "size": "medium"},
                      headers={"Authorization": key}, timeout=20)
        if r.status_code != 200:
            return None
        vids = [v for v in r.json().get("videos", []) if 3 <= v.get("duration", 0) <= 60]
        if not vids:
            return None
        v = vids[int(hashlib.md5(seed.encode()).hexdigest(), 16) % min(3, len(vids))]    # varied, but stable per clip
        files = [x for x in v.get("video_files", []) if x.get("link") and (x.get("height") or 0) >= 960]
        files.sort(key=lambda x: abs((x.get("height") or 0) - 1920))
        if not files:
            return None
        with httpx.stream("GET", files[0]["link"], timeout=60, follow_redirects=True) as resp:
            if resp.status_code != 200:
                return None
            tmp = f.with_suffix(".part")
            with open(tmp, "wb") as out:
                for chunk in resp.iter_bytes():
                    out.write(chunk)
                    if out.tell() > 80_000_000:
                        break
        tmp.replace(f)
        return f
    except Exception:  # noqa: BLE001 - B-roll is a bonus: the clip is made without it
        return None
