"""ShaydoxCut's extras: the tight edit, captions on the new timeline, emojis, sound effects, the smart camera, the
full render with every effect, the CapCut kit, the brand kit and learning. Uses a made-up video (a test pattern
with a tone), so it needs no keys and nothing leaves this machine."""
import json, os, subprocess, sys, tempfile, zipfile
from pathlib import Path
os.environ["SHAYDOX_DATA"] = tempfile.mkdtemp(prefix="sx-test-"); os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
import numpy as np
from studio import brain, camera, config, ctx, effects, export, learn, render
fails = []
def check(n, ok, x=""):
    print(("PASS " if ok else "FAIL ") + n + (f"  {x}" if x and not ok else "")); ok or fails.append(n)

# ---- tight edit: pauses and ums go, talking and loud moments stay
words = [{"w": "So", "s": 0.2, "e": 0.4}, {"w": "um", "s": 0.5, "e": 0.9}, {"w": "this", "s": 1.0, "e": 1.3},
         {"w": "is", "s": 1.35, "e": 1.5}, {"w": "crazy", "s": 4.0, "e": 4.5}, {"w": "money", "s": 4.6, "e": 5.0}]
segs = render.tighten(words, 0.0, 6.0, audio=None)
kept = sum(b - a for a, b in segs)
check("the long pause is cut", kept < 3.5, segs)
check("the um is cut", not any(a <= 0.7 < b for a, b in segs), segs)
check("the words are kept", all(any(a <= (w["s"] + w["e"]) / 2 < b for a, b in segs) for w in words if w["w"] != "um"), segs)
loud = np.zeros(16000 * 6, dtype=np.float32)
loud[int(16000 * 2.0):int(16000 * 3.2)] = 0.5 * np.sin(np.arange(int(16000 * 1.2)) / 3)       # a scream with no words
segs2 = render.tighten(words, 0.0, 6.0, audio=loud)
check("a loud moment with no words is kept", any(a <= 2.6 < b for a, b in segs2), segs2)
check("nothing to cut keeps the clip whole", render.tighten([{"w": "hi", "s": 0, "e": 5.9}], 0, 6) == [(0, 6)])
out = render.remap(words, segs)
check("captions move onto the new timeline", out[-1]["e"] <= kept + 0.01 and all(w["w"] != "um" for w in out),
      [(w["w"], w["s"]) for w in out])
check("captions keep their order", [w["s"] for w in out] == sorted(w["s"] for w in out))
s = render.srt(out, 3)
check("subtitles for editors are written", s.startswith("1\n00:00:00,") and "-->" in s, s[:80])

# ---- emojis and sounds
spaced = [{"w": "so", "s": 0.2, "e": 0.5}, {"w": "insane", "s": 1.5, "e": 2.0}, {"w": "big", "s": 3.0, "e": 3.4},
          {"w": "money", "s": 5.0, "e": 5.5}]
pick = effects.pick(spaced, ["insane"], [{"word": "money", "emoji": "💰"}])
check("the AI's emoji goes on its word", ("💰", 5.0) in pick, pick)
check("two emojis never come too close together", len(effects.pick(out, ["crazy"], [{"word": "money", "emoji": "💰"}])) == 1)
check("a said keyword brings an emoji", any(e == "🔥" for e, _ in pick), pick)
check("no emoji in the first moment of the clip", all(t > 0.6 for _, t in pick))
check("text that isn't an emoji is refused", not effects.is_emoji("money") and effects.is_emoji("🔥"))
for snd in ("whoosh", "pop", "thump"):
    f = effects.sound(snd)
    check(f"the {snd} sound is made", f.is_file() and f.stat().st_size > 2000)

# ---- a made-up wide video: a moving test pattern with a tone
work = Path(tempfile.mkdtemp(prefix="sx-vid-"))
src = work / "wide.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8",
                "-f", "lavfi", "-i", "sine=frequency=330:duration=8", "-shortest", "-c:v", "libx264", "-preset",
                "ultrafast", "-c:a", "aac", str(src)], check=True)
