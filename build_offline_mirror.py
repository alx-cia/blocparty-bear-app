#!/usr/bin/env python3
"""
Build (and optionally deploy) the offline PWA mirror of blocparty.bearblog.dev.

The live Bear Blog site can't host a service worker (Bear strips custom JS), so the
offline home-screen app is a self-hosted copy at:
    https://alx-cia.github.io/blocparty-bear-app/   (repo: alx-cia/blocparty-bear-app)

This script crawls the live site, rewrites it into a same-origin multi-page mirror
under the GitHub Pages base path, and adds a manifest + service worker that precaches
every page for full offline use.

Usage:
    python3 build_offline_mirror.py            # crawl live -> ./dist  (review, no deploy)
    python3 build_offline_mirror.py --deploy   # ...then push to GitHub Pages

After deploying, open the app from the iPhone Home Screen once while online so the new
service worker installs and refreshes the cached pages.

Requires: python3, git, gh (authenticated), rsync, ImageMagick (`magick`).
Icon source: ./icon-source.png  (swap this file to change the app icon).
"""
import argparse, hashlib, json, os, re, shutil, subprocess, time, urllib.request

LIVE = "https://blocparty.bearblog.dev"
BASE = "/blocparty-bear-app/"
UA   = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))

def fetch(path):
    req = urllib.request.Request(LIVE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# Capture the path even when a link only ever appears as an #anchor
# (each album's lyrics page is only linked as /x-lyrics/#song), else half the site is missed.
HREF = re.compile(r'''href=["']([^"'#]+)(?:#[^"']*)?["']''')

def crawl():
    seen, pages, queue = set(), {}, ["/"]
    def skip(p):
        return (not p.startswith("/")) or p.startswith(("/feed", "/hit", "/static", "//")) or "?" in p
    while queue:
        p = queue.pop(0)
        if p in seen:
            continue
        seen.add(p)
        try:
            html = fetch(p)
        except Exception as e:
            print("  ERR", p, e); continue
        pages[p] = html
        for m in HREF.findall(html):
            u = m[len(LIVE):] if m.startswith(LIVE) else m
            if not skip(u) and u not in seen and u not in queue:
                queue.append(u)
        time.sleep(0.25)
    return pages

A_HREF = re.compile(r'''(<a\b[^>]*?href=)(["'])([^"']+)\2''', re.I)

def build(pages, outdir, icon_src):
    mirrored = set(pages)  # paths like "/", "/silent-alarm/", "/silent-alarm-lyrics/"

    def map_link(url):
        frag, b = "", url
        if "#" in b:
            b, fr = b.split("#", 1); frag = "#" + fr
        if b.startswith(LIVE):
            b = b[len(LIVE):]
        if not b.startswith("/"):
            return None                               # external / relative -> leave
        if b in mirrored:
            return BASE.rstrip("/") + b + frag        # mirrored page -> base path
        if b == "/":
            return BASE + frag                        # home
        if b.startswith("/feed"):
            return LIVE + b + frag                    # feed keeps pointing at the live site
        return None

    def repl(m):
        new = map_link(m.group(3))
        return f'{m.group(1)}{m.group(2)}{new}{m.group(2)}' if new else m.group(0)

    pwa_head = (
        f'<link rel="manifest" href="{BASE}manifest.json">\n'
        f'<link rel="apple-touch-icon" href="{BASE}icon-180.png">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        '<meta name="mobile-web-app-capable" content="yes">\n'
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">\n'
        '<meta name="apple-mobile-web-app-title" content="BP Lyrics">\n'
        '<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">\n'
        '<meta name="theme-color" content="#1d1f21" media="(prefers-color-scheme: dark)">\n'
        # iOS overlays a frosted status-bar/Dynamic-Island region; keep anchored song
        # titles below it so they don't render under the blur.
        '<style>html{scroll-padding-top:60px}</style>\n')
    sw_reg = ('<script>if("serviceWorker" in navigator){addEventListener("load",function(){'
              f'navigator.serviceWorker.register("{BASE}sw.js").catch(function(){{}});}});}}</script>')

    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    for path, html in pages.items():
        html = re.sub(r'<script>.*?</script>', '', html, flags=re.S)  # strip bare Bear scripts; ld+json has a type= attr and survives
        html = A_HREF.sub(repl, html)
        html = html.replace("</head>", pwa_head + "</head>", 1)
        html = html.replace("</body>", sw_reg + "</body>", 1)
        d = outdir if path == "/" else os.path.join(outdir, path.strip("/"))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w").write(html)

    manifest = {"name": "BLOC PARTY. Lyrics", "short_name": "BP Lyrics",
                "start_url": BASE, "scope": BASE, "display": "standalone",
                "background_color": "#ffffff", "theme_color": "#ffffff",
                "icons": [{"src": BASE + "icon-180.png", "sizes": "180x180", "type": "image/png"},
                          {"src": BASE + "icon-512.png", "sizes": "512x512", "type": "image/png",
                           "purpose": "any maskable"}]}
    open(os.path.join(outdir, "manifest.json"), "w").write(json.dumps(manifest, indent=2))

    # Icons: fit then pad to a square canvas (transparent) so any source ratio works without distortion.
    for size, name in [(512, "icon-512.png"), (180, "icon-180.png")]:
        subprocess.run(["magick", icon_src, "-resize", f"{size}x{size}",
                        "-background", "none", "-gravity", "center", "-extent", f"{size}x{size}",
                        os.path.join(outdir, name)], check=True)

    # Service worker. Cache name is derived from page content, so any lyric edit yields a
    # new cache name -> the SW reinstalls and refreshes the offline copy automatically.
    shell = [BASE] + [BASE + p.strip("/") + "/" for p in sorted(mirrored) if p != "/"]
    shell += [BASE + "manifest.json", BASE + "icon-180.png", BASE + "icon-512.png"]
    digest = hashlib.sha256("".join(pages[p] for p in sorted(pages)).encode()).hexdigest()[:8]
    cache = "bp-lyrics-" + digest
    sw = ('const CACHE=%s;\nconst SHELL=%s;\n'
          'self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));});\n'
          'self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==CACHE).map(x=>caches.delete(x)))).then(()=>self.clients.claim()));});\n'
          'async function nav(req){const c=await caches.open(CACHE);try{const f=await Promise.race([fetch(req),new Promise((_,r)=>setTimeout(()=>r(),3000))]);c.put(req,f.clone());return f;}catch(e){return (await c.match(req))||(await c.match(%s))||Response.error();}}\n'
          'self.addEventListener("fetch",e=>{const req=e.request;if(req.method!=="GET")return;\n'
          ' if(req.mode==="navigate"){e.respondWith(nav(req));return;}\n'
          ' e.respondWith((async()=>{const c=await caches.open(CACHE);const hit=await c.match(req);\n'
          '  const net=fetch(req).then(r=>{if(r&&(r.ok||r.type==="opaque"))c.put(req,r.clone());return r;}).catch(()=>null);\n'
          '  return hit||(await net)||Response.error();})());});\n'
          ) % (json.dumps(cache), json.dumps(shell), json.dumps(BASE))
    open(os.path.join(outdir, "sw.js"), "w").write(sw)
    open(os.path.join(outdir, ".nojekyll"), "w").write("")
    return len(pages), cache

# This script lives inside the repo it deploys to (the local clone), so deploy syncs the
# built site into the repo root and pushes from here. The tooling files are excluded from
# the sync so --delete never removes them.
TOOLING = [".git", ".gitignore", "dist", "build_offline_mirror.py", "icon-source.png", "README.md"]

def deploy(outdir, message):
    subprocess.run(["git", "-C", HERE, "pull", "-q", "--ff-only"], check=True)
    subprocess.run(["rsync", "-a", "--delete"] + [f"--exclude=/{t}" for t in TOOLING]
                   + [outdir + "/", HERE + "/"], check=True)
    subprocess.run(["git", "-C", HERE, "add", "-A"], check=True)
    r = subprocess.run(["git", "-C", HERE, "diff", "--cached", "--quiet"])
    if r.returncode == 0:
        print("  nothing changed; not pushing."); return
    subprocess.run(["git", "-C", HERE, "-c", "user.name=alx-cia",
                    "-c", "user.email=agarcia@smartling.com", "commit", "-q", "-m", message], check=True)
    subprocess.run(["git", "-C", HERE, "push", "-q", "origin", "main"], check=True)
    print("  pushed -> https://alx-cia.github.io/blocparty-bear-app/  (rebuild takes ~1-2 min)")

def main():
    ap = argparse.ArgumentParser(description="Build/deploy the Bloc Party offline lyrics PWA mirror.")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"), help="output dir (default ./dist)")
    ap.add_argument("--icon", default=os.path.join(HERE, "icon-source.png"), help="app icon source")
    ap.add_argument("--deploy", action="store_true", help="push the built site to GitHub Pages")
    ap.add_argument("--message", default=("Update Bloc Party lyrics mirror\n\n"
                                          "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"))
    a = ap.parse_args()
    print("Crawling", LIVE, "...")
    pages = crawl()
    print(f"  {len(pages)} pages")
    n, cache = build(pages, a.out, a.icon)
    print(f"Built {n} pages -> {a.out}  (cache {cache})")
    if a.deploy:
        print("Deploying ...")
        deploy(a.out, a.message)
    else:
        print("Review ./dist, then re-run with --deploy to publish.")

if __name__ == "__main__":
    main()
