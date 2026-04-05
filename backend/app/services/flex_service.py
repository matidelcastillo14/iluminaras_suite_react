from __future__ import annotations

import json
import os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    FlexCommunity,
    FlexAssignment,
    FlexRoute,
    FlexStop,
    FlexStopShipment,
    FlexShipmentSnapshot,
    TrackingShipment,
    TrackingEvent,
    TrackingScan,
    User,
)
from .tracking_service import add_event
from .odoo_readonly import get_order_full


BRAND_COLOR_DEFAULT = "#49C8C4"


class RouteFinishBlocked(ValueError):
    """Se usa para bloquear finalizar ruta cuando hay pedidos pendientes.

    error:
      - pending_shipments: hay pedidos todavía en reparto (sin resolver)
      - pending_decisions: hay pedidos NO ENTREGADOS que requieren decisión
    payload: datos para UI
    """

    def __init__(self, error: str, payload: dict):
        super().__init__(error)
        self.error = error
        self.payload = payload


def list_depot_receivers() -> list[dict]:
    """Usuarios a los que se puede devolver a depósito (rol deposito o admin)."""
    rows = (
        User.query.filter(User.is_active == True)
        .filter(User.role.in_(["deposito", "admin"]))
        .order_by(User.role.desc(), User.username.asc())
        .all()
    )
    out = []
    for u in rows:
        out.append({
            "id": u.id,
            "label": (u.full_name or u.username or str(u.id)),
            "role": (u.role or ""),
        })
    return out



def get_or_seed_default_communities() -> None:
    """Seed mínimo para que el módulo funcione en una instalación nueva.

    Si ya existen comunidades, no hace nada.
    """
    if FlexCommunity.query.first():
        return
    defaults = [
        ("default", "General"),
    ]
    for code, name in defaults:
        db.session.add(FlexCommunity(code=code, name=name, active=True, color_hex=BRAND_COLOR_DEFAULT))
    db.session.commit()


def get_active_route_for_user(user_id: int) -> FlexRoute | None:
    return (
        FlexRoute.query.filter_by(cadete_user_id=int(user_id))
        .filter(FlexRoute.state.in_(["DRAFT", "EN_ROUTE"]))
        .order_by(FlexRoute.created_at.desc(), FlexRoute.id.desc())
        .first()
    )


def _shipment_by_any_code(raw_code: str) -> TrackingShipment | None:
    """Soporta QR con:
    - código de tracking (tracking_code)
    - URL /rastreo/go/<code>
    - referencia de pedido Odoo (order_name, típico 'S...') o id_web
    """
    code = (raw_code or "").strip()
    if "/rastreo/go/" in code:
        try:
            code = code.split("/rastreo/go/")[-1].split("?")[0].strip("/")
        except Exception:
            pass

    if not code:
        return None

    # 1) tracking_code (compatibilidad)
    sh = TrackingShipment.query.filter_by(tracking_code=code).first()
    if sh:
        return sh

    # 2) order_name (S000123)
    sh = TrackingShipment.query.filter_by(order_name=code).first()
    if sh:
        return sh

    # 3) id_web (si se usa como código)
    return TrackingShipment.query.filter_by(id_web=code).first()


def _ensure_snapshot_for_shipment(sh: TrackingShipment) -> FlexShipmentSnapshot:
    snap = FlexShipmentSnapshot.query.get(sh.id)
    now = datetime.utcnow()
    if snap and snap.updated_at and (now - snap.updated_at).total_seconds() < 3600:
        return snap

    try:
        data = get_order_full(sh.odoo_order_id)
        p = data.get("partner") or {}
        snap = snap or FlexShipmentSnapshot(shipment_id=sh.id)
        snap.recipient_name = p.get("name")
        snap.phone = p.get("phone")
        snap.street = p.get("street")
        snap.street2 = p.get("street2")
        snap.city = p.get("city")
        snap.zip = p.get("zip")
        # Coordenadas (si vienen desde Odoo)
        lat = p.get("partner_latitude") or p.get("latitude") or p.get("lat") or p.get("geo_lat") or p.get("x_lat")
        lng = p.get("partner_longitude") or p.get("longitude") or p.get("lng") or p.get("geo_lng") or p.get("x_lng")
        try:
            snap.lat = float(lat) if lat not in (None, "") else None
        except Exception:
            snap.lat = None
        try:
            snap.lng = float(lng) if lng not in (None, "") else None
        except Exception:
            snap.lng = None
        snap.raw_json = json.dumps(data, ensure_ascii=False)
        snap.updated_at = now
        db.session.merge(snap)
        db.session.commit()
        return snap
    except Exception:
        # Odoo no disponible: snapshot mínimo
        snap = snap or FlexShipmentSnapshot(shipment_id=sh.id)
        snap.raw_json = None
        snap.updated_at = now
        db.session.merge(snap)
        db.session.commit()
        return snap


