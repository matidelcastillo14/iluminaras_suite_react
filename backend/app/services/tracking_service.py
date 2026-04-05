from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime

from flask import current_app

from ..extensions import db
from ..models import TrackingShipment, TrackingEvent, TrackingScan, User


# ------------------------------------------------------------
# Reglas de negocio (anti-duplicados + máquina de estados)
# ------------------------------------------------------------

# Eventos que NO deberían repetirse nunca (por shipment)
# Nota: PICKING_STARTED / READY_FOR_DISPATCH / STOCK_MISSING pueden repetirse
# si el pedido vuelve atrás (p.ej. devuelto a depósito). Para esos casos,
# sólo bloqueamos duplicados consecutivos.
NON_REPEATABLE_EVENTS = {
    "LABEL_CREATED",
    "DELIVERED",
    "RETURNED",
}

# Transiciones permitidas basadas en el ÚLTIMO evento registrado.
# Flujo requerido:
#   Depósito: LABEL_CREATED -> PICKING_STARTED -> READY_FOR_DISPATCH
#   Cadetería: READY_FOR_DISPATCH -> OUT_FOR_DELIVERY -> (DELIVERED | DELIVERY_FAILED | RETURNED)
#   Reintentos: DELIVERY_FAILED -> OUT_FOR_DELIVERY | RETURNED
#   Re-despacho: RETURNED -> READY_FOR_DISPATCH
ALLOWED_NEXT_BY_LAST = {
    None: {"LABEL_CREATED"},
    "LABEL_CREATED": {"PICKING_STARTED"},
    "PICKING_STARTED": {"READY_FOR_DISPATCH", "STOCK_MISSING"},
    "STOCK_MISSING": {"SALES_DECISION"},
    "SALES_DECISION": {"READY_FOR_DISPATCH"},
    "READY_FOR_DISPATCH": {"OUT_FOR_DELIVERY"},
    # Compatibilidad con flujo anterior (cuando existía "IN_TRANSIT")
    "IN_TRANSIT": {"OUT_FOR_DELIVERY"},
    "OUT_FOR_DELIVERY": {"ON_ROUTE_TO_DELIVERY", "DELIVERED", "DELIVERY_FAILED", "RETURN_TO_DEPOT_REQUESTED", "RETURNED"},
    "ON_ROUTE_TO_DELIVERY": {"DELIVERED", "DELIVERY_FAILED", "RETURN_TO_DEPOT_REQUESTED", "RETURNED", "BACK_TO_OUT_FOR_DELIVERY"},
    "BACK_TO_OUT_FOR_DELIVERY": {"ON_ROUTE_TO_DELIVERY", "DELIVERED", "DELIVERY_FAILED", "RETURN_TO_DEPOT_REQUESTED", "RETURNED"},
    "DELIVERY_FAILED": {"OUT_FOR_DELIVERY", "RETURN_TO_DEPOT_REQUESTED", "DEFERRED_NEXT_SHIFT", "RETURNED"},
    "DEFERRED_NEXT_SHIFT": {"OUT_FOR_DELIVERY", "RETURN_TO_DEPOT_REQUESTED"},
    "RETURN_TO_DEPOT_REQUESTED": {"RETURNED"},
    # Al volver a Depósito se permite re-despacho directo o reiniciar armado.
    "RETURNED": {"READY_FOR_DISPATCH", "PICKING_STARTED"},
    "DELIVERED": set(),
}

# Roles que pueden emitir cada evento (admin siempre puede)
EVENT_ALLOWED_ROLES = {
    "LABEL_CREATED": {"admin", "system", "deposito"},
    "PICKING_STARTED": {"admin", "deposito"},
    "READY_FOR_DISPATCH": {"admin", "deposito"},
    "STOCK_MISSING": {"admin", "deposito"},
    "SALES_DECISION": {"admin", "ventas"},
    "OUT_FOR_DELIVERY": {"admin", "cadeteria"},
    "ON_ROUTE_TO_DELIVERY": {"admin", "cadeteria"},
    "BACK_TO_OUT_FOR_DELIVERY": {"admin", "cadeteria"},
    "DELIVERED": {"admin", "cadeteria"},
    "DELIVERY_FAILED": {"admin", "cadeteria"},
    "RETURNED": {"admin", "cadeteria", "deposito"},
    "RETURN_TO_DEPOT_REQUESTED": {"admin", "cadeteria"},
    "DEFERRED_NEXT_SHIFT": {"admin", "cadeteria"},
}


