from flask import Blueprint

bp = Blueprint("door", __name__, url_prefix="/door")

from . import routes  # noqa: E402,F401
