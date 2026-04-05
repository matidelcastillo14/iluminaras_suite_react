from __future__ import annotations

import os
import json
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app, send_file, abort, url_for
from flask_login import login_required

from ...models import PdfTemplate
from ...services import etiquetas_legacy_engine
from ...services.layout_renderer import render_layout_pdf
from ...utils import view_required
from ...services.tracking_service import ensure_tracking_for_order

bp = Blueprint("etiquetas", __name__, url_prefix="/etiquetas")

def _configure_engine():
    etiquetas_legacy_engine.configure(current_app.config, root_path=str(Path(current_app.root_path).parent), logger=current_app.logger)

@bp.get("/")
@login_required
@view_required("etiquetas")
def index():
    return render_template("embed.html", iframe_src="/_legacy/etiquetas/")


@bp.get("/api/orders/search")
@login_required
@view_required("etiquetas")
def api_orders_search():
    _configure_engine()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        rows = etiquetas_legacy_engine._odoo_search_orders(q)
        return jsonify(rows)
    except Exception as ex:
        return jsonify({"error":"odoo_error","detail":str(ex)}), 503

@bp.get("/api/orders/<int:order_id>")
@login_required
@view_required("etiquetas")
def api_order_detail(order_id: int):
    _configure_engine()
    try:
        d = etiquetas_legacy_engine._odoo_order_detail(order_id)
        return jsonify(d)
    except KeyError:
        return jsonify({"error":"not_found"}), 404
    except Exception as ex:
        return jsonify({"error":"odoo_error","detail":str(ex)}), 503

@bp.post("/generate")
@login_required
@view_required("etiquetas")
def generate():
    _configure_engine()
    try:
        order_id = int(request.form.get("order_id") or 0)
    except Exception:
        order_id = 0
    if not order_id:
        return jsonify({"ok": False, "error": "order_id_required"}), 400

    try:
        d = etiquetas_legacy_engine._odoo_order_detail(order_id)
    except Exception as ex:
        return jsonify({"ok": False, "error": "odoo_error", "detail": str(ex)}), 503

    # Crear/asegurar rastreo SOLO cuando se genera esta etiqueta (envío propio)
    try:
        tracking_code = ensure_tracking_for_order(
            odoo_order_id=order_id,
            order_name=str(d.get("pedido") or ""),
            id_web=str(d.get("id_web") or ""),
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": "tracking_error", "detail": str(ex)}), 500

    # Guardar en el contexto para plantillas editables
    d["tracking_code"] = tracking_code
    try:
        d["tracking_url"] = request.host_url.rstrip("/") + url_for("rastreo.go", tracking_code=tracking_code)
    except Exception:
        d["tracking_url"] = tracking_code

    # Resolver marca/logo para la etiqueta
    try:
        brand = str(d.get("brand") or "")
        d["logo_path"] = etiquetas_legacy_engine.resolve_logo_path(brand)
    except Exception:
        d["logo_path"] = str(current_app.config.get("LOGO_PATH", "") or "")

    # Campos esperados por legacy engine: nombre, direccion, telefono, pedido, codigo_envio, envio, observaciones, zona
    out_dir = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Si hay una plantilla layout_json activa, solo la usamos cuando se pide explícitamente.
    # El default de Suite para este proyecto es el layout RA (ReportLab legacy).
    label_style = (os.environ.get("LABEL_STYLE", "ra") or "ra").strip().lower()
    tpl = PdfTemplate.get_active("shipping_label")
    try:
        if label_style in ("layout_json", "layout", "template") and tpl and tpl.engine == "layout_json" and tpl.layout_json:
            layout = json.loads(tpl.layout_json)

            # IMPORTANTE:
            # En el diseñador (layout_json) el QR históricamente usaba label.tracking_url.
            # A partir de este cambio, el QR debe codificar SOLO el order_name de Odoo (pedido "S..."),
            # manteniendo el tracking impreso como texto en la etiqueta.
            #
            # Para no obligar a rediseñar la plantilla existente, forzamos que `label.tracking_url`
            # sea el `pedido` SOLO para el render del layout.
            d_render = dict(d)
            d_render["order_name"] = str(d.get("pedido") or "")
            d_render["tracking_url"] = d_render["order_name"]
            out_path = out_dir / f"label_layout_{d.get('pedido') or order_id}.pdf"
            ctx = {"label": d_render}
            render_layout_pdf(layout, ctx, str(out_path))
            pdf_path = str(out_path)
        else:
            data = etiquetas_legacy_engine.LabelData(
                nombre=str(d.get("nombre") or ""),
                direccion=str(d.get("direccion") or ""),
                telefono=str(d.get("telefono") or ""),
                pedido=str(d.get("pedido") or ""),
                id_web=str(d.get("id_web") or ""),
                zona=str(d.get("zona") or ""),
                envio=str(d.get("envio") or ""),
                codigo_envio=str(d.get("codigo_envio") or ""),
                observaciones=str(d.get("observaciones") or ""),
                tracking_code=str(d.get("tracking_code") or ""),
                tracking_url=str(d.get("tracking_url") or ""),
                brand=str(d.get("brand") or ""),
                logo_path=str(d.get("logo_path") or ""),
            )
            pdf_path = etiquetas_legacy_engine.generate_pdf(data)
    except Exception as ex:
        return jsonify({"ok": False, "error": "pdf_error", "detail": str(ex)}), 500

    rel = os.path.basename(pdf_path)
    return jsonify({"ok": True, "pdf_url": url_for("etiquetas.get_pdf", filename=rel)})

@bp.get("/pdf/<path:filename>")
@login_required
@view_required("etiquetas")
def get_pdf(filename: str):
    base = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    path = base / filename
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=False)
