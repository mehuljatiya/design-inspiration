#!/usr/bin/env python3
"""
fetch_media.py  -  pull the real image/video behind each Design Vault link.

The archive's thumbnails are page screenshots: for a tweet or a LinkedIn post that
means you see the platform's chrome, not the design. This fetches the actual media
each post carries, so a card shows the work instead of a screenshot of Twitter.

Strategies, picked per link:
  x        X/Twitter via the public syndication endpoint (no login) -> photo, or
           video (best mp4 under --max-video-mb) plus its poster frame
  youtube  official thumbnail endpoint (maxres, falling back to hq)
  og       the og:image the page publishes for sharing (Behance, Dribbble, Medium, Figma)
  shot     our own full-page screenshot via Playwright, for ordinary websites
  social   Instagram / LinkedIn, needs the saved browser session from
           `python3 generate_thumbs.py --login`

Everything lands in media/ with a manifest.json. Resumable: already-fetched files
are skipped, so re-running only picks up what is missing.

  python3 fetch_media.py --only x                 # one bucket at a time
  python3 fetch_media.py --only youtube,og
  python3 fetch_media.py --only shot --limit 20
  python3 fetch_media.py --report                 # what is staged so far
"""
import argparse, json, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
ROOT = Path(__file__).parent
MEDIA = ROOT / "media"
MANIFEST = MEDIA / "manifest.json"

_lock = threading.Lock()
manifest = {}


# ---------------------------------------------------------------- data loading
def load_items(html_path):
    """Pull the DATA array out of the archive HTML (same parser as generate_thumbs)."""
    html = html_path.read_text(encoding="utf-8")
    i = html.find("const DATA")
    if i == -1:
        sys.exit(f"'{html_path.name}' has no DATA array.")
    start = html.find("[", i)
    depth = 0; instr = False; esc = False; q = ""
    for j in range(start, len(html)):
        ch = html[j]
        if instr:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == q: instr = False
        elif ch in "\"'":
            instr = True; q = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:j + 1])
    sys.exit("Found DATA but could not parse it.")


def host(u):
    try: return (urlparse(u).hostname or "").replace("www.", "")
    except Exception: return ""


def strategy(u):
    h = host(u)
    if h.endswith(("x.com", "twitter.com")):        return "x"
    if h.endswith(("youtube.com", "youtu.be")):     return "youtube"
    if h.endswith(("instagram.com", "linkedin.com")): return "social"
    if h.endswith(("behance.net", "dribbble.com", "medium.com", "figma.com")): return "og"
    return "shot"


# ------------------------------------------------------------------- fetching
def get(url, timeout=25, referer=None):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if referer: hdrs["Referer"] = referer
    with urlopen(Request(url, headers=hdrs), timeout=timeout) as r:
        return r.read()


def save(stem, ext, blob):
    MEDIA.mkdir(exist_ok=True)
    p = MEDIA / f"{stem}.{ext}"
    p.write_bytes(blob)
    return p


def record(item, **kw):
    with _lock:
        manifest[item["u"]] = kw
        MANIFEST.write_text(json.dumps(manifest, indent=1))


def already(item):
    m = manifest.get(item["u"])
    return bool(m and m.get("file") and (MEDIA / m["file"]).exists())


