#!/usr/bin/env python3
"""
generate_thumbs.py  -  capture clear screenshots for the Designspiration archive.

GUARANTEE: social links (x.com, instagram.com, linkedin.com) are only captured
after a verified login. At startup the script probes each social domain; if you
are not logged in, EVERY link on that domain is skipped (never captured as a
login screen). Non-login sites capture normally.

SETUP (once)
  python -m pip install playwright
  playwright install chromium

STEP 1 - LOG IN  (opens a browser and WAITS for you to press Enter)
  python generate_thumbs.py --login

STEP 2 - CAPTURE  (resumable; skips anything already saved)
  python generate_thumbs.py

  Redo shots taken before you logged in:
    python generate_thumbs.py --only x.com,instagram.com,linkedin.com --force

  Options:
    --html PATH   archive file (default: designspiration-archive.html)
    --only D[,D]  restrict to domain(s)
    --limit N     first N only (test batch)
    --force       redo matching links even if a thumb exists
    --headed      show the browser during capture
    --width N     capture width in px (default 1366, taller = 16:10)
    --scale N     device pixel ratio (default 1; use 2 for retina-crisp, 4x size)
"""
import argparse, json, re, sys
from pathlib import Path

LOGIN_MARKERS = ("/login","/i/flow/login","/i/flow/signup","accounts/login",
                 "authwall","/signup","/uas/login","checkpoint","/challenge")
LOGIN_SITES = ["https://x.com/login","https://www.instagram.com/accounts/login/",
               "https://www.linkedin.com/login"]
SOCIAL = ("x.com","twitter.com","instagram.com","linkedin.com")

# per-domain login probe: (url to visit, selector that only exists when logged IN)
AUTH_PROBE = {
  "x.com":        ("https://x.com/home",            '[data-testid="SideNav_AccountSwitcher_Button"], [aria-label="Profile"]'),
  "twitter.com":  ("https://x.com/home",            '[data-testid="SideNav_AccountSwitcher_Button"], [aria-label="Profile"]'),
  "instagram.com":("https://www.instagram.com/",    'svg[aria-label="Home"], a[href="/explore/"]'),
  "linkedin.com": ("https://www.linkedin.com/feed/",'input[placeholder="Search"], .global-nav__me'),
}

def load_items(html_path):
    html = html_path.read_text(encoding="utf-8")
    i = html.find("const DATA")
    if i == -1:
        sys.exit(f"'{html_path.name}' has no DATA array - is this the archive HTML I built? "
                 "Pass the right file with --html.")
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
                return json.loads(html[start:j+1])
    sys.exit("Found DATA but could not parse it - the file may be truncated.")

def dom(u):
    from urllib.parse import urlparse
    try: return (urlparse(u).hostname or "").replace("www.","")
    except: return ""

def on_wall(url): 
    u=url.lower(); return any(mk in u for mk in LOGIN_MARKERS)

def do_login(session_dir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(session_dir), headless=False,
              viewport={"width":1200,"height":820}, args=["--disable-blink-features=AutomationControlled"])
        for i,site in enumerate(LOGIN_SITES):
            page = ctx.pages[0] if i==0 else ctx.new_page()
            try: page.goto(site, wait_until="domcontentloaded", timeout=25000)
            except: pass
        print("\n"+"="*64)
        print("Browser open. Log into X, Instagram, and LinkedIn in its tabs.")
        print("Then return here and press Enter to save the session.")
        print("="*64)
        input("\nPress Enter once logged into all three... ")
        ctx.close()
    print("Session saved. Now run:  python generate_thumbs.py")

def check_login(page, d):
    """Return True only if clearly logged in for domain d."""
    key = next((k for k in AUTH_PROBE if k in d), None)
    if not key: return True          # non-social: no login needed
    url, sel = AUTH_PROBE[key]
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        if on_wall(page.url): return False
        return page.query_selector(sel) is not None
    except Exception:
        return False

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--html",default="designspiration-archive.html")
    ap.add_argument("--out",default="thumbs")
    ap.add_argument("--login",action="store_true")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--headed",action="store_true")
    ap.add_argument("--only",default="")
    ap.add_argument("--force",action="store_true")
    ap.add_argument("--width",type=int,default=1366)
    ap.add_argument("--scale",type=float,default=1.0)
    ap.add_argument("--delay",type=float,default=6.0,help="seconds to wait after load before capture")
    a=ap.parse_args()

    html_path=Path(a.html).resolve()
    session_dir=html_path.parent/".dsp_session"
    if a.login: do_login(session_dir); return

    out_dir=html_path.parent/a.out; out_dir.mkdir(exist_ok=True)
    items=load_items(html_path)
    if a.only:
        wants=[s.strip() for s in a.only.split(",") if s.strip()]
        items=[d for d in items if any(w in d["u"] for w in wants)]

    if a.force:
        todo=items
        for d in todo:
            f=out_dir/d["thumb"]
            if f.exists(): f.unlink()
    else:
        todo=[d for d in items if not (out_dir/d["thumb"]).exists()]
    if a.limit: todo=todo[:a.limit]

    print(f"{len(items)} links in scope · {len(todo)} to capture · width={a.width} scale={a.scale} delay={a.delay}s")
    if not todo: print("Nothing to do."); return
    if not session_dir.exists():
        print("\nNo saved session. Run 'python generate_thumbs.py --login' first,\nor all social links will be skipped.\n")

    from playwright.sync_api import sync_playwright
    ok=wall=fail=skip=0
    h=int(a.width*0.625)
    with sync_playwright() as p:
        ctx=p.chromium.launch_persistent_context(str(session_dir),headless=not a.headed,
            viewport={"width":a.width,"height":h}, device_scale_factor=a.scale,
            args=["--disable-blink-features=AutomationControlled"])
        page=ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_navigation_timeout(25000)

        # ---- login gate: probe each social domain in scope, once ----
        scope_social=sorted({dom(d["u"]) for d in todo if any(s in dom(d["u"]) for s in SOCIAL)})
        blocked=set()
        for d in scope_social:
            logged=check_login(page,d)
            print(f"login check · {d:15} -> {'OK' if logged else 'NOT LOGGED IN (will skip)'}")
            if not logged: blocked.add(d)
        if blocked:
            print("\nSkipping "+", ".join(blocked)+" because you are not logged in there.")
            print("Fix: python generate_thumbs.py --login   (then rerun)\n")

        for i,d in enumerate(todo,1):
            if dom(d["u"]) in blocked:
                skip+=1; continue
            dest=out_dir/d["thumb"]
            try:
                try:
                    page.goto(d["u"],wait_until="load")      # wait for full load, not just DOM
                except Exception:
                    page.goto(d["u"],wait_until="domcontentloaded")
                page.wait_for_timeout(int(a.delay*1000))     # let embeds / video / fonts settle
                if on_wall(page.url):
                    wall+=1; print(f"[{i}/{len(todo)}] wall {d['thumb']}  {d['u'][:60]}"); continue
                page.screenshot(path=str(dest),type="jpeg",quality=82)
                ok+=1; print(f"[{i}/{len(todo)}] ok   {d['thumb']}  {d['u'][:64]}")
            except Exception as e:
                fail+=1; print(f"[{i}/{len(todo)}] fail {d['thumb']}  {type(e).__name__}  {d['u'][:52]}")
        ctx.close()

    print(f"\nDone. captured {ok} · skipped (not logged in) {skip} · login wall {wall} · errored {fail}.")
    print("Reopen the archive to see captured cards. Re-run anytime to retry misses.")

if __name__=="__main__": main()
