from __future__ import annotations

from pathlib import Path
import os

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from ...extensions import db
from ...models import JobApplication, JobApplicationFile, JobPosition
from ...utils import view_required


bp = Blueprint("postulaciones_admin", __name__, url_prefix="/postulaciones_admin")


def _generated_base() -> Path:
    return Path(current_app.root_path).parent / current_app.config.get("GENERATED_DIR", "generated")


def _safe_abs_path(rel_path: str) -> Path:
    base = _generated_base().resolve()
    p = (base / (rel_path or "")).resolve()
    if not str(p).startswith(str(base)):
        abort(403)
    return p


@bp.get("/")
@login_required
@view_required("admin_postulaciones")
def list_applications():
    q = (request.args.get("q") or "").strip()
    position_id = (request.args.get("position_id") or "").strip()
    status = (request.args.get("status") or "").strip()

    qry = JobApplication.query
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            (JobApplication.first_name.ilike(like))
            | (JobApplication.last_name.ilike(like))
            | (JobApplication.email.ilike(like))
        )

    if position_id:
        try:
            pid = int(position_id)
            qry = qry.filter(JobApplication.position_id == pid)
        except Exception:
            pass

    if status:
        qry = qry.filter(JobApplication.status == status)

    rows = qry.order_by(JobApplication.created_at.desc()).limit(500).all()
    puestos = JobPosition.query.order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    statuses = ["new", "reviewed", "discarded"]
    return render_template(
        "postulaciones/admin_list.html",
        rows=rows,
        puestos=puestos,
        q=q,
        position_id=position_id,
        status=status,
        statuses=statuses,
    )


@bp.get("/<int:app_id>")
@login_required
@view_required("admin_postulaciones")
def view_application(app_id: int):
    row = JobApplication.query.get_or_404(app_id)
    puestos = JobPosition.query.order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    return render_template("postulaciones/admin_detail.html", row=row, puestos=puestos)


@bp.post("/<int:app_id>/update")
@login_required
@view_required("admin_postulaciones")
def update_application(app_id: int):
    row = JobApplication.query.get_or_404(app_id)
    row.status = (request.form.get("status") or row.status or "new").strip()[:40]
    row.admin_note = (request.form.get("admin_note") or "").strip()
    db.session.commit()
    flash("Postulación actualizada.", "info")
    return redirect(url_for("postulaciones_admin.view_application", app_id=app_id))


@bp.get("/file/<int:file_id>/open")
@login_required
@view_required("admin_postulaciones")
def open_file(file_id: int):
    f = JobApplicationFile.query.get_or_404(file_id)
    path = _safe_abs_path(f.rel_path)
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=False, download_name=f.original_filename)


@bp.get("/file/<int:file_id>/download")
@login_required
@view_required("admin_postulaciones")
def download_file(file_id: int):
    f = JobApplicationFile.query.get_or_404(file_id)
    path = _safe_abs_path(f.rel_path)
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=True, download_name=f.original_filename)


# ---------------------------------------------------------------------------
# JSON API endpoints for Postulaciones (Admin)
#
# These routes expose the job applications and positions management
# functionality in a machine‑readable way for the new React frontend.
# All endpoints require the ``admin_postulaciones`` view permission.


@bp.get("/api/applications")
@login_required
@view_required("admin_postulaciones")
def api_applications_list():
    """Return a list of job applications with optional filters.

    Accepts query parameters ``q`` (search), ``position_id`` and
    ``status``.  Returns a JSON object containing ``applications``,
    ``positions`` and ``statuses``.
    """
    from flask import request, jsonify
    q = (request.args.get("q") or "").strip()
    position_id = (request.args.get("position_id") or "").strip()
    status = (request.args.get("status") or "").strip()
    qry = JobApplication.query
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            (JobApplication.first_name.ilike(like))
            | (JobApplication.last_name.ilike(like))
            | (JobApplication.email.ilike(like))
        )
    if position_id:
        try:
            pid = int(position_id)
            qry = qry.filter(JobApplication.position_id == pid)
        except Exception:
            pass
    if status:
        qry = qry.filter(JobApplication.status == status)
    rows = qry.order_by(JobApplication.created_at.desc()).limit(500).all()
    apps = []
    for a in rows:
        apps.append({
            "id": a.id,
            "first_name": a.first_name,
            "last_name": a.last_name,
            "email": a.email,
            "status": a.status,
            "admin_note": a.admin_note,
            "position_id": a.position_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })
    puestos = JobPosition.query.order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    positions = [{"id": p.id, "name": p.name, "sort_order": p.sort_order, "is_active": bool(p.is_active)} for p in puestos]
    statuses = ["new", "reviewed", "discarded"]
    return jsonify({"applications": apps, "positions": positions, "statuses": statuses})


@bp.get("/api/applications/<int:app_id>")
@login_required
@view_required("admin_postulaciones")
def api_application_get(app_id: int):
    """Return detailed information for a single job application."""
    from flask import jsonify
    a = JobApplication.query.get_or_404(app_id)
    return jsonify({
        "id": a.id,
        "first_name": a.first_name,
        "last_name": a.last_name,
        "email": a.email,
        "status": a.status,
        "admin_note": a.admin_note,
        "position_id": a.position_id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "files": [
            {"id": f.id, "filename": f.original_filename, "url": url_for("postulaciones_admin.open_file", file_id=f.id)}
            for f in (a.files or [])
        ],
    })


