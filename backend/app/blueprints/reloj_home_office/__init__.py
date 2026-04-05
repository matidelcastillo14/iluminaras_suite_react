from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    'reloj_home_office',
    __name__,
    url_prefix='/reloj-home-office',
    template_folder='../../templates',
    static_folder='../../static',
)

from . import routes  # noqa: E402,F401
