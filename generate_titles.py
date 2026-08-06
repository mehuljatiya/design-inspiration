#!/usr/bin/env python3
"""
generate_titles.py  -  read each screenshot with Claude and write a real title
+ smart tags into the archive. This is what turns "x.com post" and "Instagram
reel" into "Fluid gooey nav hover" / "Kinetic type reel, teal on black".

It looks at thumbs/*.jpg (so run generate_thumbs.py first), sends each image to
the Anthropic API, and patches the DATA inside the HTML in place. Resumable:
results are cached in enrich.json, so reruns are cheap. A .bak of the HTML is
written before the first change.

SETUP
  export ANTHROPIC_API_KEY=sk-ant-...        (Windows: setx ANTHROPIC_API_KEY ...)
  # no pip installs needed - uses the standard library

RUN
  python generate_titles.py                  # enrich every link that has a screenshot
  python generate_titles.py --limit 20       # test batch first (recommended)
  python generate_titles.py --only x.com     # one domain
  python generate_titles.py --weak-only       # only fix generic titles, skip good ones

  --model NAME   API model (default claude-sonnet-5; use claude-haiku-4-5-20251001 to cut cost)
  --force        re-enrich even if already cached
"""
import argparse, base64, json, os, re, sys, time, urllib.request
from pathlib import Path

VOCAB = ("site landing article video reel thread tool plugin template font repo "
         "motion interaction ui ux product branding typography color icon illustration 3d "
         "design-system ai data-viz fintech payments dashboard checkout onboarding "
         "portfolio studio mobile web case-study experimental reference").split()

GENERIC = re.compile(r"^(x\.com post|twitter post|instagram (post|reel)|linkedin post|"
                     r"youtube video|a post|post by|.*\bpost\b)$", re.I)

def load_items(html):
    m=re.search(r"/\*DS\*/(\[.*?\])/\*DE\*/", html, re.S) or re.search(r"const DATA = (\[.*?\]);", html, re.S)
    if not m: sys.exit("Could not find DATA in the HTML.")
    return json.loads(m.group(1)), m.span(1)

def is_weak(it):
    t=it["t"].strip()
    return bool(GENERIC.match(t)) or len(t)<4 or "review" in it["g"]

def call_api(model, key, img_bytes, dom, note):
    b64=base64.b64encode(img_bytes).decode()
    prompt=(f"This is a screenshot of a design-inspiration link (domain: {dom}). "
            f"{'Author note: '+note if note else ''}\n"
            "Label it for a searchable design library. Return ONLY minified JSON: "
            '{"title": "...", "tags": ["...", "..."]}. '
            "title = 3 to 7 words describing the DESIGN shown (the effect, layout, or subject), "
            "not the author or platform. Good: 'Gooey magnetic nav hover', 'Stripe-style pricing page', "
            "'Isometric 3D product scene'. "
            f"tags = 2 to 5 lowercase tags, chosen mostly from: {', '.join(VOCAB)}. "
            "You may add one precise tag if clearly warranted. No prose, JSON only.")
    body=json.dumps({"model":model,"max_tokens":200,"messages":[{"role":"user","content":[
        {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
        {"type":"text","text":prompt}]}]}).encode()
    req=urllib.request.Request("https://api.anthropic.com/v1/messages",data=body,
        headers={"content-type":"application/json","x-api-key":key,"anthropic-version":"2023-06-01"})
    with urllib.request.urlopen(req,timeout=60) as r:
        data=json.loads(r.read())
    text="".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text")
    text=text.strip().replace("```json","").replace("```","").strip()
    obj=json.loads(text)
    tags=[str(t).strip().lower() for t in obj.get("tags",[]) if str(t).strip()]
    return str(obj["title"]).strip(), tags[:5]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--html",default="designspiration-archive.html")
    ap.add_argument("--thumbs",default="thumbs")
    ap.add_argument("--model",default="claude-sonnet-5")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--only",default="")
    ap.add_argument("--weak-only",action="store_true")
    ap.add_argument("--force",action="store_true")
    a=ap.parse_args()

    key=os.environ.get("ANTHROPIC_API_KEY")
    if not key: sys.exit("Set ANTHROPIC_API_KEY first:  export ANTHROPIC_API_KEY=sk-ant-...")

    html_path=Path(a.html).resolve()
    thumbs=html_path.parent/a.thumbs
    cache_path=html_path.parent/"enrich.json"
    cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}

    html=html_path.read_text(encoding="utf-8")
    items,(s,e)=load_items(html)

    from urllib.parse import urlparse
    dom=lambda u:(urlparse(u).hostname or "").replace("www.","")

    # decide what to enrich
    work=[]
    for it in items:
        img=thumbs/it["thumb"]
        if not img.exists(): continue                       # need a screenshot
        if a.only and a.only not in it["u"]: continue
        if a.weak_only and not is_weak(it): continue
        if not a.force and it["thumb"] in cache: continue
        work.append(it)
    if a.limit: work=work[:a.limit]

    print(f"{len(items)} links · {len(work)} to enrich with {a.model}")
    if not work: 
        if cache: apply_and_write(items,cache,html,html_path,s,e)
        print("Nothing new to enrich."); return

    if not (html_path.parent/(html_path.name+".bak")).exists():
        (html_path.parent/(html_path.name+".bak")).write_text(html,encoding="utf-8")

    done=err=0
    for i,it in enumerate(work,1):
        try:
            title,tags=call_api(a.model,key,(thumbs/it["thumb"]).read_bytes(),dom(it["u"]),it.get("n",""))
            cache[it["thumb"]]={"t":title,"g":tags}
            done+=1; print(f"[{i}/{len(work)}] {it['thumb']}  {title}")
            if i%10==0: cache_path.write_text(json.dumps(cache,ensure_ascii=False))
        except Exception as ex:
            err+=1; print(f"[{i}/{len(work)}] ERR {it['thumb']}  {type(ex).__name__}: {str(ex)[:80]}")
            time.sleep(1.5)
    cache_path.write_text(json.dumps(cache,ensure_ascii=False))
    apply_and_write(items,cache,html,html_path,s,e)
    print(f"\nEnriched {done} · errored {err}. Titles + tags written into {html_path.name}")
    print("Reopen the archive. (.bak holds the pre-enrichment version.)")

def apply_and_write(items,cache,html,html_path,s,e):
    for it in items:
        c=cache.get(it["thumb"])
        if not c: continue
        it["t"]=c["t"]
        merged=[t for t in it["g"] if t!="review"]          # uncertainty resolved
        for t in c["g"]:
            if t not in merged: merged.append(t)
        it["g"]=merged
    new=html[:s]+json.dumps(items,ensure_ascii=False)+html[e:]
    html_path.write_text(new,encoding="utf-8")

if __name__=="__main__": main()
