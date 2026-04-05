from __future__ import annotations

import json
from pathlib import Path

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required, current_user

from . import bp

from ...utils import view_required
from ...extensions import db
from ...models import (
    TrackingShipment,
    FlexCommunity,
    FlexRoute,
    FlexStop,
    FlexStopShipment,    User,
    ViewPermission,
    TrackingEvent,

)
from ...services.flex_service import (
    get_or_seed_default_communities,
    get_active_route_for_user,
    cart_list,
    cart_scan_take,
    cart_remove,
    route_start_from_cart,
    stop_set_arriving,
    shipment_action_with_optional_photo,
    route_finish,
    ensure_snapshot_for_shipment,
    format_address_for_shipment,
    build_nav_urls,
    list_depot_receivers,
    RouteFinishBlocked,
)


@bp.app_context_processor
def _inject_flex_nav():
    """Inyecta ruta activa para renderizar pestañas (scan / reparto / mapa)."""
    try:
        if current_user.is_authenticated:
            return {"flex_active_route": get_active_route_for_user(current_user.id)}
    except Exception:
        pass
    return {"flex_active_route": None}


@bp.get("/")
@login_required
@view_required("cadete_flex")
def home():
    # Si ya hay una ruta activa, ir directo a paradas
    r = get_active_route_for_user(current_user.id)
    if r:
        return redirect(url_for("cadete_flex.route_stops", route_id=r.id))
    return redirect(url_for("cadete_flex.communities"))


@bp.get("/communities")
@login_required
@view_required("cadete_flex")
def communities():
    # Seed simple para no bloquear despliegue nuevo
    get_or_seed_default_communities()
    comms = FlexCommunity.query.filter_by(active=True).order_by(FlexCommunity.name.asc()).all()
    return render_template("flex/communities.html", title="Comunidades", communities=comms)


@bp.get("/scan")
@login_required
@view_required("cadete_flex")
def scan():
    community_id = request.args.get("community_id")
    comm = None
    if community_id:
        comm = FlexCommunity.query.get(int(community_id))
    return render_template(
        "flex/scan.html",
        title="Escanear",
        community=comm,
    )


@bp.get("/routes/<int:route_id>/stops")
@login_required
@view_required("cadete_flex")
def route_stops(route_id: int):
    r = FlexRoute.query.get_or_404(route_id)
    if r.cadete_user_id != current_user.id and current_user.role != "admin":
        abort(403)
    stops = FlexStop.query.filter_by(route_id=r.id).order_by(FlexStop.sequence.asc()).all()
    # Enriquecer conteos
    stop_items: list[dict] = []
    for s in stops:
        count = FlexStopShipment.query.filter_by(stop_id=s.id).count()
        stop_items.append({"stop": s, "count": count})
    pending = sum(1 for it in stop_items if (it["stop"].state or "") in ("PENDING", "ARRIVING"))
    stop_dicts = [
        {
            "id": it["stop"].id,
            "sequence": it["stop"].sequence,
            "address_text": it["stop"].address_text,
            "lat": it["stop"].lat,
            "lng": it["stop"].lng,
            "state": it["stop"].state,
            "count": it["count"],
        }
        for it in stop_items
    ]

    return render_template(
        "flex/stops.html",
        title="Paradas",
        route=r,
        stop_items=stop_items,
        pending_count=pending,
        stops_json=stop_dicts,
    )


@bp.get("/routes/<int:route_id>/map")
@login_required
@view_required("cadete_flex")
def route_map(route_id: int):
    r = FlexRoute.query.get_or_404(route_id)
    if r.cadete_user_id != current_user.id and current_user.role != "admin":
        abort(403)
    stops = FlexStop.query.filter_by(route_id=r.id).order_by(FlexStop.sequence.asc()).all()
    stop_dicts = [
        {
            "id": s.id,
            "sequence": s.sequence,
            "address_text": s.address_text,
            "lat": s.lat,
            "lng": s.lng,
            "state": s.state,
        }
        for s in stops
    ]
    return render_template("flex/map.html", title="Mapa", route=r, stops=stop_dicts)


