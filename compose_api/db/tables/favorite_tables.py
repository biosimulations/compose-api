"""A signed-in user's stars (docs/plan-favorites-and-studies.md, F5): private to the user, one per thing starred."""

import datetime

from sqlalchemy import String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase


class ORMFavorite(DeclarativeTableBase):
    __tablename__ = "favorite"
    __table_args__ = (UniqueConstraint("user_sub", "kind", "ref", name="uq_favorite_user_kind_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_sub: Mapped[str] = mapped_column(nullable=False, index=True)  # the identity provider's subject
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # a FavoriteKind
    ref: Mapped[str] = mapped_column(nullable=False)  # compose_api.favorites.normalize_ref
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
