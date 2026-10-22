"""Comparisons and their members (compose_api/db/tables/comparison_tables.py)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, override

from sqlalchemy import ColumnElement, exists, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.comparison_tables import (
    ORMComparison,
    ORMComparisonMember,
    ORMComparisonReference,
    ORMSuiteRun,
    ORMVerification,
)
from compose_api.db.tables.simulator_tables import ORMSimulation


@dataclass
class ComparisonRow:
    comparison: ORMComparison
    members: list[ORMComparisonMember] = field(default_factory=list)
    references: list[ORMComparisonReference] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimedSuiteRun:
    """A suite run a worker holds: which sources it has to submit, and where it got to."""

    id: int
    collection: str
    number: int
    sources: list[str]
    next_source: int


@dataclass(frozen=True)
class ClaimedVerification:
    """A verification a worker holds (docs/plan-verify-oracle.md, V3)."""

    id: int
    comparison_id: int
    kind: str
    simulators: list[str]
    settings: dict[str, Any]
    state: str
    workflow_id: str | None
    attempts: int
    #: seconds since it was submitted to biosim, by the database's clock (the deadline, V3)
    submitted_seconds_ago: float | None


class ComparisonsDatabaseService(ABC):
    @abstractmethod
    async def insert(
        self,
        name: str,
        source: str,
        sedml: str,
        task: str,
        settings: dict[str, Any],
        collection: str | None = None,
        suite_run: int | None = None,
    ) -> int:
        """A new comparison, `running`, with no members; its id."""

    @abstractmethod
    async def new_suite_run(self, collection: str, sources: list[str] | None = None) -> tuple[int, int]:
        """The suite's next run (its number one more than the last), `submitting` its ``sources``: its id and
        number."""

    @abstractmethod
    async def claim_suite_runs(self, owner: str, lease_seconds: int, limit: int) -> list["ClaimedSuiteRun"]:
        """Lease up to ``limit`` suite runs still `submitting` that no live worker holds (``SKIP LOCKED``)."""

    @abstractmethod
    async def renew_suite_run_lease(self, run_id: int, owner: str, lease_seconds: int) -> bool: ...

    @abstractmethod
    async def release_suite_run(self, run_id: int, owner: str) -> None:
        """Give the run back at once (a worker shutting down), so the next worker resumes it without waiting out the
        lease."""

    @abstractmethod
    async def advance_suite_run(
        self, run_id: int, owner: str, next_source: int, failure: tuple[str, str] | None = None
    ) -> bool:
        """Record that the run has got past source ``next_source - 1``, with its failure if it had one; False when
        ``owner`` no longer holds the run."""

    @abstractmethod
    async def finish_suite_run(self, run_id: int, owner: str | None = None) -> None:
        """Every source is through: the run is `submitted`, and released."""

    @abstractmethod
    async def suite_source_submitted(self, collection: str, number: int, source: str) -> bool:
        """Whether the run already has a comparison for ``source`` (submitted before a restart)."""

    @abstractmethod
    async def suite_runs(self, collection: str) -> list[ORMSuiteRun]:
        """The suite's runs, newest first."""

    @abstractmethod
    async def suite_comparisons(self, collection: str, number: int) -> list[ComparisonRow]:
        """One suite run's comparisons, with members and references."""

    @abstractmethod
    async def add_member(self, comparison_id: int, simulation_id: int, solver: str) -> None: ...

    @abstractmethod
    async def add_reference(self, comparison_id: int, origin: str, reports: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get(self, comparison_id: int) -> ComparisonRow | None: ...

    @abstractmethod
    async def page(
        self, limit: int, offset: int, source: str | None = None, readable: ColumnElement[bool] | None = None
    ) -> tuple[list[ComparisonRow], int]:
        """Comparisons, newest first, with their members; and the total. With ``readable``, only comparisons every
        member simulation of which satisfies it."""

    @abstractmethod
    async def set_result(self, comparison_id: int, status: str, result: dict[str, Any] | None) -> None: ...

    # -- verifications (docs/plan-verify-oracle.md, V2) -- #

    @abstractmethod
    async def insert_verification(
        self, comparison_id: int, simulators: list[str], settings: dict[str, Any], kind: str = "omex"
    ) -> int:
        """A new `requested` verification of the comparison; its id."""

    @abstractmethod
    async def claim_verifications(self, owner: str, lease_seconds: int, limit: int) -> list[ClaimedVerification]:
        """Lease up to ``limit`` due verifications (`requested` or `submitted`) that no live worker holds."""

    @abstractmethod
    async def update_verification(self, verification_id: int, owner: str, **values: Any) -> bool:
        """Set fields on a verification ``owner`` holds; False when it no longer holds it."""

    @abstractmethod
    async def verifications(self, comparison_id: int) -> list[ORMVerification]:
        """The comparison's verifications, oldest first."""

    @abstractmethod
    async def latest_verifications(self, comparison_ids: list[int]) -> dict[int, ORMVerification]:
        """Each comparison's newest verification, for those that have one."""

    @abstractmethod
    async def replace_reference(self, comparison_id: int, origin: str, reports: dict[str, Any]) -> None:
        """Add the reference, or replace the one from the same origin."""


class ComparisonsORMExecutor(ComparisonsDatabaseService):
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.session_maker = session_maker

    @override
    async def insert(
        self,
        name: str,
        source: str,
        sedml: str,
        task: str,
        settings: dict[str, Any],
        collection: str | None = None,
        suite_run: int | None = None,
    ) -> int:
        async with self.session_maker() as session, session.begin():
            row = ORMComparison(
                name=name, source=source, sedml=sedml, task=task, settings=settings, collection=collection,
                suite_run=suite_run,
            )  # fmt: skip
            session.add(row)
            await session.flush()
            return row.id

    @override
    async def new_suite_run(self, collection: str, sources: list[str] | None = None) -> tuple[int, int]:
        async with self.session_maker() as session, session.begin():
            last = (
                await session.execute(select(func.max(ORMSuiteRun.number)).where(ORMSuiteRun.collection == collection))
            ).scalar_one()
            run = ORMSuiteRun(collection=collection, number=(last or 0) + 1, sources=list(sources or []))
            session.add(run)
            await session.flush()
            return run.id, run.number

    @override
    async def claim_suite_runs(self, owner: str, lease_seconds: int, limit: int) -> list["ClaimedSuiteRun"]:
        now = func.localtimestamp()
        due = (
            select(ORMSuiteRun.id)
            .where(
                ORMSuiteRun.status == "submitting",
                or_(ORMSuiteRun.lease_expires_at.is_(None), ORMSuiteRun.lease_expires_at < now),
            )
            .order_by(ORMSuiteRun.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self.session_maker() as session, session.begin():
            ids = list((await session.execute(due)).scalars().all())
            if not ids:
                return []
            await session.execute(
                update(ORMSuiteRun)
                .where(ORMSuiteRun.id.in_(ids))
                .values(lease_owner=owner, lease_expires_at=now + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds))
            )
            rows = await session.execute(select(ORMSuiteRun).where(ORMSuiteRun.id.in_(ids)).order_by(ORMSuiteRun.id))
            return [
                ClaimedSuiteRun(r.id, r.collection, r.number, list(r.sources or []), r.next_source)
                for r in rows.scalars()
            ]

    @override
    async def renew_suite_run_lease(self, run_id: int, owner: str, lease_seconds: int) -> bool:
        expires = func.localtimestamp() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds)
        return await self._update_held(run_id, owner, lease_expires_at=expires)

    @override
    async def release_suite_run(self, run_id: int, owner: str) -> None:
        await self._update_held(run_id, owner, lease_owner=None, lease_expires_at=None)

    @override
    async def advance_suite_run(
        self, run_id: int, owner: str, next_source: int, failure: tuple[str, str] | None = None
    ) -> bool:
        async with self.session_maker() as session, session.begin():
            run = (
                await session.execute(
                    select(ORMSuiteRun)
                    .where(ORMSuiteRun.id == run_id, ORMSuiteRun.lease_owner == owner)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                return False
            run.next_source = next_source
            if failure is not None:
                run.failures = {**run.failures, failure[0]: failure[1]}
            return True

    @override
    async def finish_suite_run(self, run_id: int, owner: str | None = None) -> None:
        async with self.session_maker() as session, session.begin():
            run = await session.get(ORMSuiteRun, run_id)
            if run is not None and (owner is None or run.lease_owner == owner):
                run.status, run.lease_owner, run.lease_expires_at = "submitted", None, None

    @override
    async def suite_source_submitted(self, collection: str, number: int, source: str) -> bool:
        async with self.session_maker() as session:
            found = await session.execute(
                select(ORMComparison.id).where(
                    ORMComparison.collection == collection,
                    ORMComparison.suite_run == number,
                    ORMComparison.source == source,
                )
            )
            return found.first() is not None

    async def _update_held(self, run_id: int, owner: str, **values: object) -> bool:
        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                update(ORMSuiteRun).where(ORMSuiteRun.id == run_id, ORMSuiteRun.lease_owner == owner).values(**values)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    @override
    async def suite_runs(self, collection: str) -> list[ORMSuiteRun]:
        async with self.session_maker() as session:
            rows = await session.execute(
                select(ORMSuiteRun).where(ORMSuiteRun.collection == collection).order_by(ORMSuiteRun.number.desc())
            )
            return list(rows.scalars())

    @override
    async def suite_comparisons(self, collection: str, number: int) -> list[ComparisonRow]:
        async with self.session_maker() as session:
            ids = list(
                (
                    await session.execute(
                        select(ORMComparison.id)
                        .where(ORMComparison.collection == collection, ORMComparison.suite_run == number)
                        .order_by(ORMComparison.id)
                    )
                ).scalars()
            )
        return [row for i in ids if (row := await self.get(i)) is not None]

    @override
    async def add_member(self, comparison_id: int, simulation_id: int, solver: str) -> None:
        async with self.session_maker() as session, session.begin():
            session.add(ORMComparisonMember(comparison_id=comparison_id, simulation_id=simulation_id, solver=solver))

    @override
    async def insert_verification(
        self, comparison_id: int, simulators: list[str], settings: dict[str, Any], kind: str = "omex"
    ) -> int:
        async with self.session_maker() as session, session.begin():
            row = ORMVerification(comparison_id=comparison_id, kind=kind, simulators=simulators, settings=settings)
            session.add(row)
            await session.flush()
            return row.id

    @override
    async def claim_verifications(self, owner: str, lease_seconds: int, limit: int) -> list[ClaimedVerification]:
        now = func.localtimestamp()
        due = (
            select(ORMVerification.id)
            .where(
                ORMVerification.state.in_(["requested", "submitted"]),
                ORMVerification.next_attempt_at <= now,
                or_(ORMVerification.lease_expires_at.is_(None), ORMVerification.lease_expires_at < now),
            )
            .order_by(ORMVerification.next_attempt_at, ORMVerification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self.session_maker() as session, session.begin():
            ids = list((await session.execute(due)).scalars().all())
            if not ids:
                return []
            await session.execute(
                update(ORMVerification)
                .where(ORMVerification.id.in_(ids))
                .values(lease_owner=owner, lease_expires_at=now + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds))
            )
            rows = await session.execute(
                select(ORMVerification, func.localtimestamp()).where(ORMVerification.id.in_(ids))
            )
            return [
                ClaimedVerification(
                    id=r.id,
                    comparison_id=r.comparison_id,
                    kind=r.kind,
                    simulators=list(r.simulators or []),
                    settings=dict(r.settings or {}),
                    state=r.state,
                    workflow_id=r.workflow_id,
                    attempts=r.attempts,
                    submitted_seconds_ago=None if r.submitted_at is None else (db_now - r.submitted_at).total_seconds(),
                )
                for r, db_now in rows.tuples()
            ]

    @override
    async def update_verification(self, verification_id: int, owner: str, **values: Any) -> bool:
        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                update(ORMVerification)
                .where(ORMVerification.id == verification_id, ORMVerification.lease_owner == owner)
                .values(updated_at=func.localtimestamp(), **values)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    @override
    async def verifications(self, comparison_id: int) -> list[ORMVerification]:
        async with self.session_maker() as session:
            rows = await session.execute(
                select(ORMVerification)
                .where(ORMVerification.comparison_id == comparison_id)
                .order_by(ORMVerification.id)
            )
            return list(rows.scalars())

    @override
    async def latest_verifications(self, comparison_ids: list[int]) -> dict[int, ORMVerification]:
        if not comparison_ids:
            return {}
        async with self.session_maker() as session:
            rows = await session.execute(
                select(ORMVerification)
                .where(ORMVerification.comparison_id.in_(comparison_ids))
                .order_by(ORMVerification.comparison_id, ORMVerification.id.desc())
                .distinct(ORMVerification.comparison_id)
            )
            return {r.comparison_id: r for r in rows.scalars()}

    @override
    async def replace_reference(self, comparison_id: int, origin: str, reports: dict[str, Any]) -> None:
        async with self.session_maker() as session, session.begin():
            existing = (
                await session.execute(
                    select(ORMComparisonReference).where(
                        ORMComparisonReference.comparison_id == comparison_id, ORMComparisonReference.origin == origin
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(ORMComparisonReference(comparison_id=comparison_id, origin=origin, reports=reports))
            else:
                existing.reports = reports

    @override
    async def add_reference(self, comparison_id: int, origin: str, reports: dict[str, Any]) -> None:
        async with self.session_maker() as session, session.begin():
            session.add(ORMComparisonReference(comparison_id=comparison_id, origin=origin, reports=reports))

    @override
    async def get(self, comparison_id: int) -> ComparisonRow | None:
        async with self.session_maker() as session:
            comparison = await session.get(ORMComparison, comparison_id)
            if comparison is None:
                return None
            references = await session.execute(
                select(ORMComparisonReference).where(ORMComparisonReference.comparison_id == comparison_id)
            )
            return ComparisonRow(comparison, await _members(session, comparison_id), list(references.scalars()))

    @override
    async def page(
        self, limit: int, offset: int, source: str | None = None, readable: ColumnElement[bool] | None = None
    ) -> tuple[list[ComparisonRow], int]:
        stmt = select(ORMComparison)
        if source is not None:
            stmt = stmt.where(ORMComparison.source == source)
        if readable is not None:
            hidden_member = (
                select(ORMComparisonMember.id)
                .join(ORMSimulation, ORMSimulation.id == ORMComparisonMember.simulation_id)
                .where(ORMComparisonMember.comparison_id == ORMComparison.id, not_(readable))
            )
            stmt = stmt.where(~exists(hidden_member))
        async with self.session_maker() as session:
            total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            found = list(
                (await session.execute(stmt.order_by(ORMComparison.id.desc()).limit(limit).offset(offset))).scalars()
            )
            members: dict[int, list[ORMComparisonMember]] = {c.id: [] for c in found}
            if found:
                rows = await session.execute(
                    select(ORMComparisonMember)
                    .where(ORMComparisonMember.comparison_id.in_(list(members)))
                    .order_by(ORMComparisonMember.id)
                )
                for m in rows.scalars():
                    members[m.comparison_id].append(m)
        return [ComparisonRow(c, members[c.id]) for c in found], int(total)

    @override
    async def set_result(self, comparison_id: int, status: str, result: dict[str, Any] | None) -> None:
        async with self.session_maker() as session, session.begin():
            comparison = await session.get(ORMComparison, comparison_id)
            if comparison is not None:
                comparison.status, comparison.result = status, result


async def _members(session: AsyncSession, comparison_id: int) -> list[ORMComparisonMember]:
    rows = await session.execute(
        select(ORMComparisonMember)
        .where(ORMComparisonMember.comparison_id == comparison_id)
        .order_by(ORMComparisonMember.id)
    )
    return list(rows.scalars())
