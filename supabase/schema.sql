-- Designspiration Archive - shared edit layer
-- Run this once in the Supabase SQL Editor (Project, then SQL Editor, then New query).

create extension if not exists pgcrypto;

create table if not exists public.link_edits (
  url text primary key,
  title text not null,
  tags text[] not null default '{}',
  updated_at timestamptz not null default now()
);

create table if not exists public.edit_passcode (
  id boolean primary key default true,
  passcode_hash text not null,
  constraint edit_passcode_singleton check (id)
);

alter table public.link_edits enable row level security;
alter table public.edit_passcode enable row level security;
-- No policies are created on either table on purpose: RLS with zero policies
-- denies all direct access to anon/authenticated roles. The only way in is
-- through the SECURITY DEFINER functions below, which run with the table
-- owner's privileges and enforce the passcode check themselves.

create or replace function public.get_link_edits()
returns setof public.link_edits
language sql
security definer
set search_path = public
as $$
  select * from public.link_edits;
$$;

create or replace function public.check_passcode(p_passcode text)
returns boolean
language sql
security definer
set search_path = public, extensions
as $$
  select exists (
    select 1 from public.edit_passcode
    where passcode_hash = crypt(p_passcode, passcode_hash)
  );
$$;

create or replace function public.upsert_link_edit(p_url text, p_title text, p_tags text[], p_passcode text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.check_passcode(p_passcode) then
    raise exception 'invalid passcode';
  end if;
  insert into public.link_edits (url, title, tags, updated_at)
  values (p_url, p_title, p_tags, now())
  on conflict (url) do update
    set title = excluded.title,
        tags = excluded.tags,
        updated_at = now();
end;
$$;

grant execute on function public.get_link_edits() to anon;
grant execute on function public.check_passcode(text) to anon;
grant execute on function public.upsert_link_edit(text, text, text[], text) to anon;

-- Set the shared team passcode (run separately, replace the placeholder).
-- Anyone with this passcode can edit; rotate it by re-running with a new value.
-- insert into public.edit_passcode (id, passcode_hash) values (true, extensions.crypt('YOUR-PASSCODE-HERE', extensions.gen_salt('bf')))
--   on conflict (id) do update set passcode_hash = excluded.passcode_hash;