def _last_event(shipment_id: int) -> TrackingEvent | None:
    return (
        TrackingEvent.query.filter_by(shipment_id=shipment_id)
        .order_by(TrackingEvent.created_at.desc(), TrackingEvent.id.desc())
        .first()
    )


def _last_event_type(shipment_id: int) -> str | None:
    ev = _last_event(shipment_id)
    return (ev.event_type if ev else None)


def _actor_role(created_by_user_id: int | None) -> str:
    if not created_by_user_id:
        return "system"
    u = User.query.get(int(created_by_user_id))
    return str(getattr(u, "role", "") or "").strip() or "system"


def _validate_event(shipment: TrackingShipment, event_type: str, created_by_user_id: int | None) -> None:
    et = str(event_type or "").strip()
    if not et:
        raise ValueError("event_type_required")

    last = _last_event_type(shipment.id)

    # Si el último evento es SALES_OVERRIDE, la máquina de estados debería
    # continuar desde el estado actual del envío (shipment.status). Esto evita
    # bloqueos como SALES_OVERRIDE -> OUT_FOR_DELIVERY.
    if last == "SALES_OVERRIDE":
        status_to_last = {
            "LABEL_CREATED": "LABEL_CREATED",
            "PICKING_STARTED": "PICKING_STARTED",
            "READY_FOR_DISPATCH": "READY_FOR_DISPATCH",
            "IN_TRANSIT": "IN_TRANSIT",
            "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
            "ON_ROUTE_TO_DELIVERY": "ON_ROUTE_TO_DELIVERY",
            "DELIVERY_FAILED": "DELIVERY_FAILED",
            "RETURNED": "RETURNED",
            "DELIVERED": "DELIVERED",
            "STOCK_MISSING": "STOCK_MISSING",
            # STOCK_RESOLVED es el estado visible luego de SALES_DECISION
            "STOCK_RESOLVED": "SALES_DECISION",
        }
        last = status_to_last.get(str(shipment.status or "").strip(), last)

    # Anti doble-click
    if last == et:
        raise ValueError("duplicate_event")

    # Anti repetición histórica (para eventos no repetibles)
    if et in NON_REPEATABLE_EVENTS:
        exists = TrackingEvent.query.filter_by(shipment_id=shipment.id, event_type=et).first()
        if exists:
            raise ValueError("event_already_recorded")

    # Control de transición (máquina de estados)
    allowed = ALLOWED_NEXT_BY_LAST.get(last, set())
    if et not in allowed:
        raise ValueError(f"invalid_transition:{last or 'NONE'}->{et}")

    # Control por rol
    role = _actor_role(created_by_user_id)
    if role != "admin":
        allowed_roles = EVENT_ALLOWED_ROLES.get(et)
        if allowed_roles and role not in allowed_roles:
            raise ValueError("forbidden_by_role")


    # Validación especial: confirmación de devolución a depósito.
    # Si un cadete marcó "RETURN_TO_DEPOT_REQUESTED" indicando a qué usuario de depósito
    # lo entregó, SOLO ese usuario (o admin) puede confirmar "RETURNED".
    if et == "RETURNED" and last == "RETURN_TO_DEPOT_REQUESTED" and role != "admin":
        last_ev = _last_event(shipment.id)
        try:
            payload = json.loads(last_ev.payload_json) if (last_ev and last_ev.payload_json) else {}
        except Exception:
            payload = {}
        expected = payload.get("return_to_user_id")
        if not expected:
            raise ValueError("return_to_user_required")
        if not created_by_user_id or int(created_by_user_id) != int(expected):
            raise ValueError("forbidden_return_confirmation")


def _gen_code(secret: str, msg: str) -> str:
    # HMAC -> base32 URL-safe (sin padding)
    digest = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    code = base64.b32encode(digest).decode("ascii").rstrip("=")
    # 16-20 chars suele ser suficiente y scaneable
    return code[:18]