# --- X / Twitter ------------------------------------------------------------
def fetch_x(item, stem, args):
    m = re.search(r"status/(\d+)", item["u"])
    if not m: return "no tweet id"
    tid = m.group(1)
    api = (f"https://cdn.syndication.twimg.com/tweet-result?id={tid}"
           f"&token=a&lang=en")
    try:
        j = json.loads(get(api))
    except HTTPError as e:
        return f"syndication {e.code}"      # 404 = deleted / protected account
    except Exception as e:
        return f"syndication {type(e).__name__}"

    media = j.get("mediaDetails") or []
    if not media:
        # text-only post: keep the existing page screenshot, nothing better exists
        return "no media in post"

    md = media[0]
    if md.get("type") == "photo":
        url = md["media_url_https"] + "?format=jpg&name=large"
        blob = get(url, referer="https://x.com/")
        p = save(stem, "jpg", blob)
        record(item, file=p.name, kind="image", source="x-photo", bytes=len(blob),
               origin=md["media_url_https"])
        return None

    # video / animated gif: grab the poster, plus the best mp4 within budget
    poster = md.get("media_url_https")
    if poster:
        blob = get(poster, referer="https://x.com/")
        save(stem, "jpg", blob)
    variants = [v for v in md.get("video_info", {}).get("variants", [])
                if v.get("content_type") == "video/mp4" and v.get("bitrate")]
    vfile = vbytes = None
    if variants and not args.no_video:
        # prefer the largest variant that stays under the per-file budget
        for v in sorted(variants, key=lambda v: -v["bitrate"]):
            dur = (md.get("video_info", {}).get("duration_millis") or 0) / 1000
            est = v["bitrate"] / 8 * max(dur, 1)
            if est <= args.max_video_mb * 1024 * 1024:
                try:
                    vb = get(v["url"], timeout=90, referer="https://x.com/")
                except Exception:
                    continue
                if len(vb) <= args.max_video_mb * 1024 * 1024:
                    vfile = save(stem, "mp4", vb).name
                    vbytes = len(vb)
                break
    record(item, file=f"{stem}.jpg", kind="video", source="x-video",
           bytes=len(blob) if poster else 0, video=vfile, video_bytes=vbytes,
           origin=poster)
    return None


# --- YouTube ----------------------------------------------------------------
def fetch_youtube(item, stem, args):
    u = item["u"]
    vid = None
    m = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{6,})", u)
    if m: vid = m.group(1)
    if not vid: return "no video id"
    for name in ("maxresdefault", "hqdefault"):
        try:
            blob = get(f"https://img.youtube.com/vi/{vid}/{name}.jpg")
        except Exception:
            continue
        if len(blob) > 2000:                      # the 120x90 grey placeholder
            p = save(stem, "jpg", blob)
            record(item, file=p.name, kind="video", source=f"youtube-{name}",
                   bytes=len(blob), origin=f"https://youtu.be/{vid}")
            return None
    return "no thumbnail"


# --- og:image ---------------------------------------------------------------
OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::src)?["\'][^>]+content=["\']([^"\']+)',
    re.I)
OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)',
    re.I)

def fetch_og(item, stem, args):
    try:
        html = get(item["u"], timeout=30).decode("utf-8", "ignore")
    except Exception as e:
        return f"page {type(e).__name__}"
    m = OG_RE.search(html) or OG_RE2.search(html)
    if not m: return "no og:image"
    url = m.group(1)
    if url.startswith("//"): url = "https:" + url
    try:
        blob = get(url, timeout=30, referer=item["u"])
    except Exception as e:
        return f"image {type(e).__name__}"
    if len(blob) < 2000: return "og:image too small"
    ext = "png" if blob[:4] == b"\x89PNG" else ("webp" if blob[8:12] == b"WEBP" else "jpg")
    p = save(stem, ext, blob)
    record(item, file=p.name, kind="image", source="og", bytes=len(blob), origin=url)
    return None


# --- Playwright: websites, then Instagram / LinkedIn ------------------------
# Instagram dropped <article> on post pages and both platforms stream video from
# blob: URLs, so: take the largest real <img>, the <video>'s poster, or the
# og:image the post publishes — whichever exists, in that order of quality.
# Picking the *biggest* image is wrong: an account with no profile photo serves a
# blank 1290x1290 avatar that dwarfs the actual post. Score by CDN path instead —
# each platform puts post media on a distinct bucket.
FIND_MEDIA = """() => {
  const score = u => {
    if (!u || u.startsWith('blob:') || u.startsWith('data:')) return -1;
    if (/fbcdn\\.net\\/v\\/t1\\.|\\/t1\\.30497/.test(u)) return -1;   // IG profile pictures
    if (/static\\.(cdninstagram|licdn)\\.com|rsrc\\.php|\\/sprite/.test(u)) return -1;
    if (/\\/t51\\./.test(u)) return 3;                                // IG post media
    if (/media\\.licdn\\.com\\/dms\\/image/.test(u)) return 3;        // LinkedIn post media
    if (/snap\\.licdn\\.com\\/klipy/.test(u)) return 1;               // LinkedIn GIF preview
    return 0;
  };
  const best = [...document.querySelectorAll('img')]
    .map(i => ({ u: i.currentSrc || i.src, a: i.naturalWidth * i.naturalHeight,
                 s: score(i.currentSrc || i.src) }))
    .filter(c => c.s > 0 && c.a >= 90000)
    .sort((x, y) => (y.s - x.s) || (y.a - x.a))[0];
  const vid = document.querySelector('video');
  const og = document.querySelector('meta[property="og:image"]');
  const real = u => u && !u.startsWith('blob:') ? u : null;
  return {
    hasVideo: !!vid,
    poster:   vid ? real(vid.poster) : null,
    videoSrc: vid ? real(vid.currentSrc) : null,
    img:      best ? best.u : null,
    imgArea:  best ? best.a : 0,
    og:       og && score(og.content) >= 0 ? og.content : null
  };
}"""


