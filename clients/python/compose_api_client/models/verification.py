from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.verification_state import VerificationState
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.verification_failed_simulators_item import VerificationFailedSimulatorsItem


T = TypeVar("T", bound="Verification")


@_attrs_define
class Verification:
    """One request to biosim's /verify API about a comparison: the archive the comparison ran, on BioSimulators'
    simulators (docs/plan-verify-oracle.md). Once `completed`, each simulator's reports are a reference on the
    comparison, and `verify_close` says whether the simulators agree with each other.

        Attributes:
            verification_id (int):
            comparison_id (int):
            state (VerificationState):
            simulators (list[str]):
            workflow_id (None | str | Unset):
            workflow_status (None | str | Unset):
            verify_close (bool | None | Unset): BioSimulators' simulators agree on every report
            references (list[str] | Unset): the reference origins it added
            agrees_with (list[str] | Unset): our solvers whose every scored data set is close to each of its simulators'
                (once completed)
            failed_simulators (list[VerificationFailedSimulatorsItem] | Unset): simulators whose runs at biosimulations.org
                produced no results
            attempts (int | Unset):  Default: 0.
            last_error (None | str | Unset):
            created_at (None | str | Unset):
            updated_at (None | str | Unset):
    """

    verification_id: int
    comparison_id: int
    state: VerificationState
    simulators: list[str]
    workflow_id: None | str | Unset = UNSET
    workflow_status: None | str | Unset = UNSET
    verify_close: bool | None | Unset = UNSET
    references: list[str] | Unset = UNSET
    agrees_with: list[str] | Unset = UNSET
    failed_simulators: list[VerificationFailedSimulatorsItem] | Unset = UNSET
    attempts: int | Unset = 0
    last_error: None | str | Unset = UNSET
    created_at: None | str | Unset = UNSET
    updated_at: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        verification_id = self.verification_id

        comparison_id = self.comparison_id

        state = self.state.value

        simulators = self.simulators

        workflow_id: None | str | Unset
        if isinstance(self.workflow_id, Unset):
            workflow_id = UNSET
        else:
            workflow_id = self.workflow_id

        workflow_status: None | str | Unset
        if isinstance(self.workflow_status, Unset):
            workflow_status = UNSET
        else:
            workflow_status = self.workflow_status

        verify_close: bool | None | Unset
        if isinstance(self.verify_close, Unset):
            verify_close = UNSET
        else:
            verify_close = self.verify_close

        references: list[str] | Unset = UNSET
        if not isinstance(self.references, Unset):
            references = self.references

        agrees_with: list[str] | Unset = UNSET
        if not isinstance(self.agrees_with, Unset):
            agrees_with = self.agrees_with

        failed_simulators: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.failed_simulators, Unset):
            failed_simulators = []
            for failed_simulators_item_data in self.failed_simulators:
                failed_simulators_item = failed_simulators_item_data.to_dict()
                failed_simulators.append(failed_simulators_item)

        attempts = self.attempts

        last_error: None | str | Unset
        if isinstance(self.last_error, Unset):
            last_error = UNSET
        else:
            last_error = self.last_error

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        else:
            created_at = self.created_at

        updated_at: None | str | Unset
        if isinstance(self.updated_at, Unset):
            updated_at = UNSET
        else:
            updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "verification_id": verification_id,
            "comparison_id": comparison_id,
            "state": state,
            "simulators": simulators,
        })
        if workflow_id is not UNSET:
            field_dict["workflow_id"] = workflow_id
        if workflow_status is not UNSET:
            field_dict["workflow_status"] = workflow_status
        if verify_close is not UNSET:
            field_dict["verify_close"] = verify_close
        if references is not UNSET:
            field_dict["references"] = references
        if agrees_with is not UNSET:
            field_dict["agrees_with"] = agrees_with
        if failed_simulators is not UNSET:
            field_dict["failed_simulators"] = failed_simulators
        if attempts is not UNSET:
            field_dict["attempts"] = attempts
        if last_error is not UNSET:
            field_dict["last_error"] = last_error
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.verification_failed_simulators_item import VerificationFailedSimulatorsItem  # noqa: PLC0415

        d = dict(src_dict)
        verification_id = d.pop("verification_id")

        comparison_id = d.pop("comparison_id")

        state = VerificationState(d.pop("state"))

        simulators = cast(list[str], d.pop("simulators"))

        def _parse_workflow_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workflow_id = _parse_workflow_id(d.pop("workflow_id", UNSET))

        def _parse_workflow_status(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workflow_status = _parse_workflow_status(d.pop("workflow_status", UNSET))

        def _parse_verify_close(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        verify_close = _parse_verify_close(d.pop("verify_close", UNSET))

        references = cast(list[str], d.pop("references", UNSET))

        agrees_with = cast(list[str], d.pop("agrees_with", UNSET))

        _failed_simulators = d.pop("failed_simulators", UNSET)
        failed_simulators: list[VerificationFailedSimulatorsItem] | Unset = UNSET
        if _failed_simulators is not UNSET:
            failed_simulators = []
            for failed_simulators_item_data in _failed_simulators:
                failed_simulators_item = VerificationFailedSimulatorsItem.from_dict(failed_simulators_item_data)

                failed_simulators.append(failed_simulators_item)

        attempts = d.pop("attempts", UNSET)

        def _parse_last_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_error = _parse_last_error(d.pop("last_error", UNSET))

        def _parse_created_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_updated_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated_at = _parse_updated_at(d.pop("updated_at", UNSET))

        verification = cls(
            verification_id=verification_id,
            comparison_id=comparison_id,
            state=state,
            simulators=simulators,
            workflow_id=workflow_id,
            workflow_status=workflow_status,
            verify_close=verify_close,
            references=references,
            agrees_with=agrees_with,
            failed_simulators=failed_simulators,
            attempts=attempts,
            last_error=last_error,
            created_at=created_at,
            updated_at=updated_at,
        )

        verification.additional_properties = d
        return verification

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
