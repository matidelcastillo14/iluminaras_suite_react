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
