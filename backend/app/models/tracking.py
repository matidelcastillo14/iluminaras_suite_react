from __future__ import annotations

from datetime import datetime

from ..extensions import db


class TrackingShipment(db.Model):
    __tablename__ = "tracking_shipments"

    id = db.Column(db.Integer, primary_key=True)

    # ID del sale.order en Odoo (solo lectura)
    odoo_order_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    order_name = db.Column(db.String(64), nullable=False, index=True)  # e.g. S000123
    id_web = db.Column(db.String(64), nullable=True, index=True)

    tracking_code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="LABEL_CREATED", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    events = db.relationship("TrackingEvent", backref="shipment", lazy=True, cascade="all, delete-orphan")

    # --- Nuevos campos para trazabilidad de responsables ---
    # Responsable actual en Depósito (quien inició el armado)
    warehouse_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    warehouse_started_at = db.Column(db.DateTime, nullable=True)
    # Cadete asignado actualmente (quien está en reparto)
    courier_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    courier_assigned_at = db.Column(db.DateTime, nullable=True)

    warehouse_user = db.relationship("User", foreign_keys=[warehouse_user_id], backref="warehouse_shipments")
    courier_user = db.relationship("User", foreign_keys=[courier_user_id], backref="courier_shipments")


class TrackingEvent(db.Model):
    __tablename__ = "tracking_events"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), nullable=False, index=True)

    event_type = db.Column(db.String(32), nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(512), nullable=True)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relación a usuario creador; permite acceder a nombre de usuario en templates
    created_by = db.relationship("User", foreign_keys=[created_by_user_id], backref="tracking_events")

    @property
    def payload(self):
        import json
        if not self.payload_json:
            return None
        try:
            return json.loads(self.payload_json)
        except Exception:
            return None


class TrackingScan(db.Model):
    __tablename__ = "tracking_scans"

    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # camera/manual
    source = db.Column(db.String(16), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index("ix_tracking_scans_user_date", "user_id", "scanned_at"),
    )


# --- Nuevos modelos ---

class TrackingStockMissingItem(db.Model):
    """Items faltantes reportados en un evento STOCK_MISSING.

    Permite registrar múltiples productos faltantes por un mismo evento.
    """
    __tablename__ = "tracking_stock_missing_items"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("tracking_events.id"), nullable=False, index=True)
    # Identificadores de producto/línea (opcional)
    odoo_line_id = db.Column(db.Integer, nullable=True)
    product_id = db.Column(db.Integer, nullable=True)
    product_name_snapshot = db.Column(db.String(255), nullable=False)
    qty_missing = db.Column(db.Integer, nullable=True)
    note_item = db.Column(db.Text, nullable=True)

    shipment = db.relationship("TrackingShipment", backref="missing_items")
    event = db.relationship("TrackingEvent", backref="stock_missing_items")
