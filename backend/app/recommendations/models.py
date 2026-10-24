from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import new_id

class RecommendationSnapshot(Base):
    __tablename__ = 'recommendation_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'), index=True)
    precheck_id: Mapped[str] = mapped_column(ForeignKey('prechecks.id'))
    need: Mapped[dict] = mapped_column(JSON)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[list] = mapped_column(JSON)
    catalog_version: Mapped[str] = mapped_column(String(80))
    rules_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
