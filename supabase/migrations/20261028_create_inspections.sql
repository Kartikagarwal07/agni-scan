-- AGNI-SCAN persistent field-inspection records.
-- Run through the Supabase SQL Editor or the Supabase CLI migration workflow.

create table if not exists public.inspections (
  id uuid primary key default gen_random_uuid(),
  cell_id text not null check (char_length(cell_id) between 1 and 160),
  result text not null check (result in ('fire_evidence_found', 'no_fire_evidence_found', 'inconclusive')),
  notes text not null check (char_length(btrim(notes)) between 1 and 1000),
  created_at timestamptz not null default now()
);

create index if not exists inspections_cell_created_at_idx
  on public.inspections (cell_id, created_at desc);

create index if not exists inspections_created_at_idx
  on public.inspections (created_at desc);

alter table public.inspections enable row level security;

-- The table is not available to browser-facing anon/authenticated roles. The
-- server-side Supabase secret key uses service_role after API-token validation.
revoke all on table public.inspections from anon, authenticated;
grant select, insert on table public.inspections to service_role;
