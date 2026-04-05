from __future__ import annotations

import secrets
from datetime import timedelta

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user

from ...extensions import db, mail
from ...models import User
from flask_mail import Message

bp = Blueprint("auth", __name__, url_prefix="/auth")

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

def _send_email(to: str, subject: str, body: str) -> bool:
    # If mail not configured, skip silently but return False
    if not current_app.config.get("MAIL_SERVER"):
        return False
    try:
        msg = Message(subject=subject, recipients=[to], body=body)
        mail.send(msg)
        return True
    except Exception:
        return False

@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    return render_template("auth/login.html")

@bp.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    user = User.query.filter((User.username == username) | (User.email == username)).first()
    if not user or not user.is_active or not user.check_password(password):
        flash("Credenciales inválidas", "error")
        return redirect(url_for("auth.login"))

    login_user(user, remember=True, duration=timedelta(days=14))

    if user.must_change_password:
        return redirect(url_for("auth.change_password"))

    return redirect(url_for("main.home"))

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

@bp.get("/change-password")
@login_required
def change_password():
    return render_template("auth/change_password.html")

@bp.post("/change-password")
@login_required
def change_password_post():
    p1 = request.form.get("password1") or ""
    p2 = request.form.get("password2") or ""
    if len(p1) < 10:
        flash("La contraseña debe tener al menos 10 caracteres.", "error")
        return redirect(url_for("auth.change_password"))
    if p1 != p2:
        flash("Las contraseñas no coinciden.", "error")
        return redirect(url_for("auth.change_password"))

    current_user.set_password(p1)
    current_user.must_change_password = False
    db.session.commit()

    return redirect(url_for("main.home"))

@bp.get("/request-reset")
def request_reset():
    return render_template("auth/request_reset.html")

@bp.post("/request-reset")
def request_reset_post():
    email = (request.form.get("email") or "").strip()
    user = User.query.filter_by(email=email).first()
    # No revelar si existe o no
    if user:
        token = _serializer().dumps({"uid": user.id, "p": "reset"})
        reset_url = url_for("auth.reset_password", token=token, _external=True)
        body = f"Solicitud de restablecimiento de contraseña. Link:\n{reset_url}\n\nSi no fuiste vos, ignorá este correo."
        _send_email(user.email, "Restablecer contraseña", body)

    flash("Si el email existe, se envió un link de restablecimiento.", "info")
    return redirect(url_for("auth.login"))

@bp.get("/reset/<token>")
def reset_password(token: str):
    return render_template("auth/reset_password.html", token=token)

@bp.post("/reset/<token>")
def reset_password_post(token: str):
    p1 = request.form.get("password1") or ""
    p2 = request.form.get("password2") or ""
    if len(p1) < 10:
        flash("La contraseña debe tener al menos 10 caracteres.", "error")
        return redirect(url_for("auth.reset_password", token=token))
    if p1 != p2:
        flash("Las contraseñas no coinciden.", "error")
        return redirect(url_for("auth.reset_password", token=token))

    try:
        data = _serializer().loads(token, max_age=3600 * 24, salt=None)
    except SignatureExpired:
        flash("El link expiró. Pedí uno nuevo.", "error")
        return redirect(url_for("auth.request_reset"))
    except BadSignature:
        flash("Link inválido.", "error")
        return redirect(url_for("auth.request_reset"))

    if not isinstance(data, dict) or data.get("p") != "reset":
        flash("Link inválido.", "error")
        return redirect(url_for("auth.request_reset"))

    user = User.query.get(int(data.get("uid") or 0))
    if not user:
        flash("Link inválido.", "error")
        return redirect(url_for("auth.request_reset"))

    user.set_password(p1)
    user.must_change_password = False
    db.session.commit()

    flash("Contraseña actualizada. Ya podés iniciar sesión.", "info")
    return redirect(url_for("auth.login"))
