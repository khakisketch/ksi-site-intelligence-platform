"""NodeODM 어댑터 계약 (ADR-KSI-012 D1/D2, ADR-KSI-003, INV-051).

초점 넷:

1. **AGPL 경계가 기계로 강제된다** — 이 패키지는 ODM/WebODM 을 import 하지
   않는다. D2 가 "이 ADR 의 핵심 안전선"이라고 부른 것을 사람이 기억해서
   지키는 규칙으로 두지 않는다.
2. **engineVersion 은 제출 전에 사실과 대조된다** — 다른 엔진이 돌면 계약의
   재현성 앵커가 거짓이 된다.
3. **산출물 계보가 ODM 파이프라인의 실제 흐름과 같다** — 포인트 클라우드·카메라
   포즈가 원본, 메시·정사영상·DEM 이 파생.
4. **모르는 상태·행은 실패로 읽는다** — fail-closed.

**실제 NodeODM 컨테이너 대상 검증은 이 파일에 없다.** 여기 있는 것은 포트를
가짜로 갈아끼운 계약 시험이고, 실기동 확인은 별도 게이트다(HIL 성격).
"""

from __future__ import annotations

import ast
import hashlib
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.processing_artifact import (
    LineageAuthority,
    ProcessingArtifact,
    ProcessingArtifactKind,
)
from ksi_processing_controller import odm as odm_module
from ksi_processing_controller.odm import (
    ArtifactReport,
    EngineIdentityMismatch,
    MaskImage,
    OdmEngineInfo,
    OdmError,
    OdmTaskState,
    OdmTaskStatus,
    SourceImage,
    assert_engine_matches,
    iter_archive_entry_bytes,
    parse_task_status,
    plan_artifacts,
    run_to_completion,
    unwrap_response,
)
from ksi_processing_controller.odm_assets import ODM_ASSETS, POINT_CLOUD_ID
from rasterio.transform import from_origin

_PACKAGE_ROOT = (
    Path(odm_module.__file__).resolve().parent
)
_ENGINE_VERSION = "3.5.6"
_CRS = "EPSG:5186"


# ── AGPL 경계 (ADR-KSI-012 D2) ──────────────────────────────────────────────

# 이 패키지가 import 하면 "별도 저작물"이라는 전제가 깨지는 이름들. PyODM 은
# BSD-3 라 허용이지만(D2 "허용" 항), 지금 구현은 그것도 쓰지 않는다.
_AGPL_MODULE_PREFIXES = ("opendm", "odm", "webodm", "opensfm")


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_package_never_imports_agpl_engine_code() -> None:
    """[핵심] 엔진과의 결합은 REST 프로세스 경계뿐이다 — import 결합이 없다.

    ADR-KSI-012 D2 의 금지선("우리 오케스트레이터를 ODM 소스 트리 안에
    배치하거나 같은 프로세스·같은 빌드 산출물로 링크하는 것")을 기계가 지킨다.
    이 테스트가 없으면 D2 는 문서에만 있는 규칙이 된다.
    """
    sources = sorted(_PACKAGE_ROOT.rglob("*.py"))
    assert sources, "패키지 소스를 찾지 못했다 — 이 테스트가 공허하다"
    for source in sources:
        for name in _imported_module_names(source):
            root = name.split(".")[0].lower()
            assert root not in _AGPL_MODULE_PREFIXES, (
                f"{source.name} 이 AGPL 엔진 모듈 {name!r} 을 import 한다 — "
                "ADR-KSI-012 D2 위반(REST 경계만 허용)"
            )


def test_engine_boundary_is_five_rest_calls() -> None:
    """포트 표면이 늘어나면 경계가 흐려진다 — 늘릴 땐 이 목록을 함께 고친다."""
    surface = {
        name
        for name in vars(odm_module.NodeOdmClient)
        if not name.startswith("_")
    }
    assert surface == {
        "info", "new_task", "task_info", "download_archive", "remove_task"
    }


# ── 엔진 신원 대조 ───────────────────────────────────────────────────────────