def social_media(page, item, stem, args):
    """Instagram / LinkedIn: download the post's own media, else crop the post."""
    try:
        f = page.evaluate(FIND_MEDIA)
    except Exception as e:
        f = None
    if not f:
        return None, "page gave nothing"

    # og:image is the post's own canonical preview, so it leads for stills; for
    # video the player's poster is sharper, with og:image covering reels (which
    # stream from blob: and expose no poster)
    order = ([f["poster"], f["og"], f["img"]] if f["hasVideo"]
             else [f["og"], f["img"]])
    kind = "social-video" if f["hasVideo"] else "social-image"

    for target in [u for u in order if u]:
        try:
            # the browser context's request API carries the session cookies and
            # is not subject to the page's CORS rules, unlike fetch() in-page
            resp = page.request.get(target, timeout=45000)
            if not resp.ok:
                continue
            raw = resp.body()
        except Exception:
            continue
        if len(raw) > 5000:
            social_media.last_url = target
            if f.get("videoSrc") and not args.no_video:
                try:
                    v = page.request.get(f["videoSrc"], timeout=90000)
                    if v.ok and len(v.body()) <= args.max_video_mb * 1024 * 1024:
                        save(stem, "mp4", v.body())
                except Exception:
                    pass
            return raw, kind

    # carousel or an unreachable CDN: crop the post itself, still far better than
    # a screenshot of the whole feed page
    for sel in ('article', 'div.feed-shared-update-v2', 'main'):
        node = page.query_selector(sel)
        if node:
            try:
                return node.screenshot(type="jpeg", quality=88), "social-crop"
            except Exception:
                pass
    return None, "no media or post node"


def run_playwright(jobs, args, logged_in):
    """jobs: list of (item, stem). Reuses one browser for the whole batch."""
    from playwright.sync_api import sync_playwright
    session = ROOT / ".dsp_session"
    if logged_in and not session.exists():
        print("  ! no saved session - run: python3 generate_thumbs.py --login")
        return
    ok = fail = 0
    with sync_playwright() as p:
        if logged_in:
            # ignore_https_errors: this machine sits behind TLS interception (a
            # self-signed CA in the chain). Chrome trusts it via the system store,
            # but Playwright's request API validates against its own bundled CAs
            # and would reject every CDN fetch.
            ctx = p.chromium.launch_persistent_context(
                str(session), headless=False, viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
                args=["--disable-blink-features=AutomationControlled"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        else:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 860},
                                      device_scale_factor=2, user_agent=UA)
            page = ctx.new_page()
        for item, stem in jobs:
            try:
                page.goto(item["u"], wait_until="domcontentloaded", timeout=35000)
                page.wait_for_timeout(int(args.delay * 1000))
                if logged_in:
                    blob, how = social_media(page, item, stem, args)
                    if blob is None:
                        fail += 1
                        print(f"  × {stem} {host(item['u'])} - {how}")
                        continue
                else:
                    blob = page.screenshot(type="jpeg", quality=84)
                    how = "screenshot"
                p_ = save(stem, "jpg", blob)
                record(item, file=p_.name,
                       kind="video" if how == "social-video" else "image",
                       source=how, bytes=len(blob), post=item["u"],
                       origin=getattr(social_media, "last_url", None) if logged_in else item["u"])
                if logged_in: social_media.last_url = None
                ok += 1
                print(f"  ✓ {stem} {host(item['u'])} [{how}]")
            except Exception as e:
                fail += 1
                print(f"  × {stem} {host(item['u'])} - {type(e).__name__}")
        ctx.close()
    print(f"  {ok} captured, {fail} failed")


