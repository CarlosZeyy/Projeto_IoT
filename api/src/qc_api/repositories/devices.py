"""Heartbeat write and device status read over ``devices`` (SPEC-018 sections 4.2 and 4.3).

* A heartbeat is one ``UPDATE`` of the device row (no history): ``last_heartbeat_at`` and
  ``last_seen_at`` take the database server time (``now()``), the body fields go to the
  ``hb_*`` columns, and the edge ``sent_at`` is stored only for diagnosis.
* ``online`` is computed in SQL, with the same clock that wrote ``last_heartbeat_at``: a
  heartbeat received less than ``ONLINE_WINDOW_S`` seconds ago. The edge clock decides nothing.
* ``last_source`` is the ``source`` of the inspection of the device with the largest
  ``received_at`` (ties, such as the items of one batch, by the largest ``inspected_at`` and then
  ``inspection_id``), or ``null`` without inspections.

Every value is a psycopg parameter. ``psycopg.DataError`` and ``psycopg.IntegrityError`` of the
write propagate to the caller unchanged, after the rollback.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from qc_api.db import db_connection
from qc_contracts import DeviceStatus, HeartbeatCreate

ONLINE_WINDOW_S = 180
MAX_DEVICES = 500

UPDATE_HEARTBEAT = """
update devices set
    last_heartbeat_at = now(),
    last_seen_at = now(),
    hb_sent_at = %(sent_at)s,
    hb_model_version = %(model_version)s,
    hb_model_sha256 = %(model_sha256)s,
    hb_app_version = %(app_version)s,
    hb_uptime_s = %(uptime_s)s,
    hb_outbox_pending = %(outbox_pending)s,
    hb_outbox_dead = %(outbox_dead)s
where device_id = %(device_id)s
"""

SELECT_DEVICES = """
select
    d.device_id,
    d.last_seen_at,
    d.last_heartbeat_at,
    (
        d.last_heartbeat_at is not null
        and now() - d.last_heartbeat_at < %(online_window_s)s * interval '1 second'
    ) as online,
    d.hb_model_version as model_version,
    d.hb_model_sha256 as model_sha256,
    d.hb_app_version as app_version,
    d.hb_uptime_s as uptime_s,
    d.hb_outbox_pending as outbox_pending,
    d.hb_outbox_dead as outbox_dead,
    latest.source as last_source
from devices as d
left join lateral (
    select i.source
    from inspections as i
    where i.device_id = d.device_id
    order by i.received_at desc, i.inspected_at desc, i.inspection_id desc
    limit 1
) as latest on true
order by d.device_id collate "C"
limit %(limit)s
"""


def record_heartbeat(pool: ConnectionPool, device_id: str, heartbeat: HeartbeatCreate) -> None:
    """Store ``heartbeat`` as the last one of ``device_id``, in one transaction."""
    params = {
        "device_id": device_id,
        "sent_at": heartbeat.sent_at,
        "model_version": heartbeat.model_version,
        "model_sha256": heartbeat.model_sha256,
        "app_version": heartbeat.app_version,
        "uptime_s": heartbeat.uptime_s,
        "outbox_pending": heartbeat.outbox_pending,
        "outbox_dead": heartbeat.outbox_dead,
    }
    with db_connection(pool) as conn, conn.transaction():
        conn.execute(UPDATE_HEARTBEAT, params)


def list_devices(
    pool: ConnectionPool, *, limit: int = MAX_DEVICES, online_window_s: int = ONLINE_WINDOW_S
) -> list[DeviceStatus]:
    """At most ``limit`` devices in ``device_id`` order (the order of a Python ``str``)."""
    with db_connection(pool) as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("set transaction read only")
        cursor.execute(SELECT_DEVICES, {"online_window_s": online_window_s, "limit": limit})
        rows = cursor.fetchall()
    return [DeviceStatus.model_validate(row) for row in rows]