def _info(engine_version: str = _ENGINE_VERSION, *, engine: str = "odm") -> OdmEngineInfo:
    return OdmEngineInfo(
        engine=engine, engine_version=engine_version, node_version="2.2.4"
    )


def test_matching_engine_version_passes() -> None:
    assert_engine_matches(_info(), expected_version=_ENGINE_VERSION)


@pytest.mark.parametrize("actual", ["3.5.5", "3.5", "2.9.9", ""])
def test_any_version_difference_refuses_submission(actual: str) -> None:
    """[핵심] '호환되는가'를 판정하지 않는다 — 다르면 안 돌린다.

    semver 호환 판정을 넣으면 이 함수가 엔진별 버전 정책을 알아야 하고, 그
    정책이 틀리면 조용히 다른 엔진이 돈다.
    """
    with pytest.raises(EngineIdentityMismatch, match="재현성 앵커"):
        assert_engine_matches(_info(actual), expected_version=_ENGINE_VERSION)


def test_node_version_is_not_mistaken_for_engine_version() -> None:
    """[핵심·실물이 고쳐준 것] /info 는 버전을 둘 준다 — 대조 대상은 engineVersion 이다.

    처음 구현은 NodeODM 자신의 version(2.2.4)을 계약의 engineVersion 과 비교해서
    늘 어긋났고, 애초에 다른 것을 비교하고 있었다. 실기동 전까지 드러나지 않았다.
    """
    info = OdmEngineInfo(engine="odm", engine_version="3.5.6", node_version="2.2.4")
    assert_engine_matches(info, expected_version="3.5.6")
    with pytest.raises(EngineIdentityMismatch):
        assert_engine_matches(info, expected_version="2.2.4")


def test_a_different_engine_is_refused() -> None:
    """provider 가 odm 이 아닌 엔진에 이 어댑터를 붙이지 않는다."""
    with pytest.raises(EngineIdentityMismatch, match="어댑터"):
        assert_engine_matches(_info(engine="pix4d"), expected_version=_ENGINE_VERSION)


def test_info_payload_parsing_uses_the_real_field_names() -> None:
    """실물 /info 응답을 그대로 넣어 필드 이름을 고정한다."""
    payload = {
        "version": "2.2.4",
        "taskQueueCount": 0,
        "totalMemory": 130660868096,
        "availableMemory": 110265094144,
        "cpuCores": 20,
        "maxImages": None,
        "maxParallelTasks": 1,
        "engineVersion": "3.5.6",
        "engine": "odm",
    }
    info = OdmEngineInfo.from_payload(payload)
    assert info.engine == "odm"
    assert info.engine_version == "3.5.6"
    assert info.node_version == "2.2.4"


def test_error_envelope_arrives_with_http_200() -> None:
    """[핵심·실물이 고쳐준 것] 미지 uuid·미준비 asset 이 200 + {"error": ...} 다.

    상태 코드만 보는 클라이언트는 이것을 성공으로 읽고 다음 줄에서 KeyError 를
    낸다 — 원인이 두 겹 뒤에서 드러나는 실패다.
    """
    with pytest.raises(OdmError, match="not found"):
        unwrap_response({"error": "abc not found"}, what="/task/info")
    with pytest.raises(OdmError, match="Asset not ready"):
        unwrap_response({"error": "Asset not ready"}, what="/download")
    assert unwrap_response({"uuid": "u1"}, what="/task/new") == {"uuid": "u1"}


def test_task_state_parses_the_real_failure_payload() -> None:
    """실물이 준 실패 응답 — errorMessage 를 지어내지 않고 그대로 옮긴다."""
    state = OdmTaskState.from_payload(
        {
            "uuid": "533c4fd7",
            "processingTime": 4373,
            "status": {"code": 30, "errorMessage": "Cannot process dataset"},
            "imagesCount": 2,
            "progress": 100,
        }
    )
    assert state.status is OdmTaskStatus.FAILED
    assert state.error_message == "Cannot process dataset"
    assert state.progress == 100


