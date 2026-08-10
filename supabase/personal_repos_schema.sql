-- Personal repositories - experimental feature, built on the "personal-repos" branch.
-- Each person picks a handle + their own passcode (independent of the shared
-- edit_passcode from schema.sql) and gets a private-by-default collection of
-- uploaded images/videos, with a toggle to make it public via a shareable link.
-- Run this once in the Supabase SQL Editor, after schema.sql.

create extension if not exists pgcrypto;

create table if not exists public.personal_repos (
  id uuid primary key default gen_random_uuid(),
  handle text unique not null,
  passcode_hash text not null,
  is_public boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.personal_items (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid not null references public.personal_repos(id) on delete cascade,
  kind text not null check (kind in ('image','video')),
  storage_path text not null,
  title text not null default '',
  tags text[] not null default '{}',
  note text not null default '',
  created_at timestamptz not null default now()
);

alter table public.personal_repos enable row level security;
alter table public.personal_items enable row level security;
-- No policies on purpose, same pattern as schema.sql: RLS denies all direct
-- access, everything goes through the SECURITY DEFINER functions below.

-- Storage bucket for uploaded files. Public bucket (so images/videos can be
-- served directly by URL) with size/type guardrails, since uploads aren't
-- individually passcode-gated at the storage layer (see project notes).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'personal-uploads', 'personal-uploads', true, 52428800,
  array['image/png','image/jpeg','image/gif','image/webp','video/mp4','video/webm','video/quicktime']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "personal-uploads anon insert" on storage.objects;
create policy "personal-uploads anon insert"
on storage.objects for insert
to anon
with check (bucket_id = 'personal-uploads');

drop policy if exists "personal-uploads anon select" on storage.objects;
create policy "personal-uploads anon select"
on storage.objects for select
to anon
using (bucket_id = 'personal-uploads');

drop policy if exists "personal-uploads anon delete" on storage.objects;
create policy "personal-uploads anon delete"
on storage.objects for delete
to anon
using (bucket_id = 'personal-uploads');

-- Create a new personal repo. Fails if the handle is already taken.
create or replace function public.create_personal_repo(p_handle text, p_passcode text)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_id uuid;
begin
  insert into public.personal_repos (handle, passcode_hash)
  values (lower(p_handle), extensions.crypt(p_passcode, extensions.gen_salt('bf')))
  returning id into v_id;
  return v_id;
end;
$$;

-- Verify a repo's passcode; returns the repo id if correct, no row otherwise.
create or replace function public.auth_personal_repo(p_handle text, p_passcode text)
returns uuid
language sql
security definer
set search_path = public, extensions
as $$
  select id from public.personal_repos
  where handle = lower(p_handle)
    and passcode_hash = extensions.crypt(p_passcode, passcode_hash);
$$;

-- Public metadata lookup by handle (no passcode needed) - lets the app decide
-- whether to show a public read-only view or prompt for a passcode.
create or replace function public.get_personal_repo(p_handle text)
returns table(id uuid, handle text, is_public boolean)
language sql
security definer
set search_path = public
as $$
  select id, handle, is_public from public.personal_repos where handle = lower(p_handle);
$$;

-- List items in a repo. Enforces visibility itself: public repos need no
-- passcode, private repos require the correct one - the client can't bypass
-- this by calling the RPC directly with a made-up repo id.
create or replace function public.list_personal_items(p_repo_id uuid, p_passcode text default null)
returns setof public.personal_items
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_public boolean;
begin
  select is_public into v_public from public.personal_repos where id = p_repo_id;
  if v_public is null then
    return;
  end if;
  if not v_public then
    if p_passcode is null or not exists (
      select 1 from public.personal_repos
      where id = p_repo_id and passcode_hash = extensions.crypt(p_passcode, passcode_hash)
    ) then
      raise exception 'private repository';
    end if;
  end if;
  return query select * from public.personal_items where repo_id = p_repo_id order by created_at desc;
end;
$$;

-- Add an item; requires the repo's passcode.
create or replace function public.add_personal_item(
  p_repo_id uuid, p_passcode text, p_kind text, p_storage_path text,
  p_title text, p_tags text[], p_note text
)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_id uuid;
begin
  if not exists (
    select 1 from public.personal_repos
    where id = p_repo_id and passcode_hash = extensions.crypt(p_passcode, passcode_hash)
  ) then
    raise exception 'invalid passcode';
  end if;
  insert into public.personal_items (repo_id, kind, storage_path, title, tags, note)
  values (p_repo_id, p_kind, p_storage_path, p_title, p_tags, p_note)
  returning id into v_id;
  return v_id;
end;
$$;

-- Update an item's title/tags/note; requires the repo's passcode.
create or replace function public.update_personal_item(
  p_item_id uuid, p_passcode text, p_title text, p_tags text[], p_note text
)
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_repo uuid;
begin
  select repo_id into v_repo from public.personal_items where id = p_item_id;
  if v_repo is null then raise exception 'not found'; end if;
  if not exists (
    select 1 from public.personal_repos
    where id = v_repo and passcode_hash = extensions.crypt(p_passcode, passcode_hash)
  ) then
    raise exception 'invalid passcode';
  end if;
  update public.personal_items set title = p_title, tags = p_tags, note = p_note where id = p_item_id;
end;
$$;

-- Delete an item; requires the repo's passcode. Returns the storage_path so
-- the client can also remove the underlying file from storage.
create or replace function public.delete_personal_item(p_item_id uuid, p_passcode text)
returns text
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_repo uuid;
  v_path text;
begin
  select repo_id, storage_path into v_repo, v_path from public.personal_items where id = p_item_id;
  if v_repo is null then raise exception 'not found'; end if;
  if not exists (
    select 1 from public.personal_repos
    where id = v_repo and passcode_hash = extensions.crypt(p_passcode, passcode_hash)
  ) then
    raise exception 'invalid passcode';
  end if;
  delete from public.personal_items where id = p_item_id;
  return v_path;
end;
$$;

-- Toggle a repo's visibility; requires the repo's passcode.
create or replace function public.set_personal_repo_visibility(p_repo_id uuid, p_passcode text, p_is_public boolean)
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not exists (
    select 1 from public.personal_repos
    where id = p_repo_id and passcode_hash = extensions.crypt(p_passcode, passcode_hash)
  ) then
    raise exception 'invalid passcode';
  end if;
  update public.personal_repos set is_public = p_is_public where id = p_repo_id;
end;
$$;

grant execute on function public.create_personal_repo(text, text) to anon;
grant execute on function public.auth_personal_repo(text, text) to anon;
grant execute on function public.get_personal_repo(text) to anon;
grant execute on function public.list_personal_items(uuid, text) to anon;
grant execute on function public.add_personal_item(uuid, text, text, text, text, text[], text) to anon;
grant execute on function public.update_personal_item(uuid, text, text, text[], text) to anon;
grant execute on function public.delete_personal_item(uuid, text) to anon;
grant execute on function public.set_personal_repo_visibility(uuid, text, boolean) to anon;