def _format_address(snap: FlexShipmentSnapshot | None, sh: TrackingShipment) -> str:
    if snap:
        parts = [
            (snap.street or "").strip(),
            (snap.street2 or "").strip(),
            (snap.city or "").strip(),
            (snap.zip or "").strip(),
        ]
        parts = [p for p in parts if p]
        if parts:
            return ", ".join(parts)
    # fallback: sin dirección
    return f"Pedido {sh.id_web or sh.order_name} (sin dirección)"


# ------------------------------------------------------------
# Helpers públicos para vistas
# ------------------------------------------------------------


def ensure_snapshot_for_shipment(sh: TrackingShipment) -> FlexShipmentSnapshot:
    """Wrapper público (útil desde routes/templates)."""
    return _ensure_snapshot_for_shipment(sh)


def format_address_for_shipment(sh: TrackingShipment) -> str:
    """Dirección legible para mostrar en UI."""
    snap = FlexShipmentSnapshot.query.get(sh.id)
    if not snap:
        snap = _ensure_snapshot_for_shipment(sh)
    return _format_address(snap, sh)


def build_nav_urls(lat: float | None, lng: float | None, address_text: str | None) -> dict:
    """Devuelve URLs para navegación (Google Maps / Waze).

    - Si hay coordenadas se usan.
    - Si no, se usa texto de dirección.
    """
    addr = (address_text or "").strip()
    if lat is not None and lng is not None:
        ll = f"{lat},{lng}"
        return {
            "google": f"https://www.google.com/maps/search/?api=1&query={ll}",
            "waze": f"https://waze.com/ul?ll={ll}&navigate=yes",
        }
    if addr:
        from urllib.parse import quote_plus

        q = quote_plus(addr)
        return {
            "google": f"https://www.google.com/maps/search/?api=1&query={q}",
            "waze": f"https://waze.com/ul?q={q}&navigate=yes",
        }
    return {"google": "https://www.google.com/maps", "waze": "https://waze.com"}


def cart_list(user_id: int, community_id: int | None = None) -> dict:
    q = FlexAssignment.query.filter_by(cadete_user_id=int(user_id)).filter(FlexAssignment.state == "IN_CART")
    if community_id:
        q = q.filter(FlexAssignment.community_id == int(community_id))
    rows = q.order_by(FlexAssignment.created_at.asc(), FlexAssignment.id.asc()).all()
    items = []
    for a in rows:
        sh = TrackingShipment.query.get(a.shipment_id)
        if not sh:
            continue
        items.append(
            {
                "shipment_id": sh.id,
                "id_web": sh.id_web,
                "order_name": sh.order_name,
                "tracking_code": sh.tracking_code,
                "status": sh.status,
            }
        )
    return {"count": len(items), "items": items}


