-- 001_init: devices and inspections (docs/architecture.md section 5, SPEC-003 section 4.1).
--
-- No BEGIN/COMMIT here: the transaction belongs to infra/migrate.py.
-- Idempotent DDL (if not exists): running this file again, by hand (SQL Editor / psql) or
-- through the runner, does not fail and does not change the schema.
-- No credentials in this file (R-03).

create table if not exists devices (
    device_id text primary key
        constraint devices_device_id_check check (device_id ~ '^[a-z0-9-]{3,32}$'),
    api_key_hash text not null
        constraint devices_api_key_hash_key unique
        constraint devices_api_key_hash_check check (api_key_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now(),
    -- null until the device writes for the first time
    last_seen_at timestamptz
);

create table if not exists inspections (
    inspection_id uuid primary key,
    device_id text not null references devices (device_id) on delete restrict,
    lot_id text not null,
    inspected_at timestamptz not null,
    received_at timestamptz not null default now(),
    object_type text not null,
    grade text,
    grade_score real,
    type_confidence real not null,
    grade_confidence real,
    needs_review boolean not null,
    model_version text not null,
    model_sha256 text not null,
    -- integer: the type itself rejects values above 2147483647 (SQLSTATE 22003), which is the
    -- contract ceiling (qc_contracts.MAX_LATENCY_MS, contract 0.2.0); no upper bound in the check.
    latency_ms integer not null,
    source text not null,
    -- Mirror of qc_contracts.is_defective (ADR-013): only poor and unusable are defective.
    is_defective boolean generated always as (coalesce(grade in ('poor', 'unusable'), false)) stored,

    constraint inspections_object_type_check
        check (object_type in ('screw', 'nut', 'unknown')),
    constraint inspections_grade_check
        check (grade in ('perfect', 'good', 'fair', 'poor', 'unusable')),
    constraint inspections_source_check
        check (source in ('live', 'simulated')),
    constraint inspections_grade_null_iff_unknown
        check ((object_type = 'unknown') = (grade is null)),
    -- Defense in depth, mirroring the contract validators (does not change the contract).
    constraint inspections_grade_fields_null_together
        check (
            (grade is null) = (grade_score is null)
            and (grade is null) = (grade_confidence is null)
        ),
    constraint inspections_ranges_check
        check (
            type_confidence between 0 and 1
            and grade_confidence between 0 and 1
            and grade_score between 0 and 4
            and latency_ms >= 0
        ),
    constraint inspections_formats_check
        check (
            lot_id ~ '^[A-Za-z0-9_-]{1,40}$'
            and model_sha256 ~ '^[0-9a-f]{64}$'
        )
);

create index if not exists inspections_inspected_at_idx on inspections (inspected_at);
create index if not exists inspections_lot_id_idx on inspections (lot_id);
create index if not exists inspections_source_inspected_at_idx on inspections (source, inspected_at);
create index if not exists inspections_device_id_idx on inspections (device_id);

-- RLS on, no policies: the Supabase anon/authenticated keys read and write nothing.
-- No "force row level security": the table owner (the API's DATABASE_URL user) keeps access.
alter table devices enable row level security;
alter table inspections enable row level security;
