from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from flask import current_app
from sqlalchemy import text

from ..extensions import db
from ..models import User
from .modules_registry import is_module_internal_enabled


EVENT_SOURCE_SUITE = 'suite_home_office'
DEVICE_IP_SUITE = 'suite-home-office'


@dataclass
class ClockSnapshot:
    enabled: bool
    module_enabled: bool
    has_ref_code: bool
    ref_code: str
    last_event_ts: datetime | None
    last_event_state: str | None
    last_event_error: str | None
    last_event_source: str | None


def _user_enabled(user: User) -> bool:
    return bool(getattr(user, 'home_office_clock_enabled', False)) and bool(
        getattr(user, 'attendance_ref_code', '') or ''
    )


def get_user_clock_snapshot(user: User) -> ClockSnapshot:
    ref_code = (getattr(user, 'attendance_ref_code', '') or '').strip()
    row = db.session.execute(
        text(
            '''
            SELECT ts, state, last_error, COALESCE(event_source, 'zk_device') AS event_source
            FROM zk_events
            WHERE zk_user_id = :zk_user_id
            ORDER BY ts DESC, id DESC
            LIMIT 1
            '''
        ),
        {'zk_user_id': ref_code or '__none__'},
    ).mappings().first()
    return ClockSnapshot(
        enabled=bool(getattr(user, 'home_office_clock_enabled', False)),
        module_enabled=is_module_internal_enabled('reloj_home_office', default=True),
        has_ref_code=bool(ref_code),
        ref_code=ref_code,
        last_event_ts=row['ts'] if row else None,
        last_event_state=row['state'] if row else None,
        last_event_error=row['last_error'] if row else None,
        last_event_source=row['event_source'] if row else None,
    )


def queue_home_office_mark(user: User) -> tuple[bool, str]:
    if not is_module_internal_enabled('reloj_home_office', default=True):
        return False, 'El módulo de reloj Home Office está deshabilitado.'
    if not bool(getattr(user, 'home_office_clock_enabled', False)):
        return False, 'Tu usuario no está habilitado para usar este reloj.'

    ref_code = (getattr(user, 'attendance_ref_code', '') or '').strip()
    if not ref_code:
        return False, 'Tu usuario no tiene configurada la Cédula de identidad.'

    now_local = datetime.now()
    ts_str = now_local.strftime('%Y-%m-%d %H:%M:%S')
    base = f'{EVENT_SOURCE_SUITE}|{user.id}|{ref_code}|{ts_str}|0|0'
    event_key = sha256(base.encode('utf-8')).hexdigest()

    try:
        db.session.execute(
            text(
                '''
                INSERT INTO zk_events(device_ip, zk_user_id, ts, punch, status, event_key, event_source)
                VALUES (:device_ip, :zk_user_id, :ts, :punch, :status, :event_key, :event_source)
                ON CONFLICT (event_key) DO NOTHING
                '''
            ),
            {
                'device_ip': DEVICE_IP_SUITE,
                'zk_user_id': ref_code,
                'ts': ts_str,
                'punch': 0,
                'status': 0,
                'event_key': event_key,
                'event_source': EVENT_SOURCE_SUITE,
            },
        )
        db.session.commit()
        current_app.logger.info(
            'home_office_mark_queued user_id=%s username=%s ref=%s event_key=%s',
            getattr(user, 'id', None),
            getattr(user, 'username', None),
            ref_code,
            event_key,
        )
        return True, 'Marcada registrada en cola. El bridge la enviará a Odoo con la misma lógica del reloj.'
    except Exception as ex:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('home_office_mark_failed user_id=%s', getattr(user, 'id', None))
        return False, f'No se pudo registrar la marcada: {ex}'
