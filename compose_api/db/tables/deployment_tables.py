"""This deployment's identity (#543): one row, written once, so `GET /health` can say which deployment answered."""

import datetime

from sqlalchemy import CheckConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase

SINGLETON_ID = 1


class ORMDeployment(DeclarativeTableBase):
    __tablename__ = "deployment"
    __table_args__ = (CheckConstraint(f"id = {SINGLETON_ID}", name="ck_deployment_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=SINGLETON_ID)
    deployment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