@bp.get("/stops/<int:stop_id>")
@login_required
@view_required("cadete_flex")
def stop_detail(stop_id: int):
    s = FlexStop.query.get_or_404(stop_id)
    r = FlexRoute.query.get_or_404(s.route_id)
    if r.cadete_user_id != current_user.id and current_user.role != "admin":
        abort(403)
    joins = FlexStopShipment.query.filter_by(stop_id=s.id).all()
    shipments = []
    for j in joins:
        sh = TrackingShipment.query.get(j.shipment_id)
        if sh:
            shipments.append(sh)
    shipments.sort(key=lambda x: str(x.id_web or x.order_name or ""))

    # Snapshots (teléfono, nombre, dirección, coords) para UI y navegación
    snapshots_map: dict[int, dict] = {}
    nav_map: dict[int, dict] = {}
    for sh in shipments:
        try:
            snap = ensure_snapshot_for_shipment(sh)
            addr = format_address_for_shipment(sh)
            snapshots_map[sh.id] = {
                "recipient_name": getattr(snap, "recipient_name", None),
                "phone": getattr(snap, "phone", None),
                "address_text": addr,
                "lat": getattr(snap, "lat", None),
                "lng": getattr(snap, "lng", None),
            }
            nav_map[sh.id] = build_nav_urls(
                lat=getattr(snap, "lat", None),
                lng=getattr(snap, "lng", None),
                address_text=addr,
            )
        except Exception:
            snapshots_map[sh.id] = {"recipient_name": None, "phone": None, "address_text": None, "lat": None, "lng": None}
            nav_map[sh.id] = build_nav_urls(None, None, None)
    depot_receivers = list_depot_receivers()

    # Para mostrar "entregado por" en lista (si aplica)
    delivered_by_map = {}
    for sh in shipments:
        if str(getattr(sh, "status", "") or "") != "DELIVERED":
            continue
        ev = (
            TrackingEvent.query.filter_by(shipment_id=sh.id, event_type="DELIVERED")
            .order_by(TrackingEvent.created_at.desc(), TrackingEvent.id.desc())
            .first()
        )
        if ev and ev.created_by:
            delivered_by_map[sh.id] = ev.created_by.full_name or ev.created_by.username

    return render_template(
        "flex/stop_detail.html",
        title="Parada",
        stop=s,
        route=r,
        shipments=shipments,
        snapshots_map=snapshots_map,
        nav_map=nav_map,
        depot_receivers=depot_receivers,
        delivered_by_map=delivered_by_map,
    )


@bp.get("/shipments/<int:shipment_id>")
@login_required
@view_required("cadete_flex")
def shipment_detail(shipment_id: int):
    """Detalle simple del pedido para que el cadete pueda contactar/navegar."""
    sh = TrackingShipment.query.get_or_404(int(shipment_id))

    # Autorizar: admin o shipment incluido en alguna ruta del usuario
    if current_user.role != "admin":
        in_my_route = (
            db.session.query(FlexStopShipment)
            .join(FlexStop, FlexStopShipment.stop_id == FlexStop.id)
            .join(FlexRoute, FlexStop.route_id == FlexRoute.id)
            .filter(FlexStopShipment.shipment_id == sh.id)
            .filter(FlexRoute.cadete_user_id == current_user.id)
            .first()
        )
        if not in_my_route:
            abort(403)

    snap = ensure_snapshot_for_shipment(sh)
    addr = format_address_for_shipment(sh)
    nav = build_nav_urls(getattr(snap, "lat", None), getattr(snap, "lng", None), addr)

    events = (
        TrackingEvent.query.filter_by(shipment_id=sh.id)
        .order_by(TrackingEvent.created_at.desc(), TrackingEvent.id.desc())
        .limit(30)
        .all()
    )

    return render_template(
        "flex/shipment_detail.html",
        title="Detalle",
        shipment=sh,
        snapshot=snap,
        address_text=addr,
        nav=nav,
        events=events,
    )


# -----------------------------
# API JSON
# -----------------------------


@bp.get("/api/cart")
@login_required
@view_required("cadete_flex")
def api_cart_list():
    community_id = request.args.get("community_id")
    cid = int(community_id) if community_id else None
    data = cart_list(current_user.id, community_id=cid)
    return jsonify({"ok": True, **data})