# ── 상태 코드 매핑 — 모르는 값은 실패다 ──────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (10, OdmTaskStatus.QUEUED),
        (20, OdmTaskStatus.RUNNING),
        (30, OdmTaskStatus.FAILED),
        (40, OdmTaskStatus.COMPLETED),
        (50, OdmTaskStatus.CANCELED),
    ],
)
def test_known_status_codes_map_to_domain(code: int, expected: OdmTaskStatus) -> None:
    assert parse_task_status(code) is expected


@pytest.mark.parametrize("code", [0, 15, 60, 999, -1])
def test_unknown_status_code_is_read_as_failure(code: int) -> None:
    """[fail-closed] '아직 안 끝났나 보다'로 읽으면 워커가 영원히 폴링한다."""
    assert parse_task_status(code) is OdmTaskStatus.FAILED


# ── 가짜 NodeODM ─────────────────────────────────────────────────────────────


class FakeNodeOdm:
    """포트 계약만 만족하는 가짜 엔진 — 네트워크·컨테이너 없이 돈다."""

    def __init__(
        self,
        *,
        engine_version: str = _ENGINE_VERSION,
        states: list[OdmTaskState] | None = None,
        entries: set[str] | None = None,
    ) -> None:
        self.engine_version = engine_version
        self.states = states or [OdmTaskState(status=OdmTaskStatus.COMPLETED)]
        self.entries = (
            entries if entries is not None else {a.archive_entry for a in ODM_ASSETS}
        )
        self.submitted: list[SourceImage] = []
        self.submitted_masks: list[MaskImage] = []
        self.removed: list[str] = []
        self._state_index = 0

    def info(self) -> OdmEngineInfo:
        return OdmEngineInfo(
            engine="odm", engine_version=self.engine_version, node_version="2.2.4"
        )

    def new_task(
        self, images: Any, options: dict[str, Any], *, masks: Any = ()
    ) -> str:
        del options
        self.submitted = list(images)
        self.submitted_masks = list(masks)
        return "task-uuid-1"

    def task_info(self, uuid: str) -> OdmTaskState:
        del uuid
        state = self.states[min(self._state_index, len(self.states) - 1)]
        self._state_index += 1
        return state

    def download_archive(self, uuid: str, dest: Path) -> Path:
        del uuid
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w") as archive:
            for entry in sorted(self.entries):
                archive.writestr(entry, f"내용:{entry}".encode())
        return dest

    def remove_task(self, uuid: str) -> None:
        self.removed.append(uuid)


def _archive(tmp_path: Path, engine: FakeNodeOdm | None = None) -> Path:
    """가짜 엔진이 만든 all.zip — plan_artifacts 의 실제 입력."""
    return (engine or FakeNodeOdm()).download_archive("u1", tmp_path / "all.zip")


_IMAGES = (SourceImage(media_id="img-1.jpg", download_url="https://s.invalid/1"),)
_GSD = {"orthophoto": 0.031, "dsm": 0.05, "dtm": 0.05}


# ── 산출물 계보 ─────────────────────────────────────────────────────────────


def test_lineage_matches_the_odm_pipeline(tmp_path: Path) -> None:
    """[핵심] 원본은 SfM/MVS 직접 산출물, 나머지는 거기서 파생(ADR-KSI-003)."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact=_GSD)
    by_id = {r.artifact_id: r for r in reports}

    assert by_id["camera-poses"].authority == "source"
    assert by_id[POINT_CLOUD_ID].authority == "source"
    assert by_id["mesh"].authority == "derived"
    assert by_id["mesh"].derived_from == (POINT_CLOUD_ID,)
    assert by_id["orthophoto"].derived_from == ("mesh",)
    assert by_id["dsm"].derived_from == (POINT_CLOUD_ID,)


def test_parents_are_registered_before_their_children(tmp_path: Path) -> None:
    """등록 순서가 곧 계보다 — Core 는 실재하는 부모만 허용한다."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact=_GSD)
    position = {r.artifact_id: i for i, r in enumerate(reports)}
    for report in reports:
        for parent in report.derived_from:
            assert position[parent] < position[report.artifact_id], (
                f"{report.artifact_id} 가 부모 {parent} 보다 먼저 등록된다"
            )


