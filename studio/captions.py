"""Caption looks and the hook heading, written as an ASS subtitle file that ffmpeg burns into the clip.

Every word is measured and placed by hand, so the word being said can grow, glow, sit in a box or fill with colour
without pushing its neighbours. Colours in STYLES are ordinary RGB ("FF0000" is red); ASS wants them as blue,
green, red, which `bgr` does at the last moment.

Animation modes:
  pop        the word being said changes colour and pops bigger
  reveal     words appear only when they are said (typewriter feel)
  dim        everything is grey except the word being said
  box        a coloured box slides behind the word being said
  underline  a bar under the word being said
  glow       the word being said glows
  karaoke    the line fills with colour as it is spoken
  single     one big word at a time
  line       a whole line on a soft box, key words coloured (podcast style)
"""
import re
from pathlib import Path

from . import config, roman

W, H = config.OUT_W, config.OUT_H
CAP_MAX_W = 960                 # captions never run wider than this, whatever is said
CAPTION_LEAD = 0.0              # measured: word stamps are within 0.15 s of the voice, so no shift is needed

FONT_FILES = {
    "Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Poppins Black": "Poppins-Black.ttf", "Anton": "Anton-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf", "Montserrat Black": "Montserrat-Black.ttf",
    "Montserrat ExtraBold": "Montserrat-ExtraBold.ttf", "Bebas Neue": "BebasNeue-Regular.ttf",
    "Bangers": "Bangers-Regular.ttf", "Luckiest Guy": "LuckiestGuy-Regular.ttf", "Lilita One": "LilitaOne-Regular.ttf",
    "Oswald Bold": "Oswald-Bold.ttf", "Inter Black": "Inter-Black.ttf", "Inter Bold": "Inter-Bold.ttf",
    "Permanent Marker": "PermanentMarker-Regular.ttf", "Rubik Black": "Rubik-Black.ttf", "Titan One": "TitanOne-Regular.ttf",
    "Space Mono Bold": "SpaceMono-Bold.ttf", "Playfair Display Black Italic": "PlayfairDisplay-BlackItalic.ttf",
    "Kanit ExtraBold Italic": "Kanit-ExtraBoldItalic.ttf", "Nunito Black": "Nunito-Black.ttf",
}
FONT_PATHS: dict = {}           # fonts uploaded to a brand kit: name -> file

BASE = {"mode": "pop", "size": 128, "base": "FFFFFF", "active": "FFE14D", "strong": None, "outline": 7,
        "outline_color": "000000", "shadow": 0, "shadow_color": "000000", "upper": True, "per": 3, "pop": 112,
        "box": "C8F542", "box_text": "0B0C0E", "dim": "9A9A9A", "glow": None, "glow_all": False, "tilt": 0,
        "line_alpha": "50"}

STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "active": "FFF000", "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "active": "FF3C3C", "strong": "FFD700", "per": 2, "pop": 114},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "active": "6BD7FF", "outline": 5, "pop": 106,
              "upper": False, "per": 4},
    "boxed": {"label": "Boxed", "font": "Montserrat Black", "size": 112, "mode": "box", "box": "C8F542",
              "box_text": "0B0C0E", "outline": 6, "per": 3},
    "highlighter": {"label": "Highlighter", "font": "Montserrat ExtraBold", "size": 110, "mode": "box", "box": "8B5CF6",
                    "box_text": "FFFFFF", "outline": 6, "per": 3},
    "spotlight": {"label": "Spotlight", "font": "Inter Black", "size": 112, "mode": "dim", "dim": "8C8C8C",
                  "active": "FFFFFF", "outline": 6, "per": 4},
    "karaoke": {"label": "Karaoke", "font": "Montserrat ExtraBold", "size": 116, "mode": "karaoke", "active": "FFD400",
                "outline": 7, "per": 4},
    "oneword": {"label": "One word", "font": "Anton", "size": 196, "mode": "single", "strong": "C8F542", "outline": 8,
                "per": 1, "shadow": 4},
    "comic": {"label": "Comic", "font": "Bangers", "size": 150, "base": "FFE14D", "active": "FFFFFF", "outline": 9,
              "shadow": 7, "tilt": -3, "per": 3},
    "bubble": {"label": "Bubble", "font": "Luckiest Guy", "size": 126, "active": "FF5FA2", "outline": 9, "shadow": 6,
               "per": 3},
    "gamer": {"label": "Gamer", "font": "Lilita One", "size": 136, "mode": "glow", "active": "39FF14", "glow": "1F9E0B",
              "outline": 7, "per": 3},
    "neon": {"label": "Neon", "font": "Oswald Bold", "size": 132, "mode": "glow", "active": "FF4FD8", "glow": "22D3EE",
             "glow_all": True, "outline": 4, "outline_color": "0A1A2A", "per": 3},
    "marker": {"label": "Marker", "font": "Permanent Marker", "size": 118, "mode": "box", "box": "FFE14D",
               "box_text": "111111", "upper": False, "outline": 6, "tilt": -2, "per": 3},
    "minimal": {"label": "Minimal", "font": "Inter Bold", "size": 88, "mode": "line", "upper": False, "per": 5,
                "active": "FFE14D", "outline": 0, "line_alpha": "60"},
    "podcast": {"label": "Podcast", "font": "Rubik Black", "size": 110, "mode": "underline", "box": "FF4D4D",
                "active": "FFFFFF", "outline": 6, "per": 3},
    "headline": {"label": "Headline", "font": "Bebas Neue", "size": 210, "active": "FF3B30", "outline": 6, "per": 2,
                 "pop": 108},
    "typewriter": {"label": "Typewriter", "font": "Space Mono Bold", "size": 96, "mode": "reveal", "active": "C8F542",
                   "outline": 6, "per": 4, "upper": False},
    "glow": {"label": "Glow", "font": "Poppins Black", "size": 124, "mode": "glow", "active": "FFE14D", "glow": "FF9F0A",
             "outline": 6, "per": 3},
    "story": {"label": "Story", "font": "Nunito Black", "size": 116, "active": "60A5FA", "outline": 5, "shadow": 5,
              "upper": False, "per": 3},
    "sport": {"label": "Sport", "font": "Kanit ExtraBold Italic", "size": 138, "active": "FF6A00", "outline": 7, "per": 2},
    "luxury": {"label": "Luxury", "font": "Playfair Display Black Italic", "size": 120, "active": "E7C878",
               "outline": 3, "shadow": 6, "shadow_color": "000000", "upper": False, "per": 3, "pop": 106, "mode": "reveal"},
    "chunky": {"label": "Chunky", "font": "Titan One", "size": 126, "active": "FF8A00", "outline": 8, "shadow": 5,
               "per": 3},
    "mrbold": {"label": "Bold red", "font": "Archivo Black", "size": 124, "mode": "box", "box": "E11D2E",
               "box_text": "FFFFFF", "outline": 7, "per": 3},
}

HOOK_STYLES = {
    "classic": {"label": "Classic", "font": "Poppins ExtraBold", "size": 96, "ink": "0E1014", "box": "FFFFFF", "upper": True},
    "statement": {"label": "Statement", "font": "Inter Black", "size": 92, "ink": "0B0C0E", "box": "C8F542", "upper": True},
    "outline": {"label": "Outline", "font": "Montserrat Black", "size": 104, "ink": "FFFFFF", "box": None, "outline": 8,
                "shadow": 4, "upper": True},
    "banner": {"label": "Banner", "font": "Anton", "size": 104, "ink": "FFFFFF", "box": "111111", "full": True, "upper": True},
    "editorial": {"label": "Editorial", "font": "Playfair Display Black Italic", "size": 104, "ink": "FFFFFF", "box": None,
                  "outline": 0, "shadow": 6, "upper": False},
}
HOOK_LAYOUT = {"pad_x": 36, "pad_y": 22, "radius": 26, "max_w": 900}


def bgr(rgb: str) -> str:
    """An RGB colour as ASS writes it (blue, green, red)."""
    rgb = (rgb or "FFFFFF").upper()
    return rgb[4:6] + rgb[2:4] + rgb[0:2]


