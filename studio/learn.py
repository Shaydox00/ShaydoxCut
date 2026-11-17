"""Learning from results: what worked on a channel, fed back to the AI the next time it picks clips.

Two kinds of signal are used:
- What you thought: the thumbs up / thumbs down on a clip.
- What viewers thought: the views each posted clip got (read from YouTube and Instagram by posting.py).

From these it writes a few plain lines for the AI ("on this channel, fails and rage clips get the most views; hooks
like X worked, hooks like Y did not") and works out a small boost or penalty per kind of clip."""
import time

from . import ctx

MIN_SIGNALS = 3          # below this there is nothing worth telling the AI yet


def _clips_by_id(uid) -> dict:
    from . import jobs
    out = {}
    for j in jobs.all_jobs():
        if j.get("user") != uid:
            continue
        for c in j.get("clips", []):
            out[(j["id"], c["id"])] = (j, c)
    return out


def signals(creator=None, uid=None) -> list:
    """Every clip with an opinion on it: [{category, hook, title, score, views, rating, creator}]."""
    from . import posting
    uid = uid or ctx.uid()
    clips = _clips_by_id(uid)
    seen, out = set(), []
    posts = [p for p in posting._posts if p.get("user") == uid and p.get("status") == "posted"]
    for p in posts:
        if creator and p.get("creator") != creator:
            continue
        jc = clips.get((p["job"], p["clip"]))
        c = jc[1] if jc else {}
        key = (p["job"], p["clip"])
        if key in seen:
            for o in out:                                   # the same clip on two accounts: add the views up
                if o["key"] == key and p.get("views") is not None:
                    o["views"] = (o["views"] or 0) + p["views"]
            continue
        seen.add(key)
        out.append({"key": key, "category": c.get("category", "other"), "hook": c.get("hook") or p.get("title", ""),
                    "title": c.get("title") or p.get("title", ""), "score": c.get("score", p.get("score", 0)),
                    "views": p.get("views"), "rating": c.get("rating", 0), "posted_at": p.get("posted_at", 0)})
    for (jid, cid), (j, c) in clips.items():
        if (jid, cid) in seen or not c.get("rating"):
            continue
        if creator and j.get("creator") != creator:
            continue
        out.append({"key": (jid, cid), "category": c.get("category", "other"), "hook": c.get("hook", ""),
                    "title": c.get("title", ""), "score": c.get("score", 0), "views": None, "rating": c["rating"],
                    "posted_at": 0})
    return out


def insights(creator=None, uid=None) -> dict:
    """What has been learned, as text for the AI, a per-kind weight, and a summary for the page."""
    sig = signals(creator, uid)
    viewed = [s for s in sig if s["views"] is not None and time.time() - s["posted_at"] > 6 * 3600]
    rated = [s for s in sig if s["rating"]]
    if len(viewed) + len(rated) < MIN_SIGNALS:
        return {"text": "", "weights": {}, "summary": {"posted": len(viewed), "rated": len(rated), "ready": False,
                                                       "best": [], "worst": [], "kinds": []}}
    # how each kind of clip did, compared with this channel's usual
    kinds = {}
    if viewed:
        avg = sum(s["views"] for s in viewed) / len(viewed) or 1
        for s in viewed:
            kinds.setdefault(s["category"], []).append(s["views"] / avg)
    for s in rated:
        kinds.setdefault(s["category"], []).append(1.4 if s["rating"] > 0 else 0.6)
    weights, rows = {}, []
    for k, vals in kinds.items():
        m = sum(vals) / len(vals)
        weight = max(0.8, min(1.25, 1 + (m - 1) * 0.25 * min(1.0, len(vals) / 4)))   # gentle: a few clips are not proof
        weights[k] = round(weight, 3)
        rows.append({"kind": k, "clips": len(vals), "vs_usual": round(m, 2)})
    rows.sort(key=lambda r: -r["vs_usual"])
    good = sorted([s for s in viewed], key=lambda s: -s["views"])[:5] + [s for s in rated if s["rating"] > 0][:5]
    bad = sorted([s for s in viewed], key=lambda s: s["views"])[:3] + [s for s in rated if s["rating"] < 0][:5]
    good_keys = {g["key"] for g in good}
    bad = [b for b in bad if b["key"] not in good_keys]

    def line(s):
        v = f"{s['views']} views" if s["views"] is not None else ("liked by the owner" if s["rating"] > 0 else "disliked by the owner")
        return f'- [{s["category"]}] "{s["hook"]}" / "{s["title"][:70]}" ({v})'

    text = ["", "What has worked on this channel before (learn from it, but still judge each moment on its own):"]
    if rows:
        text.append("Kinds of clips, compared with this channel's usual: " +
                    ", ".join(f"{r['kind']} x{r['vs_usual']}" for r in rows[:6]) + ".")
    if good:
        text.append("Clips that did well:")
        text += [line(s) for s in good[:6]]
    if bad:
        text.append("Clips that did badly (avoid moments, hooks and titles like these):")
        text += [line(s) for s in bad[:5]]
    return {"text": "\n".join(text) + "\n", "weights": weights,
            "summary": {"posted": len(viewed), "rated": len(rated), "ready": True, "kinds": rows,
                        "best": [{"hook": s["hook"], "views": s["views"], "liked": s["rating"] > 0} for s in good[:5]],
                        "worst": [{"hook": s["hook"], "views": s["views"], "liked": False} for s in bad[:5]]}}
