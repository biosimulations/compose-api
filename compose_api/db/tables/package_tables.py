import datetime
import enum
import logging

from sqlalchemy import ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase, package_table_name
from compose_api.simulation.models import (
    BiGraphCompute,
    BiGraphComputeType,
    BiGraphProcess,
    BiGraphStep,
    PackageType,
    RegisteredPackage,
)

logger = logging.getLogger(__name__)


class PackageTypeDB(enum.Enum):
    PYPI = "pypi"
    CONDA = "conda"

    def to_package_type(self) -> "PackageType":
        return PackageType(self.value)

    @classmethod
    def from_package_type(cls, package_type: PackageType) -> "PackageTypeDB":
        return PackageTypeDB(package_type.value)


class BiGraphComputeTypeDB(enum.Enum):
    PROCESS = "process"
    STEP = "step"

    def to_compute_type(self) -> "BiGraphComputeType":
        return BiGraphComputeType(self.value)

    @classmethod
    def from_compute_type(cls, compute_type: BiGraphComputeType | None) -> "BiGraphComputeTypeDB":
        if compute_type is None:
            raise ValueError("No compute type specified")
        return BiGraphComputeTypeDB(compute_type.value)


class ORMPackage(DeclarativeTableBase):
    __tablename__ = package_table_name

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    package_type: Mapped[PackageTypeDB] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)

    __table_args__ = (UniqueConstraint("name", "package_type", name="unique_package_name_and_type"),)

    @classmethod
    def from_bigraph_package(cls, package: RegisteredPackage) -> "ORMPackage":
        return cls(
            id=package.database_id,
            name=package.name,
            package_type=PackageTypeDB.from_package_type(package.package_type),
        )

    def to_bigraph_package(self, processes: list[BiGraphProcess], steps: list[BiGraphStep]) -> RegisteredPackage:
        return RegisteredPackage(
            database_id=self.id,
            package_type=PackageType(self.package_type.value),
            name=self.name,
            processes=processes,
            steps=steps,
        )


class ORMBiGraphCompute(DeclarativeTableBase):
    __tablename__ = "bigraph_compute"

    id: Mapped[int] = mapped_column(primary_key=True)
    inserted_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    package_ref: Mapped[int] = mapped_column(ForeignKey(ORMPackage.__tablename__ + ".id"), nullable=False, index=True)
    module: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    compute_type: Mapped[BiGraphComputeTypeDB] = mapped_column(nullable=False)
    inputs: Mapped[str] = mapped_column(nullable=True)
    outputs: Mapped[str] = mapped_column(nullable=True)

    @classmethod
    def from_bigraph_compute(cls, compute: BiGraphCompute) -> "ORMBiGraphCompute":
        return cls(
            id=compute.database_id,
            module=compute.module,
            name=compute.name,
            compute_type=BiGraphComputeTypeDB.from_compute_type(compute.compute_type),
            inputs=compute.inputs,
            outputs=compute.outputs,
        )

    def to_bigraph_process(self) -> BiGraphProcess:
        if self.compute_type != BiGraphComputeTypeDB.PROCESS:
            raise TypeError("Compute type must be BiGraphComputeTypeDB Process")
        return BiGraphProcess(
            database_id=self.id,
            module=self.module,
            name=self.name,
            compute_type=self.compute_type.to_compute_type(),
            inputs=self.inputs,
            outputs=self.outputs,
        )

    def to_bigraph_step(self) -> BiGraphStep:
        if self.compute_type != BiGraphComputeTypeDB.STEP:
            raise TypeError("Compute type must be BiGraphComputeTypeDB Step")
        return BiGraphStep(
            database_id=self.id,
            module=self.module,
            name=self.name,
            compute_type=self.compute_type.to_compute_type(),
            inputs=self.inputs,
            outputs=self.outputs,
        )

    def to_bigraph_compute(self) -> BiGraphCompute:
        compute_type = self.compute_type.to_compute_type()
        match compute_type:
            case BiGraphComputeType.PROCESS:
                return self.to_bigraph_process()
            case BiGraphComputeType.STEP:
                return self.to_bigraph_step()
        raise ValueError(f"Compute type must be BiGraphComputeTypeDB: {compute_type}")


class ORMAllowList(DeclarativeTableBase):
    __tablename__ = "allow_list"

    id: Mapped[int] = mapped_column(primary_key=True)
    approved_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    package_name: Mapped[str] = mapped_column(nullable=False, index=True)
    package_type: Mapped[PackageTypeDB] = mapped_column(nullable=False)
    package_version: Mapped[str] = mapped_column(nullable=False)