class _Font:
    """Measures text exactly as the renderer will draw it."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(FONT_PATHS[name]) if name in FONT_PATHS else \
            Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        version = struct.unpack(">H", d[o: o + 2])[0]
        cap = struct.unpack(">h", d[o + 88: o + 90])[0] if version >= 2 else 0
        self.cap = cap or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this ASS size."""
        try:
            from PIL import ImageFont
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_h(self, size):
        return self.cap * size / (self.asc + self.desc)

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    import shutil
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists() or (config.FONTS_DIR / f.name).stat().st_size != f.stat().st_size:
            shutil.copyfile(f, config.FONTS_DIR / f.name)


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > (16 if per > 1 else 99)
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _rrect(x0, y0, x1, y1, r):
    """A rounded rectangle as an ASS drawing."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    n = lambda v: f"{v:.0f}"                                                         # noqa: E731
    return (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
            f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
            f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
            f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")


def hook_look(name: str, kit: dict = None) -> dict:
    """The hook heading's look: one of HOOK_STYLES, with the brand kit's colours on the boxed ones."""
    hk = {**HOOK_STYLES.get(name or "classic", HOOK_STYLES["classic"]), **HOOK_LAYOUT}
    if kit and (name or "classic") == "classic":
        hk.update(box=kit.get("hook_box") or hk["box"], ink=kit.get("hook_ink") or hk["ink"])
        if kit.get("hook_font") and (kit["hook_font"] in FONT_FILES or kit["hook_font"] in FONT_PATHS):
            hk["font"] = kit["hook_font"]
    return hk


def _hook_events(hook, dur, y, hk):
    """The heading at the top: in a box, on a full-width banner, or as outlined text."""
    f, size = _Font.get(hk["font"]), hk["size"]
    hook = hook if hk.get("upper", True) else hook.title()
    words = hook.split()
    if not words:
        return []
    max_w = W - 120 if hk.get("full") else hk["max_w"]
    lines = [" ".join(words)]
    if f.width(lines[0], size) > max_w and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > max_w:
        size = max(40, int(size * max_w / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    span = f"{_ts(0)},{_ts(dur)}"
    ev = []
    if hk.get("box"):
        bw, bh = widest + 2 * hk["pad_x"], line_h * len(lines) + 2 * hk["pad_y"]
        if hk.get("full"):
            x0, x1, r = 0, W, 0
        else:
            x0, x1, r = (W - bw) / 2, (W + bw) / 2, min(hk["radius"], bh / 2)
        y0, y1 = y - bh / 2, y + bh / 2
        ev.append(f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{bgr(hk['box'])}&\\bord0\\shad0\\p1}}"
                  f"{_rrect(x0, y0, x1, y1, r)}{{\\p0}}")
    for i, line in enumerate(lines):
        cy = y - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fad(160,0)\\fs{size}}}{line}")
    return ev


def style(name: str, kit: dict = None) -> dict:
    """A caption style with every field filled in: a built-in one, or one saved in the brand kit."""
    if name in STYLES:
        return {**BASE, **STYLES[name]}
    s = (kit or {}).get("style_map", {}).get(name)
    if not s:
        return {**BASE, **STYLES["bounce"]}
    return {**BASE, "label": s["name"], "font": s["font"], "size": s["size"], "base": s["base"], "active": s["active"],
            "strong": s.get("strong") or None, "outline": s["outline"], "pop": s.get("pop", 112), "upper": s["upper"],
            "per": s["per"], "mode": s.get("mode", "pop"), "box": s.get("box", s["active"]),
            "box_text": s.get("box_text", "0B0C0E")}


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, st=None, hook_look=None) -> str:
    st = {**BASE, **(st or STYLES.get(style_name, STYLES["bounce"]))}
    hk = {**HOOK_STYLES["classic"], **HOOK_LAYOUT, **(hook_look or {})}
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    mode = st["mode"]
    c = {k: bgr(st[k]) for k in ("base", "active", "outline_color", "shadow_color", "box", "box_text", "dim")}
    c["strong"] = bgr(st["strong"]) if st.get("strong") else c["base"]
    c["glow"] = bgr(st["glow"]) if st.get("glow") else c["active"]
    hk_out = hk.get("outline", 0)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00{c['base']},&H00{c['base']},&H00{c['outline_color']},&H40{c['shadow_color']},0,0,0,0,100,100,0,0,1,{st['outline']},{st['shadow']},5,0,0,0,1
Style: CapLine,{st['font']},{st['size']},&H00{c['base']},&H00{c['base']},&H{st['line_alpha']}000000,&H{st['line_alpha']}000000,0,0,0,0,100,100,0,0,3,18,0,5,0,0,0,1
Style: Hook,{hk['font']},{hk['size']},&H00{bgr(hk['ink'])},&H00{bgr(hk['ink'])},&H00000000,&H60000000,0,0,0,0,100,100,0,0,1,{hk_out},{hk.get('shadow', 0)},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    ev = _hook_events(_clean(hook), dur, hook_y, hk)
    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, 1 if mode == "single" else st["per"])
    tilt = f"\\frz{st['tilt']}" if st.get("tilt") else ""
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            texts.append(t.upper() if st["upper"] else t)
        if not all(roman.drawable(t) for t in texts):
            # A script the caption font cannot draw (Japanese, Thai, Chinese...): its words cannot be measured, so
            # they are not placed one by one. The line is drawn whole and centred, in a font the system has for it.
            line = " ".join(texts)
            fs = max(44, min(int(st["size"] * 0.7), int(1500 / max(1, len(line)) * 1.6)))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({W // 2},{cap_y:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = st["size"]
        pad_word = 2 * st["outline"] + 6 + (st["size"] * 0.1 if mode == "box" else 0)

        def measure(sz):
            gap_ = f.width("n n", sz) - 2 * f.width("n", sz) + pad_word * sz / st["size"]   # a space, plus room for outlines
            return gap_, sum(f.width(t, sz) for t in texts) + gap_ * (len(texts) - 1)
        gap, total = measure(size)
        limit = CAP_MAX_W - (60 if mode == "line" else 0)
        if total > limit:                                  # a long phrase: shrink it to fit, never run off the frame
            size = max(36, int(size * limit / total))
            gap, total = measure(size)
        cy = cap_y - f.cap_shift(size)
        a0, b0 = _ts(g_start), _ts(g_end)

        def colour_of(w):
            return c["strong"] if _key(w["w"]) in strong else c["base"]

        if mode in ("karaoke", "line"):
            parts, prev = [], g_start
            for i, (w, t) in enumerate(zip(g, texts)):
                a = max(g_start, w["s"] - start)
                b = (g[i + 1]["s"] - start) if i + 1 < len(g) else min(g_end, w["e"] - start + 0.1)
                if mode == "karaoke":
                    lead = int(round((a - prev) * 100))
                    k = max(1, int(round((max(b, a + 0.05) - a) * 100)))
                    parts.append((f"{{\\k{lead}}}" if lead > 0 else "") + f"{{\\kf{k}}}{t}" + (" " if i + 1 < len(g) else ""))
                    prev = a + k / 100
                else:
                    col = c["active"] if _key(w["w"]) in strong else c["base"]
                    parts.append(f"{{\\c&H{col}&}}{t}" + (" " if i + 1 < len(g) else ""))
            if mode == "karaoke":
                ev.append(f"Dialogue: 2,{a0},{b0},Cap,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fs{size}{tilt}"
                          f"\\1c&H{c['active']}&\\2c&H{c['base']}&}}{''.join(parts)}")
            else:
                ev.append(f"Dialogue: 2,{a0},{b0},CapLine,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fs{size}\\fad(80,60)}}"
                          f"{''.join(parts)}")
            continue
        if mode == "single":
            w, t = g[0], texts[0]
            col = (c["strong"] if st.get("strong") else c["active"]) if _key(w["w"]) in strong else c["base"]
            ev.append(f"Dialogue: 2,{a0},{b0},Cap,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fs{size}{tilt}\\c&H{col}&"
                      f"\\fscx72\\fscy72\\t(0,90,\\fscx110\\fscy110)\\t(90,170,\\fscx100\\fscy100)}}{t}")
            continue
        x = (W - total) / 2
        cap_half = f.cap_h(size) / 2
        positions = []
        for w, t in zip(g, texts):
            wd = f.width(t, size)
            positions.append((x + wd / 2, wd))
            x += wd + gap
        if st.get("glow_all"):                              # a soft coloured glow behind the whole line
            for (px, wd), t in zip(positions, texts):
                ev.append(f"Dialogue: 0,{a0},{b0},Cap,,0,0,0,,{{\\an5\\pos({px:.0f},{cy:.0f})\\fs{size}{tilt}\\1a&HFF&"
                          f"\\3c&H{c['glow']}&\\bord{st['outline'] + 9}\\blur9\\shad0}}{t}")
        for i, ((px, wd), w, t) in enumerate(zip(positions, g, texts)):
            p = max(104, min(st["pop"], 100 + int(2200 / max(wd, 1))))   # long words grow less, so they never touch
            pos = f"\\an5\\pos({px:.0f},{cy:.0f})\\fs{size}{tilt}"
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            base = c["dim"] if mode == "dim" else colour_of(w)
            if a - g_start >= 0.02 and mode != "reveal":                                # waiting to be said
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base}&}}{t}")
            if b - a >= 0.02:                                                           # being said
                if mode == "box":
                    pad_x, pad_y = size * 0.11, size * 0.13
                    box = _rrect(px - wd / 2 - pad_x, cap_y - cap_half - pad_y, px + wd / 2 + pad_x,
                                 cap_y + cap_half + pad_y * 1.15, size * 0.14)
                    org = f"\\org({px:.0f},{cap_y:.0f})" if tilt else ""      # a tilted box turns around its word
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{\\an7\\pos(0,0){org}\\bord0\\shad0{tilt}"
                              f"\\c&H{c['box']}&\\fad(40,0)\\p1}}{box}{{\\p0}}")
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['box_text']}&\\bord0\\shad0}}{t}")
                elif mode == "underline":
                    bar = _rrect(px - wd / 2, cap_y + cap_half + size * 0.12, px + wd / 2,
                                 cap_y + cap_half + size * 0.12 + max(8, size * 0.09), 5)
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{\\an7\\pos(0,0)\\bord0\\shad0"
                              f"\\c&H{c['box']}&\\p1}}{bar}{{\\p0}}")
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['active']}&}}{t}")
                elif mode == "glow":
                    ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\1a&HFF&\\3c&H{c['glow']}&"
                              f"\\bord{st['outline'] + 12}\\blur12\\shad0\\fscx{p}\\fscy{p}}}{t}")
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['active']}&\\fscx94\\fscy94"
                              f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
                elif mode == "dim":
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['active']}&\\fscx97\\fscy97"
                              f"\\t(0,80,\\fscx104\\fscy104)}}{t}")
                elif mode == "reveal":
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['active']}&\\fad(70,0)"
                              f"\\fscx88\\fscy88\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,180,\\fscx100\\fscy100)}}{t}")
                else:                                                                   # pop
                    ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{c['active']}&\\fscx94\\fscy94"
                              f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
            if g_end - b >= 0.02:                                                       # said
                done = c["dim"] if mode == "dim" else colour_of(w)
                shrink = "" if mode in ("box", "underline", "dim", "reveal") else f"\\fscx{p - 5}\\fscy{p - 5}\\t(0,90,\\fscx100\\fscy100)"
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{done}&{shrink}}}{t}")
    return head + "\n".join(ev) + "\n"


# ---------------------------------------------------------------- previews for the style picker
def preview(kind: str, sid: str, kit: dict = None) -> Path:
    """A small picture of a caption style (kind "caption") or a hook look (kind "hook"), drawn by the same code that
    makes the clips, so the picker shows exactly what you will get. Made once and kept."""
    import hashlib
    import json
    import shutil
    import subprocess
    import tempfile
    from .media import NO_WINDOW
    look = style(sid, kit) if kind == "caption" else hook_look(sid, kit)
    key = hashlib.md5(json.dumps([kind, sid, look, 5], sort_keys=True).encode()).hexdigest()[:12]
    out_dir = config.DATA_DIR / "fx" / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{kind}-{key}.png"
    if out.is_file():
        return out
    if kind == "caption":
        say = ["Clip", "this", "moment"] if look["per"] > 2 else ["This", "moment"] if look["per"] == 2 else ["Wow"]
        ws = [{"w": w, "s": 0.4 * i, "e": 0.4 * i + 0.38} for i, w in enumerate(say)]
        ass = build_ass(ws, 0, 3, "", sid, ["moment", "wow"], -999, 960, st=look)
        last = 0.4 * (len(say) - 1)
        t, band = (last + 0.1 if look["mode"] == "karaoke" else last + 0.15), 960
    else:
        ass = build_ass([], 0, 3, "This changed everything", "bounce", [], 960, 2400, hook_look=look)
        t, band = 0.5, 960
    work = Path(tempfile.mkdtemp(prefix="sxp"))
    try:
        (work / "p.ass").write_text(ass, encoding="utf-8")
        (work / "f").mkdir()
        for f in (Path(__file__).resolve().parent / "fonts").glob("*.ttf"):
            shutil.copyfile(f, work / "f" / f.name)
        for f in FONT_PATHS.values():
            if Path(f).is_file():
                shutil.copyfile(f, work / "f" / Path(f).name)
        vf = f"ass=p.ass:fontsdir=f,crop=1000:300:40:{band - 150},scale=600:-2"
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"gradients=s={W}x{H}:c0=0x34343a:c1=0x141416:x0=0:y0=0:x1={W}:y1={H}:d=3",
                            "-ss", f"{t:.2f}", "-frames:v", "1", "-vf", vf, "p.png"],
                           cwd=work, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(p.stderr[-300:])
        shutil.move(str(work / "p.png"), str(out))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out