@bp.post("/api/cart/scan")
@login_required
@view_required("cadete_flex")
def api_cart_scan():
    payload = request.get_json(silent=True) or {}
    raw_code = str(payload.get("raw_code") or "").strip()
    source = str(payload.get("source") or "camera").strip()[:16]
    community_id = payload.get("community_id")
    cid = int(community_id) if community_id else None
    if not raw_code:
        return jsonify({"ok": False, "error": "code_required"}), 400
    try:
        res = cart_scan_take(current_user.id, raw_code=raw_code, source=source, community_id=cid)
        return jsonify({"ok": True, **res})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


@bp.post("/api/cart/remove")
@login_required
@view_required("cadete_flex")
def api_cart_remove():
    payload = request.get_json(silent=True) or {}
    shipment_id = payload.get("shipment_id")
    if not shipment_id:
        return jsonify({"ok": False, "error": "shipment_id_required"}), 400
    try:
        cart_remove(current_user.id, shipment_id=int(shipment_id))
        return jsonify({"ok": True})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


@bp.post("/api/route/start")
@login_required
@view_required("cadete_flex")
def api_route_start():
    payload = request.get_json(silent=True) or {}
    community_id = payload.get("community_id")
    cid = int(community_id) if community_id else None
    try:
        r = route_start_from_cart(current_user.id, community_id=cid)
        return jsonify({"ok": True, "route_id": r.id})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


@bp.post("/api/stop/arriving")
@login_required
@view_required("cadete_flex")
def api_stop_arriving():
    payload = request.get_json(silent=True) or {}
    stop_id = payload.get("stop_id")
    if not stop_id:
        return jsonify({"ok": False, "error": "stop_id_required"}), 400
    try:
        stop_set_arriving(current_user.id, stop_id=int(stop_id))
        return jsonify({"ok": True})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400



@bp.post("/api/route/reorder")
@login_required
@view_required("cadete_flex")
def api_route_reorder():
    payload = request.get_json(silent=True) or {}
    route_id = payload.get("route_id")
    stop_ids = payload.get("stop_ids") or []
    if not route_id or not isinstance(stop_ids, list) or not stop_ids:
        return jsonify({"ok": False, "error": "route_id_and_stop_ids_required"}), 400

    r = FlexRoute.query.get(int(route_id))
    if not r:
        return jsonify({"ok": False, "error": "route_not_found"}), 404
    if r.cadete_user_id != current_user.id and current_user.role != "admin":
        return jsonify({"ok": False, "error": "forbidden"}), 403

    # Validar que todas las paradas pertenecen a la ruta
    stops = FlexStop.query.filter(FlexStop.id.in_([int(x) for x in stop_ids])).all()
    stop_set = {s.id for s in stops if s.route_id == r.id}
    if len(stop_set) != len(stop_ids):
        return jsonify({"ok": False, "error": "invalid_stops"}), 400

    # Reasignar secuencia
    seq = 1
    for sid in [int(x) for x in stop_ids]:
        s = next((x for x in stops if x.id == sid), None)
        if not s:
            continue
        s.sequence = seq
        seq += 1

    db.session.commit()
    return jsonify({"ok": True, "count": len(stop_ids)})


@bp.post("/api/route/finish")
@login_required
@view_required("cadete_flex")
def api_route_finish():
    payload = request.get_json(silent=True) or {}
    route_id = payload.get("route_id")
    if not route_id:
        return jsonify({"ok": False, "error": "route_id_required"}), 400
    try:
        route_finish(current_user.id, route_id=int(route_id))
        return jsonify({"ok": True})
    except RouteFinishBlocked as ex:
        out = {"ok": False, "error": ex.error}
        try:
            out.update(ex.payload or {})
        except Exception:
            pass
        return jsonify(out), 409
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


