"""Draw a vertical (1080x1920) brief video with Pillow and encode it with FFmpeg."""
import math
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1080, 1920, 30

# Safe area: TikTok/Reels overlay the caption at the bottom and buttons on the right.
SAFE_L, SAFE_R, SAFE_T, SAFE_B = 90, W - 170, 220, H - 430

INTRO, STORY, OUTRO = 3.5, 6.0, 4.0


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def mix(c1, c2, k):
    return tuple(int(a * (1 - k) + b * k) for a, b in zip(c1, c2))


class Style:
    def __init__(self, site):
        c = site["colors"]
        self.bg_top = hex2rgb(c["bg_top"])
        self.bg_bottom = hex2rgb(c["bg_bottom"])
        self.accent = hex2rgb(c["accent"])
        self.text = hex2rgb(c["text"])
        self.soft = hex2rgb(c["soft"])
        self.wave = hex2rgb(c["wave"])
        self.wave_deep = hex2rgb(c["wave_deep"])
        self.dot_off = hex2rgb(c["dot_off"])
        self.font_name = site["font"]
        self.weights = site["weights"]
        self.logo = os.path.join(ROOT, site["logo"])
        self.music = os.path.join(ROOT, site["music"])
        self._fonts = {}
        self._badges = {}

    def font(self, role_or_weight, size):
        w = self.weights.get(role_or_weight, role_or_weight)
        key = (w, size)
        if key not in self._fonts:
            path = os.path.join(ROOT, "assets", "fonts", f"{self.font_name}-{w}.ttf")
            self._fonts[key] = ImageFont.truetype(path, size)
        return self._fonts[key]

    def badge(self, diameter):
        """Logo on a white disc, so a dark logo still reads on a dark background."""
        if diameter in self._badges:
            return self._badges[diameter]
        S = 3
        D = diameter * S
        disc = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        ImageDraw.Draw(disc).ellipse([0, 0, D - 1, D - 1], fill=(255, 255, 255, 255))
        if os.path.exists(self.logo):
            logo = Image.open(self.logo).convert("RGBA")
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)
            inner = int(D * 0.86)
            sc = inner / max(logo.width, logo.height)
            logo = logo.resize((max(1, int(logo.width * sc)), max(1, int(logo.height * sc))), Image.LANCZOS)
            disc.alpha_composite(logo, ((D - logo.width) // 2, (D - logo.height) // 2))
        out = disc.resize((diameter, diameter), Image.LANCZOS)
        self._badges[diameter] = out
        return out


def paste_badge(st, img, diameter, cx, cy, k=1.0):
    if k <= 0:
        return
    d = max(2, int(diameter * (0.85 + 0.15 * k)))
    b = st.badge(d)
    if k < 1:
        b = b.copy()
        b.putalpha(b.split()[3].point(lambda v: int(v * k)))
    img.paste(b, (int(cx - d / 2), int(cy - d / 2)), b)


def wrap(draw, text, fnt, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_lines(st, draw, text, role, start, minimum, width, max_lines):
    """Largest font size (start..minimum) where text wraps into max_lines. None if it can't."""
    size = start
    while size >= minimum:
        f = st.font(role, size)
        lines = wrap(draw, text, f, width)
        if len(lines) <= max_lines:
            return f, lines
        size -= 2
    return None, None


def background(st):
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        grad.putpixel((0, y), mix(st.bg_top, st.bg_bottom, y / H))
    return grad.resize((W, H))


def waves_spec(st):
    return [
        (1500, 38, 1300, 55, st.wave + (34,)),
        (1590, 30, 950, -42, st.wave + (46,)),
        (1680, 44, 1600, 30, st.wave_deep + (70,)),
        (1780, 26, 800, -65, st.wave + (40,)),
    ]


def with_waves(st, base, T):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, (y0, amp, wl, speed, col) in enumerate(waves_spec(st)):
        bob = math.sin(T * 0.6 + i) * 12
        pts = [(x, y0 + bob + amp * math.sin(2 * math.pi * (x + speed * T) / wl)
                + amp * 0.35 * math.sin(2 * math.pi * (x - speed * 0.6 * T) / (wl * 0.45)))
               for x in range(0, W + 20, 20)]
        d.polygon(pts + [(W, H), (0, H)], fill=col)
    pts = [(x, 120 + 22 * math.sin(2 * math.pi * (x - 35 * T) / 1400)) for x in range(0, W + 20, 20)]
    d.polygon([(0, 0), (W, 0)] + pts[::-1], fill=st.wave + (22,))
    out = base.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def centered(d, text, f, y, col):
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2, y), text, font=f, fill=col)


def frame_intro(st, bg, t, brief):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    paste_badge(st, img, 400, W // 2, 570, ease(t / 0.8))
    k2 = ease((t - 0.3) / 0.8)
    lines = brief["title_lines"]
    f = None
    for size in range(112, 60, -4):  # shrink if a line is too wide
        f = st.font("title", size)
        if all(d.textlength(l, font=f) <= W - 2 * SAFE_L for l in lines):
            break
    lh = int(f.size * 1.12)
    y0 = 860
    for i, line in enumerate(lines):
        centered(d, line, f, y0 + i * lh + int(60 * (1 - k2)), mix(st.bg_top, st.text, k2))
    yb = y0 + len(lines) * lh + 30
    k3 = ease((t - 0.9) / 0.8)
    centered(d, brief["date_label"], st.font("body", 46), yb, mix(st.bg_top, st.accent, k3))
    rw = int(260 * k3)
    d.rectangle([W / 2 - rw, yb + 80, W / 2 + rw, yb + 86], fill=st.accent)
    return img


def frame_story(st, bg, t, i, story, n, header):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    paste_badge(st, img, 140, SAFE_L + 70, 190)
    fh_title = st.font("head", 36)
    if d.textlength(header, font=fh_title) > SAFE_R - SAFE_L - 170:
        fh_title = st.font("head", 30)
    d.text((SAFE_L + 170, 148), header, font=fh_title, fill=st.text)
    for j in range(n):
        cx, cy = SAFE_L + 180 + j * 40, 225
        r = 11 if j == i else 8
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=st.accent if j <= i else st.dot_off)

    k = ease(t / 0.6)
    fn = st.font("title", 300)
    num = str(i + 1)
    d.text((SAFE_L - 10, 330 - int(80 * (1 - k))), num, font=fn, fill=mix(st.bg_top, st.accent, k))
    d.text((SAFE_L + d.textlength(num, font=fn) + 20, 560), f"of {n}", font=st.font("medium", 44),
           fill=mix(st.bg_top, st.soft, k))

    y = 720
    if story.get("tag"):
        k_tag = ease((t - 0.25) / 0.6)
        ft = st.font("head", 36)
        tag = story["tag"].upper()
        tw = d.textlength(tag, font=ft)
        d.rounded_rectangle([SAFE_L, 700, SAFE_L + tw + 44, 762], radius=31, fill=mix(st.bg_top, st.accent, k_tag))
        d.text((SAFE_L + 22, 708), tag, font=ft, fill=st.bg_top)
        y = 820

    k_h = ease((t - 0.45) / 0.7)
    for line, lh in story["_head_lines"]:
        d.text((SAFE_L, y + int(70 * (1 - k_h))), line, font=story["_head_font"], fill=mix(st.bg_top, st.text, k_h))
        y += lh

    if story.get("_fact_lines"):
        k_f = ease((t - 1.4) / 0.7)
        y += 40
        bar_top = y
        ff = story["_fact_font"]
        fl = int(ff.size * 1.3)
        for line in story["_fact_lines"]:
            d.text((SAFE_L + 40, y + int(30 * (1 - k_f))), line, font=ff, fill=mix(st.bg_top, st.soft, k_f))
            y += fl
        if k_f > 0:
            d.rectangle([SAFE_L, bar_top + 8, SAFE_L + 8, bar_top + 8 + int((y - bar_top - 14) * k_f)], fill=st.accent)

    d.rectangle([0, H - 12, int(W * min(1, t / STORY)), H], fill=st.accent)
    return img


def frame_outro(st, bg, t, brief):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    k = ease(t / 0.7)
    paste_badge(st, img, 320, W // 2, 520, k)
    centered(d, "Read the full brief at", st.font("medium", 58), 760 + int(50 * (1 - k)), mix(st.bg_top, st.soft, k))
    centered(d, brief["domain"], st.font("title", 96), 850 + int(50 * (1 - k)), mix(st.bg_top, st.text, k))
    k2 = ease((t - 0.6) / 0.7)
    rw = int(200 * k2)
    d.rectangle([W / 2 - rw, 1010, W / 2 + rw, 1016], fill=st.accent)
    centered(d, brief["tagline"], st.font("body", 46), 1060, mix(st.bg_top, st.accent, k2))
    return img


def layout_stories(st, stories):
    """Pre-compute text wrapping so every frame doesn't redo it; drop facts that won't fit."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    width = SAFE_R - SAFE_L
    for s in stories:
        top = 820 if s.get("tag") else 720
        fh, lines = fit_lines(st, probe, s["headline"], "head", 84, 52, width, 5)
        if fh is None:
            fh = st.font("head", 52)
            lines = wrap(probe, s["headline"], fh, width)
        lh = int(fh.size * 1.16)
        s["_head_font"] = fh
        s["_head_lines"] = [(l, lh) for l in lines]
        y_after = top + lh * len(lines)
        s["_fact_lines"] = None
        if s.get("fact"):
            room = SAFE_B - (y_after + 40)
            for size in range(50, 37, -2):
                ff = st.font("body", size)
                fl = wrap(probe, s["fact"], ff, width - 40)
                if len(fl) * int(size * 1.3) <= room:
                    s["_fact_font"], s["_fact_lines"] = ff, fl
                    break
    return stories


def render(site, brief, out_path):
    st = Style(site)
    stories = layout_stories(st, brief["stories"])
    n = len(stories)
    base = background(st)
    scenes = [("intro", INTRO, None)] + [("story", STORY, i) for i in range(n)] + [("outro", OUTRO, None)]
    total = sum(s[1] for s in scenes)

    audio_in, audio_filter = [], []
    if os.path.exists(st.music):
        audio_in = ["-i", st.music]
        audio_filter = ["-map", "1:a", "-af",
                        f"atrim=0:{total},afade=t=in:d=0.3,afade=t=out:st={total - 2.5}:d=2.5",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           *audio_in, "-map", "0:v", *audio_filter,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
           "-t", f"{total}", "-movflags", "+faststart", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    g = 0
    for kind, dur, idx in scenes:
        for fi in range(int(dur * FPS)):
            t = fi / FPS
            bg = with_waves(st, base, g / FPS)
            g += 1
            if kind == "intro":
                img = frame_intro(st, bg, t, brief)
                k = min(1.0, (dur - t) / 0.25)
            elif kind == "story":
                img = frame_story(st, bg, t, idx, stories[idx], n, brief["header_title"])
                k = min(1.0, t / 0.25, (dur - t) / 0.25)
            else:
                img = frame_outro(st, bg, t, brief)
                k = min(1.0, t / 0.25)
            if k < 1:
                img = Image.blend(bg, img, max(0.0, k))
            p.stdin.write(img.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return total
