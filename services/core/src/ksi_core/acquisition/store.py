"""Durable, organization-scoped acquisition profile and heartbeat projection."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from ksi_core.acquisition.models import (
    RC_REQUIRED_CAPABILITIES,
    AcquisitionDeploymentProfileV1,
    AcquisitionReadinessView,
    CapabilityStatus,
    ConnectionState,
    ConnectivitySnapshotV1,
    OperatingMode,
    ReadinessStatus,
)
from ksi_core.api_base import iso_utc
from ksi_core.durable_journal import DurableJournal
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from collections.abc import Callable


class AcquisitionConnectivityStoreRecoveryError(RuntimeError):
    pass


class AcquisitionConnectivityStore:
    """장치 binding 변경 시 이전 snapshot을 폐기하는 append-only store."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_exists: Callable[[str, str], bool],
    ) -> None:
        self._journal = journal
        self._site_exists = site_exists
        self._lock = threading.RLock()
        self._profiles: dict[tuple[str, str], AcquisitionDeploymentProfileV1] = {}
        self._snapshots: dict[tuple[str, str], ConnectivitySnapshotV1] = {}
        self._snapshot_actors: dict[tuple[str, str], str] = {}
        self._snapshot_ids: set[tuple[str, str]] = set()
        self._replay(journal.replay())

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self, records: list[dict[str, object]]) -> None:
        try:
            for raw in records:
                kind = raw["kind"]
                organization_id = str(raw["organizationId"])
                if not is_path_safe_identifier(organization_id):
                    raise ValueError("invalid organizationId")
                if kind == "acquisition-profile-upserted":
                    profile = AcquisitionDeploymentProfileV1.model_validate(raw["profile"])
                    self._profiles[(organization_id, profile.site_id)] = profile
                    # Live upsert와 같은 projection: binding을 바꾸면 heartbeat도 초기화한다.
                    self._snapshots.pop((organization_id, profile.site_id), None)
                    self._snapshot_actors.pop((organization_id, profile.site_id), None)
                elif kind == "connectivity-observed":
                    snapshot = ConnectivitySnapshotV1.model_validate(raw["snapshot"])
                    actor = str(raw["actor"])
                    if not is_path_safe_identifier(actor):
                        raise ValueError("invalid snapshot actor")
                    snapshot_key = (organization_id, snapshot.snapshot_id)
                    if snapshot_key in self._snapshot_ids:
                        raise ValueError("reused snapshotId")
                    bound_profile = self._profiles.get((organization_id, snapshot.site_id))
                    if bound_profile is None:
                        raise ValueError("snapshot before profile")
                    self._assert_binding(bound_profile, snapshot)
                    current = self._snapshots.get((organization_id, snapshot.site_id))
                    if current is not None and snapshot.observed_at < current.observed_at:
                        raise ValueError("out-of-order snapshot")
                    self._snapshots[(organization_id, snapshot.site_id)] = snapshot
                    self._snapshot_actors[(organization_id, snapshot.site_id)] = actor
                    self._snapshot_ids.add(snapshot_key)
                else:
                    raise ValueError(f"unknown kind={kind!r}")
        except (KeyError, TypeError, ValueError) as exc:
            raise AcquisitionConnectivityStoreRecoveryError(
                f"acquisition connectivity journal 재생 실패: {exc}"
            ) from exc

    @staticmethod
    def _assert_binding(
        profile: AcquisitionDeploymentProfileV1, snapshot: ConnectivitySnapshotV1
    ) -> None:
        if snapshot.gateway_device_id != profile.gateway_device_id:
            raise ValueError("gatewayDeviceId가 Site profile binding과 다르다")
        if snapshot.edge_device_id != profile.edge_device_id:
            raise ValueError("edgeDeviceId가 Site profile binding과 다르다")

    def upsert_profile(
        self,
        profile: AcquisitionDeploymentProfileV1,
        *,
        organization_id: str,
        actor: str,
        now: datetime,
    ) -> AcquisitionDeploymentProfileV1:
        if not self._site_exists(profile.site_id, organization_id):
            raise LookupError("현장을 찾을 수 없다")
        record = {
            "kind": "acquisition-profile-upserted",
            "ts": iso_utc(now),
            "organizationId": organization_id,
            "actor": actor,
            "profile": profile.model_dump(mode="json", by_alias=True),
        }
        with self._lock:
            self._journal.append(record)
            self._profiles[(organization_id, profile.site_id)] = profile
            self._snapshots.pop((organization_id, profile.site_id), None)
            self._snapshot_actors.pop((organization_id, profile.site_id), None)
        return profile

    def get_profile(
        self, site_id: str, *, organization_id: str
    ) -> AcquisitionDeploymentProfileV1 | None:
        with self._lock:
            return self._profiles.get((organization_id, site_id))

    def current_trusted_context(
        self, site_id: str, *, organization_id: str
    ) -> tuple[
        AcquisitionDeploymentProfileV1 | None,
        ConnectivitySnapshotV1 | None,
        str | None,
    ]:
        """Return the exact current profile/snapshot plus authenticated ingest actor.

        CAP-5 uses this as a read-only legacy adapter input.  Keeping the actor
        projected from the original journal record preserves producer
        provenance across restart instead of inventing it during adaptation.
        """

        with self._lock:
            key = (organization_id, site_id)
            profile = self._profiles.get(key)
            snapshot = self._snapshots.get(key)
            actor = self._snapshot_actors.get(key)
            return profile, snapshot, actor

    @contextmanager
    def issuance_commit_guard(
        self, site_id: str, *, organization_id: str
    ) -> Iterator[
        tuple[AcquisitionDeploymentProfileV1 | None, ConnectivitySnapshotV1 | None]
    ]:
        """Mission OCC의 Acquisition witness를 보호하는 store-owned guard.

        Profile upsert와 heartbeat observation이 쓰는 동일 ``RLock``을 유지한 채
        현재 profile/snapshot을 돌려준다. Coordinator는 이 guard를 Site와 선택적
        WorkOrder guard 뒤, Mission append 앞에서 획득한다.
        """

        with self._lock:
            key = (organization_id, site_id)
            yield self._profiles.get(key), self._snapshots.get(key)

    def observe(
        self,
        snapshot: ConnectivitySnapshotV1,
        *,
        organization_id: str,
        actor: str,
        now: datetime,
    ) -> ConnectivitySnapshotV1:
        with self._lock:
            profile = self._profiles.get((organization_id, snapshot.site_id))
            if profile is None:
                raise LookupError("현장 acquisition profile을 찾을 수 없다")
            self._assert_binding(profile, snapshot)
            snapshot_key = (organization_id, snapshot.snapshot_id)
            if snapshot_key in self._snapshot_ids:
                raise ValueError("snapshotId는 재사용할 수 없다")
            current = self._snapshots.get((organization_id, snapshot.site_id))
            if current is not None and snapshot.observed_at < current.observed_at:
                raise ValueError("observedAt이 현재 heartbeat보다 과거다")
            if snapshot.observed_at > now + timedelta(minutes=1):
                raise ValueError("observedAt은 Core 시각보다 1분 이상 미래일 수 없다")
            self._journal.append(
                {
                    "kind": "connectivity-observed",
                    "ts": iso_utc(now),
                    "organizationId": organization_id,
                    "actor": actor,
                    "snapshot": snapshot.model_dump(mode="json", by_alias=True),
                }
            )
            self._snapshots[(organization_id, snapshot.site_id)] = snapshot
            self._snapshot_actors[(organization_id, snapshot.site_id)] = actor
            self._snapshot_ids.add(snapshot_key)
        return snapshot

    def readiness(
        self, site_id: str, *, organization_id: str, now: datetime
    ) -> AcquisitionReadinessView:
        with self._lock:
            profile = self._profiles.get((organization_id, site_id))
            snapshot = self._snapshots.get((organization_id, site_id))
        if profile is None:
            return self._view(site_id, ReadinessStatus.PROFILE_MISSING, now, None, None)
        if profile.operating_mode is OperatingMode.DOCK_AUTOMATED:
            return self._view(
                site_id,
                ReadinessStatus.DOCK_ADAPTER_NOT_IMPLEMENTED,
                now,
                profile,
                snapshot,
                "Dock adapter는 RC 제품 실증 뒤 구현한다",
            )
        if snapshot is None:
            return self._view(
                site_id,
                ReadinessStatus.CONNECTIVITY_MISSING,
                now,
                profile,
                None,
                "Gateway heartbeat가 없다",
            )
        if (
            snapshot.gateway_device_id != profile.gateway_device_id
            or snapshot.edge_device_id != profile.edge_device_id
        ):
            return self._view(
                site_id,
                ReadinessStatus.DEVICE_MISMATCH,
                now,
                profile,
                snapshot,
                "Gateway/Edge 장치 binding이 profile과 다르다",
            )
        if now >= snapshot.expires_at:
            return self._view(
                site_id,
                ReadinessStatus.CONNECTIVITY_STALE,
                now,
                profile,
                snapshot,
                "Gateway heartbeat가 만료됐다",
            )
        if snapshot.transport not in profile.gateway_transports:
            return self._view(
                site_id,
                ReadinessStatus.TRANSPORT_NOT_ALLOWED,
                now,
                profile,
                snapshot,
                "현재 transport가 profile에 허용되지 않았다",
            )
        if snapshot.gateway_state is not ConnectionState.CONNECTED:
            return self._view(
                site_id,
                ReadinessStatus.GATEWAY_OFFLINE,
                now,
                profile,
                snapshot,
                "RC Gateway 연결이 확인되지 않았다",
            )
        if not snapshot.internet_reachable:
            return self._view(
                site_id,
                ReadinessStatus.INTERNET_REQUIRED,
                now,
                profile,
                snapshot,
                "새 KSI 임무 발급 전 RC 인터넷이 필요하다",
            )
        verified = {
            item.capability
            for item in snapshot.capabilities
            if item.status is CapabilityStatus.VERIFIED and item.evidence_ref
        }
        missing = sorted(item.value for item in RC_REQUIRED_CAPABILITIES - verified)
        if missing:
            return self._view(
                site_id,
                ReadinessStatus.CAPABILITY_NOT_VERIFIED,
                now,
                profile,
                snapshot,
                "실기 검증이 필요한 capability: " + ", ".join(missing),
            )
        return self._view(site_id, ReadinessStatus.READY, now, profile, snapshot)

    @staticmethod
    def _view(
        site_id: str,
        status: ReadinessStatus,
        now: datetime,
        profile: AcquisitionDeploymentProfileV1 | None,
        snapshot: ConnectivitySnapshotV1 | None,
        *reasons: str,
    ) -> AcquisitionReadinessView:
        return AcquisitionReadinessView(
            site_id=site_id,
            status=status,
            ready_for_mission_issue=status is ReadinessStatus.READY,
            reasons=tuple(reasons),
            evaluated_at=now,
            profile=profile,
            connectivity=snapshot,
            in_flight_contract_policy="REMAINS_VALID_UNTIL_CONTRACT_EXPIRY",
        )


__all__ = ["AcquisitionConnectivityStore", "AcquisitionConnectivityStoreRecoveryError"]
