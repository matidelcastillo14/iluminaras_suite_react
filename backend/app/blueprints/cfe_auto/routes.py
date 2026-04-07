from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_file, url_for
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
    rows = ProcessedItem.query.order_by(ProcessedItem.updated_at.desc()).limit(80).all()
    out = []
    for r in rows:
        serie = (r.cfe_serie or "").strip()
        numero = (r.cfe_numero or "").strip()
        cfe_code = f"{serie}{numero}".strip()
        pdf_url = url_for("cfe_auto.get_pdf", filename=r.pdf_receipt_path) if r.pdf_receipt_path else None
        change_pdf_url = url_for("cfe_auto.get_pdf", filename=r.pdf_change_path) if r.pdf_change_path else None
        out.append({
            "source_type": r.source_type,
            "source_id": r.source_id,
            "status": r.status,
            "attempts": r.attempts,
            "last_error": r.last_error,
            "tipo": "e-Ticket" if cfe_code else "-",
            "serie": serie or None,
            "numero": numero or None,
            "fecha": r.updated_at.isoformat() if r.updated_at else None,
            "cfe": cfe_code or None,
            "receptor": r.receptor_nombre,
            "pdf_url": pdf_url,
            "download_pdf_url": f"{pdf_url}?download=1" if pdf_url else None,
            "change_pdf_url": change_pdf_url,
            "download_change_pdf_url": f"{change_pdf_url}?download=1" if change_pdf_url else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return jsonify({"ok": True, "items": out, "count": len(out)})


@bp.post("/api/cfes/poll_now")
@login_required
@view_required("cfe_auto")
def api_poll_now():
    return jsonify({"ok": True, **(poll_once() or {})})


@bp.get("/pdf/<path:filename>")
@login_required
@view_required("cfe_auto")
def get_pdf(filename: str):
    base = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    path = base / filename
    if not path.exists() or not path.is_file():
        abort(404)
    as_attachment = request.args.get("download", "0") in {"1", "true", "True"}
    return send_file(str(path), as_attachment=as_attachment, download_name=path.name)
