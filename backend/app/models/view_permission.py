from __future__ import annotations

from datetime import datetime

from ..extensions import db


class ViewPermission(db.Model):
    """Permisos por rol para habilitar/deshabilitar vistas del sistema."""

    __tablename__ = "view_permissions"

    id = db.Column(db.Integer, primary_key=True)

    # roles son strings (admin/operator/readonly/ventas/deposito/cadeteria/..)
    role = db.Column(db.String(64), nullable=False, index=True)
    view_key = db.Column(db.String(64), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("role", "view_key", name="uq_view_permissions_role_view"),
    )
