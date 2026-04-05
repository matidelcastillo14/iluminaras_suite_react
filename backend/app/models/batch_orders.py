from __future__ import annotations

from datetime import datetime

from ..extensions import db


class ImportedBatch(db.Model):
    __tablename__ = "imported_batches"

    id = db.Column(db.Integer, primary_key=True)
    odoo_batch_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    batch_name = db.Column(db.String(64), nullable=False, index=True)  # e.g. BATCH/01950
    imported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    picking_count = db.Column(db.Integer, nullable=False, default=0)
    order_count = db.Column(db.Integer, nullable=False, default=0)

    orders = db.relationship("BatchOrder", backref="batch", lazy=True, cascade="all, delete-orphan")


class BatchOrder(db.Model):
    __tablename__ = "batch_orders"

    id = db.Column(db.Integer, primary_key=True)
    imported_batch_id = db.Column(db.Integer, db.ForeignKey("imported_batches.id"), nullable=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Odoo sale.order
    sale_order_id = db.Column(db.Integer, nullable=False, index=True)
    sale_order_ref = db.Column(db.String(64), nullable=True, index=True)

    # Odoo sale.order.date_order (guardado como UTC naive)
    order_date = db.Column(db.DateTime, nullable=True, index=True)

    id_web = db.Column(db.String(64), nullable=True)
    id_melicart = db.Column(db.String(64), nullable=True)
    id_meli = db.Column(db.Text, nullable=True)

    cliente = db.Column(db.String(256), nullable=True)
    direccion = db.Column(db.Text, nullable=True)

    monto_compra = db.Column(db.Numeric(16, 2), nullable=True)

    n_factura = db.Column(db.String(64), nullable=True)
    estado_factura = db.Column(db.String(32), nullable=True)
    link_factura = db.Column(db.Text, nullable=True)  # URL o 'Facturado' o vacío

    __table_args__ = (
        db.UniqueConstraint("imported_batch_id", "sale_order_id", name="uq_batch_order_sale"),
    )
