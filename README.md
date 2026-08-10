# Design Vault

Inspiration for designers — UX, UI, motion, branding and graphics — in one dark, image-first
browser. Built from 641 references curated in the Cashfree `#designspiration` Slack channel
(Nov 2024 – Jul 2026), with screenshots, full-text search, category / tag / source filtering,
and an in-page edit mode.

## Use it

Open `index.html` in a browser, or host the folder (Vercel / Netlify / GitHub Pages).
Keep `index.html` and `thumbs/` together — thumbnails load by relative path.

- **Tabs** — *Latest*, *Categories* (grouped sections), *Sources* (X, Instagram, LinkedIn,
  websites…), *Needs review*.
- **Search** across titles, notes, tags and domains. `/` or `⌘K` focuses it.
- **Filter panel** (`F`, or the Filter button) — sort, category, tag, source. Active filters
  appear as removable chips; *Reset all* clears them.
- **Detail view** — click any card for the full screenshot, tags and source. `←`/`→` steps
  through results, `Esc` closes.
- **Edit mode**: fix titles/tags inline. Requires the shared team passcode (once per browser
  session). Edits sync to Supabase — everyone sees the same titles/tags, no matter who edited
  or which browser they're on. A local cache in `localStorage` is kept as an offline fallback.
  "Download backup" exports a portable copy of the whole page with the current data baked in.
- **Mine** (`personal.html`) — a personal vault: drop in your own screens and videos, keep it
  private or share a read-only link.

## Interface

Dark canvas (`#0A0A0B`), Inter for UI with JetBrains Mono for micro-labels, and cards that
present each screenshot as a floating panel with its title below. Cards render progressively
(48 at a time) so 641 items stay fast, and images lazy-load with a fade. Tokens live in the
`:root` block at the top of each file — both pages share the same set.

## Regenerate / extend

- `generate_thumbs.py` — capture screenshots into `thumbs/`. Logs into X/Instagram/
  LinkedIn once (`--login`), then captures (resumable, skips saved). Requires
  `pip install playwright && playwright install chromium`.
- `generate_titles.py` — optional. Reads each screenshot via the Anthropic API and
  writes content-aware titles/tags. Needs `ANTHROPIC_API_KEY`.

Links without a screenshot fall back to a lettered placeholder tile — nothing breaks, and
`missing_thumbnails.txt` lists them.

## Shared edit layer (Supabase)

Edit mode writes go to a Supabase Postgres table (`link_edits`), keyed by URL. Reads
are open to anyone; writes require a shared passcode checked server-side via a
`SECURITY DEFINER` RPC function (`upsert_link_edit`) — RLS denies all direct table
access, so the passcode check can't be bypassed from the client. See
`supabase/schema.sql` for the full schema. The Supabase project URL and publishable
key are hardcoded in `index.html` (safe to expose client-side by design); rotate the
passcode any time by re-running the `edit_passcode` insert in the SQL Editor.

## Notes

Browsing and search stay offline-durable — only Edit mode and the personal vault need a
network connection, and edits fall back to a local `localStorage` cache if Supabase is
unreachable.
