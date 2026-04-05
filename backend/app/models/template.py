from __future__ import annotations

from datetime import datetime
from ..extensions import db

class PdfTemplate(db.Model):
    __tablename__ = "pdf_templates"

    id = db.Column(db.Integer, primary_key=True)
    template_type = db.Column(db.String(64), nullable=False, index=True)  # cfe_ticket, cfe_change, shipping_label
    name = db.Column(db.String(120), nullable=False)
    engine = db.Column(db.String(32), nullable=False, default="legacy")  # legacy | layout_json
    layout_json = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @staticmethod
    def get_active(template_type: str) -> "PdfTemplate|None":
        return PdfTemplate.query.filter_by(template_type=template_type, is_active=True).first()
