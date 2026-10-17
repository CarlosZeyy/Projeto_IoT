-- 002_contract_checks: checks that mirror the contract on inspections (SPEC-027 section 4.1,
-- docs/architecture.md section 5).
--
-- Without them, a row written outside the API (SQL Editor, manual migration) with a non-v4
-- inspection_id, a model_version outside the contract regex or inspected_at = 'infinity'
-- breaks every read route that returns it (500).
--
-- No BEGIN/COMMIT here: the transaction belongs to infra/migrate.py.
-- Idempotent: each constraint is added only if no constraint with that name exists on
-- inspections, so running this file again (SQL Editor / psql / runner) changes nothing.
-- One single DO block: the check of the existing rows and the ALTER TABLEs succeed or fail
-- together, also in a psql session without ON_ERROR_STOP.
-- The error message carries only counts, never row values. No credentials here (R-03).

do $$
declare
    bad_model_version bigint;
    bad_inspection_id bigint;
    bad_inspected_at bigint;
    bad_received_at bigint;
    bad_total bigint;
begin
    -- 1. Existing rows, before any ALTER TABLE. A row that breaks several rules counts once in
    -- the total and once in each rule it breaks.
    select
        count(*) filter (where not (model_version ~ '^[a-z0-9.-]{3,40}$')),
        count(*) filter (
            where not (
                inspection_id::text
                ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            )
        ),
        count(*) filter (
            where not (
                inspected_at >= timestamptz '0001-01-01 00:00:00+00'
                and inspected_at < timestamptz '10000-01-01 00:00:00+00'
            )
        ),
        count(*) filter (
            where not (
                received_at >= timestamptz '0001-01-01 00:00:00+00'
                and received_at < timestamptz '10000-01-01 00:00:00+00'
            )
        ),
        count(*) filter (
            where not (
                model_version ~ '^[a-z0-9.-]{3,40}$'
                and inspection_id::text
                    ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                and inspected_at >= timestamptz '0001-01-01 00:00:00+00'
                and inspected_at < timestamptz '10000-01-01 00:00:00+00'
                and received_at >= timestamptz '0001-01-01 00:00:00+00'
                and received_at < timestamptz '10000-01-01 00:00:00+00'
            )
        )
    into bad_model_version, bad_inspection_id, bad_inspected_at, bad_received_at, bad_total
    from inspections;

    if bad_total > 0 then
        raise exception 'migration 002: % row(s) of inspections violate the new checks '
            '(model_version=%, inspection_id=%, inspected_at=%, received_at=%); '
            'fix or delete them before migrating',
            bad_total, bad_model_version, bad_inspection_id, bad_inspected_at, bad_received_at;
    end if;

    -- 2. Named constraints, each one only if it does not exist yet on inspections.
    -- Mirror of qc_contracts.MODEL_VERSION_PATTERN.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'inspections'::regclass and conname = 'inspections_model_version_check'
    ) then
        alter table inspections
            add constraint inspections_model_version_check
            check (model_version ~ '^[a-z0-9.-]{3,40}$');
    end if;

    -- Mirror of pydantic's UUID4: version 4, RFC 4122 variant. uuid::text is always lowercase.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'inspections'::regclass
          and conname = 'inspections_inspection_id_v4_check'
    ) then
        alter table inspections
            add constraint inspections_inspection_id_v4_check
            check (
                inspection_id::text
                ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            );
    end if;

    -- Range of Python's datetime in UTC (UtcDatetime); refuses infinity and -infinity.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'inspections'::regclass
          and conname = 'inspections_inspected_at_range_check'
    ) then
        alter table inspections
            add constraint inspections_inspected_at_range_check
            check (
                inspected_at >= timestamptz '0001-01-01 00:00:00+00'
                and inspected_at < timestamptz '10000-01-01 00:00:00+00'
            );
    end if;

    -- Same range for received_at (InspectionRead.received_at).
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'inspections'::regclass
          and conname = 'inspections_received_at_range_check'
    ) then
        alter table inspections
            add constraint inspections_received_at_range_check
            check (
                received_at >= timestamptz '0001-01-01 00:00:00+00'
                and received_at < timestamptz '10000-01-01 00:00:00+00'
            );
    end if;
end
$$;
