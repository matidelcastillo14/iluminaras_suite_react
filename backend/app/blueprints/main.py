from __future__ import annotations

from flask import Blueprint, render_template, redirect, request, url_for
from flask_login import current_user

bp = Blueprint("main", __name__)

@bp.get("/")
def home():
    # Canonical public URL lives under:
    #   https://suite.iluminaras.cloud/postulaciones/
    # If the old subdomain is still pointed to this app, redirect to the canonical.
    host = (request.host or "").split(":", 1)[0].strip().lower()
    if host == "postulaciones.iluminaras.cloud":
        return redirect("https://suite.iluminaras.cloud/postulaciones/")

    if not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login", next=request.full_path))
    return render_template("home.html")
