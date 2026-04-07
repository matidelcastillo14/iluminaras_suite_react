from __future__ import annotations

import json
import secrets
import string
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file, jsonify
from flask_login import login_required

from ...extensions import db, mail
from ...models import User, Setting, PdfTemplate, ViewPermission
from ...utils import admin_required
from ...services.layout_renderer import render_layout_pdf
from ...services.settings_sync import SETTINGS_KEYS, apply_db_settings, sync_settings_to_legacy_app
from ...services.timezone import list_timezones
from ...services.views_registry import VIEW_DEFS, all_view_keys
from ...services.modules_registry import all_modules, internal_setting_key, public_setting_key, is_module_internal_enabled, is_module_public_enabled
from flask_mail import Message

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _all_roles() -> list[str]:
    """Lista de roles disponibles.

    Incluye un set base de roles usados por el sistema, y añade
    roles ya existentes en la BD para no romper instalaciones
    previas.
    """
    base = {
        "admin",
        "operator",
        "readonly",
        "ventas",
        "deposito",
        "cadeteria",
        "cadete_flex",
        "system",
    }
    try:
        existing = {r[0] for r in db.session.query(User.role).distinct().all() if r and r[0]}
    except Exception:
        existing = set()
    roles = sorted({*(base | existing)})
    return roles

def _rand_password(n: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))

def _send_email(to: str, subject: str, body: str) -> bool:
    if not current_app.config.get("MAIL_SERVER"):
        return False
    try:
        msg = Message(subject=subject, recipients=[to], body=body)
        mail.send(msg)
        return True
    except Exception:
        return False


def _list_static_images() -> list[str]:
    """Lista (relativa a /static) de imágenes disponibles en app/static (recursivo)."""
    static_dir = Path(current_app.static_folder or "")
    if not static_dir.exists():
        return []
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    out: list[str] = []
    try:
        for p in static_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in allowed:
                continue
            rel = p.relative_to(static_dir).as_posix()
            # Evitar archivos ocultos o paths raros
            if rel.startswith(".") or "/." in rel:
                continue
            out.append(rel)
    except Exception:
        return []
    return sorted(set(out))

@bp.get("/")
@login_required
@admin_required
def dashboard():
    return render_template("admin/dashboard.html")

@bp.get("/users")
@login_required
@admin_required
def users():
    rows = User.query.order_by(User.role.desc(), User.username.asc()).all()
    return render_template("admin/users.html", users=rows)

@bp.get("/users/new")
@login_required
@admin_required
def users_new():
    return render_template("admin/user_new.html", roles=_all_roles())

@bp.post("/users/new")
@login_required
@admin_required
def users_new_post():
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    attendance_ref_code = (request.form.get("attendance_ref_code") or "").strip()
    home_office_clock_enabled = bool(request.form.get("home_office_clock_enabled"))
    role = (request.form.get("role") or "operator").strip()
    if role not in set(_all_roles()):
        role = "operator"

    if not username or not email or not first_name or not last_name:
        flash("Faltan datos obligatorios.", "error")
        return redirect(url_for("admin.users_new"))

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("Usuario o email ya existe.", "error")
        return redirect(url_for("admin.users_new"))

    tmp = _rand_password()
    u = User(username=username, email=email, first_name=first_name, last_name=last_name, phone=phone, attendance_ref_code=attendance_ref_code, home_office_clock_enabled=home_office_clock_enabled, role=role, is_active=True, must_change_password=True)
    u.set_password(tmp)
    db.session.add(u)
    db.session.commit()

    body = f"Usuario creado: {username}\nContraseña temporal: {tmp}\n\nAl iniciar sesión se te solicitará cambiarla."
    sent = _send_email(email, "Acceso Iluminaras Suite", body)

    flash(f"Usuario creado. Contraseña temporal: {tmp}" + (" (enviada por email)" if sent else " (email no configurado)"), "info")
    return redirect(url_for("admin.users"))


@bp.get("/users/<int:user_id>/edit")
@login_required
@admin_required
def users_edit(user_id: int):
    u = User.query.get_or_404(user_id)
    return render_template("admin/user_edit.html", u=u, roles=_all_roles())


@bp.post("/users/<int:user_id>/edit")
@login_required
@admin_required
def users_edit_post(user_id: int):
    u = User.query.get_or_404(user_id)
    u.username = (request.form.get("username") or u.username).strip()
    u.email = (request.form.get("email") or u.email).strip()
    u.first_name = (request.form.get("first_name") or u.first_name).strip()
    u.last_name = (request.form.get("last_name") or u.last_name).strip()
    u.phone = (request.form.get("phone") or u.phone or "").strip()
    u.attendance_ref_code = (request.form.get("attendance_ref_code") or u.attendance_ref_code or "").strip()
    u.home_office_clock_enabled = bool(request.form.get("home_office_clock_enabled"))
    role = (request.form.get("role") or u.role or "operator").strip()
    if role not in set(_all_roles()):
        role = u.role
    u.role = role
    u.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash("Usuario actualizado.", "info")
    return redirect(url_for("admin.users"))

