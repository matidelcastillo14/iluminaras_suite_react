from __future__ import annotations

from datetime import datetime
from ..extensions import db

class PollState(db.Model):
    __tablename__ = "poll_state"
    id = db.Column(db.Integer, primary_key=True, default=1)

    last_poll_ts = db.Column(db.Float, default=0.0, nullable=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ProcessedItem(db.Model):
    __tablename__ = "processed_items"
    id = db.Column(db.Integer, primary_key=True)

    source_type = db.Column(db.String(32), nullable=False, default="attachment")  # attachment|edi_doc
    source_id = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="ok")  # ok|error
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)

    cfe_serie = db.Column(db.String(16), nullable=True)
    cfe_numero = db.Column(db.String(32), nullable=True)
    receptor_nombre = db.Column(db.String(255), nullable=True)

    pdf_receipt_path = db.Column(db.String(512), nullable=True)
    pdf_change_path = db.Column(db.String(512), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("source_type", "source_id", name="uq_source"),)
