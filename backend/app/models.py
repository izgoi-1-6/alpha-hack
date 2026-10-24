from datetime import date, datetime
from uuid import uuid4
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def new_id() -> str:
    return str(uuid4())

class User(Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint("role IN ('CLIENT','CREDIT_OFFICER')", name='valid_user_role'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class AuthSession(Base):
    __tablename__ = 'sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class Company(Base):
    __tablename__ = 'companies'
    __table_args__ = (UniqueConstraint('owner_user_id', 'inn', name='company_owner_inn'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    inn: Mapped[str] = mapped_column(String(12))
    entity_type: Mapped[str] = mapped_column(String(3))
    name: Mapped[str | None] = mapped_column(String(250))
    registered_at: Mapped[date | None] = mapped_column(Date)
    registry_status: Mapped[str] = mapped_column(String(10))
    okved: Mapped[str | None] = mapped_column(String(30))
    region: Mapped[str | None] = mapped_column(String(200))
    legal_address: Mapped[str | None] = mapped_column(String(500))
    fixture_id: Mapped[str | None] = mapped_column(String(80))
    business_reference_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Precheck(Base):
    __tablename__ = 'prechecks'
    __table_args__ = (UniqueConstraint('company_id', 'company_version', name='precheck_company_revision'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'), index=True)
    company_version: Mapped[int] = mapped_column(Integer)
    registry_source_status: Mapped[str] = mapped_column(String(12))
    turnover_source_status: Mapped[str] = mapped_column(String(12))
    registry_payload: Mapped[dict] = mapped_column(JSON)
    turnover_payload: Mapped[dict] = mapped_column(JSON)
    monthly_revenue_rub: Mapped[int | None] = mapped_column(BigInteger)
    previous_monthly_revenue_rub: Mapped[int | None] = mapped_column(BigInteger)
    financial_period_end: Mapped[date | None] = mapped_column(Date)
    source_version: Mapped[str] = mapped_column(String(80))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

class Consent(Base):
    __tablename__ = 'consents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'), index=True)
    # Application FK is introduced by the application milestone migration.
    application_id: Mapped[str | None] = mapped_column(String(36))
    code: Mapped[str] = mapped_column(String(40))
    text_version: Mapped[str] = mapped_column(String(80))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class IdempotencyRecord(Base):
    __tablename__ = 'idempotency_records'
    __table_args__ = (UniqueConstraint('actor_id', 'method', 'path', 'key', name='idempotency_scope'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSON)
    resource_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
