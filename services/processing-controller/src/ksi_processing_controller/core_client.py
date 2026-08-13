"""Core HTTP 클라이언트 — 워커가 처리 작업 표면을 말하는 유일한 경로.

:mod:`ksi_processing_controller.odm`/``http_node_odm`` 과 같은 관용구다 —
Protocol 로 포트를 두고, httpx 구현체는 "요청을 보내고 봉투를 벗긴다"까지만
한다. 상태 판정·재시도 정책은 이 모듈 밖(:mod:`worker`)에 둔다.

## Core 가 이미 정한 것을 여기서 다시 판단하지 않는다

lease 관문·전이표·INV-051 게이트는 전부 Core(``ksi_core.processing_jobs``)
쪽에 있다. 이 클라이언트는 그 판정 결과(HTTP status + verdict 문자열)를
그대로 :class:`CoreClientError` 로 옮길 뿐, "이 verdict 면 재시도해도 될까"
같은 판단을 하지 않는다 — 그 판단은 호출자(:mod:`worker`)의 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_event_contracts.change_region_report import ChangeRegionSetReport
from ksi_event_contracts.comparison_policy import ComparisonPolicy
from ksi_event_contracts.design_conformance_report import DesignConformanceReport, DiffRasterRef
from ksi_event_contracts.region_extraction_policy import RegionExtractionPolicy
from ksi_event_contracts.vertical_reference import VerticalReference
from ksi_event_contracts.volume_change_report import VolumeChangeReport


class CoreClientError(RuntimeError):
    """Core 가 성공 아닌 verdict 를 돌려줬다 — 워커가 다음 행동을 정한다.

    ``verdict`` 를 문자열로 들고 있는 이유: 워커가 재시도할지(``STORE_
    UNAVAILABLE``) 포기할지(``ILLEGAL_TRANSITION``)를 가르려면 값이 필요하다.
    이 클라이언트는 그 분기를 하지 않는다(모듈 docstring).
    """

    def __init__(self, *, what: str, verdict: str, detail: str | None) -> None:
        self.verdict = verdict
        self.detail = detail
        super().__init__(f"{what}: {verdict}" + (f" — {detail}" if detail else ""))


@dataclass(frozen=True, slots=True)
class PendingJob:
    """워커가 다음에 잡을 후보 1건 — Core 의 ``PendingProcessingJobView`` 를 옮긴 것.

    ``mission_id``·계약 내용이 없는 것이 의도다(``PROCESSING_WORK`` 는
    ``MISSIONS_READ`` 를 포함하지 않는다 — Core 쪽 스키마 docstring 참조). lease 를
    잡은 다음에야 :meth:`CoreClient.get_input` 이 전체 사양을 준다.
    """

    job_id: str


@dataclass(frozen=True, slots=True)
class JobInputMedia:
    media_id: str
    download_url: str


@dataclass(frozen=True, slots=True)
class JobInput:
    """``GET /input`` 을 옮긴 것 — **신고값이 없다**(source_media.py 참고)."""

    mission_id: str
    site_id: str
    status: str
    provider: str
    engine_version: str
    engine_digest: str
    execution_locus: str
    processing_params: dict[str, Any]
    source_bundle_digest: str
    media: tuple[JobInputMedia, ...]
    # 현장 등록 시점의 CRS — Core 가 site_store 에서 읽어 준다(워커·발급자가
    # 자기 신고하지 않는다). None 이면 현장 원장 이상 상태다.
    site_crs: str | None


@dataclass(frozen=True, slots=True)
class MeasuredImage:
    """워커가 실측한 값 — 신고값이 아니라 **바이트에서 잰 값**이다."""

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ArtifactSubmission:
    """``POST .../artifacts`` 요청 payload — 계보 앵커를 실을 자리가 없다."""

    artifact_id: str
    kind: str
    authority: str
    derived_from: tuple[str, ...]
    digest: str
    format: str
    crs: str | None
    gsd: float | None
    # 주 파일(digest/objectKey 가 가리키는 파일) 외 나머지 파일들의 basename —
    # 산출물이 파일 하나면 빈 튜플(mesh-multi-file-artifact-persistence).
    auxiliary_files: tuple[str, ...] = ()
    # 이 산출물 높이의 수직기준 — **파이프라인이 자기 동작을 근거로 선언한다**
    # (worker._ODM_VERTICAL_REFERENCE). None 이면 payload 에서 키째 빠져,
    # 그 등록은 수직기준을 밝히지 않은 v1.1 산출물로 남는다.
    vertical_reference: VerticalReference | None = None


@dataclass(frozen=True, slots=True)
class ArtifactUploadTarget:
    """산출물 바이트를 올릴 자리 — Core 가 정해서 내려준다.

    **워커가 객체 키를 고르지 않는다.** 고를 수 있으면 워커 토큰 하나로 버킷의
    임의 경로에 쓸 수 있고, "서버가 정한 자리에만 쓴다"를 워커 코드가 매번
    기억해야 한다.
    """

    object_key: str
    upload_url: str


@dataclass(frozen=True, slots=True)
class PendingComparisonRequest:
    """비교 워커가 다음에 잡을 후보 1건 — ``PendingJob`` 과 동형(§ 그 docstring)."""

    request_id: str


@dataclass(frozen=True, slots=True)
class ComparisonInput:
    """``GET /v1/comparison-requests/{id}/input`` 을 옮긴 것.

    ``*_url`` 은 presigned GET(바이트를 받을 자리), ``point_cloud_*``/``dsm_*``
    (``ArtifactRef | None``)는 그 바이트가 어느 (작업, 산출물)인지다 —
    ``ChangeDetectionResult``/``VolumeChangeReport`` 제출에 둘 다 필요하다.
    각 쌍이 ``None`` 이면 그 비교(변화탐지/체적)는 이 요청에서 시도하지 않는다.
    """

    request_id: str
    mission_id: str
    # 워커가 QUEUED→RUNNING 전이를 시도해도 되는지는 이 값으로만 안다 — 재개된
    # 요청(다른 워커가 이미 RUNNING 으로 바꿔 놓은 것)에 또 전이를 시도하면
    # ILLEGAL_TRANSITION 이다(worker.py 의 JobInput.status 와 동일 원칙).
    status: str
    # 이 요청 생성 시점에 굳어진 기준값 — 계산 함수의 기본값 대신 **이 값**을
    # 쓴다. 그래야 원장의 스냅샷이 "실제로 쓴 값"이 되고, 화면이 그 값을
    # 표시하는 것이 사실이 된다(comparison_policy 모듈 docstring).
    policy: ComparisonPolicy
    point_cloud_baseline: ArtifactRef | None
    point_cloud_baseline_url: str | None
    point_cloud_current: ArtifactRef | None
    point_cloud_current_url: str | None
    dsm_baseline: ArtifactRef | None
    dsm_baseline_url: str | None
    dsm_current: ArtifactRef | None
    dsm_current_url: str | None
    zones: dict[str, dict[str, Any]] | None
    zone_crs: str | None
    # 두 DSM 산출물이 각각 선언한 수직기준(``ProcessingArtifact.verticalReference``
    # 를 Core 가 그대로 전달한 것). ``None`` 이면 그 산출물은 수직기준이 기록되기
    # 전에 등록된 것이다 — 워커가 레거시 상수로 대체한다(comparison_worker
    # ``_resolve_vertical_datum``). 점군 쪽에 같은 필드를 두지 않은 이유는
    # ``ChangeDetectionResult`` 에 수직기준 필드가 없기 때문이다(C2C 거리는 세
    # 축의 차이라 단일 수직기준을 리포트가 싣지 않는다) — 쓰이지 않을 값을
    # 워커까지 실어 나르지 않는다.
    dsm_baseline_vertical_reference: VerticalReference | None = None
    dsm_current_vertical_reference: VerticalReference | None = None


@dataclass(frozen=True, slots=True)
class PendingDesignSurface:
    """검증 대기 설계면 1건 — ``GET /v1/design-surfaces`` 를 옮긴 것.

    **선언값(sha256·CRS)이 없는 것이 이 모델의 요점이다.** 그 값을 워커가 알면
    파일을 읽지 않고 되읊어 검증을 통과할 수 있다 — Core 는 "어느 파일을 어디서
    받아라"만 준다(``PendingJob``·``JobInput`` 과 같은 원칙).
    """

    design_surface_id: str
    site_id: str
    download_url: str


@dataclass(frozen=True, slots=True)
class DesignSurfaceMeasurement:
    """설계면 GeoTIFF 에서 **실제로 잰 값** — 판정도, 신원도, 시각도 없다.

    ``measuredAt``/``measuredBy`` 가 빠진 것이 의도다. 둘 다 Core 가 서버 시계와
    인증된 principal 로 채운다 — 워커가 "저쪽이 쟀다"거나 "어제 쟀다"를 주장할
    통로를 만들지 않는다(``MeasuredImage`` 와 같은 경계).
    """

    sha256: str
    crs: str
    width: int
    height: int
    band_count: int
    dtype: str
    pixel_size_x_m: float
    pixel_size_y_m: float
    transform: tuple[float, float, float, float, float, float]
    bounds_min_x: float
    bounds_min_y: float
    bounds_max_x: float
    bounds_max_y: float
    finite_cell_count: int
    vertical_crs_epsg: int | None = None
    nodata: float | None = None
    nodata_is_nan: bool = False


class DesignSurfaceCoreClient(Protocol):
    """설계면 검증 워커가 쓰는 Core 표면 — **딱 세 가지**.

    :class:`CoreClient` 에 합치지 않은 이유: 이 워커는 lease·전이·산출물 등록을
    하나도 쓰지 않는다. 큰 Protocol 하나에 얹으면 이 워커의 가짜 구현(테스트)이
    쓰지도 않는 20개 메서드를 흉내 내야 하고, 반대로 이 세 메서드가 없는 기존
    가짜 구현들이 전부 깨진다. 소비자가 필요로 하는 만큼만 요구한다.
    """

    def list_pending_design_surfaces(self, *, limit: int = 50) -> list[PendingDesignSurface]:
        """``GET /v1/design-surfaces?status=SEALED``. 봉인 순서(FIFO)."""
        ...

    def report_design_surface_observation(
        self, design_surface_id: str, measurement: DesignSurfaceMeasurement
    ) -> str:
        """``POST /observations``. 반환값은 Core 의 판정(``VERIFIED``/``REJECTED``…).

        ``REJECTED`` 는 **예외가 아니다** — 워커는 할 일을 다 했고, 파일이 선언과
        다르다는 것은 정상적으로 도출된 결론이다. 그걸 예외로 만들면 워커 루프가
        "실패"로 재시도하게 되는데, 같은 파일을 다시 읽어도 결과는 같다.
        """
        ...

    def report_design_surface_verification_failure(
        self, design_surface_id: str, *, detail: str | None = None
    ) -> None:
        """``POST /verification-failure``. 사유는 Core 가 UNREADABLE_RASTER 로 고정한다."""
        ...


@dataclass(frozen=True, slots=True)
class PendingDesignConformanceRequest:
    """설계 대비 워커가 다음에 잡을 후보 1건 — ``PendingComparisonRequest`` 동형."""

    request_id: str


@dataclass(frozen=True, slots=True)
class DesignConformanceInput:
    """``GET /v1/design-conformance-requests/{id}/input`` 을 옮긴 것.

    ``design_surface_sha256`` 이 여기 실리는 이유는 설계면 **검증** 워커와 반대다.
    저쪽은 신고값을 알면 파일을 읽지 않고 되읊을 수 있어 받지 않지만, 여기서 이
    값의 용도는 판정이 아니라 "받아온 바이트가 그때 검증된 그 파일인가"이고
    (``run_design_conformance._assert_design_bytes_unchanged``), 그 확인은 이 값
    없이는 불가능하다.

    ``design_conformance_id``/``diff_raster_id`` 도 Core 가 준다 — id 도출 규칙을
    워커가 복제하면 한쪽만 바뀌는 날 리포트가 어느 요청의 것인지 되짚어지지 않는다.
    """

    request_id: str
    mission_id: str
    status: str
    policy: ComparisonPolicy
    design_conformance_id: str
    diff_raster_id: str
    design_surface_id: str
    design_surface_sha256: str
    design_surface_url: str
    design_vertical_reference: VerticalReference
    current: ArtifactRef
    current_url: str
    current_vertical_reference: VerticalReference
    zones: dict[str, dict[str, Any]]
    zone_crs: str


@dataclass(frozen=True, slots=True)
class DiffRasterUploadTarget:
    """차분 래스터를 올릴 자리 — ``ArtifactUploadTarget`` 과 같은 경계(키는 Core 가 정한다)."""

    object_key: str
    upload_url: str
    content_type: str


class DesignConformanceCoreClient(Protocol):
    """설계 대비 워커가 쓰는 Core 표면 — ``DesignSurfaceCoreClient`` 와 같은 관용구.

    :class:`CoreClient` 에 합치지 않는 이유도 같다: 이 워커는 재구성·비교 표면을
    하나도 쓰지 않는다. 큰 Protocol 하나에 얹으면 이 워커의 가짜 구현이 쓰지도
    않는 20개 메서드를 흉내 내야 하고, 반대로 기존 가짜 구현들이 전부 깨진다.
    """

    def list_pending_design_conformances(
        self, *, limit: int = 50
    ) -> list[PendingDesignConformanceRequest]:
        """``GET /v1/design-conformance-requests``. QUEUED + lease 만료된 RUNNING."""
        ...

    def acquire_design_conformance_lease(self, request_id: str) -> None:
        """``POST /{id}/lease``. LEASED·LEASE_RENEWED 외엔 :class:`CoreClientError`."""
        ...

    def get_design_conformance_input(self, request_id: str) -> DesignConformanceInput:
        """``GET /{id}/input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition_design_conformance(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        """``POST /{id}/transitions``. TRANSITIONED 외엔 :class:`CoreClientError`."""
        ...

    def presign_diff_raster_upload(self, request_id: str) -> DiffRasterUploadTarget:
        """``POST /{id}/diff-raster-upload-url``. UPLOAD_READY 외엔 예외."""
        ...

    def verify_diff_raster(
        self, request_id: str, *, digest: str, size_bytes: int
    ) -> datetime:
        """``POST /{id}/diff-raster-verification`` — **Core 가 그 객체를 다시 해싱한다.**

        반환값은 Core 가 확인한 시각이고, 그것만이 리포트의
        ``diffRaster.coreVerifiedDigestAt`` 이 될 수 있다. 신고와 다르면
        ``DIFF_RASTER_DIGEST_MISMATCH`` 로 :class:`CoreClientError` 가 오른다 —
        그래야 **리포트가 아예 만들어지지 않는다**.
        """
        ...

    def submit_design_conformance(
        self, mission_id: str, report: DesignConformanceReport
    ) -> None:
        """``POST /v1/missions/{id}/design-conformance``. RECORDED 외엔 예외."""
        ...


@dataclass(frozen=True, slots=True)
class PendingRegionExtractionRequest:
    """변화 영역 추출 워커가 다음에 잡을 후보 1건 — ``PendingComparisonRequest`` 동형."""

    request_id: str


@dataclass(frozen=True, slots=True)
class RegionExtractionInput:
    """``GET /v1/region-extraction-requests/{id}/input`` 을 옮긴 것.

    이 요청은 설계 대비 잔량 리포트가 이미 만든 diffRaster 를 **다시 만들지
    않고 읽기만** 한다 — 그래서 ``diff_raster`` 는 그 원본 리포트의 ``DiffRasterRef``
    를 그대로 옮긴 것이고, ``threshold_m``/``crs`` 도 그 리포트의 값이다(계산이
    새로 정하는 값이 아니다). ``extraction_policy`` 만 예외다 — policy-owned
    기반안(``region_extraction_policy.py`` 모듈 docstring)에 따라 Core 가
    ``current_region_extraction_policy()`` 를 매 호출마다 새로 계산해 준다.
    """

    request_id: str
    mission_id: str
    status: str
    design_conformance_id: str
    change_region_set_id: str
    diff_raster_id: str
    diff_raster_url: str
    diff_raster: DiffRasterRef
    threshold_m: float
    crs: str
    extraction_policy: RegionExtractionPolicy


class RegionExtractionCoreClient(Protocol):
    """변화 영역 추출 워커가 쓰는 Core 표면 — ``DesignConformanceCoreClient`` 와 같은 관용구.

    :class:`CoreClient` 에 합치지 않는 이유도 같다: 이 워커는 재구성·비교·
    설계면 검증 표면을 하나도 쓰지 않는다.
    """

    def list_pending_region_extractions(
        self, *, limit: int = 50
    ) -> list[PendingRegionExtractionRequest]:
        """``GET /v1/region-extraction-requests``. QUEUED + lease 만료된 RUNNING."""
        ...

    def acquire_region_extraction_lease(self, request_id: str) -> None:
        """``POST /{id}/lease``. LEASED·LEASE_RENEWED 외엔 :class:`CoreClientError`."""
        ...

    def get_region_extraction_input(self, request_id: str) -> RegionExtractionInput:
        """``GET /{id}/input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition_region_extraction(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        """``POST /{id}/transitions``. TRANSITIONED 외엔 :class:`CoreClientError`."""
        ...

    def submit_region_extraction(self, mission_id: str, report: ChangeRegionSetReport) -> None:
        """``POST /v1/missions/{id}/region-extraction``. RECORDED 외엔 예외."""
        ...


class CoreClient(Protocol):
    """워커가 필요로 하는 Core 표면. 이 이상을 워커가 알 필요는 없다."""

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        """``GET /v1/processing-jobs``. QUEUED + lease 만료된 RUNNING(죽은 워커가
        쥐고 있던 작업), 오래된 것부터(FIFO)."""
        ...

    def acquire_lease(self, job_id: str) -> None:
        """``POST /lease``. LEASED·LEASE_RENEWED 외엔 :class:`CoreClientError`."""
        ...

    def get_input(self, job_id: str) -> JobInput:
        """``GET /input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition(self, job_id: str, target: str, *, detail: str | None = None) -> None:
        """``POST /transitions``. TRANSITIONED 외엔 :class:`CoreClientError`."""
        ...

    def verify_source_media(
        self, mission_id: str, measurements: list[MeasuredImage]
    ) -> None:
        """``POST /source-media/verify``. VERIFIED·ALREADY_VERIFIED 외엔 예외."""
        ...

    def presign_artifact_upload(
        self, job_id: str, *, artifact_id: str, content_type: str, filename: str | None = None
    ) -> ArtifactUploadTarget:
        """``POST /artifacts/upload-url``. UPLOAD_READY 외엔 :class:`CoreClientError`.

        ``filename`` 은 다중 파일 산출물(mesh 등)에서 주 파일 외 나머지 각각을
        올릴 때 채운다 — ``None`` 이면 주 파일 자리(기존 동작과 동일)다.
        """
        ...

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        """``POST /artifacts``. ARTIFACT_REGISTERED 외엔 :class:`CoreClientError`."""
        ...

    # ── W2 비교 요청(comparison_requests.py) ────────────────────────────────

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        """``GET /v1/comparison-requests``. QUEUED + lease 만료된 RUNNING, 오래된 것부터."""
        ...

    def acquire_comparison_lease(self, request_id: str) -> None:
        """``POST /comparison-requests/{id}/lease``. LEASED·LEASE_RENEWED 외엔 예외."""
        ...

    def get_comparison_input(self, request_id: str) -> ComparisonInput:
        """``GET /comparison-requests/{id}/input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        """``POST /comparison-requests/{id}/transitions``. TRANSITIONED 외엔 예외."""
        ...

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        """``POST /v1/missions/{id}/change-detection``. RECORDED 외엔 :class:`CoreClientError`."""
        ...

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        """``POST /v1/missions/{id}/volume-changes``. RECORDED 외엔 :class:`CoreClientError`."""
        ...


class WorkerCoreClient(
    CoreClient,
    DesignSurfaceCoreClient,
    DesignConformanceCoreClient,
    RegionExtractionCoreClient,
    Protocol,
):
    """폴링 루프(:mod:`runner`) 하나가 요구하는 표면 전부 — 다섯 종류 후보의 합집합.

    Protocol 을 나눠 두고 여기서만 합치는 이유: 각 워커 함수는 자기가 쓰는
    것만 요구해야 가짜 구현이 작아지고(``run_comparison_request`` 는 설계면 표면을
    모른다), 반대로 **한 프로세스가 다섯 종류를 다 도는 것**은 runner 의 사실이라
    그 자리에서만 합집합을 요구한다.
    """


class HttpCoreClient:
    """httpx 로 Core 표면을 말한다. 판단은 하지 않는다(모듈 docstring)."""

    def __init__(self, base_url: str, *, token: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        # ``client`` 를 주입해도(테스트 등) ``token`` 이 조용히 무시되지 않는다 —
        # 둘 다 준 호출자는 "이 토큰으로 이 클라이언트를 써라"를 뜻하지 "클라이언트가
        # 있으니 토큰은 버려라"를 뜻하지 않는다. 실기동 전까지 이 자리가 정확히
        # 거꾸로였다: 주입된 클라이언트는 인증 헤더 없이 나갔다.
        self._client.headers["Authorization"] = f"Bearer {token}"

    def _post(
        self,
        path: str,
        *,
        what: str,
        ok: str | frozenset[str],
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``ok`` 는 문자열 하나 또는 성공으로 볼 verdict 집합이다.

        **집합을 받는 이유가 실기동에서 드러났다.** ``acquire_lease`` 가 처음엔
        ``ok="LEASED"`` 만 넘기고, 갱신(``LEASE_RENEWED``)까지 성공으로 보는
        검증은 이 함수가 이미 예외를 던진 **뒤**에 있는 죽은 코드였다 — 가짜
        ``CoreClient`` 로 짠 단위 테스트는 이 HTTP 번역 계층 자체를 우회해서
        통과했지만, 실제 Core+NodeODM 대상 완주 시도에서 heartbeat 갱신이
        일어나는 순간 곧바로 죽었다(``lease: LEASE_RENEWED`` 예외). 그래서
        판정 집합은 호출부가 아니라 이 함수가 한 번에 본다.
        """
        response = self._client.post(f"{self._base_url}{path}", json=json)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what=what, verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        verdict = payload.get("verdict")
        accepted = {ok} if isinstance(ok, str) else ok
        if verdict not in accepted:
            raise CoreClientError(what=what, verdict=str(verdict), detail=payload.get("detail"))
        return payload

    def _get_json(
        self, path: str, *, what: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """대기 목록 4종이 공유하는 GET — 봉투를 벗기고 status 를 verdict 로 옮긴다.

        ``_post`` 와 달리 verdict 필드가 없는 표면이라(목록 응답은 성공 하나뿐)
        HTTP 상태가 곧 판정이다. 네 곳이 같은 다섯 줄을 반복하고 있었다.
        """
        response = self._client.get(f"{self._base_url}{path}", params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what=what, verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if response.status_code != 200:
            raise CoreClientError(
                what=what,
                verdict=f"HTTP_{response.status_code}",
                detail=str(payload.get("detail")) if isinstance(payload, dict) else None,
            )
        return dict(payload)

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        payload = self._get_json(
            "/v1/processing-jobs", what="list-pending", params={"limit": limit}
        )
        return [PendingJob(job_id=item["jobId"]) for item in payload["jobs"]]

    def acquire_lease(self, job_id: str) -> None:
        self._post(
            f"/v1/processing-jobs/{job_id}/lease",
            what="lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

    def get_input(self, job_id: str) -> JobInput:
        response = self._client.get(f"{self._base_url}/v1/processing-jobs/{job_id}/input")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="input", verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="input", verdict=str(payload.get("verdict")), detail=payload.get("detail")
            )
        data = payload["input"]
        return JobInput(
            mission_id=data["missionId"],
            site_id=data["siteId"],
            status=data["status"],
            provider=data["provider"],
            engine_version=data["engineVersion"],
            engine_digest=data["engineDigest"],
            execution_locus=data["executionLocus"],
            processing_params=data["processingParams"],
            source_bundle_digest=data["sourceBundleDigest"],
            site_crs=data.get("siteCrs"),
            media=tuple(
                JobInputMedia(media_id=m["mediaId"], download_url=m["downloadUrl"])
                for m in data["media"]
            ),
        )

    def transition(self, job_id: str, target: str, *, detail: str | None = None) -> None:
        self._post(
            f"/v1/processing-jobs/{job_id}/transitions",
            what=f"transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def verify_source_media(
        self, mission_id: str, measurements: list[MeasuredImage]
    ) -> None:
        # ALREADY_VERIFIED 도 성공이다 — 재시도 작업(이전 시도가 실패한 뒤
        # 새로 발급된 작업)이 같은 미션의 이미 검증된 번들에 다시 보고하면
        # 정확히 이 verdict 가 나온다(실기동에서 실제로 발생, 2026-08-06).
        self._post(
            f"/v1/missions/{mission_id}/source-media/verify",
            what="verify",
            ok=frozenset({"VERIFIED", "ALREADY_VERIFIED"}),
            json={
                "measurements": [
                    {
                        "mediaId": m.media_id,
                        "sha256": m.sha256,
                        "bytes": m.size_bytes,
                        "width": m.width,
                        "height": m.height,
                    }
                    for m in measurements
                ]
            },
        )

    def presign_artifact_upload(
        self, job_id: str, *, artifact_id: str, content_type: str, filename: str | None = None
    ) -> ArtifactUploadTarget:
        payload = self._post(
            f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
            what=f"upload-url:{artifact_id}:{filename or '(primary)'}",
            ok="UPLOAD_READY",
            json={
                "artifactId": artifact_id,
                "contentType": content_type,
                "filename": filename,
            },
        )
        object_key = payload.get("objectKey")
        upload_url = payload.get("uploadUrl")
        if not isinstance(object_key, str) or not isinstance(upload_url, str):
            # verdict 는 UPLOAD_READY 인데 자리가 안 왔다 — 여기서 잡지 않으면
            # 다음 줄의 PUT 이 None 을 URL 로 쓴다.
            raise CoreClientError(
                what=f"upload-url:{artifact_id}",
                verdict="UPLOAD_READY",
                detail="응답에 objectKey/uploadUrl 이 없다",
            )
        return ArtifactUploadTarget(object_key=object_key, upload_url=upload_url)

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        payload: dict[str, Any] = {
            "artifactId": submission.artifact_id,
            "kind": submission.kind,
            "authority": submission.authority,
            "derivedFrom": list(submission.derived_from),
            "digest": submission.digest,
            "format": submission.format,
            "crs": submission.crs,
            "gsd": submission.gsd,
            "auxiliaryFiles": list(submission.auxiliary_files),
        }
        if submission.vertical_reference is not None:
            # 모를 때 명시적 null 을 보내지 않는다 — 키가 없는 것과 null 은
            # Core 에서 같은 None 이지만, 보내지 않으면 옛 워커의 payload 와
            # 바이트가 같아 "이 필드가 무해하다"가 요청 표면에서도 사실이 된다.
            payload["verticalReference"] = submission.vertical_reference.model_dump(
                by_alias=True, mode="json"
            )
        self._post(
            f"/v1/processing-jobs/{job_id}/artifacts",
            what=f"artifact:{submission.artifact_id}",
            ok="ARTIFACT_REGISTERED",
            json=payload,
        )

    # ── W2 비교 요청(comparison_requests.py) ────────────────────────────────

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        payload = self._get_json(
            "/v1/comparison-requests",
            what="list-pending-comparisons",
            params={"limit": limit},
        )
        return [
            PendingComparisonRequest(request_id=item["requestId"]) for item in payload["requests"]
        ]

    def acquire_comparison_lease(self, request_id: str) -> None:
        self._post(
            f"/v1/comparison-requests/{request_id}/lease",
            what="comparison-lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

    def get_comparison_input(self, request_id: str) -> ComparisonInput:
        response = self._client.get(f"{self._base_url}/v1/comparison-requests/{request_id}/input")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="comparison-input", verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="comparison-input",
                verdict=str(payload.get("verdict")),
                detail=payload.get("detail"),
            )
        data = payload["input"]

        def _ref(key: str) -> ArtifactRef | None:
            raw = data.get(key)
            if raw is None:
                return None
            return ArtifactRef(job_id=raw["jobId"], artifact_id=raw["artifactId"])

        def _vertical_reference(key: str) -> VerticalReference | None:
            raw = data.get(key)
            if raw is None:
                return None
            return VerticalReference.model_validate(raw)

        return ComparisonInput(
            request_id=data["requestId"],
            mission_id=data["missionId"],
            status=data["status"],
            policy=ComparisonPolicy.model_validate(data["policy"]),
            point_cloud_baseline=_ref("pointCloudBaseline"),
            point_cloud_baseline_url=data.get("pointCloudBaselineUrl"),
            point_cloud_current=_ref("pointCloudCurrent"),
            point_cloud_current_url=data.get("pointCloudCurrentUrl"),
            dsm_baseline=_ref("dsmBaseline"),
            dsm_baseline_url=data.get("dsmBaselineUrl"),
            dsm_current=_ref("dsmCurrent"),
            dsm_current_url=data.get("dsmCurrentUrl"),
            zones=data.get("zones"),
            zone_crs=data.get("zoneCrs"),
            dsm_baseline_vertical_reference=_vertical_reference("dsmBaselineVerticalReference"),
            dsm_current_vertical_reference=_vertical_reference("dsmCurrentVerticalReference"),
        )

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self._post(
            f"/v1/comparison-requests/{request_id}/transitions",
            what=f"comparison-transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        self._post(
            f"/v1/missions/{mission_id}/change-detection",
            what=f"change-detection:{result.change_detection_id}",
            ok="RECORDED",
            json=result.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        self._post(
            f"/v1/missions/{mission_id}/volume-changes",
            what=f"volume-change:{report.volume_change_id}",
            ok="RECORDED",
            json=report.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    # ── M4-A 설계 기준면 검증 (design_surfaces.py) ─────────────────────────

    def list_pending_design_surfaces(self, *, limit: int = 50) -> list[PendingDesignSurface]:
        payload = self._get_json(
            "/v1/design-surfaces",
            what="list-pending-design-surfaces",
            params={"status": "SEALED", "limit": limit},
        )
        return [
            PendingDesignSurface(
                design_surface_id=item["designSurfaceId"],
                site_id=item["siteId"],
                download_url=item["downloadUrl"],
            )
            for item in payload["surfaces"]
        ]

    def report_design_surface_observation(
        self, design_surface_id: str, measurement: DesignSurfaceMeasurement
    ) -> str:
        payload = self._post(
            f"/v1/design-surfaces/{design_surface_id}/observations",
            what=f"design-surface-observation:{design_surface_id}",
            # REJECTED·ALREADY_JUDGED 도 정상 종료다 — 워커는 잰 값을 전달했고
            # 판정은 Core 의 몫이다(Protocol docstring).
            ok=frozenset({"VERIFIED", "REJECTED", "ALREADY_JUDGED"}),
            json={
                "sha256": measurement.sha256,
                "crs": measurement.crs,
                "verticalCrsEpsg": measurement.vertical_crs_epsg,
                "width": measurement.width,
                "height": measurement.height,
                "bandCount": measurement.band_count,
                "dtype": measurement.dtype,
                "nodata": measurement.nodata,
                "nodataIsNan": measurement.nodata_is_nan,
                "pixelSizeXM": measurement.pixel_size_x_m,
                "pixelSizeYM": measurement.pixel_size_y_m,
                "transform": list(measurement.transform),
                "boundsMinX": measurement.bounds_min_x,
                "boundsMinY": measurement.bounds_min_y,
                "boundsMaxX": measurement.bounds_max_x,
                "boundsMaxY": measurement.bounds_max_y,
                "finiteCellCount": measurement.finite_cell_count,
            },
        )
        return str(payload["verdict"])

    def report_design_surface_verification_failure(
        self, design_surface_id: str, *, detail: str | None = None
    ) -> None:
        self._post(
            f"/v1/design-surfaces/{design_surface_id}/verification-failure",
            what=f"design-surface-verification-failure:{design_surface_id}",
            ok=frozenset({"REJECTED", "ALREADY_JUDGED"}),
            json={"detail": detail},
        )

    # ── M4-A 설계 대비 잔량 (design_conformance_requests.py) ───────────────

    def list_pending_design_conformances(
        self, *, limit: int = 50
    ) -> list[PendingDesignConformanceRequest]:
        payload = self._get_json(
            "/v1/design-conformance-requests",
            what="list-pending-design-conformances",
            params={"limit": limit},
        )
        return [
            PendingDesignConformanceRequest(request_id=item["requestId"])
            for item in payload["requests"]
        ]

    def acquire_design_conformance_lease(self, request_id: str) -> None:
        self._post(
            f"/v1/design-conformance-requests/{request_id}/lease",
            what="design-conformance-lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

    def get_design_conformance_input(self, request_id: str) -> DesignConformanceInput:
        response = self._client.get(
            f"{self._base_url}/v1/design-conformance-requests/{request_id}/input"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="design-conformance-input",
                verdict="NON_JSON_RESPONSE",
                detail=response.text[:200],
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="design-conformance-input",
                verdict=str(payload.get("verdict")),
                detail=payload.get("detail"),
            )
        data = payload["input"]
        return DesignConformanceInput(
            request_id=data["requestId"],
            mission_id=data["missionId"],
            status=data["status"],
            policy=ComparisonPolicy.model_validate(data["policy"]),
            design_conformance_id=data["designConformanceId"],
            diff_raster_id=data["diffRasterId"],
            design_surface_id=data["designSurfaceId"],
            design_surface_sha256=data["designSurfaceSha256"],
            design_surface_url=data["designSurfaceUrl"],
            design_vertical_reference=VerticalReference.model_validate(
                data["designVerticalReference"]
            ),
            current=ArtifactRef(
                job_id=data["current"]["jobId"], artifact_id=data["current"]["artifactId"]
            ),
            current_url=data["currentUrl"],
            current_vertical_reference=VerticalReference.model_validate(
                data["currentVerticalReference"]
            ),
            zones=data["zones"],
            zone_crs=data["zoneCrs"],
        )

    def transition_design_conformance(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self._post(
            f"/v1/design-conformance-requests/{request_id}/transitions",
            what=f"design-conformance-transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def presign_diff_raster_upload(self, request_id: str) -> DiffRasterUploadTarget:
        payload = self._post(
            f"/v1/design-conformance-requests/{request_id}/diff-raster-upload-url",
            what=f"diff-raster-upload-url:{request_id}",
            ok="UPLOAD_READY",
        )
        object_key = payload.get("objectKey")
        upload_url = payload.get("uploadUrl")
        content_type = payload.get("contentType")
        if (
            not isinstance(object_key, str)
            or not isinstance(upload_url, str)
            or not isinstance(content_type, str)
        ):
            # verdict 는 UPLOAD_READY 인데 자리가 안 왔다 — 여기서 잡지 않으면
            # 다음 줄의 PUT 이 None 을 URL 로 쓴다(presign_artifact_upload 와 동일).
            raise CoreClientError(
                what=f"diff-raster-upload-url:{request_id}",
                verdict="UPLOAD_READY",
                detail="응답에 objectKey/uploadUrl/contentType 이 없다",
            )
        return DiffRasterUploadTarget(
            object_key=object_key, upload_url=upload_url, content_type=content_type
        )

    def verify_diff_raster(
        self, request_id: str, *, digest: str, size_bytes: int
    ) -> datetime:
        payload = self._post(
            f"/v1/design-conformance-requests/{request_id}/diff-raster-verification",
            what=f"diff-raster-verification:{request_id}",
            ok="DIFF_RASTER_VERIFIED",
            json={"digest": digest, "sizeBytes": size_bytes},
        )
        verified_at = payload.get("verifiedAt")
        if not isinstance(verified_at, str):
            # 확인 시각 없이는 리포트를 만들 수 없다(계약 필수 필드) — 조용히
            # 지금 시각으로 채우면 그 필드가 다시 워커의 주장이 된다.
            raise CoreClientError(
                what=f"diff-raster-verification:{request_id}",
                verdict="DIFF_RASTER_VERIFIED",
                detail="응답에 verifiedAt 이 없다",
            )
        return datetime.fromisoformat(verified_at)

    def submit_design_conformance(
        self, mission_id: str, report: DesignConformanceReport
    ) -> None:
        self._post(
            f"/v1/missions/{mission_id}/design-conformance",
            what=f"design-conformance:{report.design_conformance_id}",
            ok="RECORDED",
            json=report.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    # ── M4-E 변화 영역 자동 추출 (region_extraction_requests.py) ────────────

    def list_pending_region_extractions(
        self, *, limit: int = 50
    ) -> list[PendingRegionExtractionRequest]:
        payload = self._get_json(
            "/v1/region-extraction-requests",
            what="list-pending-region-extractions",
            params={"limit": limit},
        )
        return [
            PendingRegionExtractionRequest(request_id=item["requestId"])
            for item in payload["requests"]
        ]

    def acquire_region_extraction_lease(self, request_id: str) -> None:
        self._post(
            f"/v1/region-extraction-requests/{request_id}/lease",
            what="region-extraction-lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

    def get_region_extraction_input(self, request_id: str) -> RegionExtractionInput:
        response = self._client.get(
            f"{self._base_url}/v1/region-extraction-requests/{request_id}/input"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="region-extraction-input",
                verdict="NON_JSON_RESPONSE",
                detail=response.text[:200],
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="region-extraction-input",
                verdict=str(payload.get("verdict")),
                detail=payload.get("detail"),
            )
        data = payload["input"]
        return RegionExtractionInput(
            request_id=data["requestId"],
            mission_id=data["missionId"],
            status=data["status"],
            design_conformance_id=data["designConformanceId"],
            change_region_set_id=data["changeRegionSetId"],
            diff_raster_id=data["diffRasterId"],
            diff_raster_url=data["diffRasterUrl"],
            diff_raster=DiffRasterRef.model_validate(data["diffRaster"]),
            threshold_m=data["thresholdM"],
            crs=data["crs"],
            extraction_policy=RegionExtractionPolicy.model_validate(data["extractionPolicy"]),
        )

    def transition_region_extraction(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self._post(
            f"/v1/region-extraction-requests/{request_id}/transitions",
            what=f"region-extraction-transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def submit_region_extraction(self, mission_id: str, report: ChangeRegionSetReport) -> None:
        self._post(
            f"/v1/missions/{mission_id}/region-extraction",
            what=f"region-extraction:{report.change_region_set_id}",
            ok="RECORDED",
            json=report.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    def close(self) -> None:
        self._client.close()


__all__ = [
    "ArtifactSubmission",
    "ArtifactUploadTarget",
    "ComparisonInput",
    "CoreClient",
    "CoreClientError",
    "DesignConformanceCoreClient",
    "DesignConformanceInput",
    "DesignSurfaceCoreClient",
    "DesignSurfaceMeasurement",
    "DiffRasterUploadTarget",
    "HttpCoreClient",
    "JobInput",
    "JobInputMedia",
    "MeasuredImage",
    "PendingComparisonRequest",
    "PendingDesignConformanceRequest",
    "PendingDesignSurface",
    "PendingJob",
    "PendingRegionExtractionRequest",
    "RegionExtractionCoreClient",
    "RegionExtractionInput",
    "WorkerCoreClient",
]