if camera.available():
    cam = camera.plan_clip(src, [(1.0, 6.0)], "split")
    check("no facecam in a test pattern: falls back to following", cam["layout"] == "track" and cam["note"], cam["layout"])
    n, fps = camera.draw(src, [(1.0, 3.0), (4.0, 6.0)], cam, work / "base.mp4", zoom_events=[(0.5, 1.0)])
    check("the camera draws every kept frame", abs(n - 4 * fps) <= 3, (n, fps))
    m = camera.motion_per_second(src, 0, 8)
    check("picture changes are measured each second", 6 <= len(m) <= 9 and max(m) > 0, len(m))
    check("still frames are taken for the AI", len(camera.still_frames(src, 1, 6, n=3)) == 3)
    z = camera.zoom_curve([(1.0, 2.0)], 4, 30)
    check("a punch-in zooms in and comes back", z[0] == 1.0 and z[45] > 1.1 and z[110] == 1.0)

# ---- the full render with every effect, and the CapCut kit
with ctx.as_user("u_local"):
    clip = {"start": 1.0, "end": 7.0, "hook": "TEST HOOK", "style": "bounce", "layout": "track",
            "highlight_words": ["crazy"], "emojis": [{"word": "money", "emoji": "💰"}]}
    ws = [{"w": w, "s": 1.2 + i * 0.6, "e": 1.6 + i * 0.6} for i, w in enumerate("this is crazy money right here wow".split())]
    res = render.render_clip(src, work / "clips", "clip01", clip, ws, 1280, 720)
    d = work / "clips"
    check("the finished clip is made", (d / "clip01.mp4").is_file() and (d / "clip01.mp4").stat().st_size > 10000)
    check("a clean copy for editing is made", (d / "clip01_clean.mp4").is_file())
    check("captions files are made", (d / "clip01.srt").is_file() and (d / "clip01.words.srt").is_file())
    info = json.loads((d / "clip01.cues.json").read_text(encoding="utf-8"))
    check("the effects are listed with their times", info["sounds"] and info["sounds"][0]["sound"] == "whoosh", info["sounds"][:2])
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                            str(d / "clip01.mp4")], capture_output=True, text=True).stdout
    check("the clip is 1080x1920", "1080,1920" in probe, probe)
    # the kit, built from a job that holds this clip
    from studio import jobs
    job = {"id": "20990101-000000-test0001", "user": "u_local", "kind": "video", "creator": None, "dir": str(work),
           "created": 0, "source": {"type": "file", "name": "x"}, "options": {}, "status": "done", "clips": [
               dict(clip, id="clip01", status="done", file="clip01.mp4", clean="clip01_clean.mp4", title="A test",
                    hashtags=["one", "two"], description="Desc", score=80)]}
    jobs._jobs[job["id"]] = job
    jobs._by_user.setdefault("u_local", {})[job["id"]] = job
    f, name = export.build([(job["id"], "clip01")])
    names = zipfile.ZipFile(f).namelist()
    for want in ("A_test_captioned.mp4", "A_test_clean.mp4", "captions.srt", "captions_word_by_word.srt", "cues.txt",
                 "post.txt", "timeline_premiere_davinci.xml", "HOW TO OPEN IN CAPCUT.txt", "assets/whoosh.wav"):
        check(f"the CapCut kit has {want}", want in names, names)
    timeline = zipfile.ZipFile(f).read("timeline_premiere_davinci.xml").decode()
    from xml.dom import minidom
    try:
        minidom.parseString(timeline)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("the editor timeline is valid XML", ok and "<marker>" in timeline)

    # ---- the brand kit
    from studio import brand
    from PIL import Image
    import io
    b = io.BytesIO(); Image.new("RGBA", (200, 80), (255, 0, 0, 200)).save(b, "PNG")
    k = brand.put_logo(b.getvalue(), "logo.png")
    check("a logo is saved", k["has_logo"] and brand.logo_path() is not None)
    k = brand.save({"styles": [{"name": "Mine", "base": "#00ff00", "active": "ff00ff", "size": 999}], "logo_pos": "bl"})
    st = k["styles"][0]
    check("a caption style is saved and kept in range", st["base"] == "00FF00" and st["size"] == 200 and st["id"].startswith("u_"), st)
    check("saved styles are offered with the built-in ones", st["id"] in brand.style_names())
    try:
        brand.put_logo(b"not a picture", "x.png"); bad = False
    except ValueError:
        bad = True
    check("a file that isn't a picture is refused as a logo", bad)
    kit = brand.for_render("u_local")
    clip2 = dict(clip, style=st["id"], end=4.0)
    render.render_clip(src, work / "clips", "clip02", clip2, ws, 1280, 720, kit=kit)
    check("a clip renders with the logo and a saved style", (work / "clips" / "clip02.mp4").is_file())

    # ---- learning: nothing to say until there are a few opinions
    check("learning stays quiet with no signals", learn.insights()["text"] == "")
    for i, (cat, r) in enumerate([("fail", 1), ("fail", 1), ("funny", -1), ("rage", 1)]):
        job["clips"].append(dict(job["clips"][0], id=f"r{i}", category=cat, rating=r, hook=f"HOOK {i}"))
    ins = learn.insights()
    check("learning speaks up after a few ratings", "What has worked" in ins["text"] and ins["summary"]["ready"], ins["summary"])
    check("liked kinds get a small boost, disliked a small cut", ins["weights"]["fail"] > 1 > ins["weights"]["funny"] >= 0.8, ins["weights"])

