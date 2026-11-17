"""Brand kit: your logo on every clip, your own fonts and colours, and caption styles you save and reuse.

Everything is kept in the user's own folder: brand.json, plus the logo and fonts that were uploaded."""
import json
import re
import threading
import uuid
from pathlib import Path

from . import config, ctx

_lock = threading.Lock()
POSITIONS = ("tl", "tr", "bl", "br")
from .captions import FONT_FILES as _FONTS

BUILTIN_FONTS = tuple(_FONTS)
HEX = re.compile(r"^[0-9A-Fa-f]{6}$")

DEFAULTS = {
    "logo": "",                 # file name inside the brand folder, or ""
    "logo_pos": "tr",
    "logo_size": 16,            # % of the video's width
    "logo_opacity": 85,         # %
    "bar_color": "C8F542",      # progress bar, RGB
    "hook_box": "FFFFFF",       # the big heading's box, RGB
    "hook_ink": "0E1014",       # the big heading's text, RGB
    "hook_font": "Poppins ExtraBold",
    "styles": [],               # saved caption styles
    "fonts": [],                # [{"file", "name"}] uploaded fonts
}
STYLE_DEFAULTS = {"name": "My style", "font": "Poppins ExtraBold", "base": "FFFFFF", "active": "FFD400",
                  "strong": "FFFFFF", "outline": 7, "size": 130, "upper": True, "per": 3, "pop": 112}


def folder(uid=None) -> Path:
    d = config.user_dir(uid or ctx.uid()) / "brand"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file(uid=None) -> Path:
    return folder(uid) / "brand.json"


def get(uid=None) -> dict:
    try:
        data = json.loads(_file(uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def _write(kit, uid=None):
    with _lock:
        f = _file(uid)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(kit, indent=1), encoding="utf-8")
        tmp.replace(f)


def _color(v, default):
    v = str(v or "").strip().lstrip("#")
    return v.upper() if HEX.match(v) else default


def font_names(kit=None) -> list:
    kit = kit or get()
    return list(BUILTIN_FONTS) + [f["name"] for f in kit["fonts"]]


def _clean_style(s: dict, kit: dict) -> dict:
    out = dict(STYLE_DEFAULTS)
    out["name"] = re.sub(r"[\x00-\x1f<>]", "", str(s.get("name") or out["name"]))[:40] or "My style"
    out["font"] = s.get("font") if s.get("font") in font_names(kit) else out["font"]
    for k in ("base", "active", "strong"):
        out[k] = _color(s.get(k), out[k])
    out["outline"] = max(0, min(14, int(float(s.get("outline", out["outline"])))))
    out["size"] = max(60, min(200, int(float(s.get("size", out["size"])))))
    out["per"] = max(1, min(6, int(float(s.get("per", out["per"])))))
    out["upper"] = bool(s.get("upper", out["upper"]))
    out["id"] = s.get("id") if re.fullmatch(r"u_[0-9a-f]{8}", str(s.get("id") or "")) else "u_" + uuid.uuid4().hex[:8]
    return out


def save(patch: dict) -> dict:
    kit = get()
    for k, v in (patch or {}).items():
        if k == "logo_pos":
            kit[k] = v if v in POSITIONS else kit[k]
        elif k == "logo_size":
            kit[k] = max(5, min(40, int(float(v))))
        elif k == "logo_opacity":
            kit[k] = max(10, min(100, int(float(v))))
        elif k in ("bar_color", "hook_box", "hook_ink"):
            kit[k] = _color(v, kit[k])
        elif k == "hook_font":
            kit[k] = v if v in font_names(kit) else kit[k]
        elif k == "styles" and isinstance(v, list):
            kit[k] = [_clean_style(s, kit) for s in v if isinstance(s, dict)][:12]
        elif k == "logo" and v == "":
            old = kit.get("logo")
            if old:
                (folder() / old).unlink(missing_ok=True)
            kit["logo"] = ""
    _write(kit)
    return public()


def put_logo(data: bytes, filename: str) -> dict:
    from io import BytesIO
    from PIL import Image
    try:
        im = Image.open(BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        raise ValueError("That file isn't a picture. Use a PNG (best, with a see-through background) or a JPG.")
    if im.width < 16 or im.height < 16:
        raise ValueError("That picture is too small for a logo.")
    im = im.convert("RGBA")
    if max(im.size) > 1200:
        im.thumbnail((1200, 1200))
    kit = get()
    if kit.get("logo"):
        (folder() / kit["logo"]).unlink(missing_ok=True)
    name = f"logo_{uuid.uuid4().hex[:6]}.png"
    im.save(folder() / name)
    kit["logo"] = name
    _write(kit)
    return public()


def put_font(data: bytes, filename: str) -> dict:
    from io import BytesIO
    from PIL import ImageFont
    ext = Path(filename or "").suffix.lower()
    if ext not in (".ttf", ".otf"):
        raise ValueError("Fonts must be .ttf or .otf files.")
    if len(data) > 20_000_000:
        raise ValueError("That font file is too big.")
    try:
        family, style = ImageFont.truetype(BytesIO(data), 40).getname()
    except Exception:  # noqa: BLE001
        raise ValueError("That file isn't a font this computer can read.")
    name = re.sub(r"[\x00-\x1f,{}\\]", "", f"{family}" + (f" {style}" if style and style.lower() not in ("regular", "normal") else ""))[:60]
    kit = get()
    if name in BUILTIN_FONTS or any(f["name"] == name for f in kit["fonts"]):
        raise ValueError(f"A font called {name} is already in your kit.")
    fname = f"font_{uuid.uuid4().hex[:6]}{ext}"
    (folder() / fname).write_bytes(data)
    kit["fonts"] = (kit["fonts"] + [{"file": fname, "name": name, "family": family}])[:20]
    _write(kit)
    return public()


def delete_font(name: str) -> dict:
    kit = get()
    keep = []
    for f in kit["fonts"]:
        if f["name"] == name:
            (folder() / f["file"]).unlink(missing_ok=True)
        else:
            keep.append(f)
    kit["fonts"] = keep
    for s in kit["styles"]:
        if s.get("font") == name:
            s["font"] = STYLE_DEFAULTS["font"]
    if kit.get("hook_font") == name:
        kit["hook_font"] = DEFAULTS["hook_font"]
    _write(kit)
    return public()


def public() -> dict:
    kit = get()
    return {**kit, "has_logo": bool(kit["logo"]), "font_names": font_names(kit),
            "positions": {"tl": "Top left", "tr": "Top right", "bl": "Bottom left", "br": "Bottom right"}}


def logo_path(uid=None) -> Path | None:
    kit = get(uid)
    f = folder(uid) / kit["logo"] if kit["logo"] else None
    return f if f and f.is_file() else None


def style_names(uid=None) -> dict:
    return {s["id"]: s["name"] for s in get(uid)["styles"]}


def for_render(uid: str) -> dict:
    """Everything the renderer needs from the kit, with real file paths."""
    kit = get(uid)
    d = folder(uid)
    fonts = {f["name"]: {"path": str(d / f["file"]), "family": f.get("family") or f["name"]}
             for f in kit["fonts"] if (d / f["file"]).is_file()}
    return {**kit, "logo_path": str(logo_path(uid) or ""), "font_files": fonts,
            "style_map": {s["id"]: s for s in kit["styles"]}}
