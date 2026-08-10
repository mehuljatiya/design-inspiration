-- Design Vault — public bucket for link media
-- Run once in the Supabase SQL editor.
--
-- Holds the image (or video poster frame) pulled from each saved post, so a card
-- shows the design itself rather than a screenshot of the platform it was posted on.
-- Read is open to everyone (the site loads these unauthenticated); writes are
-- service-role only, i.e. the one-time bulk upload from upload_media.py.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'link-media',
  'link-media',
  true,                                   -- public read; URLs are stable and CDN-cached
  10485760,                               -- 10MB per object; posters are ~100-300KB
  array['image/jpeg','image/png','image/webp']
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- Anyone may read an object in this bucket.
drop policy if exists "link-media public read" on storage.objects;
create policy "link-media public read"
  on storage.objects for select
  to public
  using (bucket_id = 'link-media');

-- No insert/update/delete policy is defined on purpose: without one, RLS denies
-- writes to every client key. The service-role key bypasses RLS, so the upload
-- script can still write. Keep that key out of the repo and out of the browser.