# ---- the AI is told about action, the channel's history, and asked for the extras
lines = brain._add_action([{"s": 0.0, "e": 3.0, "text": "hello there", "loud": False}], [1] * 10 + [30, 30, 30] + [1] * 10)
check("a burst of action with nobody talking becomes a line for the AI", any(l["text"] == brain.SILENT_ACTION for l in lines), lines)
check("the AI is asked for emojis and a score breakdown", "emojis" in brain.SCHEMA["items"]["properties"] and "scores" in brain.SCHEMA["items"]["properties"])
t = brain._tidy({"score": 90, "scores": {"hook": 120, "payoff": 50, "emotion": 40, "share": "x"}, "emojis": [{"word": "a", "emoji": "🔥"}], "hook": "x"}, 0, 1)
check("the AI's breakdown is kept in range", t["scores"]["hook"] == 100 and t["scores"]["share"] == 0 and t["emojis"][0]["emoji"] == "🔥", t)
check("captions can be translated into many languages", {"es", "fr", "de", "pt", "hi-latn"} <= set(brain.LANGUAGES))
if fails:
    print("FAILED:", len(fails)); sys.exit(1)
print("ALL PASSED")

# ---- pictures reach each AI service in the shape it expects (a stand-in answers, nothing is sent)
from studio import ai
import httpx
sent = []
class R:
    def __init__(self, code, data): self.status_code, self._d, self.text = code, data, json.dumps(data)
    def json(self): return self._d
