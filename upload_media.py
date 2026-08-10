#!/usr/bin/env python3
"""
upload_media.py  -  push the fetched post images into Supabase Storage and
                    wire them into index.html.

Images and video poster frames go to the public `link-media` bucket; the .mp4s
staged by fetch_media.py stay local by design (they are ~90% of the bytes and
would eat the free tier's egress). A card with video shows its poster and the
play badge, and opening it goes to the original post.

Before running:
  1. run supabase/link_media_schema.sql once in the SQL editor
  2. put the service_role key in .env.local (gitignored):
        SUPABASE_SERVICE_KEY=eyJ...
     It bypasses RLS - never commit it, never put it in the HTML.

  python3 upload_media.py --dry-run     # what would go up, and how big
  python3 upload_media.py               # upload, then patch index.html
  python3 upload_media.py --wire-only   # just patch the HTML from the manifest
"""
import argparse, json, mimetypes, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).parent
MEDIA = ROOT / "media"
MANIFEST = MEDIA / "manifest.json"
PROJECT = "https://ezepjkidinqebmlnstdp.supabase.co"
BUCKET = "link-media"
MAX_PX = 1400          # posters are never displayed larger than a card or the overlay
QUALITY = 82

_lock = threading.Lock()


def service_key():
    env = ROOT / ".env.local"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("SUPABASE_SERVICE_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    k = os.environ.get("SUPABASE_SERVICE_KEY")
    if k: return k
    sys.exit("No service key. Put SUPABASE_SERVICE_KEY=... in .env.local "
             "(Dashboard → Project Settings → API → service_role).")


def shrink(path):
    """Re-encode to a web-sized JPEG. Returns (bytes, content_type)."""
    from PIL import Image
    im = Image.open(path)
    if im.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", im.size, (18, 18, 20))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if max(im.size) > MAX_PX:
        im.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
    import io
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue(), "image/jpeg"


def upload(name, blob, ctype, key):
    url = f"{PROJECT}/storage/v1/object/{BUCKET}/{name}"
    req = Request(url, data=blob, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": ctype,
        "x-upsert": "true",
    })
    with urlopen(req, timeout=60) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wire-only", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--html", default="index.html")
    args = ap.parse_args()

    if not MANIFEST.exists():
        sys.exit("No media/manifest.json - run fetch_media.py first.")
    manifest = json.loads(MANIFEST.read_text())
    entries = {u: m for u, m in manifest.items() if m.get("file")}

    if not args.wire_only:
        total = 0
        plan = []
        for u, m in entries.items():
            p = MEDIA / m["file"]
            if not p.exists(): continue
            plan.append((u, m, p))
            total += p.stat().st_size
        print(f"{len(plan)} images to upload · {total/1e6:.1f} MB on disk "
              f"(re-encoded to ≤{MAX_PX}px, expect roughly half that)")
        vid = sum(m.get("video_bytes") or 0 for m in manifest.values())
        if vid:
            print(f"{sum(1 for m in manifest.values() if m.get('video'))} videos "
                  f"({vid/1e6:.1f} MB) stay local — not uploaded")
        if args.dry_run:
            return

        key = service_key()
        done = {"n": 0, "bytes": 0}
        fails = []

        def work(job):
            u, m, p = job
            name = Path(m["file"]).stem + ".jpg"
            try:
                blob, ctype = shrink(p)
                upload(name, blob, ctype, key)
            except HTTPError as e:
                fails.append((name, f"HTTP {e.code} {e.read()[:120].decode('utf8','ignore')}"))
                return
            except Exception as e:
                fails.append((name, f"{type(e).__name__}: {e}"))
                return
            with _lock:
                m["remote"] = name
                done["n"] += 1
                done["bytes"] += len(blob)
                if done["n"] % 25 == 0:
                    print(f"  {done['n']}/{len(plan)} · {done['bytes']/1e6:.1f} MB")

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(work, plan))

        MANIFEST.write_text(json.dumps(manifest, indent=1))
        print(f"uploaded {done['n']} · {done['bytes']/1e6:.1f} MB in the bucket")
        if fails:
            print(f"{len(fails)} failed:")
            for n, e in fails[:15]: print(f"  {n}  {e}")

    # ---- wire the results into the page ---------------------------------
    html_path = ROOT / args.html
    html = html_path.read_text(encoding="utf-8")
    m = re.search(r"/\*DS\*/(\[.*?\])/\*DE\*/", html, re.S)
    if not m: sys.exit("Could not find the DATA literal in the HTML.")
    data = json.loads(m.group(1))

    n = 0
    for d in data:
        e = manifest.get(d["u"])
        remote = e.get("remote") if e else None
        if remote:
            d["m"] = remote            # media file in the bucket
            n += 1
        else:
            d.pop("m", None)
    safe = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html[:m.start(1)] + safe + html[m.end(1):]
    html_path.write_text(html, encoding="utf-8")
    print(f"index.html: {n} of {len(data)} links now point at bucket media")


if __name__ == "__main__":
    main()