def ensure_tracking_for_order(odoo_order_id: int, order_name: str, id_web: str | None = None) -> str:
    """Asegura que exista un tracking para un pedido.

    Se invoca únicamente desde el flujo de generación de etiquetas legacy.
    """
    if not odoo_order_id:
        raise ValueError("odoo_order_id_required")

    existing = TrackingShipment.query.filter_by(odoo_order_id=int(odoo_order_id)).first()
    if existing:
        # Si el pedido ya existe pero quedó en LABEL_CREATED (p.ej. primera impresión),
        # lo promovemos automáticamente a READY_FOR_DISPATCH para habilitar escaneo inmediato.
        try:
            if str(existing.status or "").strip() == "LABEL_CREATED":
                existing.status = "READY_FOR_DISPATCH"
                db.session.add(
                    TrackingEvent(
                        shipment_id=existing.id,
                        event_type="READY_FOR_DISPATCH",
                        note="Listo para despacho (auto)",
                    )
                )
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return existing.tracking_code

    secret = str(current_app.config.get("TRACKING_SECRET") or os.getenv("TRACKING_SECRET") or "dev-change-me")
    if secret.strip() in ("", "dev-change-me"):
        # En producción debe configurarse.
        current_app.logger.warning("TRACKING_SECRET no configurado; usando valor por defecto")

    base_msg = f"{odoo_order_id}|{order_name}|{id_web or ''}|{datetime.utcnow().isoformat()}"

    # Proteger contra colisiones: reintentar con salt
    for i in range(0, 10):
        msg = base_msg + (f"|{i}" if i else "")
        code = _gen_code(secret, msg)
        if not TrackingShipment.query.filter_by(tracking_code=code).first():
            # Desde 2026-01: al generar la etiqueta dejamos el envío "Listo para despacho"
            # para que el flujo sea automático (Cadete Flex puede escanear inmediatamente).
            sh = TrackingShipment(
                odoo_order_id=int(odoo_order_id),
                order_name=str(order_name or str(odoo_order_id)),
                id_web=(str(id_web) if id_web else None),
                tracking_code=code,
                status="READY_FOR_DISPATCH",
            )
            db.session.add(sh)
            db.session.flush()

            # Guardar historial: se registra creación de etiqueta y luego el estado final automático.
            db.session.add(TrackingEvent(shipment_id=sh.id, event_type="LABEL_CREATED", note="Etiqueta generada"))
            db.session.add(
                TrackingEvent(
                    shipment_id=sh.id,
                    event_type="READY_FOR_DISPATCH",
                    note="Listo para despacho (auto)",
                )
            )

            db.session.commit()
            return code

    raise RuntimeError("tracking_code_collision")