def test_reports_satisfy_the_artifact_contract(tmp_path: Path) -> None:
    """[수용기준] 어댑터가 만든 값이 계약을 실제로 통과한다 — 필드 이름만 맞추지 않는다."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact=_GSD)
    for report in reports:
        artifact = ProcessingArtifact(
            artifact_id=report.artifact_id,
            job_id="mission-1-pj1",
            kind=ProcessingArtifactKind(report.kind),
            lineage={  # type: ignore[arg-type]
                "authority": report.authority,
                "derivedFrom": list(report.derived_from),
                "sourceDigest": "sha256:" + "a" * 64,
            },
            digest=report.digest,
            format=report.fmt,
            crs=report.crs,
            gsd=report.gsd,
            accuracy=None,
        )
        # ODM 경로에는 구조화된 정확도 리포트가 없다 — 지어내지 않는다.
        assert artifact.accuracy is None


def test_camera_poses_carry_no_crs(tmp_path: Path) -> None:
    """공간 좌표계가 원천적으로 없는 산출물에 값을 지어내지 않는다."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact=_GSD)
    poses = next(r for r in reports if r.artifact_id == "camera-poses")
    assert poses.crs is None


# ── CRS 는 신고가 아니라 실측이다 (2026-08-15 실물 확인 — DSM 실제
#    EPSG:32630 인데 등록된 crs 는 site crs "EPSG:5186" 이었다) ────────────────


def _real_geotiff_bytes(epsg: str) -> bytes:
    """단일 밴드 2x2 GeoTIFF — 임베디드 CRS만 의미 있고 셀 값은 무관하다."""
    with rasterio.io.MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            crs=epsg,
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.zeros((2, 2), dtype="uint8"), 1)
        return memfile.read()


def _archive_with_real_dsm(tmp_path: Path, *, dsm_epsg: str) -> Path:
    """표준 all.zip 이되, dsm.tif 만 실제 GeoTIFF(다른 CRS)로 채운다.

    나머지 엔트리는 기존 관용구(플레이스홀더 텍스트)를 그대로 둔다 — 그래야
    "실측이 있으면 그것을 쓰고, 없으면(파싱 실패) site crs 로 폴백한다"는
    분기 둘 다를 이 archive 하나로 같이 확인할 수 있다.
    """
    dsm_entry = next(a for a in ODM_ASSETS if a.artifact_id == "dsm").archive_entry
    path = tmp_path / "all.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for asset in ODM_ASSETS:
            if asset.archive_entry == dsm_entry:
                archive.writestr(dsm_entry, _real_geotiff_bytes(dsm_epsg))
            else:
                archive.writestr(asset.archive_entry, f"내용:{asset.archive_entry}".encode())
    return path


def test_dsm_crs_is_read_from_the_real_file_not_assumed_from_site(tmp_path: Path) -> None:
    """[핵심] 산출물의 crs는 실제로 그 파일을 열어 읽은 값이다 — site crs 를 그냥 베끼지 않는다.

    GPS 없이 재구성되면 NodeODM 은 site crs 와 무관한 임의 좌표계를 낸다
    (실물 확인, EPSG:32630). 이전엔 이 경우에도 site crs 를 그대로 신고해
    Core 의 산출물 메타데이터가 실제 파일과 어긋났다.
    """
    archive_path = _archive_with_real_dsm(tmp_path, dsm_epsg="EPSG:32630")
    reports = plan_artifacts(archive_path, crs=_CRS, gsd_by_artifact=_GSD)
    dsm = next(r for r in reports if r.artifact_id == "dsm")
    assert dsm.crs == "EPSG:32630"
    assert dsm.crs != _CRS


