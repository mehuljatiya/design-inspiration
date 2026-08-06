# Designspiration Archive

A self-contained, searchable directory of design-inspiration links curated from the
Cashfree `#designspiration` Slack channel (Nov 2024 – Jul 2026). 641 links across 17
categories, with screenshots, full-text search, category and tag filtering, and an
in-page edit mode.

## Use it

Open `index.html` in a browser, or host the folder (Vercel / Netlify / GitHub Pages).
Keep `index.html` and `thumbs/` together — thumbnails load by relative path.

- **Search** across titles, notes, tags, and domains.
- **Filter** by category (left rail) and by tag (high-signal tags surfaced with counts).
- **Views**: Gallery (image-first), By category, By date.
- **Edit mode**: fix titles/tags inline. Requires the shared team passcode (once per
  browser session). Edits sync to Supabase — everyone sees the same titles/tags,
  no matter who edited or which browser they're on. A local cache in `localStorage`
  is kept as an offline fallback. "Download backup" exports a portable copy.

## Regenerate / extend

- `generate_thumbs.py` — capture screenshots into `thumbs/`. Logs into X/Instagram/
  LinkedIn once (`--login`), then captures (resumable, skips saved). Requires
  `pip install playwright && playwright install chromium`.
- `generate_titles.py` — optional. Reads each screenshot via the Anthropic API and
  writes content-aware titles/tags. Needs `ANTHROPIC_API_KEY`.

## Status

- 496 links titled from facts (notes, in-URL handles, known domains).
- 145 opaque social posts flagged with the `review` tag — filter to `review` in Edit
  mode to finish them by eye. `missing_thumbnails.txt` lists links without a screenshot.

## Shared edit layer (Supabase)

Edit mode writes go to a Supabase Postgres table (`link_edits`), keyed by URL. Reads
are open to anyone; writes require a shared passcode checked server-side via a
`SECURITY DEFINER` RPC function (`upsert_link_edit`) — RLS denies all direct table
access, so the passcode check can't be bypassed from the client. See
`supabase/schema.sql` for the full schema. The Supabase project URL and publishable
key are hardcoded in `index.html` (safe to expose client-side by design); rotate the
passcode any time by re-running the `edit_passcode` insert in the SQL Editor.

## Notes

The archive stays offline-durable for browsing and search — only Edit mode needs a
network connection, and falls back to a local `localStorage` cache if Supabase is
unreachable.
