from __future__ import annotations

from datetime import datetime
from ..extensions import db

class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @staticmethod
    def get(key: str, default: str = "") -> str:
        row = Setting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key: str, value: str) -> None:
        row = Setting.query.get(key)
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            db.session.add(row)
