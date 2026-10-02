# Bloc Party Lyrics — offline app builder

Rebuilds and redeploys the offline home-screen app that mirrors
**blocparty.bearblog.dev** → **https://alx-cia.github.io/blocparty-bear-app/**
(repo `alx-cia/blocparty-bear-app`).

Why a mirror: Bear Blog can't host a service worker (it strips custom JS), so true
offline is impossible on the live domain. This is a self-hosted copy.

## Update the app after editing lyrics

1. Publish your lyric changes to the live Bear site as usual (paste `.txt` into the Bear
   dashboard — see `../bloc_party_lyrics/`).
2. Rebuild + deploy from this folder:

   ```
   python3 build_offline_mirror.py --deploy
   ```

   It crawls the live site, rebuilds the mirror, and pushes to GitHub Pages
   (rebuild takes ~1–2 min).
3. On the iPhone, open the app from the Home Screen **once while online** so the new
   service worker installs and refreshes the cached pages.

Drop `--deploy` to build into `./dist` and review first without publishing.

## What it does
- Crawls every page (home, 12 albums + their `-lyrics` pages, complete list + lyrics,
  `/blog/`, `/welcome/`) — fragment-aware, so `#anchor`-only lyrics pages aren't missed.
- Repoints internal links to the `/blocparty-bear-app/` base path, strips Bear's
  analytics scripts, adds PWA `<head>` tags + `scroll-padding-top` (keeps song titles
  clear of the iOS status-bar/Dynamic-Island blur).
- Writes `manifest.json` and a service worker that precaches all pages. The cache name is
  a hash of the content, so any change refreshes the offline copy automatically.

## Requirements
`python3`, `git`, `gh` (authenticated), `rsync`, ImageMagick (`magick`).

## Change the app icon
Replace `icon-source.png` (any size/ratio; it's fit-and-padded to a transparent square),
then run with `--deploy`.
