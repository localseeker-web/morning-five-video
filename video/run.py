"""Daily job: for each enabled site whose brief is out today, render the video and post it.

python -m video.run --check          # list sites with work to do (no rendering)
python -m video.run                  # render + post everything pending
python -m video.run --dry-run        # render only, never post
python -m video.run --site ncrnow --force   # redo one site even if already posted today
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from . import brief as briefmod
from . import facebook
from .render import render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state", "posted.json")
OUT = os.path.join(ROOT, "out")


def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    # keep the last 30 days only
    for k in sorted(state)[:-30]:
        del state[k]
    with open(STATE, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")


def fill(text, n):
    return text.replace("{n}", str(n))


def caption(site, data, date_label):
    n = len(data["stories"])
    lines = [f"{fill(site['header_title'], n).title()} – {date_label}", ""]
    lines += [f"{i}. {s['headline']}" for i, s in enumerate(data["stories"], 1)]
    lines += ["", f"Full brief: {data['link']}", "", site.get("hashtags", "")]
    return "\n".join(lines).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: today in the configured timezone)")
    ap.add_argument("--brief-file", default="",
                    help="WordPress REST JSON of the brief (a post or a one-item list) instead of fetching it; needs --site")
    a = ap.parse_args()

    cfg = load_json(os.path.join(ROOT, "config.json"), {})
    tz = ZoneInfo(cfg.get("timezone", "America/Toronto"))
    today = datetime.fromisoformat(a.date).date() if a.date else datetime.now(tz).date()
    key = today.isoformat()
    date_label = f"{today:%A}, {today:%B} {today.day}, {today.year}"
    state = load_json(STATE, {})
    done_today = state.setdefault(key, {})

    pending, failures = [], []
    for site in cfg["sites"]:
        sid = site["id"]
        if a.site and a.site != sid:
            continue
        if not site.get("enabled") and not a.site:
            continue
        token = os.environ.get(site["fb_token_secret"], "").strip()
        posted = done_today.get(sid, {}).get("facebook")
        if posted and not a.force and not a.dry_run:
            print(f"[{sid}] already posted today ({posted.get('video_id')}); skipping")
            continue
        if done_today.get(sid, {}).get("rendered_only") and not token and not a.force and not a.dry_run:
            print(f"[{sid}] already rendered today (no Facebook key set); skipping")
            continue
        try:
            if a.brief_file:
                data = briefmod.from_post(site, load_json(a.brief_file, None), today)
            else:
                data = briefmod.fetch_today(site, today)
        except Exception as e:
            print(f"[{sid}] could not read the brief: {e}")
            failures.append(sid)
            continue
        if not data:
            print(f"[{sid}] no brief published yet for {key}")
            continue
        if not token and not a.dry_run:
            print(f"[{sid}] brief found but secret {site['fb_token_secret']} is not set; rendering only")
        pending.append(sid)
        if a.check:
            continue

        n = len(data["stories"])
        render_input = {
            "title_lines": [fill(l, n) for l in site["title_lines"]],
            "header_title": fill(site["header_title"], n),
            "date_label": date_label,
            "domain": site["domain"],
            "tagline": site["outro_tagline"],
            "stories": data["stories"],
        }
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"{sid}-{key}.mp4")
        try:
            print(f"[{sid}] rendering {data['title']} ({n} stories)")
            for s in data["stories"]:
                print(f"    - {s['headline']}\n      fact: {s['fact'] or '(none)'}")
            secs = render(site, render_input, path)
            print(f"[{sid}] video ready: {path} ({secs:.1f}s)")
            cap = caption(site, data, date_label)
            with open(path.replace(".mp4", ".txt"), "w") as fh:
                fh.write(cap + "\n")
            # TikTok doesn't make links clickable, so name the site instead.
            with open(path.replace(".mp4", "-tiktok.txt"), "w") as fh:
                fh.write(cap.replace(f"Full brief: {data['link']}", f"Full brief at {site['domain']}") + "\n")
            if a.dry_run:
                continue
            if not token:
                done_today.setdefault(sid, {})["rendered_only"] = True
                save_state(state)
                continue
            res = facebook.publish_reel(token, path, cap)
            print(f"[{sid}] Facebook Reel posted on '{res['page']}' (video {res['video_id']}, status {res['status']})")
            done_today.setdefault(sid, {})["facebook"] = {
                "video_id": res["video_id"], "post_id": data["post_id"],
                "at": datetime.now(tz).isoformat(timespec="seconds"),
            }
            save_state(state)
        except Exception:
            traceback.print_exc()
            failures.append(sid)

    if a.check:
        print("pending:", ",".join(pending) or "(none)")
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a") as fh:
                fh.write(f"pending={'yes' if pending else ''}\n")
    if failures:
        print("FAILED:", ", ".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