def fake_post(url, json=None, headers=None, timeout=None):
    sent.append((url, dict(json)))
    if "generateContent" in url:
        return R(200, {"candidates": [{"content": {"parts": [{"text": '{"visual": 70}'}]}}], "usageMetadata": {"promptTokenCount": 5, "totalTokenCount": 9}})
    if url.endswith("/messages"):
        if "output_config" in json and "old" in json["model"]:
            return R(400, {"error": {"message": "output_config.effort: not supported"}})
        return R(200, {"content": [{"type": "text", "text": '{"visual": 70}'}], "usage": {"input_tokens": 5, "output_tokens": 4}, "stop_reason": "end_turn"})
    return R(200, {"choices": [{"message": {"content": '{"visual": 70}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 4}})
real_post, ai.httpx.post = ai.httpx.post, fake_post
for prov in ("gemini", "openai", "anthropic"):
    ai.current = lambda prov=prov: {"provider": prov, "models": ["m"], "base_url": "", "key": "k"}
    sent.clear()
    out, a, b = ai.call("m", "look", brain.VISION_SCHEMA, images=[b"\xff\xd8jpeg"])
    body = json.dumps(sent[-1][1])
    check(f"{prov}: the picture is sent with the words", out.get("visual") == 70 and ("inline_data" in body or "image_url" in body or '"image"' in body), body[:120])
ai.current = lambda: {"provider": "anthropic", "models": ["claude-old"], "base_url": "", "key": "k"}
sent.clear()
ai.call("claude-old", "hi", brain.FIX_SCHEMA)
check("Claude: low effort is asked for, and dropped for an older model that refuses it", len(sent) == 2 and "output_config" in sent[0][1] and "output_config" not in sent[1][1])
check("Claude: answers have room so they are never cut short", sent[-1][1]["max_tokens"] >= 16000)
ai.httpx.post = real_post
if fails:
    print("FAILED:", len(fails)); sys.exit(1)
print("ALL PASSED (AI shapes)")

# ---- caption looks: every style and hook look draws, with its own font
from studio import captions
check("there are many caption styles", len(captions.STYLES) >= 20)
missing = [n for n in captions.FONT_FILES.values() if not (Path("studio/fonts") / n).is_file()]
check("every caption font is bundled", not missing, missing)
say = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.35} for i, w in enumerate("clip this moment right here".split())]
for sid in captions.STYLES:
    a = captions.build_ass(say, 0, 3, "HOOK TEXT", sid, ["moment"], 300, 1380, st=captions.style(sid))
    check(f"caption style {sid} writes captions", a.count("Dialogue:") >= 3 and captions.STYLES[sid]["font"] in a)
kar = captions.build_ass(say, 0, 3, "", "karaoke", [], 300, 1380, st=captions.style("karaoke"))
check("karaoke fills word by word", r"\kf" in kar)
box = captions.build_ass(say, 0, 3, "", "boxed", [], 300, 1380, st=captions.style("boxed"))
check("boxed draws a box behind the spoken word", r"\p1" in box.split("[Events]")[1].split("HOOK")[-1])
for hid in captions.HOOK_STYLES:
    a = captions.build_ass([], 0, 3, "THIS CHANGED EVERYTHING", "bounce", [], 300, 1380, hook_look=captions.hook_look(hid))
    check(f"hook look {hid} writes the heading", "Hook" in a and ("This" in a or "THIS" in a))
f = captions.preview("caption", "boxed")
check("style previews are drawn", f.is_file() and f.stat().st_size > 2000)

# ---- the progress bar grows instead of starting full
check("the progress bar slides with time", "overlay=x='-w+w*t/" in open("studio/render.py", encoding="utf-8").read())

# ---- the AI is limited to emojis that exist as 3D pictures, and the owner's wish reaches the prompt
check("emoji choices are limited to the 3D set", effects.pick(spaced, [], [{"word": "money", "emoji": "🦄"}]) == [] or all(e in effects.FLUENT for e, _ in effects.pick(spaced, [], [{"word": "money", "emoji": "🦄"}])))
check("the owner's wish is passed to the AI", "funny fails" in brain.wish_text("all the funny fails") and brain.wish_text("") == "")
from studio import jobs as _jobs
o = _jobs.clean_options({"hook_style": "banner", "prompt": "x" * 500, "enhance": "false", "broll": True, "color": "on"})
check("new options are checked", o["hook_style"] == "banner" and len(o["prompt"]) == 300 and o["enhance"] is False and o["broll"] is True and o["color"] is True, o)
if fails:
    print("FAILED:", len(fails)); sys.exit(1)
print("ALL PASSED (looks)")

# ---- picking the best moments (ideas from careful editors): hooks, ranking, cuts, teasers
W2 = lambda t, s0=0.0: [{"w": w, "s": s0 + i * 0.4, "e": s0 + i * 0.4 + 0.3} for i, w in enumerate(t.split())]
said = W2("So yeah we went out. The yacht just sank in ten seconds! That cost 1.7 million dollars?")
check("a hook is taken from what is said when there is no AI", brain.smart_hook(said) == "THAT COST 1.7 MILLION DOLLARS?", brain.smart_hook(said))
check("generic hooks are recognised", brain.is_generic("WAIT FOR IT") and brain.is_generic("Watch this!") and not brain.is_generic("HE SANK A YACHT"))
t = brain._tidy({"hook": "WAIT FOR IT", "score": 70, "payoff": "You see a yacht sink.", "needs": "nothing"}, 0, 12, said, 5)
check("a generic hook from the AI is replaced by what is said", t["hook"] == "THAT COST 1.7 MILLION DOLLARS?", t["hook"])
words3 = W2("Who won the race last year? That was me, I won it by a mile and nobody believed it.", 10)
lines3 = brain.make_lines(words3)
s_, e_ = brain._snap({"start": words3[6]["s"], "end": words3[-1]["e"]}, lines3, words3, 3, 30, 60)
check("a clip never opens on a word that points back", s_ <= words3[0]["s"], (s_, words3[6]["w"]))
long_words = W2(" ".join(["word"] * 80))
c = {"keep": [{"start": 0, "end": 10}, {"start": 16, "end": 30}], "cold_open": {"start": 20, "end": 23}}
k = brain._ranges(c, 0, 31, long_words, 10)
check("the AI's keep ranges are kept when they cut something out", k and len(k) == 2 and k[0][0] >= 0 and k[1][1] <= 31, k)
check("keep ranges that cut nothing are ignored", brain._ranges({"keep": [{"start": 0, "end": 31}]}, 0, 31, long_words, 10) is None)
check("a teaser inside the clip is kept", brain._cold(c, 0, 31, long_words) is not None)
check("a teaser at the very start is pointless and dropped", brain._cold({"cold_open": {"start": 0.5, "end": 3}}, 0, 31, long_words) is None)
cands = [{"title": f"c{i}", "hook": f"HOOK {i}", "start": i * 40, "end": i * 40 + 30, "score": 60 + i, "category": "funny",
          "payoff": "p", "reason": "r"} for i in range(6)]
real_ask = brain.ask_ai
brain.ask_ai = lambda prompt, schema=None, purpose="", **k: ({"ranked": [{"id": 1, "why": "x"}, {"id": 4, "why": "y"}, {"id": 0, "why": "z"}]}, "m", 9)
real_ready = brain.config.ai_ready
brain.config.ai_ready = lambda: True
best, spent = brain.rank(cands, 3, "t")
check("the ranking pass decides the order across the whole video", [c["title"] for c in best[:3]] == ["c1", "c4", "c0"] and len(best) == 6, [c["title"] for c in best])
brain.ask_ai = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
best, _s = brain.rank(cands, 3, "t", log=lambda m: None)
check("without the AI the scores decide", best[0]["title"] == "c5")
brain.ask_ai = lambda prompt, schema=None, purpose="", **k: (["HE SANK THE YACHT", "WAIT FOR IT", "$1.7M GONE IN SECONDS"], "m", 5)
hooks = brain.new_hooks("we sank the yacht in ten seconds and it cost 1.7 million", "t")
check("new hook ideas drop generic ones", hooks == ["HE SANK THE YACHT", "$1.7M GONE IN SECONDS"], hooks)
brain.ask_ai, brain.config.ai_ready = real_ask, real_ready
from studio import reactions
lines4 = brain._add_reactions([{"s": 5.0, "e": 7.0, "text": "that was hilarious", "loud": False}], {"laughter": [0] * 6 + [0.6, 0.7, 0] , "cheering": [0] * 9, "screaming": [0] * 9})
check("a heard laugh is marked for the AI", lines4[0].get("react") == "LAUGH" and "(LAUGH)" in brain._fmt(lines4))
check("the laughter detector reports its own state", isinstance(reactions.available(), bool))
check("the AI is told how to cut tight and stand alone", all(x in brain.RULES for x in ("payoff", "needs", "keep", "cold_open", "NEVER generic")))
from studio import render as _r
check("keep ranges intersect the silence cuts", _r._intersect([(0, 5), (6, 20)], [[2, 8], [15, 30]]) == [(2, 5), (6, 8), (15, 20)])
if fails:
    print("FAILED:", len(fails)); sys.exit(1)
print("ALL PASSED (picking)")

# ---- clips aim for a full story, and a short one loses points
check("the AI is told a target length", "AIM FOR 36 TO 60" in brain.RULES.format(min_len=15, max_len=60, transcript="", emoji_set="", target_lo=brain._target_lo(15, 60)))
check("the target never falls below the minimum", brain._target_lo(40, 50) == 40 and brain._target_lo(15, 60) == 36)
if fails:
    print("FAILED:", len(fails)); sys.exit(1)
print("ALL PASSED (length)")
