# Persistent field inspections with Supabase

AGNI-SCAN uses a Supabase PostgreSQL table only from its Next.js server route. The browser never receives the database secret key.

## 1. Create the table

Create a Supabase project, open its **SQL Editor**, and run [`../supabase/migrations/20261028_create_inspections.sql`](../supabase/migrations/20261028_create_inspections.sql).

The migration enables Row Level Security, revokes browser-role access, and grants only the server-side service role the required read/write permissions.

## 2. Configure local development

Copy the safe variable names from [`.env.example`](../.env.example) into `.env.local`, then set real values:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=your-secret-key
AGNI_SCAN_WRITE_TOKEN=a-long-random-team-token
```

Never commit `.env.local`, the secret key, raw FIRMS data, or real grid output. Do not use a `NEXT_PUBLIC_` prefix for these settings.

## 3. Behaviour and deployment guardrail

- With both Supabase settings, `GET` and `POST /api/inspections` use the database. `SUPABASE_SECRET_KEY` is preferred; the older `SUPABASE_SERVICE_ROLE_KEY` is accepted only for migration compatibility.
- During local development without either setting, the existing temporary in-memory store remains available for interface work.
- In production, missing or partial Supabase configuration returns HTTP 503. The app never silently uses temporary memory in production.
- `POST /api/inspections` still requires `x-agni-scan-write-token` to match `AGNI_SCAN_WRITE_TOKEN` before the server calls Supabase.

The current token protects a small trusted team. Before public rollout, replace it with individual Supabase Auth accounts and role-based access control.
