from __future__ import annotations

from functools import wraps
from flask import abort
from flask_login import current_user

from .models import ViewPermission, User
from .services.modules_registry import module_for_view, is_module_internal_enabled

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if getattr(current_user, "role", "") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def can_view(view_key: str, user: User | None = None) -> bool:
    """Retorna True si el usuario puede acceder a una vista determinada.

    Orden:
    1) Si el módulo que contiene la vista está desactivado (INTERNAL), devuelve False para TODOS.
    2) Si está activado:
       - admin: True
       - otros: depende de view_permissions por rol
    """
    u = user or current_user
    try:
        if not u or not getattr(u, "is_authenticated", False):
            return False

        # Module gate (aplica incluso para admin)
        try:
            m = module_for_view(view_key)
            if m and not is_module_internal_enabled(m.key, default=True):
                return False
        except Exception:
            # Si falla el gate, no abrimos acceso por error
            return False


        if view_key == 'reloj_home_office' and not bool(getattr(u, 'home_office_clock_enabled', False)):
            return False

        if getattr(u, "role", "") == "admin":
            return True

        role = str(getattr(u, "role", "") or "").strip()
        if not role:
            return False
        p = ViewPermission.query.filter_by(role=role, view_key=view_key).first()
        return bool(p and p.enabled)
    except Exception:
        return False



def view_required(view_key: str):
    """Decorator: requiere que el usuario tenga habilitada la vista (por rol)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not can_view(view_key):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return deco