@bp.post("/api/shipment/action")
@login_required
@view_required("cadete_flex")
def api_shipment_action():
    # multipart/form-data para soportar foto opcional
    shipment_id = (request.form.get("shipment_id") or "").strip()
    action = (request.form.get("action") or "").strip()
    note = (request.form.get("note") or "").strip() or None
    stop_id = (request.form.get("stop_id") or "").strip()
    photo = request.files.get("photo")
    delivered_by_user_id = (request.form.get("delivered_by_user_id") or "").strip()
    receiver_relation = (request.form.get("receiver_relation") or "").strip()
    receiver_name = (request.form.get("receiver_name") or "").strip()
    receiver_id = (request.form.get("receiver_id") or "").strip()
    return_to_user_id = (request.form.get("return_to_user_id") or "").strip()
    if not shipment_id or not action:
        return jsonify({"ok": False, "error": "shipment_id_and_action_required"}), 400
    try:
        ev = shipment_action_with_optional_photo(
            current_user.id,
            shipment_id=int(shipment_id),
            action=action,
            note=note,
            photo=photo,
            delivered_by_user_id=int(delivered_by_user_id) if delivered_by_user_id else None,
            receiver_relation=receiver_relation or None,
            receiver_name=receiver_name or None,
            receiver_id=receiver_id or None,
            stop_id=int(stop_id) if stop_id else None,
            return_to_user_id=int(return_to_user_id) if return_to_user_id else None,
        )
        return jsonify({"ok": True, "event_id": ev.id})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


# ---------------------------------------------------------------------------
# Additional JSON API endpoints for React frontend
#
# The new React frontend for the cadete flex module expects a small set of
# convenience endpoints that wrap the existing service functions.  These
# endpoints provide JSON payloads instead of server rendered HTML.  They
# intentionally mirror the names used in the frontend (e.g. routes/current,
# routes/start, communities, stops/<id>, shipments/<id>/event) and should
# not conflict with the existing cart/route/shipment APIs above.


@bp.get("/api/communities")
@login_required
@view_required("cadete_flex")
def api_flex_communities() -> tuple[object, int] | object:
    """Return a list of active communities for cadetes.

    The React client displays a list of communities when the user does not
    already have an active route.  We seed a set of default communities if
    none exist.  The response is always JSON with an array of objects
    containing ``id`` and ``name``.
    """
    # Ensure there is at least one community available
    try:
        get_or_seed_default_communities()
    except Exception:
        # ignore seeding errors and continue; query will simply return empty
        pass
    comms = (
        FlexCommunity.query.filter_by(active=True)
        .order_by(FlexCommunity.name.asc())
        .all()
    )
    items = [{"id": c.id, "name": c.name} for c in comms]
    return jsonify({"ok": True, "items": items})


@bp.get("/api/routes/current")
@login_required
@view_required("cadete_flex")
def api_flex_route_current() -> tuple[object, int] | object:
    """Return the currently active route and its stops for the user.

    If the user has no active route, the ``route`` field will be null and
    the caller should prompt for community selection.  Each stop contains
    its id, sequence number, address text, state and the number of
    shipments assigned to that stop.
    """
    r = get_active_route_for_user(current_user.id)
    if not r:
        return jsonify({"ok": True, "route": None, "stops": []})
    # Collect basic stop info and counts
    stops = (
        FlexStop.query.filter_by(route_id=r.id)
        .order_by(FlexStop.sequence.asc())
        .all()
    )
    items = []
    for s in stops:
        count = FlexStopShipment.query.filter_by(stop_id=s.id).count()
        items.append(
            {
                "id": s.id,
                "sequence": s.sequence,
                "address_text": s.address_text,
                "lat": s.lat,
                "lng": s.lng,
                "state": s.state,
                "count": count,
            }
        )
    # Fetch community name, if available
    comm_name = None
    if r.community_id:
        try:
            comm = FlexCommunity.query.get(r.community_id)
            comm_name = comm.name if comm else None
        except Exception:
            comm_name = None
    return jsonify({
        "ok": True,
        "route": {"id": r.id, "community_id": r.community_id, "community_name": comm_name},
        "stops": items,
    })