def test_dsm_crs_falls_back_to_site_crs_when_file_has_none(tmp_path: Path) -> None:
    """실제 파일에서 읽을 CRS가 없으면(파싱 실패 등) site crs 로 폴백한다 —
    조용히 빈 값으로 두지 않는다."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact=_GSD)
    dsm = next(r for r in reports if r.artifact_id == "dsm")
    assert dsm.crs == _CRS


def test_missing_optional_assets_are_skipped_not_failed(tmp_path: Path) -> None:
    """ODM 은 옵션에 따라 DTM·정사영상을 안 만든다 — 정상 설정이 실패가 되면 안 된다."""
    engine = FakeNodeOdm(
        entries={
            "odm_report/shots.geojson",
            "odm_georeferencing/odm_georeferenced_model.laz",
        }
    )
    reports = plan_artifacts(_archive(tmp_path, engine), crs=_CRS)
    assert {r.artifact_id for r in reports} == {"camera-poses", POINT_CLOUD_ID}


def test_raster_without_gsd_is_skipped_rather_than_invented(tmp_path: Path) -> None:
    """[핵심] 지어낸 GSD 를 싣느니 산출물을 뺀다 — 계약이 null 을 금지하는 kind 다."""
    reports = plan_artifacts(_archive(tmp_path), crs=_CRS, gsd_by_artifact={})
    assert not [r for r in reports if r.artifact_id in {"orthophoto", "dsm", "dtm"}]
    # 원본은 그대로 남는다 — GSD 는 래스터만의 고유 속성이다.
    assert POINT_CLOUD_ID in {r.artifact_id for r in reports}


def test_derived_without_its_parent_is_not_registered(tmp_path: Path) -> None:
    """부모 없이 파생만 내놓는 엔진 응답은 계보 없는 파생이라 등록하지 않는다."""
    engine = FakeNodeOdm(
        entries={
            "odm_report/shots.geojson",
            "odm_texturing/odm_textured_model_geo.obj",  # mesh, 부모(point cloud) 없음
        }
    )
    reports = plan_artifacts(_archive(tmp_path, engine), crs=_CRS)
    assert {r.artifact_id for r in reports} == {"camera-poses"}


def test_no_source_artifact_is_an_error(tmp_path: Path) -> None:
    """[핵심] 파생물만으로는 성공한 재구성이 아니다(Core 의 SUCCEEDED 게이트와 같은 판단)."""
    engine = FakeNodeOdm(entries={"odm_orthophoto/odm_orthophoto.tif"})
    with pytest.raises(OdmError, match="원본 산출물"):
        plan_artifacts(_archive(tmp_path, engine), crs=_CRS, gsd_by_artifact=_GSD)


# ── mesh digest 가 텍스처를 덮는가(risk mesh-digest-ignores-textures) ────────


def _mesh_archive(tmp_path: Path, name: str, *, obj: bytes, mtl: bytes, texture: bytes,
                   glb: bytes | None = None) -> Path:
    path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("odm_report/shots.geojson", b"x")
        archive.writestr("odm_georeferencing/odm_georeferenced_model.laz", b"x")
        archive.writestr("odm_texturing/odm_textured_model_geo.obj", obj)
        archive.writestr("odm_texturing/odm_textured_model_geo.mtl", mtl)
        archive.writestr(
            "odm_texturing/odm_textured_model_geo_material0000_map_Kd.png", texture
        )
        if glb is not None:
            archive.writestr("odm_texturing/odm_textured_model_geo.glb", glb)
    return path


def _mesh_digest(tmp_path: Path, **kwargs: bytes) -> str:
    name = "-".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
    reports = plan_artifacts(_mesh_archive(tmp_path, name, **kwargs), crs=_CRS)
    return next(r for r in reports if r.artifact_id == "mesh").digest


def test_mesh_digest_changes_when_texture_changes(tmp_path: Path) -> None:
    """[핵심] .obj 는 그대로인데 텍스처만 바뀌어도 mesh digest 가 바뀐다."""
    common = dict(obj=b"same-obj", mtl=b"same-mtl")
    digest_v1 = _mesh_digest(tmp_path, texture=b"texture-v1", **common)
    digest_v2 = _mesh_digest(tmp_path, texture=b"texture-v2", **common)
    assert digest_v1 != digest_v2


def test_mesh_digest_changes_when_mtl_changes(tmp_path: Path) -> None:
    """[핵심] .mtl 만 바뀌어도 mesh digest 가 바뀐다."""
    common = dict(obj=b"same-obj", texture=b"same-texture")
    digest_v1 = _mesh_digest(tmp_path, mtl=b"mtl-v1", **common)
    digest_v2 = _mesh_digest(tmp_path, mtl=b"mtl-v2", **common)
    assert digest_v1 != digest_v2


def test_mesh_digest_ignores_unrelated_files_in_same_directory(tmp_path: Path) -> None:
    """[비공허 대조] .glb 는 obj/mtl 이 참조하는 텍스처가 아니라 mesh digest 밖이다."""
    common = dict(obj=b"same-obj", mtl=b"same-mtl", texture=b"same-texture")
    digest_v1 = _mesh_digest(tmp_path, glb=b"glb-v1", **common)
    digest_v2 = _mesh_digest(tmp_path, glb=b"glb-v2", **common)
    assert digest_v1 == digest_v2


# ── 실행 루프 ───────────────────────────────────────────────────────────────


def test_run_polls_until_completion() -> None:
    engine = FakeNodeOdm(
        states=[
            OdmTaskState(status=OdmTaskStatus.QUEUED),
            OdmTaskState(status=OdmTaskStatus.RUNNING),
            OdmTaskState(status=OdmTaskStatus.COMPLETED),
        ]
    )
    polls = 0

    def poll() -> None:
        nonlocal polls
        polls += 1

    uuid = run_to_completion(
        engine, _IMAGES, expected_version=_ENGINE_VERSION, options={}, poll=poll
    )
    assert uuid == "task-uuid-1"
    assert polls == 2
    assert [i.media_id for i in engine.submitted] == ["img-1.jpg"]


def test_run_forwards_masks_to_new_task() -> None:
    """[핵심] 마스크는 ``new_task`` 로 그대로 전달된다 — 별도 REST 호출이 아니다
    (odm_masking 모듈 docstring 1번, 실기동 확인)."""
    engine = FakeNodeOdm()
    masks = [MaskImage(filename="img-1_mask.png", png_bytes=b"\x89PNG-fake")]

    run_to_completion(
        engine, _IMAGES, expected_version=_ENGINE_VERSION, options={},
        poll=lambda: None, masks=masks,
    )

    assert engine.submitted_masks == masks


def test_run_without_masks_submits_none_by_default() -> None:
    """마스킹을 쓰지 않는 기존 호출부는 동작이 그대로다(회귀 없음)."""
    engine = FakeNodeOdm()

    run_to_completion(
        engine, _IMAGES, expected_version=_ENGINE_VERSION, options={}, poll=lambda: None
    )

    assert engine.submitted_masks == []


def test_run_refuses_before_submitting_when_engine_differs() -> None:
    """[핵심] 신원 대조가 제출 **앞**이다 — 틀린 엔진에 사진을 넘기지 않는다."""
    engine = FakeNodeOdm(engine_version="9.9.9")
    with pytest.raises(EngineIdentityMismatch):
        run_to_completion(
            engine, _IMAGES, expected_version=_ENGINE_VERSION, options={},
            poll=lambda: None,
        )
    assert engine.submitted == [], "거부됐는데 사진이 이미 넘어갔다"


def test_run_propagates_engine_failure_message() -> None:
    engine = FakeNodeOdm(
        states=[OdmTaskState(status=OdmTaskStatus.FAILED, error_message="메모리 부족")]
    )
    with pytest.raises(OdmError, match="메모리 부족"):
        run_to_completion(
            engine, _IMAGES, expected_version=_ENGINE_VERSION, options={},
            poll=lambda: None,
        )


def test_hung_engine_fails_instead_of_looping_forever() -> None:
    """[fail-closed] lease 가 없는 지금 구조에서 갇힌 워커는 작업을 영구 점유한다."""
    engine = FakeNodeOdm(states=[OdmTaskState(status=OdmTaskStatus.RUNNING)])
    with pytest.raises(OdmError, match="폴링"):
        run_to_completion(
            engine, _IMAGES, expected_version=_ENGINE_VERSION, options={},
            poll=lambda: None, max_polls=5,
        )


def test_artifact_report_has_no_place_for_the_lineage_anchor() -> None:
    """[핵심] 워커가 sourceDigest 를 실을 자리가 없다 — Core 가 원장에서 채운다."""
    fields = set(ArtifactReport.__dataclass_fields__)
    assert "source_digest" not in fields
    assert "job_id" not in fields


def test_asset_kinds_are_all_valid_contract_values() -> None:
    """매핑 표의 kind·authority 가 계약 enum 을 벗어나지 않는다."""
    for asset in ODM_ASSETS:
        assert isinstance(asset.kind, ProcessingArtifactKind)
        assert isinstance(asset.authority, LineageAuthority)


# ── 실물 아카이브 대조 (완주한 ODM 산출물) ──────────────────────────────────

_REAL_ENTRIES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "odm" / "pacifica_all_zip_entries.txt"
)


def _real_archive_entries() -> set[str]:
    """무수정 NodeODM 이 실제로 만든 all.zip 의 엔트리 목록(fixtures/odm/README.md)."""
    return {
        line.strip()
        for line in _REAL_ENTRIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_every_mapped_entry_exists_in_a_real_archive() -> None:
    """[핵심] 경로 매핑을 파일 이름 추측이 아니라 **실물 목록**과 대조한다.

    이 대조가 없어서 ``cameras.json``(카메라 내부 파라미터 — focal·왜곡계수,
    카메라 모델당 1개)을 카메라 포즈로 매핑한 채 초록불이었다. 실제 포즈는
    ``odm_report/shots.geojson`` 이고, 그 차이는 실물 아카이브를 열어야 보인다.
    """
    entries = _real_archive_entries()
    assert entries, "픽스처가 비어 있다 — 이 테스트가 공허하다"
    missing = [a.archive_entry for a in ODM_ASSETS if a.archive_entry not in entries]
    assert not missing, (
        f"매핑된 경로가 실물 아카이브에 없다: {missing} — "
        "ODM 이 그 이름으로 내놓지 않으면 그 산출물은 영영 등록되지 않는다"
    )


def test_camera_poses_map_to_shots_not_to_camera_intrinsics() -> None:
    """[회귀] cameras.json 은 카메라 *모델*의 내부 파라미터지 사진별 포즈가 아니다."""
    poses = next(a for a in ODM_ASSETS if a.kind is ProcessingArtifactKind.CAMERA_POSES)
    assert poses.archive_entry == "odm_report/shots.geojson"
    assert "cameras.json" not in {a.archive_entry for a in ODM_ASSETS}


def test_real_archive_yields_the_expected_lineage(tmp_path: Path) -> None:
    """실물 엔트리 목록으로 만든 아카이브가 계보 7건을 그대로 낸다.

    바이트는 없지만 **경로 집합은 실물 그대로**라, 이 테스트는 "엔진이 내놓는
    것들 중 우리가 무엇을 어떤 계보로 등록하는가"를 고정한다.
    """
    archive_path = tmp_path / "real-shape.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for entry in sorted(_real_archive_entries()):
            archive.writestr(entry, b"x")

    reports = plan_artifacts(
        archive_path,
        crs=_CRS,
        gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
    )
    assert [r.artifact_id for r in reports] == [
        "camera-poses", "point-cloud", "mesh", "orthophoto", "dsm", "dtm", "report",
    ]
    by_id = {r.artifact_id: r for r in reports}
    assert by_id["camera-poses"].crs is None
    assert by_id["report"].crs is None and by_id["report"].gsd is None
    assert by_id["point-cloud"].authority == "source"
    assert sum(r.authority == "source" for r in reports) == 2


# ── 산출물 바이트 (M1) ──────────────────────────────────────────────────────
#
# 여기까지가 검증한 것은 "계보가 정직한가"였다. 아래는 그 계보가 가리키는
# **바이트를 실제로 다시 꺼낼 수 있는가**를 본다.


def test_plan_artifacts_records_which_entries_back_each_artifact(tmp_path: Path) -> None:
    """등록할 산출물마다 그 바이트가 아카이브 어디에 있는지 남긴다.

    이게 없으면 워커가 digest 계산 뒤 같은 파일을 다시 찾을 방법이 없다 —
    지금까지 바이트를 버려 온 이유가 정확히 이 연결의 부재였다.
    """
    entries = {a.archive_entry for a in ODM_ASSETS}
    # 메시의 텍스처·재질을 실제로 담는다 — 이게 있어야 digest 가 결합 해시가 된다.
    entries |= {
        "odm_texturing/odm_textured_model_geo.mtl",
        "odm_texturing/odm_textured_model_geo_map_Kd.png",
    }
    reports = plan_artifacts(
        _archive(tmp_path, FakeNodeOdm(entries=entries)), crs=_CRS, gsd_by_artifact=_GSD
    )
    by_id = {report.artifact_id: report for report in reports}

    point_cloud = by_id[POINT_CLOUD_ID]
    assert point_cloud.archive_entry == "odm_georeferencing/odm_georeferenced_model.laz"
    assert point_cloud.is_single_file is True

    mesh = by_id["mesh"]
    assert mesh.archive_entry == "odm_texturing/odm_textured_model_geo.obj"
    # 텍스처·재질이 digest 에 함께 들어가는 산출물이라 파일 하나가 아니다 —
    # 객체 키 하나에 충실히 담을 수 없다는 뜻이고, 워커가 이 플래그로 판단한다.
    assert mesh.is_single_file is False


def test_single_file_artifact_bytes_hash_to_the_registered_digest(
    tmp_path: Path,
) -> None:
    """[핵심] 저장할 바이트와 등록할 digest 가 같은 것이다.

    이 등식이 깨지면 계보 검증이 의미를 잃는다 — "digest 는 A 인데 저장된 건
    B"인 상태가 조용히 만들어진다. 저장 시점에 포맷을 변환하지 않기로 한
    결정(ADR-KSI-016 관련, COG 변환은 파생 산출물의 몫)이 기계로 고정되는
    지점이기도 하다.
    """
    archive_path = _archive(tmp_path)
    reports = plan_artifacts(archive_path, crs=_CRS, gsd_by_artifact=_GSD)

    for report in reports:
        if not report.is_single_file:
            continue
        digest = hashlib.sha256()
        for chunk in iter_archive_entry_bytes(archive_path, report.archive_entry):
            digest.update(chunk)
        assert f"sha256:{digest.hexdigest()}" == report.digest, report.artifact_id


def test_iter_archive_entry_bytes_streams_in_chunks(tmp_path: Path) -> None:
    """청크로 읽는다 — point cloud 는 GB 단위라 통째로 메모리에 올리지 않는다."""
    archive_path = tmp_path / "big.zip"
    payload = b"x" * (3 * 1024 * 1024)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("big.bin", payload)

    chunks = list(iter_archive_entry_bytes(archive_path, "big.bin", chunk_size=1024 * 1024))

    assert len(chunks) > 1, "한 덩어리로 읽으면 스트리밍이 아니다"
    assert b"".join(chunks) == payload


def test_iter_archive_entry_bytes_refuses_a_missing_entry(tmp_path: Path) -> None:
    """[음성] 없는 엔트리를 빈 바이트로 돌려주지 않는다."""
    with pytest.raises(OdmError):
        list(iter_archive_entry_bytes(_archive(tmp_path), "does/not/exist.tif"))
