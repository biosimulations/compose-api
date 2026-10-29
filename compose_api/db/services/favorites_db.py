"""Storage for favorites (docs/plan-favorites-and-studies.md, F5)."""

from abc import ABC, abstractmethod
from typing import override

from sqlalchemy import ColumnElement, Integer, Select, cast, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from compose_api.db.tables.favorite_tables import ORMFavorite
from compose_api.favorites import Favorite, FavoriteKind, iso


def favorite_ids(user_sub: str, kind: FavoriteKind) -> Select[tuple[int]]:
    """The ids the user starred, of a kind named by id (a simulation or a comparison), as a subquery for listings."""
    return select(cast(ORMFavorite.ref, Integer)).where(
        ORMFavorite.user_sub == user_sub, ORMFavorite.kind == kind.value
    )


def starred(column: InstrumentedAttribute[int], user_sub: str, kind: FavoriteKind) -> ColumnElement[bool]:
    """``column`` (an id) is one the user starred."""
    return column.in_(favorite_ids(user_sub, kind))


class FavoritesDatabaseService(ABC):
    @abstractmethod
    async def add(self, user_sub: str, kind: FavoriteKind, ref: str) -> Favorite:
        """Star it; starring it again changes nothing and returns the star there is."""

    @abstractmethod
    async def remove(self, user_sub: str, kind: FavoriteKind, ref: str) -> bool:
        """Unstar it; whether there was a star."""

    @abstractmethod
    async def list_favorites(self, user_sub: str, kind: FavoriteKind | None = None) -> list[Favorite]:
        """The user's stars, newest first; of one kind, or all."""

    @abstractmethod
    async def refs(self, user_sub: str, kind: FavoriteKind) -> set[str]:
        """The references of the user's stars of one kind."""


class FavoritesORMExecutor(FavoritesDatabaseService):
    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    @override
    async def add(self, user_sub: str, kind: FavoriteKind, ref: str) -> Favorite:
        async with self.async_session_maker() as session, session.begin():
            await session.execute(
                insert(ORMFavorite)
                .values(user_sub=user_sub, kind=kind.value, ref=ref)
                .on_conflict_do_nothing(constraint="uq_favorite_user_kind_ref")
            )
            row = (
                await session.execute(
                    select(ORMFavorite).where(
                        ORMFavorite.user_sub == user_sub, ORMFavorite.kind == kind.value, ORMFavorite.ref == ref
                    )
                )
            ).scalar_one()
            return _favorite(row)

    @override
    async def remove(self, user_sub: str, kind: FavoriteKind, ref: str) -> bool:
        async with self.async_session_maker() as session, session.begin():
            result = await session.execute(
                delete(ORMFavorite)
                .where(ORMFavorite.user_sub == user_sub, ORMFavorite.kind == kind.value, ORMFavorite.ref == ref)
                .returning(ORMFavorite.id)
            )
            return result.first() is not None

    @override
    async def list_favorites(self, user_sub: str, kind: FavoriteKind | None = None) -> list[Favorite]:
        stmt = select(ORMFavorite).where(ORMFavorite.user_sub == user_sub)
        if kind is not None:
            stmt = stmt.where(ORMFavorite.kind == kind.value)
        async with self.async_session_maker() as session:
            rows = (await session.execute(stmt.order_by(ORMFavorite.id.desc()))).scalars().all()
        return [_favorite(row) for row in rows]

    @override
    async def refs(self, user_sub: str, kind: FavoriteKind) -> set[str]:
        stmt = select(ORMFavorite.ref).where(ORMFavorite.user_sub == user_sub, ORMFavorite.kind == kind.value)
        async with self.async_session_maker() as session:
            return set((await session.execute(stmt)).scalars().all())


def _favorite(row: ORMFavorite) -> Favorite:
    return Favorite(kind=FavoriteKind(row.kind), ref=row.ref, created_at=iso(row.created_at))