@bp.put("/api/applications/<int:app_id>")
@login_required
@view_required("admin_postulaciones")
def api_application_update(app_id: int):
    """Update a job application.  Accepts JSON payload."""
    from flask import request, jsonify
    a = JobApplication.query.get_or_404(app_id)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400
    # Updatable fields
    status = payload.get("status")
    admin_note = payload.get("admin_note")
    position_id = payload.get("position_id")
    if status:
        a.status = status
    if admin_note is not None:
        a.admin_note = admin_note
    if position_id:
        try:
            a.position_id = int(position_id)
        except Exception:
            pass
    db.session.commit()
    return jsonify({"ok": True})


@bp.get("/api/positions")
@login_required
@view_required("admin_postulaciones")
def api_positions_list():
    """Return a list of job positions."""
    from flask import jsonify
    rows = JobPosition.query.order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "name": r.name,
            "sort_order": r.sort_order,
            "is_active": bool(r.is_active),
        })
    return jsonify({"positions": out})


@bp.post("/api/positions")
@login_required
@view_required("admin_postulaciones")
def api_position_create():
    """Create a new job position."""
    from flask import request, jsonify
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    sort_order = payload.get("sort_order")
    if not name:
        return jsonify({"error": "name_required"}), 400
    try:
        so = int(sort_order) if sort_order not in (None, "") else 0
    except Exception:
        so = 0
    if JobPosition.query.filter(JobPosition.name.ilike(name)).first():
        return jsonify({"error": "exists"}), 400
    row = JobPosition(name=name, sort_order=so, is_active=True)
    db.session.add(row)
    db.session.commit()
    return jsonify({"id": row.id, "name": row.name, "sort_order": row.sort_order, "is_active": bool(row.is_active)})


@bp.put("/api/positions/<int:pid>")
@login_required
@view_required("admin_postulaciones")
def api_position_update(pid: int):
    """Update an existing job position."""
    from flask import request, jsonify
    row = JobPosition.query.get_or_404(pid)
    payload = request.get_json(silent=True) or {}
    if 'name' in payload:
        nm = (payload.get('name') or '').strip()
        if nm:
            row.name = nm
    if 'sort_order' in payload:
        try:
            row.sort_order = int(payload.get('sort_order'))
        except Exception:
            pass
    if 'is_active' in payload:
        row.is_active = bool(payload.get('is_active'))
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/api/positions/<int:pid>/toggle")
@login_required
@view_required("admin_postulaciones")
def api_position_toggle(pid: int):
    """Toggle active/inactive state for a position."""
    from flask import jsonify
    row = JobPosition.query.get_or_404(pid)
    row.is_active = not bool(row.is_active)
    db.session.commit()
    return jsonify({"id": row.id, "is_active": bool(row.is_active)})


@bp.delete("/api/positions/<int:pid>")
@login_required
@view_required("admin_postulaciones")
def api_position_delete(pid: int):
    """Delete a job position if no applications reference it."""
    from flask import jsonify
    row = JobPosition.query.get_or_404(pid)
    in_use = JobApplication.query.filter_by(position_id=row.id).first()
    if in_use:
        return jsonify({"error": "in_use"}), 400
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


# -------------------------
# Puestos (configurable)
# -------------------------


@bp.get("/puestos")
@login_required
@view_required("admin_postulaciones")
def puestos_list():
    rows = JobPosition.query.order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    return render_template("postulaciones/puestos_list.html", rows=rows)


@bp.post("/puestos/new")
@login_required
@view_required("admin_postulaciones")
def puestos_new():
    name = (request.form.get("name") or "").strip()
    sort_order = (request.form.get("sort_order") or "0").strip()
    if not name:
        flash("Nombre obligatorio.", "error")
        return redirect(url_for("postulaciones_admin.puestos_list"))
    try:
        so = int(sort_order)
    except Exception:
        so = 0

    if JobPosition.query.filter(JobPosition.name.ilike(name)).first():
        flash("Ese puesto ya existe.", "error")
        return redirect(url_for("postulaciones_admin.puestos_list"))

    db.session.add(JobPosition(name=name, sort_order=so, is_active=True))
    db.session.commit()
    flash("Puesto creado.", "info")
    return redirect(url_for("postulaciones_admin.puestos_list"))


@bp.post("/puestos/<int:pid>/toggle")
@login_required
@view_required("admin_postulaciones")
def puestos_toggle(pid: int):
    row = JobPosition.query.get_or_404(pid)
    row.is_active = not bool(row.is_active)
    db.session.commit()
    return redirect(url_for("postulaciones_admin.puestos_list"))


@bp.post("/puestos/<int:pid>/edit")
@login_required
@view_required("admin_postulaciones")
def puestos_edit(pid: int):
    row = JobPosition.query.get_or_404(pid)
    name = (request.form.get("name") or row.name).strip()
    sort_order = (request.form.get("sort_order") or str(row.sort_order or 0)).strip()
    try:
        so = int(sort_order)
    except Exception:
        so = int(row.sort_order or 0)
    if not name:
        flash("Nombre obligatorio.", "error")
        return redirect(url_for("postulaciones_admin.puestos_list"))
    row.name = name
    row.sort_order = so
    db.session.commit()
    flash("Puesto actualizado.", "info")
    return redirect(url_for("postulaciones_admin.puestos_list"))


@bp.post("/puestos/<int:pid>/delete")
@login_required
@view_required("admin_postulaciones")
def puestos_delete(pid: int):
    row = JobPosition.query.get_or_404(pid)
    in_use = JobApplication.query.filter_by(position_id=row.id).first()
    if in_use:
        flash("No se puede eliminar: hay postulaciones con este puesto.", "error")
        return redirect(url_for("postulaciones_admin.puestos_list"))
    db.session.delete(row)
    db.session.commit()
    flash("Puesto eliminado.", "info")
    return redirect(url_for("postulaciones_admin.puestos_list"))
