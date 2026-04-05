from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, render_template, jsonify, current_app, send_file, abort, url_for
from flask_login import login_required

from ...models import ProcessedItem
from ...services.poller import poll_once
from ...utils import view_required

bp = Blueprint("cfe_auto", __name__, url_prefix="/cfe/auto")

@bp.get("/")
@login_required
@view_required("cfe_auto")
def index():
    return render_template("embed.html", iframe_src="/_legacy/cfe_auto/")


@bp.get("/api/cfes")
@login_required
@view_required("cfe_auto")
def api_cfes():
    rows = ProcessedItem.query.order_by(ProcessedItem.updated_at.desc()).limit(100).all()
    out = []
    for r in rows:
        out.append({
            "source_type": r.source_type,
            "source_id": r.source_id,
            "status": r.status,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "cfe": f"{r.cfe_serie or ''}{r.cfe_numero or ''}",
            "receptor": r.receptor_nombre,
            "pdf_url": url_for("cfe_auto.get_pdf", filename=r.pdf_receipt_path) if r.pdf_receipt_path else None,
            "change_pdf_url": url_for("cfe_auto.get_pdf", filename=r.pdf_change_path) if r.pdf_change_path else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return jsonify(out)

@bp.post("/api/cfes/poll_now")
@login_required
@view_required("cfe_auto")
def api_poll_now():
    res = poll_once()
    return jsonify(res)

@bp.get("/pdf/<path:filename>")
@login_required
@view_required("cfe_auto")
def get_pdf(filename: str):
    base = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    path = base / filename
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=False)
