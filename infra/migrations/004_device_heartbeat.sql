-- 004_device_heartbeat: the last heartbeat of each device, on devices (SPEC-018 section 4.2,
-- docs/architecture.md section 5).
--
-- A heartbeat is an UPDATE of the device row (no history). Every new column is nullable: a
-- device that never sent a heartbeat keeps them all null.
--
-- * last_heartbeat_at: server time (now()) when the last heartbeat arrived; decides "online".
-- * hb_sent_at: the edge clock (HeartbeatCreate.sent_at), only for diagnosis.
-- * hb_model_version, hb_model_sha256, hb_app_version: the regexes of qc_contracts 0.5.0
--   (MODEL_VERSION_PATTERN, SHA256_PATTERN, APP_VERSION_PATTERN), and the model pair is null
--   together, like the contract.
-- * hb_uptime_s, hb_outbox_pending, hb_outbox_dead: integer >= 0 (the contract caps them at
--   MAX_HEARTBEAT_COUNT, the integer limit).
--
-- No BEGIN/COMMIT here: the transaction belongs to infra/migrate.py. One single DO block, so the
-- columns and the checks succeed or fail together, also in a psql session without
-- ON_ERROR_STOP. Idempotent: each column is added only if missing and each named check only if
-- no constraint with that name exists on devices, so running this file again (SQL Editor /
-- psql / runner) changes nothing. Existing rows get nulls, which every check accepts. No
-- credentials here (R-03).

do $$
begin
    alter table devices
        add column if not exists last_heartbeat_at timestamptz,
        add column if not exists hb_sent_at timestamptz,
        add column if not exists hb_model_version text,
        add column if not exists hb_model_sha256 text,
        add column if not exists hb_app_version text,
        add column if not exists hb_uptime_s integer,
        add column if not exists hb_outbox_pending integer,
        add column if not exists hb_outbox_dead integer;

    -- Mirror of qc_contracts.MODEL_VERSION_PATTERN.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_model_version_check'
    ) then
        alter table devices
            add constraint devices_hb_model_version_check
            check (hb_model_version ~ '^[a-z0-9.-]{3,40}$');
    end if;

    -- Mirror of qc_contracts.SHA256_PATTERN.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_model_sha256_check'
    ) then
        alter table devices
            add constraint devices_hb_model_sha256_check
            check (hb_model_sha256 ~ '^[0-9a-f]{64}$');
    end if;

    -- Mirror of qc_contracts.APP_VERSION_PATTERN.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_app_version_check'
    ) then
        alter table devices
            add constraint devices_hb_app_version_check
            check (hb_app_version ~ '^[0-9A-Za-z.+-]{1,40}$');
    end if;

    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_uptime_s_check'
    ) then
        alter table devices
            add constraint devices_hb_uptime_s_check check (hb_uptime_s >= 0);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_outbox_pending_check'
    ) then
        alter table devices
            add constraint devices_hb_outbox_pending_check check (hb_outbox_pending >= 0);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_outbox_dead_check'
    ) then
        alter table devices
            add constraint devices_hb_outbox_dead_check check (hb_outbox_dead >= 0);
    end if;

    -- HeartbeatCreate: model_sha256 is null if and only if model_version is null.
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'devices'::regclass and conname = 'devices_hb_model_pair_check'
    ) then
        alter table devices
            add constraint devices_hb_model_pair_check
            check ((hb_model_version is null) = (hb_model_sha256 is null));
    end if;
end
$$;
