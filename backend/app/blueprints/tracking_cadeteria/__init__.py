from __future__ import annotations

from flask import Blueprint

bp = Blueprint("tracking_cadeteria", __name__, url_prefix="/tracking-cadeteria")

from . import routes  # noqa: E402,F401
