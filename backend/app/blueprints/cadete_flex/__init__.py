from __future__ import annotations

from flask import Blueprint


bp = Blueprint(
    "cadete_flex",
    __name__,
    url_prefix="/flex",
    template_folder="../../templates",
    static_folder="../../static",
)


from . import routes  # noqa: E402,F401