def add_event(
    shipment: TrackingShipment,
    event_type: str,
    note: str | None = None,
    payload: dict | None = None,
    created_by_user_id: int | None = None,
    image_path: str | None = None,
    *,
    commit: bool = True,
) -> TrackingEvent:
    _validate_event(shipment, event_type=event_type, created_by_user_id=created_by_user_id)

    # Snapshot del cadete asignado al momento de ENTREGAR (para que quede visible aunque se limpie courier_user_id).
    if str(event_type).upper() == "DELIVERED":
        if payload is None:
            payload = {}
        if isinstance(payload, dict):
            try:
                if shipment.courier_user_id and "delivered_courier_user_id" not in payload:
                    payload["delivered_courier_user_id"] = int(shipment.courier_user_id)
                    try:
                        from ..models.user import User
                        u = User.query.get(int(shipment.courier_user_id))
                        if u:
                            payload["delivered_courier_name"] = u.full_name
                    except Exception:
                        pass
            except Exception:
                pass

    payload_json = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else None
    # Crear evento y actualizar campos de auditoría/estado
    ev = TrackingEvent(
        shipment_id=shipment.id,
        event_type=str(event_type),
        note=(note or None),
        payload_json=payload_json,
        created_by_user_id=created_by_user_id,
        image_path=image_path,
    )
    db.session.add(ev)

    # Mapear eventos a estados (lo que ve el usuario)
    status_by_event = {
        "LABEL_CREATED": "LABEL_CREATED",
        "PICKING_STARTED": "PICKING_STARTED",
        "READY_FOR_DISPATCH": "READY_FOR_DISPATCH",
        "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
        "ON_ROUTE_TO_DELIVERY": "ON_ROUTE_TO_DELIVERY",
        "BACK_TO_OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
        "DELIVERED": "DELIVERED",
        "DELIVERY_FAILED": "DELIVERY_FAILED",
        "DEFERRED_NEXT_SHIFT": "DEFERRED_NEXT_SHIFT",
        "RETURN_TO_DEPOT_REQUESTED": "RETURN_TO_DEPOT_REQUESTED",
        "RETURNED": "RETURNED",
        "STOCK_MISSING": "STOCK_MISSING",
        "SALES_DECISION": "STOCK_RESOLVED",
    }
    # Actualizar estado del pedido
    shipment.status = status_by_event.get(str(event_type), str(event_type))

    # Actualizar asignaciones en TrackingShipment según el tipo de evento
    try:
        # Para eventos de Depósito: asignar warehouse_user
        if event_type == "PICKING_STARTED" and created_by_user_id:
            shipment.warehouse_user_id = int(created_by_user_id)
            shipment.warehouse_started_at = datetime.utcnow()
        # Para eventos de salida: asignar cadete
        if event_type in {"OUT_FOR_DELIVERY", "ON_ROUTE_TO_DELIVERY"} and created_by_user_id:
            shipment.courier_user_id = int(created_by_user_id)
            # La asignación inicial se registra solo una vez, al salir de depósito
            if event_type == "OUT_FOR_DELIVERY" and shipment.courier_assigned_at is None:
                shipment.courier_assigned_at = datetime.utcnow()
        # Limpiar cadete cuando se entrega o se confirma devolución, o cuando se solicita devolución a depósito
        if event_type in {"DELIVERED", "RETURNED", "RETURN_TO_DEPOT_REQUESTED"}:
            shipment.courier_user_id = None
            shipment.courier_assigned_at = None
    except Exception:
        # No bloquear si hay error al asignar
        pass

    if commit:
        db.session.commit()
    else:
        # Mantener cambios en la transacción actual (para operaciones atómicas)
        db.session.flush()
    return ev


def ventas_override_status(
    shipment: TrackingShipment,
    new_status: str,
    note: str | None = None,
    created_by_user_id: int | None = None,
) -> TrackingEvent:
    """Override de estado SOLO para módulo Ventas.

    Se usa para:
      - Restablecer un pedido a otro estado (por ejemplo después de DELIVERED).
      - Destrabar casos especiales.

    No usa la máquina de estados; deja auditoría en tracking_events.
    """
    prev = str(shipment.status or "").strip() or None
    ns = str(new_status or "").strip()
    if not ns:
        raise ValueError("new_status_required")

    payload = {"prev_status": prev, "new_status": ns}
    ev = TrackingEvent(
        shipment_id=shipment.id,
        event_type="SALES_OVERRIDE",
        note=(note or None),
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_user_id=created_by_user_id,
    )
    shipment.status = ns
    db.session.add(ev)
    db.session.commit()
    return ev


def ventas_reset_to_zero(
    shipment: TrackingShipment,
    note: str | None = None,
    created_by_user_id: int | None = None,
) -> None:
    """Volver a cero: limpia historial (events + scans) y deja el pedido en LABEL_CREATED.

    Mantiene tracking_code y odoo_order_id.
    """
    # borrar scans
    TrackingScan.query.filter_by(shipment_id=shipment.id).delete(synchronize_session=False)
    # borrar events
    TrackingEvent.query.filter_by(shipment_id=shipment.id).delete(synchronize_session=False)
    shipment.status = "LABEL_CREATED"
    db.session.flush()
    # dejar auditoría y recrear evento inicial para que la máquina de estados funcione
    db.session.add(
        TrackingEvent(
            shipment_id=shipment.id,
            event_type="SALES_RESET",
            note=(note or "Reset por Ventas"),
            created_by_user_id=created_by_user_id,
        )
    )
    db.session.add(
        TrackingEvent(
            shipment_id=shipment.id,
            event_type="LABEL_CREATED",
            note="Etiqueta generada (post-reset)",
            created_by_user_id=created_by_user_id,
        )
    )
    db.session.commit()


def record_scan(shipment: TrackingShipment, user_id: int, source: str | None = None) -> None:
    sc = TrackingScan(shipment_id=shipment.id, user_id=int(user_id), source=(source or None))
    db.session.add(sc)
    db.session.commit()
