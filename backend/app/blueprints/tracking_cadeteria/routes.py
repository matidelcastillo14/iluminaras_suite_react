from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import render_template, request, abort, jsonify, current_app
from flask_login import login_required, current_user

from . import bp
from ...models import TrackingShipment, TrackingEvent
from ...utils import view_required
from ...services.tracking_service import add_event
from ...services import etiquetas_legacy_engine
from ...services.tracking_labels import label_status


def _configure_engine():
    etiquetas_legacy_engine.configure(
        current_app.config,
        root_path=str(Path(current_app.root_path).parent),
        logger=current_app.logger,
    )


def _shipment_by_code(code: str) -> TrackingShipment:
    code = (code or "").strip()
    if not code:
        abort(404)
    sh = TrackingShipment.query.filter_by(tracking_code=code).first()
    if not sh:
        abort(404)
    return sh


@bp.get("")
@login_required
@view_required("rastreo_cadeteria")
def index():
    # UI nueva para cadetería, sin tocar RastreoCadetería existente.
    return render_template("tracking_cadeteria/index.html", title="TrackingCadetería")


@bp.get("/pedido/<tracking_code>")
@login_required
@view_required("rastreo_cadeteria")
def pedido(tracking_code: str):
    sh = _shipment_by_code(tracking_code)
    _configure_engine()
    try:
        order = etiquetas_legacy_engine._odoo_order_detail(sh.odoo_order_id)
    except Exception:
        order = {"pedido": sh.order_name, "direccion": "", "telefono": ""}
    events = TrackingEvent.query.filter_by(shipment_id=sh.id).order_by(TrackingEvent.created_at.desc()).limit(50).all()
    return render_template(
        "tracking_cadeteria/pedido.html",
        title=f"Pedido {sh.order_name}",
        shipment=sh,
        order=order,
        events=events,
        status_label=label_status(sh.status),
    )


@bp.get("/api/order_detail")
@login_required
@view_required("rastreo_cadeteria")
def api_order_detail():
    code = (request.args.get("code") or "").strip()
    sh = _shipment_by_code(code)
    _configure_engine()
    try:
        order = etiquetas_legacy_engine._odoo_order_detail(sh.odoo_order_id)
    except Exception:
        order = {"pedido": sh.order_name, "direccion": "", "telefono": "", "observaciones": ""}
    return jsonify(
        {
            "ok": True,
            "shipment": {
                "tracking_code": sh.tracking_code,
                "order_name": sh.order_name,
                "status": sh.status,
                "status_label": label_status(sh.status),
            },
            "order": order,
        }
    )


@bp.post("/api/retry")
@login_required
@view_required("rastreo_cadeteria")
def api_retry():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    note = (data.get("note") or "").strip() or "Reintento de entrega"
    sh = _shipment_by_code(code)

    # Sólo tiene sentido reintentar si quedó como DELIVERY_FAILED
    if sh.status != "DELIVERY_FAILED":
        return jsonify({"ok": False, "error": "invalid_status"}), 400

    try:
        add_event(sh, event_type="OUT_FOR_DELIVERY", note=note, created_by_user_id=current_user.id)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400

    return jsonify(
        {
            "ok": True,
            "shipment": {
                "tracking_code": sh.tracking_code,
                "order_name": sh.order_name,
                "status": sh.status,
                "status_label": label_status(sh.status),
            },
        }
    )