@bp.post("/users/<int:user_id>/toggle")
@login_required
@admin_required
def users_toggle(user_id: int):
    u = User.query.get_or_404(user_id)
    u.is_active = not u.is_active
    db.session.commit()
    return redirect(url_for("admin.users"))

@bp.post("/users/<int:user_id>/reset-temp")
@login_required
@admin_required
def users_reset_temp(user_id: int):
    u = User.query.get_or_404(user_id)
    tmp = _rand_password()
    u.set_password(tmp)
    u.must_change_password = True
    db.session.commit()

    body = f"Tu contraseña fue restablecida.\nUsuario: {u.username}\nContraseña temporal: {tmp}\n\nAl iniciar sesión se te solicitará cambiarla."
    sent = _send_email(u.email, "Restablecer contraseña (Iluminaras Suite)", body)

    flash(f"Contraseña temporal generada: {tmp}" + (" (enviada por email)" if sent else " (email no configurado)"), "info")
    return redirect(url_for("admin.users"))

@bp.get("/settings")
@login_required
@admin_required
def settings():
    keys = SETTINGS_KEYS
    values = {k: Setting.get(k, str(current_app.config.get(k,""))) for k in keys}
    timezones = list_timezones()
    static_images = _list_static_images()
    return render_template(
        "admin/settings.html",
        values=values,
        keys=keys,
        timezones=timezones,
        static_images=static_images,
    )

@bp.post("/settings")
@login_required
@admin_required
def settings_post():
    for k, v in request.form.items():
        if k.startswith("__"):
            continue
        Setting.set(k, v)
    db.session.commit()

    # Aplicar en caliente sobre la app principal
    apply_db_settings(current_app)

    # Propagar hacia apps legacy montadas (si existen)
    legacy_apps = (current_app.extensions or {}).get("legacy_apps")
    if isinstance(legacy_apps, dict):
        for _name, legacy_app in legacy_apps.items():
            try:
                sync_settings_to_legacy_app(current_app, legacy_app)
            except Exception:
                pass

    flash("Configuración guardada.", "info")
    return redirect(url_for("admin.settings"))


@bp.get("/views")
@login_required
@admin_required
def view_permissions():
    # Roles existentes + roles comunes
    roles: set[str] = set(["operator", "readonly", "ventas", "deposito", "cadeteria"])
    for r in db.session.query(User.role).distinct().all():
        if r and r[0] and str(r[0]) != "admin":
            roles.add(str(r[0]))
    roles_list = sorted(roles)

    # Ensure rows exist
    keys = all_view_keys()
    for role in roles_list:
        for k in keys:
            if not ViewPermission.query.filter_by(role=role, view_key=k).first():
                db.session.add(ViewPermission(role=role, view_key=k, enabled=False))
    db.session.commit()

    perms: dict[tuple[str, str], bool] = {}
    for p in ViewPermission.query.filter(ViewPermission.role.in_(roles_list)).all():
        perms[(p.role, p.view_key)] = bool(p.enabled)

    # Group views
    groups: dict[str, list] = {}
    for v in VIEW_DEFS:
        groups.setdefault(v.group, []).append(v)

    return render_template("admin/view_permissions.html", roles=roles_list, groups=groups, perms=perms)


@bp.post("/views")
@login_required
@admin_required
def view_permissions_post():
    new_role = (request.form.get("new_role") or "").strip()
    if new_role and new_role != "admin":
        keys = all_view_keys()
        for k in keys:
            if not ViewPermission.query.filter_by(role=new_role, view_key=k).first():
                db.session.add(ViewPermission(role=new_role, view_key=k, enabled=False))
        db.session.commit()

    keys = set(all_view_keys())
    # Actualizar checkboxes: name = "<role>__<view_key>"
    roles_in_db = [r[0] for r in db.session.query(ViewPermission.role).distinct().all() if r and r[0] and r[0] != "admin"]
    for role in roles_in_db:
        for k in keys:
            field = f"{role}__{k}"
            enabled = field in request.form
            vp = ViewPermission.query.filter_by(role=role, view_key=k).first()
            if vp:
                vp.enabled = bool(enabled)
    db.session.commit()

    flash("Permisos guardados.", "info")
    return redirect(url_for("admin.view_permissions"))

@bp.get("/templates")
@login_required
@admin_required
def templates():
    rows = PdfTemplate.query.order_by(PdfTemplate.template_type.asc(), PdfTemplate.is_active.desc(), PdfTemplate.name.asc()).all()
    return render_template("admin/templates.html", templates=rows)

@bp.get("/templates/<int:tpl_id>/edit")
@login_required
@admin_required
def template_edit(tpl_id: int):
    tpl = PdfTemplate.query.get_or_404(tpl_id)
    if tpl.engine != "layout_json":
        flash("Solo se editan plantillas 'Editable'.", "error")
        return redirect(url_for("admin.templates"))
    layout = tpl.layout_json or "{}"
    return render_template("admin/template_editor.html", tpl=tpl, layout_json=layout)

