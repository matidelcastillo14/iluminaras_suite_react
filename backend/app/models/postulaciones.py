from __future__ import annotations

from datetime import datetime

from ..extensions import db


class JobPosition(db.Model):
    """Puestos disponibles para la postulación."""

    __tablename__ = "job_positions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobPosition {self.id} {self.name}>"


class JobApplication(db.Model):
    """Una postulación recibida desde el formulario público."""

    __tablename__ = "job_applications"

    id = db.Column(db.Integer, primary_key=True)

    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)

    # Teléfono de contacto (opcional pero recomendado en el formulario público)
    phone = db.Column(db.String(40), nullable=True)

    position_id = db.Column(db.Integer, db.ForeignKey("job_positions.id"), nullable=False)
    position = db.relationship("JobPosition", lazy="joined")

    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)

    status = db.Column(db.String(40), nullable=False, default="new")
    admin_note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    files = db.relationship(
        "JobApplicationFile",
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="JobApplicationFile.id.asc()",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobApplication {self.id} {self.email}>"


class JobApplicationFile(db.Model):
    """Adjunto subido junto a una postulación."""

    __tablename__ = "job_application_files"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("job_applications.id"), nullable=False)
    application = db.relationship("JobApplication", back_populates="files")

    original_filename = db.Column(db.String(260), nullable=False)
    stored_filename = db.Column(db.String(260), nullable=False)
    mime_type = db.Column(db.String(160), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    sha256 = db.Column(db.String(64), nullable=True)

    # Ruta relativa dentro de GENERATED_DIR. Ej: "postulaciones_files/123/uuid.pdf"
    rel_path = db.Column(db.String(520), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobApplicationFile {self.id} {self.original_filename}>"