def cart_scan_take(user_id: int, raw_code: str, source: str = "camera", community_id: int | None = None) -> dict:
    try:
        sh = _shipment_by_any_code(raw_code)
        if not sh:
            raise ValueError("not_found")

        # Registrar scan (auditoría)
        db.session.add(TrackingScan(shipment_id=sh.id, user_id=int(user_id), source=source))
        db.session.flush()

        # Validar estado para tomar
        if str(sh.status or "").strip() != "READY_FOR_DISPATCH":
            raise ValueError("not_ready_for_dispatch")

        # Si ya hay ruta activa, el escaneo agrega directo a esa ruta.
        active_route = get_active_route_for_user(int(user_id))

        existing = FlexAssignment.query.filter_by(shipment_id=sh.id).first()
        if existing and existing.state != "RELEASED":
            if existing.cadete_user_id == int(user_id):
                # Si ya está en ruta, reportar como duplicado
                if existing.state == "IN_ROUTE":
                    return {
                        "added": False,
                        "already_in_route": True,
                        "shipment": _shipment_payload(sh),
                        "route_id": active_route.id if active_route else None,
                    }
                # En carrito
                data = cart_list(user_id, community_id=community_id)
                return {"added": False, "shipment": _shipment_payload(sh), **data}
            u = User.query.get(existing.cadete_user_id)
            raise ValueError(f"already_assigned:{(u.full_name if u else existing.cadete_user_id)}")

        if active_route:
            # Agregar directo a ruta activa
            stop = _route_add_shipment(active_route, sh, user_id=int(user_id))

            # Marcar assignment IN_ROUTE
            if existing and existing.state == "RELEASED":
                existing.cadete_user_id = int(user_id)
                existing.community_id = int(community_id) if community_id else None
                existing.state = "IN_ROUTE"
                existing.released_at = None
            else:
                a = FlexAssignment(
                    shipment_id=sh.id,
                    cadete_user_id=int(user_id),
                    community_id=int(community_id) if community_id else None,
                    state="IN_ROUTE",
                )
                db.session.add(a)

            db.session.commit()
            return {
                "added": True,
                "added_to_route": True,
                "route_id": active_route.id,
                "stop_id": stop.id,
                "shipment": _shipment_payload(sh),
            }

        if existing and existing.state == "RELEASED":
            # Reutilizar registro
            existing.cadete_user_id = int(user_id)
            existing.community_id = int(community_id) if community_id else None
            existing.state = "IN_CART"
            existing.released_at = None
        else:
            # Crear assignment
            a = FlexAssignment(
                shipment_id=sh.id,
                cadete_user_id=int(user_id),
                community_id=int(community_id) if community_id else None,
                state="IN_CART",
            )
            db.session.add(a)

        db.session.commit()
        data = cart_list(user_id, community_id=community_id)
        return {"added": True, "shipment": _shipment_payload(sh), **data}
    except Exception:
        db.session.rollback()
        raise


def _route_add_shipment(route: FlexRoute, sh: TrackingShipment, user_id: int) -> FlexStop:
    """Agrega un shipment a una ruta activa.

    Crea parada si no existe (agrupa por address_text).
    """
    snap = _ensure_snapshot_for_shipment(sh)
    addr = _format_address(snap, sh)
    # buscar parada existente por dirección exacta
    stop = (
        FlexStop.query.filter_by(route_id=route.id)
        .filter(FlexStop.address_text == addr)
        .order_by(FlexStop.sequence.asc())
        .first()
    )
    if not stop:
        max_seq = db.session.query(db.func.max(FlexStop.sequence)).filter_by(route_id=route.id).scalar() or 0
        stop = FlexStop(
            route_id=route.id,
            sequence=int(max_seq) + 1,
            address_text=addr,
            state="PENDING",
            lat=getattr(snap, "lat", None),
            lng=getattr(snap, "lng", None),
        )
        db.session.add(stop)
        db.session.flush()

    # link stop-shipment (idempotente)
    exists = FlexStopShipment.query.filter_by(stop_id=stop.id, shipment_id=sh.id).first()
    if not exists:
        db.session.add(FlexStopShipment(stop_id=stop.id, shipment_id=sh.id))

    # Transición tracking: OUT_FOR_DELIVERY
    try:
        add_event(sh, "OUT_FOR_DELIVERY", note="Salida a reparto (Flex - agregado)", created_by_user_id=int(user_id))
    except Exception as ex:
        # Propagar mensaje claro
        raise ValueError(str(ex))

    return stop


def cart_remove(user_id: int, shipment_id: int) -> None:
    a = (
        FlexAssignment.query.filter_by(cadete_user_id=int(user_id), shipment_id=int(shipment_id))
        .filter(FlexAssignment.state == "IN_CART")
        .first()
    )
    if not a:
        raise ValueError("not_in_cart")
    a.state = "RELEASED"
    a.released_at = datetime.utcnow()
    db.session.commit()