# ------------------------------------------------------------------- driver
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="index.html")
    ap.add_argument("--only", default="x,youtube,og",
                    help="comma list: x,youtube,og,shot,social")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=3.0, help="settle time for screenshots")
    ap.add_argument("--max-video-mb", type=float, default=12)
    ap.add_argument("--no-video", action="store_true", help="posters only, skip mp4s")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--rebuild", action="store_true",
                    help="reconstruct manifest.json from the files on disk "
                         "(filenames are the link index, so this is lossless "
                         "and repairs a manifest clobbered by parallel runs)")
    args = ap.parse_args()

    global manifest
    MEDIA.mkdir(exist_ok=True)
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())

    items = load_items(ROOT / args.html)
    for i, d in enumerate(items, 1):
        d["_stem"] = f"{i:04d}"

    if args.rebuild:
        by_stem = {d["_stem"]: d for d in items}
        rebuilt = {}
        for f in sorted(MEDIA.iterdir()):
            if f.suffix not in (".jpg", ".png", ".webp", ".mp4"): continue
            d = by_stem.get(f.stem)
            if not d: continue
            e = rebuilt.setdefault(d["u"], {})
            if f.suffix == ".mp4":
                e["video"] = f.name; e["video_bytes"] = f.stat().st_size
                e["kind"] = "video"
            else:
                e["file"] = f.name; e["bytes"] = f.stat().st_size
                e.setdefault("kind", "image")
            # keep whatever the live manifest already knew about this link
            old = manifest.get(d["u"], {})
            for k in ("source", "origin"):
                if old.get(k): e.setdefault(k, old[k])
            e.setdefault("source", strategy(d["u"]))
        MANIFEST.write_text(json.dumps(rebuilt, indent=1))
        print(f"manifest rebuilt from disk: {len(rebuilt)} links")
        return

    if args.report:
        by = {}
        total = vtotal = 0
        for u, m in manifest.items():
            by[m.get("source", "?")] = by.get(m.get("source", "?"), 0) + 1
            total += m.get("bytes") or 0
            vtotal += m.get("video_bytes") or 0
        print(f"{len(manifest)} of {len(items)} links have media staged")
        for k, v in sorted(by.items(), key=lambda x: -x[1]):
            print(f"  {k:16}{v:>5}")
        print(f"  images {total/1e6:.1f} MB · video {vtotal/1e6:.1f} MB "
              f"· total {(total+vtotal)/1e6:.1f} MB")
        return

    want = set(args.only.split(","))
    if "rest" in want:
        # sweep: anything still without media that a plain screenshot can cover
        # (websites, plus og:image failures like Figma event pages)
        want.discard("rest")
        todo = [d for d in items
                if not already(d) and strategy(d["u"]) in want | {"shot", "og"}]
        for d in todo:
            d["_force_shot"] = True
    else:
        todo = [d for d in items if strategy(d["u"]) in want and not already(d)]
    if args.limit: todo = todo[:args.limit]
    print(f"{len(todo)} links to fetch  ({args.only})")

    net = {"x": fetch_x, "youtube": fetch_youtube, "og": fetch_og}
    jobs_shot, jobs_social, failures = [], [], []

    def work(d):
        s = "shot" if d.get("_force_shot") else strategy(d["u"])
        if s in net:
            try:
                err = net[s](d, d["_stem"], args)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            if err: failures.append((d["_stem"], host(d["u"]), err))
            else:   print(f"  ✓ {d['_stem']} {host(d['u'])}")
            time.sleep(0.25)

    def bucket(d):
        return "shot" if d.get("_force_shot") else strategy(d["u"])

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, [d for d in todo if bucket(d) in net]))

    jobs_shot   = [(d, d["_stem"]) for d in todo if bucket(d) == "shot"]
    jobs_social = [(d, d["_stem"]) for d in todo if bucket(d) == "social"]
    if jobs_shot:
        print(f"\nscreenshotting {len(jobs_shot)} websites…")
        run_playwright(jobs_shot, args, logged_in=False)
    if jobs_social:
        print(f"\ncapturing {len(jobs_social)} social posts (logged in)…")
        run_playwright(jobs_social, args, logged_in=True)

    if failures:
        print(f"\n{len(failures)} could not be fetched:")
        for stem, h, err in failures[:40]:
            print(f"  {stem} {h:22} {err}")
    print(f"\nstaged: {len(manifest)} links  →  media/  (run --report for totals)")


if __name__ == "__main__":
    main()