@bp.post("/templates/<int:tpl_id>/save")
@login_required
@admin_required
def template_save(tpl_id: int):
    tpl = PdfTemplate.query.get_or_404(tpl_id)
    if tpl.engine != "layout_json":
        return jsonify({"ok": False, "error": "not_editable"}), 400
    data = request.get_json(silent=True) or {}
    layout = data.get("layout")
    if not isinstance(layout, dict):
        return jsonify({"ok": False, "error": "layout_required"}), 400
    tpl.layout_json = json.dumps(layout, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})

@bp.post("/templates/<int:tpl_id>/activate")
@login_required
@admin_required
def template_activate(tpl_id: int):
    tpl = PdfTemplate.query.get_or_404(tpl_id)
    # deactivate others in type
    PdfTemplate.query.filter_by(template_type=tpl.template_type).update({"is_active": False})
    tpl.is_active = True
    db.session.commit()
    flash("Plantilla activa actualizada.", "info")
    return redirect(url_for("admin.templates"))

@bp.post("/templates/<int:tpl_id>/preview")
@login_required
@admin_required
def template_preview(tpl_id: int):
    tpl = PdfTemplate.query.get_or_404(tpl_id)
    if tpl.engine != "layout_json" or not tpl.layout_json:
        return jsonify({"ok": False, "error": "not_editable"}), 400
    layout = json.loads(tpl.layout_json)

    # simple demo context
    ctx = {
        "cfe": {"emisor_razon_social":"ILUMINARAS S.A.","emisor_ruc":"000000000000","tipo_texto":"e-Ticket","serie":"A","numero":"123","fecha_emision":"2026-01-02","total":"$ 0"},
        "items": [{"descripcion":"Producto demo","cantidad":"1","total_linea":"$0"}],
        "label": {"nombre":"Nombre demo","direccion":"Dirección demo","telefono":"000","pedido":"SO0001"},
    }

    out_dir = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"preview_tpl_{tpl.id}.pdf"
    render_layout_pdf(layout, ctx, str(out_path))
    return send_file(str(out_path), as_attachment=False)


@bp.get("/views")
@login_required
@admin_required
def views_permissions():
    # roles existentes + roles comunes
    roles = {"operator", "readonly", "ventas", "deposito", "cadeteria"}
    for r in db.session.query(User.role).distinct().all():
        if r and r[0]:
            roles.add(str(r[0]))
    roles = sorted(roles)

    # map permisos
    perms: dict[str, dict[str, bool]] = {role: {} for role in roles}
    keys = all_view_keys()
    for role in roles:
        for k in keys:
            vp = ViewPermission.query.filter_by(role=role, view_key=k).first()
            perms[role][k] = bool(vp and vp.enabled)

    # agrupar vistas por group
    groups: dict[str, list] = {}
    for v in VIEW_DEFS:
        groups.setdefault(v.group, []).append(v)

    return render_template("admin/view_permissions.html", roles=roles, groups=groups, perms=perms)


@bp.post("/views")
@login_required
@admin_required
def views_permissions_post():
    # crear rol opcional
    new_role = (request.form.get("new_role") or "").strip()
    if new_role:
        for k in all_view_keys():
            if not ViewPermission.query.filter_by(role=new_role, view_key=k).first():
                db.session.add(ViewPermission(role=new_role, view_key=k, enabled=False))

    # actualizar checkboxes
    roles = {"operator", "readonly", "ventas", "deposito", "cadeteria"}
    for r in db.session.query(User.role).distinct().all():
        if r and r[0]:
            roles.add(str(r[0]))
    if new_role:
        roles.add(new_role)

    for role in roles:
        for v in VIEW_DEFS:
            name = f"vp__{role}__{v.key}"
            enabled = bool(request.form.get(name))
            vp = ViewPermission.query.filter_by(role=role, view_key=v.key).first()
            if not vp:
                vp = ViewPermission(role=role, view_key=v.key, enabled=enabled)
                db.session.add(vp)
            else:
                vp.enabled = enabled

    db.session.commit()
    flash("Permisos de vistas guardados.", "info")
    return redirect(url_for("admin.views_permissions"))


@bp.get("/modules")
@login_required
@admin_required
def modules():
    mods = []
    for m in all_modules():
        mods.append(
            {
                "key": m.key,
                "label": m.label,
                "has_public": bool(m.has_public),
                "public_label": m.public_label or "Público",
                "internal_enabled": is_module_internal_enabled(m.key, default=True),
                "public_enabled": is_module_public_enabled(m.key, default=True) if m.has_public else True,
            }
        )
    return render_template("admin/modules.html", modules=mods)


@bp.post("/modules")
@login_required
@admin_required
def modules_post():
    # Form fields: internal_<key> / public_<key>
    for m in all_modules():
        internal_val = "1" if request.form.get(f"internal_{m.key}") == "on" else "0"
        Setting.set(internal_setting_key(m.key), internal_val)

        if m.has_public:
            public_val = "1" if request.form.get(f"public_{m.key}") == "on" else "0"
            Setting.set(public_setting_key(m.key), public_val)

    try:
        db.session.commit()
        flash("Configuración de módulos guardada.", "info")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash("No se pudo guardar la configuración de módulos.", "error")

    return redirect(url_for("admin.modules"))
