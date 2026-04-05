from __future__ import annotations

import os
import json
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app, send_file, abort, url_for
from flask_login import login_required

from ...models import PdfTemplate
from ...services import cfe_legacy_engine
from ...services.layout_renderer import render_layout_pdf
from ...utils import view_required

bp = Blueprint("cfe_manual", __name__, url_prefix="/cfe/manual")

def _configure_engine():
    cfe_legacy_engine.configure(current_app.config, root_path=str(Path(current_app.root_path).parent), logger=current_app.logger)

@bp.get("/")
@login_required
@view_required("cfe_manual")
def index():
    return render_template("embed.html", iframe_src="/_legacy/cfe_manual/")

@bp.get("/api/orders/search")
@login_required
@view_required("cfe_manual")
def api_orders_search():
    if not current_app.config.get("ENABLE_ODOO_LOOKUP", True):
        return jsonify({"error": "odoo_lookup_disabled"}), 501
    _configure_engine()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        rows = cfe_legacy_engine._odoo_search_orders(q)
        return jsonify(rows)
    except Exception as ex:
        return jsonify({"error":"odoo_error","detail":str(ex)}), 503

@bp.get("/api/orders/<int:order_id>")
@login_required
@view_required("cfe_manual")
def api_order_detail(order_id: int):
    _configure_engine()
    try:
        d = cfe_legacy_engine._odoo_order_detail(order_id)
        return jsonify(d)
    except KeyError:
        return jsonify({"error":"not_found"}), 404
    except Exception as ex:
        return jsonify({"error":"odoo_error","detail":str(ex)}), 503

@bp.post("/generate")
@login_required
@view_required("cfe_manual")
def generate():
    _configure_engine()
    try:
        order_id = int(request.form.get("order_id") or 0)
    except Exception:
        order_id = 0
    if not order_id:
        return jsonify({"ok": False, "error": "order_id_required"}), 400

    # 1) Download XML from Odoo
    try:
        _xml_name, xml_bytes = cfe_legacy_engine._odoo_get_cfe_xml_from_order(order_id)
    except Exception as ex:
        return jsonify({"ok": False, "error": "odoo_cfe_error", "detail": str(ex)}), 409

    # 2) Parse XML
    try:
        cfe = cfe_legacy_engine.parse_cfe_xml(xml_bytes, default_adenda="")
        # apply default adenda by emisor if empty
        if not (cfe.adenda or "").strip():
            try:
                cfe.adenda = cfe_legacy_engine._default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
            except Exception:
                pass
    except Exception as ex:
        return jsonify({"ok": False, "error": "parse_error", "detail": str(ex)}), 400

    out_dir = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Select template engine
    tpl = PdfTemplate.get_active("cfe_ticket")
    try:
        if tpl and tpl.engine == "layout_json" and tpl.layout_json:
            layout = json.loads(tpl.layout_json)
            out_path = out_dir / f"cfe_layout_{cfe.serie}{cfe.numero}.pdf"
            ctx = {"cfe": cfe.__dict__, "items": [it.__dict__ for it in cfe.items]}
            render_layout_pdf(layout, ctx, str(out_path))
            pdf_path = str(out_path)
        else:
            pdf_path = cfe_legacy_engine.generate_receipt_pdf(cfe)
    except Exception as ex:
        return jsonify({"ok": False, "error": "pdf_error", "detail": str(ex)}), 500

    # Optional: change ticket
    change_path = None
    try:
        tplc = PdfTemplate.get_active("cfe_change")
        if tplc and tplc.engine == "layout_json" and tplc.layout_json:
            layout = json.loads(tplc.layout_json)
            out_path = out_dir / f"cambio_layout_{cfe.serie}{cfe.numero}.pdf"
            ctx = {"cfe": cfe.__dict__, "items": [it.__dict__ for it in cfe.items]}
            render_layout_pdf(layout, ctx, str(out_path))
            change_path = str(out_path)
        else:
            change_path = cfe_legacy_engine.generate_change_ticket_pdf(cfe)
    except Exception:
        change_path = None

    def _rel(p: str|None) -> str|None:
        if not p: return None
        try:
            return os.path.relpath(p, str(Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]))
        except Exception:
            return os.path.basename(p)

    return jsonify({
        "ok": True,
        "pdf_url": url_for("cfe_manual.get_pdf", filename=_rel(pdf_path)),
        "change_pdf_url": url_for("cfe_manual.get_pdf", filename=_rel(change_path)) if change_path else None,
    })

@bp.get("/pdf/<path:filename>")
@login_required
@view_required("cfe_manual")
def get_pdf(filename: str):
    base = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    path = base / filename
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=False)