def route_start_from_cart(user_id: int, community_id: int | None = None) -> FlexRoute:
    try:
        # no permitir dos rutas activas
        if get_active_route_for_user(user_id):
            raise ValueError("route_already_active")

        q = FlexAssignment.query.filter_by(cadete_user_id=int(user_id)).filter(FlexAssignment.state == "IN_CART")
        if community_id:
            q = q.filter(FlexAssignment.community_id == int(community_id))
        assigns = q.order_by(FlexAssignment.created_at.asc()).all()
        if not assigns:
            raise ValueError("cart_empty")

        # Crear ruta
        r = FlexRoute(cadete_user_id=int(user_id), community_id=int(community_id) if community_id else None, state="EN_ROUTE")
        r.started_at = datetime.utcnow()
        db.session.add(r)
        db.session.flush()

        # Agrupar por dirección
        groups: "OrderedDict[str, dict]" = OrderedDict()  # addr -> {ship_ids:[], lat:float|None, lng:float|None}
        for a in assigns:
            sh = TrackingShipment.query.get(a.shipment_id)
            if not sh:
                continue
            snap = _ensure_snapshot_for_shipment(sh)
            addr = _format_address(snap, sh)
            g = groups.setdefault(addr, {"ship_ids": [], "lat": None, "lng": None})
            g["ship_ids"].append(sh.id)
            if g.get("lat") is None and getattr(snap, "lat", None) is not None:
                g["lat"] = snap.lat
            if g.get("lng") is None and getattr(snap, "lng", None) is not None:
                g["lng"] = snap.lng

        # Crear paradas
        seq = 1
        for addr, g in groups.items():
            s = FlexStop(route_id=r.id, sequence=seq, address_text=addr, state="PENDING", lat=g.get("lat"), lng=g.get("lng"))
            ship_ids = g.get("ship_ids") or []
            db.session.add(s)
            db.session.flush()
            for sid in ship_ids:
                db.session.add(FlexStopShipment(stop_id=s.id, shipment_id=sid))
            seq += 1

        # Transición tracking: OUT_FOR_DELIVERY para cada shipment
        for a in assigns:
            sh = TrackingShipment.query.get(a.shipment_id)
            if not sh:
                continue
            try:
                add_event(sh, "OUT_FOR_DELIVERY", note="Salida a reparto (Flex)", created_by_user_id=int(user_id))
            except Exception as ex:
                # Si falla por transición, abortar todo
                raise ValueError(str(ex))
            a.state = "IN_ROUTE"

        db.session.commit()
        return r
    except Exception:
        db.session.rollback()
        raise


def stop_set_arriving(user_id: int, stop_id: int) -> None:
    s = FlexStop.query.get(int(stop_id))
    if not s:
        raise ValueError("stop_not_found")
    r = FlexRoute.query.get(s.route_id)
    if not r or (r.cadete_user_id != int(user_id) and _role(user_id) != "admin"):
        raise ValueError("forbidden")

    if s.state != "ARRIVING":
        s.state = "ARRIVING"

    joins = FlexStopShipment.query.filter_by(stop_id=s.id).all()
    for j in joins:
        sh = TrackingShipment.query.get(j.shipment_id)
        if not sh:
            continue
        # Idempotente: si ya está en ON_ROUTE..., add_event lo bloqueará como duplicate
        try:
            add_event(sh, "ON_ROUTE_TO_DELIVERY", note="Estoy llegando (Flex)", created_by_user_id=int(user_id))
        except Exception:
            pass

    db.session.commit()


def _role(user_id: int) -> str:
    u = User.query.get(int(user_id))
    return str(getattr(u, "role", "") or "")


def _shipment_payload(sh: TrackingShipment) -> dict:
    return {
        "shipment_id": sh.id,
        "id_web": sh.id_web,
        "order_name": sh.order_name,
        "tracking_code": sh.tracking_code,
        "status": sh.status,
    }


