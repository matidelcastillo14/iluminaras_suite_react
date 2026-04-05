from __future__ import annotations

from datetime import datetime
from typing import Optional

from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from ..extensions import db

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    first_name = db.Column(db.String(120), nullable=False, default="")
    last_name = db.Column(db.String(120), nullable=False, default="")
    phone = db.Column(db.String(50), nullable=True)
    attendance_ref_code = db.Column(db.String(64), nullable=True, index=True)
    home_office_clock_enabled = db.Column(db.Boolean, default=False, nullable=False)

    role = db.Column(db.String(32), nullable=False, default="operator")  # admin/operator/readonly
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def has_role(self, role: str) -> bool:
        if self.role == "admin":
            return True
        return self.role == role
