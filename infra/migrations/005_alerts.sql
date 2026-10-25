-- 005_alerts: the Telegram alerts already handled (SPEC-017 section 4.3,
-- docs/architecture.md sections 4 and 5).
--
-- One row per (lot_id, source, kind), inserted by the API *before* the message is sent
-- (INSERT ... ON CONFLICT DO NOTHING): the primary key guarantees one message per lot, also
-- with more than one uvicorn worker. delivered turns true only after Telegram accepts the
-- message; a failed send keeps false and is never retried. created_at feeds the hourly cap.
--
-- No BEGIN/COMMIT here: the transaction belongs to infra/migrate.py. Idempotent DDL (if not
-- exists): running this file again (SQL Editor / psql / runner) changes nothing. No
-- credentials here (R-03).

create table if not exists alerts_sent (
    -- Mirror of qc_contracts.LOT_ID_PATTERN.
    lot_id text not null
        constraint alerts_sent_lot_id_check check (lot_id ~ '^[A-Za-z0-9_-]{1,40}$'),
    source text not null
        constraint alerts_sent_source_check check (source in ('live', 'simulated')),
    kind text not null
        constraint alerts_sent_kind_check check (kind in ('out_of_control')),
    created_at timestamptz not null default now(),
    delivered boolean not null default false,
    constraint alerts_sent_pkey primary key (lot_id, source, kind)
);

-- The hourly cap counts the rows of the last hour on every check.
create index if not exists alerts_sent_created_at_idx on alerts_sent (created_at);

-- RLS on, no policies, like the other tables: the Supabase anon/authenticated keys read and
-- write nothing. No "force row level security": the owner (the API) keeps access.
alter table alerts_sent enable row level security;