@bp.post("/api/routes/start")
@login_required
@view_required("cadete_flex")
def api_flex_route_start() -> tuple[object, int] | object:
    """Start a new delivery route from the user's cart.

    The request body should include ``community_id`` (optional) to scope
    the route to a particular community.  On success the new route and its
    stops are returned; if there is an error (for example, the cart is
    empty) an ``ok: false`` response with ``error`` is sent.
    """
    payload = request.get_json(silent=True) or {}
    community_id = payload.get("community_id")
    cid = int(community_id) if community_id not in (None, "") else None
    try:
        r = route_start_from_cart(current_user.id, community_id=cid)
    except ValueError as ex:
        # propagate error to client
        return jsonify({"ok": False, "error": str(ex)}), 400
    # Build response with stop list
    stops = (
        FlexStop.query.filter_by(route_id=r.id)
        .order_by(FlexStop.sequence.asc())
        .all()
    )
    items = []
    for s in stops:
        count = FlexStopShipment.query.filter_by(stop_id=s.id).count()
        items.append(
            {
                "id": s.id,
                "sequence": s.sequence,
                "address_text": s.address_text,
                "lat": s.lat,
                "lng": s.lng,
                "state": s.state,
                "count": count,
            }
        )
    # Fetch community name
    comm_name = None
    if r.community_id:
        try:
            comm = FlexCommunity.query.get(r.community_id)
            comm_name = comm.name if comm else None
        except Exception:
            comm_name = None
    return jsonify({
        "ok": True,
        "route": {"id": r.id, "community_id": r.community_id, "community_name": comm_name},
        "stops": items,
    })


@bp.get("/api/stops/<int:stop_id>")
@login_required
@view_required("cadete_flex")
def api_flex_stop_detail(stop_id: int) -> tuple[object, int] | object:
    """Return details for a stop and its shipments.

    The stop must belong to the active route of the user (or the user
    must be admin).  The payload contains a minimal stop object and
    an array of shipments assigned to that stop.  Each shipment includes
    id, order_name, id_web, tracking_code and status.
    """
    s = FlexStop.query.get_or_404(int(stop_id))
    r = FlexRoute.query.get_or_404(s.route_id)
    # Authorize: only the cadete assigned or admin may view
    if r.cadete_user_id != current_user.id and current_user.role != "admin":
        abort(403)
    # Gather shipments
    joins = FlexStopShipment.query.filter_by(stop_id=s.id).all()
    shipments_list: list[dict] = []
    for j in joins:
        sh = TrackingShipment.query.get(j.shipment_id)
        if sh:
            shipments_list.append(
                {
                    "id": sh.id,
                    "order_name": getattr(sh, "order_name", None),
                    "id_web": getattr(sh, "id_web", None),
                    "tracking_code": getattr(sh, "tracking_code", None),
                    "status": getattr(sh, "status", None),
                }
            )
    # Sort by order_name/id_web for consistency
    shipments_list.sort(key=lambda x: str(x.get("id_web") or x.get("order_name") or ""))
    return jsonify(
        {
            "ok": True,
            "stop": {
                "id": s.id,
                "sequence": s.sequence,
                "address_text": s.address_text,
                "lat": s.lat,
                "lng": s.lng,
                "state": s.state,
            },
            "shipments": shipments_list,
        }
    )


@bp.post("/api/shipments/<int:shipment_id>/event")
@login_required
@view_required("cadete_flex")
def api_flex_shipment_event(shipment_id: int) -> tuple[object, int] | object:
    """Record an event (e.g. delivered/not delivered) for a shipment.

    The payload must include ``action`` (event type).  An optional
    ``stop_id`` may be provided to associate the event with a specific
    stop.  Other optional fields (note, delivered_by_user_id, etc.) are
    ignored for now but could be extended in future.  Returns the
    created event id.
    """
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()
    stop_id = payload.get("stop_id")
    note = (payload.get("note") or "").strip() or None
    if not shipment_id or not action:
        return jsonify({"ok": False, "error": "shipment_id_and_action_required"}), 400
    try:
        ev = shipment_action_with_optional_photo(
            current_user.id,
            shipment_id=int(shipment_id),
            action=action,
            note=note,
            photo=None,
            delivered_by_user_id=None,
            receiver_relation=None,
            receiver_name=None,
            receiver_id=None,
            stop_id=int(stop_id) if stop_id else None,
            return_to_user_id=None,
        )
        return jsonify({"ok": True, "event_id": ev.id})
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400