def _save_event_photo(shipment_id: int, photo: FileStorage, event_type: str) -> str:
    if not photo:
        raise ValueError("photo_required")
    if not (photo.mimetype or "").startswith("image/"):
        raise ValueError("invalid_photo_type")

    gen_base = Path(current_app.root_path).parent / current_app.config.get("GENERATED_DIR", "generated") / "tracking_photos"
    gen_base.mkdir(parents=True, exist_ok=True)
    sub = gen_base / str(int(shipment_id))
    sub.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fn = secure_filename(photo.filename or "photo.jpg")
    if not fn:
        fn = "photo.jpg"
    # Forzar extensión razonable
    base, ext = os.path.splitext(fn)
    ext = (ext or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    out_name = f"{event_type}_{ts}{ext}"
    out_path = sub / out_name
    photo.save(str(out_path))
    # path relativo para /rastreo/photo?p=
    rel = f"{int(shipment_id)}/{out_name}"
    return rel


def _detach_from_route_links(shipment_id: int, stop_id: int | None = None) -> None:
    if stop_id:
        FlexStopShipment.query.filter_by(stop_id=int(stop_id), shipment_id=int(shipment_id)).delete(synchronize_session=False)
    else:
        FlexStopShipment.query.filter_by(shipment_id=int(shipment_id)).delete(synchronize_session=False)
    db.session.flush()


def _move_assignment_to_cart(user_id: int, shipment_id: int) -> None:
    a = (
        FlexAssignment.query.filter_by(shipment_id=int(shipment_id))
        .filter(FlexAssignment.state != "RELEASED")
        .first()
    )
    if not a:
        return
    a.cadete_user_id = int(user_id)
    a.state = "IN_CART"
    a.released_at = None
    db.session.flush()


def shipment_action_with_optional_photo(
    user_id: int,
    shipment_id: int,
    action: str,
    note: str | None,
    photo: FileStorage | None,
    delivered_by_user_id: int | None = None,  # legacy (ignorado en Flex)
    receiver_relation: str | None = None,
    receiver_name: str | None = None,
    receiver_id: str | None = None,
    stop_id: int | None = None,
    return_to_user_id: int | None = None,
) -> TrackingEvent:
    sh = TrackingShipment.query.get(int(shipment_id))
    if not sh:
        raise ValueError("shipment_not_found")

    action = (action or "").strip().upper()
    # OUT_FOR_DELIVERY se usa para "reintentar" cuando se marcó NO ENTREGADO.
    if action not in {"DELIVERED", "DELIVERY_FAILED", "RETURNED", "OUT_FOR_DELIVERY", "DEFERRED_NEXT_SHIFT", "RETURN_TO_DEPOT_REQUESTED"}:
        raise ValueError("invalid_action")

    # Guardar foto si viene
    image_path = None
    if photo and (photo.filename or ""):
        image_path = _save_event_photo(sh.id, photo, event_type=action)

    payload: dict = {}
    if stop_id:
        payload["stop_id"] = int(stop_id)
    payload["source"] = "cadete_flex"

    if action == "DELIVERED":
        # Campos obligatorios al entregar
        rr = (receiver_relation or "").strip()
        rn = (receiver_name or "").strip()
        rid = (receiver_id or "").strip()
        if not rr or not rn or not rid:
            raise ValueError("receiver_required")
        payload["receiver_relation"] = rr
        payload["receiver_name"] = rn
        payload["receiver_id"] = rid

    # Defaults de notas
    if action == "OUT_FOR_DELIVERY" and not note:
        note = "Reintento de entrega (Flex)"
    if action == "DEFERRED_NEXT_SHIFT" and not note:
        note = "Pendiente para siguiente turno (Flex)"
    if action == "RETURN_TO_DEPOT_REQUESTED":
        if not return_to_user_id:
            raise ValueError("return_to_user_required")
        payload["return_to_user_id"] = int(return_to_user_id)
        if not note:
            note = "Devuelto a depósito (pendiente de confirmación)"

    try:
        ev = add_event(
            sh,
            action,
            note=note,
            payload=payload,
            created_by_user_id=int(user_id),
            image_path=image_path,
        )
    except Exception as ex:
        raise ValueError(str(ex))

    # Acciones post-evento (Flex)
    if action in {"DELIVERED", "RETURNED"}:
        _release_assignment(sh.id)

    # En devolución solicitada, el pedido deja de ser del cadete (se libera).
    if action == "RETURN_TO_DEPOT_REQUESTED":
        _release_assignment(sh.id)
        _detach_from_route_links(sh.id, stop_id=stop_id)

    # Para siguiente turno: queda en carrito del mismo cadete para próxima ruta.
    if action == "DEFERRED_NEXT_SHIFT":
        _move_assignment_to_cart(int(user_id), sh.id)
        _detach_from_route_links(sh.id, stop_id=stop_id)

    # Reintento programado desde modal de finalizar ruta (sin stop_id): mover a carrito.
    if action == "OUT_FOR_DELIVERY" and not stop_id:
        _move_assignment_to_cart(int(user_id), sh.id)
        _detach_from_route_links(sh.id, stop_id=None)

    # actualizar estado de parada si corresponde
    if stop_id and action in {"DELIVERED", "RETURNED", "DELIVERY_FAILED", "DEFERRED_NEXT_SHIFT", "RETURN_TO_DEPOT_REQUESTED"}:
        _update_stop_state(int(stop_id))

    db.session.commit()
    return ev


def _release_assignment(shipment_id: int) -> None:
    a = FlexAssignment.query.filter_by(shipment_id=int(shipment_id)).filter(FlexAssignment.state != "RELEASED").first()
    if not a:
        return
    a.state = "RELEASED"
    a.released_at = datetime.utcnow()
    db.session.commit()


def _update_stop_state(stop_id: int) -> None:
    s = FlexStop.query.get(int(stop_id))
    if not s:
        return
    joins = FlexStopShipment.query.filter_by(stop_id=s.id).all()
    all_done = True
    for j in joins:
        sh = TrackingShipment.query.get(j.shipment_id)
        if not sh:
            continue
        if sh.status not in {"DELIVERED", "RETURNED", "DELIVERY_FAILED", "DEFERRED_NEXT_SHIFT", "RETURN_TO_DEPOT_REQUESTED"}:
            all_done = False
            break
    if all_done:
        s.state = "DONE"
        db.session.commit()


def route_finish(user_id: int, route_id: int) -> None:
    r = FlexRoute.query.get(int(route_id))
    if not r:
        raise ValueError("route_not_found")
    if r.cadete_user_id != int(user_id) and _role(user_id) != "admin":
        raise ValueError("forbidden")

    # Listar shipments de la ruta (stop -> shipment)
    rows = (
        db.session.query(
            TrackingShipment,
            FlexStop.id.label("stop_id"),
            FlexStop.address_text.label("address_text"),
        )
        .join(FlexStopShipment, FlexStopShipment.shipment_id == TrackingShipment.id)
        .join(FlexStop, FlexStopShipment.stop_id == FlexStop.id)
        .filter(FlexStop.route_id == r.id)
        .all()
    )

    resolved_statuses = {"DELIVERED", "RETURNED", "DEFERRED_NEXT_SHIFT", "RETURN_TO_DEPOT_REQUESTED"}
    pending_shipments = []
    pending_decisions = []
    for sh, stop_id, addr in rows:
        status = str(sh.status or "").strip()
        item = {
            "shipment_id": sh.id,
            "id_web": sh.id_web,
            "order_name": sh.order_name,
            "tracking_code": sh.tracking_code,
            "status": status,
            "stop_id": int(stop_id) if stop_id else None,
            "address_text": addr,
        }
        if status == "DELIVERY_FAILED":
            pending_decisions.append(item)
        elif status not in resolved_statuses:
            pending_shipments.append(item)

    if pending_shipments:
        raise RouteFinishBlocked("pending_shipments", {"pending_shipments": pending_shipments})

    if pending_decisions:
        raise RouteFinishBlocked(
            "pending_decisions",
            {
                "pending_decisions": pending_decisions,
                "depot_receivers": list_depot_receivers(),
            },
        )

    r.state = "FINISHED"
    r.finished_at = datetime.utcnow()
    db.session.commit()
