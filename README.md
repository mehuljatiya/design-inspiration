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
- **Edit mode**: fix titles/tags inline. Edits autosave to your browser and persist
  across sessions on the same file. "Download backup" exports a portable copy.

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

## Notes

The archive is intentionally dependency-free and offline-durable. A shared, multi-user
edit layer (Supabase) is a possible future addition; the single file remains the
source of truth.
