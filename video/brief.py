"""Fetch today's brief from a WordPress site and turn it into video text."""
import html
import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

ABBREV = re.compile(r"(?:\b(?:[A-Za-z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Inc|Ltd|Co|No|Mt|Lt|Gen|Sgt|Prof|Rev|Hon|vs|approx|ca)\.)$")


def split_sentences(text):
    """Split on . ! ? followed by a capital, but not after abbreviations like U.K. or Dr."""
    out, start = [], 0
    for m in re.finditer(r"[.!?][\"”’)]?\s+(?=[A-Z0-9“\"‘(])", text):
        chunk = text[start:m.end()].strip()
        before = text[start:m.start() + 1].strip()
        if ABBREV.search(before):
            continue
        out.append(chunk)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def clean_paragraph(p):
    # Drop the trailing "Source(s): ..." credit.
    for strong in p.find_all("strong"):
        if strong.get_text(strip=True).lower().startswith("source"):
            for sib in list(strong.next_siblings):
                sib.extract()
            strong.extract()
    text = p.get_text(" ", strip=True)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


MAX_FACT_WORDS = 30

ATTRIBUTION = re.compile(
    r",\s*(?:according to [^,]+|(?:the )?[A-Z][\w.’'& -]{1,60} (?:reports|reported|says|said))\.?$")


def pick_fact(paragraph_text):
    """Fallback when the brief has no video notes: first sentence, minus its attribution."""
    sents = split_sentences(paragraph_text)
    if not sents:
        return None
    first = sents[0].rstrip()
    first = ATTRIBUTION.sub("", first.rstrip(".")).rstrip(",") + "."
    if len(first.split()) <= MAX_FACT_WORDS:
        return first
    return None  # too long for the screen; the headline carries the story


NOTES = re.compile(r"<!--\s*morning-five-video:\s*(\{.*?\})\s*-->", re.S)


def video_notes(content_html):
    """Short tag + key fact per story, written by the brief writer in a hidden HTML comment."""
    m = NOTES.search(content_html)
    if not m:
        return []
    raw = html.unescape(m.group(1))
    for a, b in (("“", '"'), ("”", '"'), ("″", '"')):
        raw = raw.replace(a, b)
    try:
        return json.loads(raw).get("stories", [])
    except ValueError:
        return []


def parse_brief(content_html):
    soup = BeautifulSoup(content_html, "html.parser")
    stories = []
    for h2 in soup.find_all("h2"):
        headline = html.unescape(h2.get_text(" ", strip=True))
        para = h2.find_next_sibling()
        while para is not None and para.name not in ("p", "h2"):
            para = para.find_next_sibling()
        fact = None
        if para is not None and para.name == "p":
            fact = pick_fact(clean_paragraph(para))
        stories.append({"headline": headline, "fact": fact, "tag": None})
    notes = video_notes(content_html)
    if len(notes) == len(stories):
        for s, n in zip(stories, notes):
            if (n.get("fact") or "").strip():
                s["fact"] = n["fact"].strip()
            if (n.get("tag") or "").strip():
                s["tag"] = n["tag"].strip()[:18]
    return stories


def fetch_today(site, today):
    """Return the newest published brief in the site's category if it is dated today, else None."""
    r = requests.get(
        site["url"].rstrip("/") + "/wp-json/wp/v2/posts",
        params={"categories": site["category_id"], "per_page": 1, "status": "publish",
                "_fields": "id,date,link,title,content"},
        headers={"User-Agent": "morning-five-video/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    posts = r.json()
    if not posts:
        return None
    return from_post(site, posts[0], today)


def from_post(site, post, today):
    """Turn a WordPress REST post object into video data, or None if it isn't today's."""
    if isinstance(post, list):
        if not post:
            return None
        post = post[0]
    if datetime.fromisoformat(post["date"]).date() != today:
        return None
    stories = parse_brief(post["content"]["rendered"])
    if len(stories) < 3:
        raise RuntimeError(f"{site['id']}: brief {post['id']} has only {len(stories)} headlines")
    return {
        "post_id": post["id"],
        "link": post["link"],
        "title": html.unescape(BeautifulSoup(post["title"]["rendered"], "html.parser").get_text()),
        "stories": stories,
    }
