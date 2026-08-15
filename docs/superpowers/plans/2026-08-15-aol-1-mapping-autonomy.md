# AOL-1 매핑 자율 — 소프트웨어 종단 구현 계획

> **실행 완료 (2026-08-15).** 13개 Task 전부 구현·검증됐다. 커밋 10건
> (`5a9f46d`…`5240dfd`), 전체 스위트 `3299 passed / 23 skipped / 3 xfailed`,
> `ruff check` · `mypy`(322 files) · 대시보드 `vitest` 227 · `eslint` · `tsc` ·
> `next build` 전부 통과 — 전부 직접 실행 확인.
>
> **완료 등급은 `Backend Ready` + 일부 `Product Ready`(대시보드)이고 `HIL Proven`
> 이 아니다**(ADR-KSI-018 완료 판정 규율). 실기 비행 0회이며 종단 시험의 커버리지
> 보고·재구성 워커는 계약대로 행동하는 대역이다.
>
> **계획 대비 달라진 것 두 가지** — 실측이 계획을 정정했다:
> 1. `ruff format --check` 는 이 저장소의 게이트가 **아니다**(CI 가 안 돌리고 170개
>    파일이 이미 통과 못 한다). Global Constraints 를 그에 맞게 고쳤다.
> 2. Task 11(G4)의 전제가 좁아졌다 — 브라우저 없는 업로더는 이미 있었고 실제 구멍은
>    트리거였다. ADR-KSI-019 §4 의 G4 서술도 함께 정정했다.
>
> 아래 본문은 실행 당시의 계획 원문이다(체크박스는 갱신하지 않았다 — 계획과 실제
> 결과를 섞으면 무엇이 계획이었는지 알 수 없게 된다). 실제 결과는 ADR-KSI-019 §4·§5.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현장 경계에서 시작해 매핑 임무 발급 → 실행 상태 추적 → 촬영 자동 수집 → 재구성 성공 → 현장 상태 자동 전진까지, 사람이 화면 버튼을 눌러 상태를 옮기지 않아도 서버가 스스로 판단하는 AOL-1 루프를 소프트웨어로 완주한다.

**Architecture:** 새 원장을 최소로 만든다. "이 현장에 공간모델이 있는가·낡았는가"는 **새 저장소가 아니라 처리 작업 원장 위의 순수 파생 판정**이다(`ProcessingJobRecord` 가 곧 재구성 epoch — ADR-KSI-016 D3). 반면 "이 임무가 실제로 날았는가"는 파생될 수 없는 새 사실이라 `MissionExecutionStore` 라는 원장을 하나만 추가한다. 자동 전이는 저장소 안이 아니라 **라우터 계층에서 오케스트레이션**한다 — 저장소 간 잠금 순서를 만들지 않고, 전진 실패가 원래 요청(재구성 성공 보고·커버리지 접수)을 절대 깨뜨리지 않게 하기 위해서다.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, Pydantic v2, `DurableJournal`(append-only JSONL) + 인메모리 projection, pytest, Next.js 16 / React 19 / TypeScript / vitest (대시보드)

**Spec:** `docs/architecture/ADR-KSI-019-autonomous-observation-loop.md` (§3 D1~D5, §4 G1·G2·G4, §5 순서 1·2·3·5)

---

## 전체 완성 로드맵 (이 계획의 위치)

ADR-KSI-019 §5 의 8단계를 실행 가능한 계획 단위로 쪼갠 것이다. 이 문서는 **계획 1**이다.

| 계획 | 범위 | 상태 | 관문 |
|---|---|---|---|
| **계획 1 (이 문서)** | G1 공간모델 생애주기 + G2 임무 실행 생애주기 + G4 ingest 트리거 + AOL-1 소프트웨어 종단 | 실행 가능 | 없음 — 실기 하드웨어 불필요 |
| 계획 2 | G5 재관측 계획 심화 + AOL-2 소프트웨어 종단 | 계획 1 완료 후 | 계획 1 의 `SpatialModelStatus`·`MissionExecutionStatus` 인터페이스 확정 |
| 계획 3 | G3 임무 → 기체 자동 배포 | **막힘** | DJI M4D 의 Pilot Cloud 지원 여부 실기 확인(ADR-KSI-004). 확인 전까지 "운영자 수동 이관"이 공식 경로 |
| 계획 4 | G6 지형/공간모델 인지 경로계획(AOL-3) | **보류** | ADR-KSI-019 D2 가 순서를 고정 — AOL-1 종단·실제 현장 검증 이후에만 착수 |

계획 3·4 를 지금 쓰지 않는 이유는 분량이 아니라 근거다. 계획 3 은 아직 답을 모르는 장비 동작 위에 코드를 설계하게 되고, 계획 4 는 ADR 이 순서를 명시적으로 금지했다.

---

## Global Constraints

이 절의 값은 저장소에서 그대로 옮긴 것이다. 모든 Task 의 요구사항에 암묵적으로 포함된다.

- **언어 규약**: 코드 식별자는 영어, docstring·주석은 한국어. 기존 파일의 밀도와 어조를 그대로 따른다.
- **테스트 실행**: `ulimit -n 8192` 를 먼저 올린 뒤 `uv run pytest`. FD 기본값 1024 로는 전체 스위트가 인프라 사유로 깨진다.
- **대시보드**: `cd apps/dashboard && npm run test` · `npm run lint` · `npm run build`.
- **정적 검사**: `uv run ruff check .` · `uv run mypy` (CI scope). **`ruff format --check` 는 게이트가 아니다** — CI(`.github/workflows/ci.yml`)가 돌리지 않고, 저장소 170개 파일이 이미 그 검사를 통과하지 못한다(2026-08-15 실측). 새로 만드는 파일에는 `uv run ruff format <새 파일>` 을 적용하되, **기존 파일을 통째로 재포맷하지 않는다** — 무관한 대량 diff 가 리뷰를 못 하게 만든다.
- **INV-052 보존**: 현장 상태 전이는 `ksi_domain.enums.assert_site_transition` 을 **통해서만** 한다. 전이표를 새로 만들거나 우회하지 않는다.
- **INV-051 보존**: `authority=source` 산출물 없는 `SUCCEEDED` 는 없다. 이 계획은 그 게이트를 완화하지 않고 **읽기만** 한다.
- **INV-010 보존**: 완료 판정의 권위는 CoverageReport 하나다. 이 계획이 추가하는 `MissionExecutionStatus` 는 완료 판정의 **권위가 아니라 투영**이며, 커버리지 보고 접수를 막는 조건으로 절대 쓰지 않는다.
- **ADR-KSI-019 D3 (반순환 불변식)**: 최초 매핑 임무는 그 현장의 공간모델 없이 생성 가능해야 한다. 경로 생성기·계약 발급 경로에 공간모델을 **필수 입력으로** 추가하는 변경은 금지다. Task 1 이 이 규칙의 회귀 게이트를 만든다.
- **새 `/v1/*` 경로**: `contracts/api/openapi-core.yaml` 에 반드시 문서화하고 `security` 를 선언한다. 누락하면 `tests/contract/test_api_contract_sync.py` 가 깨진다.
- **자율운영 승인 경계**: 자동 전이는 `ksi_domain.enums.requires_autonomy_approval` 이 참인 간선(자율 개시·정식 순찰 승인·SUSPENDED 진출입)을 **절대** 밟지 않는다. 그 간선은 사람의 `SITES_AUTONOMY_APPROVE` 전용이다.
- **`references/repos/` 금지**: runtime import 금지, 수정 금지.
- **커밋**: 각 Task 끝에서 커밋한다. 커밋 직전에 그 Task 의 테스트를 실제로 돌려 통과를 확인한다.

---

## File Structure

**신규 생성**

| 파일 | 책임 |
|---|---|
| `services/core/src/ksi_core/spatial_model.py` | 공간모델 유무·최신도 **순수 판정** + 처리작업/임무실행 신호로 현장 상태를 전진시키는 오케스트레이터 + `GET /v1/sites/{site_id}/spatial-model` |
| `services/core/src/ksi_core/mission_execution.py` | 임무 실행 생애주기 원장(`MissionExecutionStore`) + 실행 상태 API |
| `tools/ingest_watch.py` | 디렉터리 감시 → `upload_source_bundle` 재사용 → 임무별 1회 ingest 트리거 |
| `tests/contract/test_spatial_model.py` | 순수 판정·전진 규칙·API 계약 |
| `tests/contract/test_mission_execution.py` | 실행 상태 전이표·원장·API·훅 |
| `tests/contract/test_ingest_watch.py` | 감시 러너의 트리거·멱등·실패 격리 |
| `tests/contract/test_anti_circularity_gate.py` | ADR-KSI-019 D3 회귀 게이트 |
| `tests/e2e/test_aol1_mapping_autonomy.py` | AOL-1 소프트웨어 종단 1회 |

**수정**

| 파일 | 변경 |
|---|---|
| `packages/domain/src/ksi_domain/enums.py` | `MissionExecutionStatus` + 전이표 + `assert_mission_execution_transition` |
| `services/core/src/ksi_core/sites.py` | `SiteRecord.model_max_age_days` + 선언 경로 |
| `services/core/src/ksi_core/processing_jobs.py` | 발급·SUCCEEDED 라우터에 현장 전진 훅 |
| `services/core/src/ksi_core/coverage_reports.py` | 접수 라우터에 임무 실행 상태 훅 |
| `services/core/src/ksi_core/edge_dispatch.py` | dispatch·activation 라우터에 임무 실행 상태 훅 |
| `services/core/src/ksi_core/app.py` | `create_app` 배선 |
| `services/core/src/ksi_core/app_assembly.py` | 조립 |
| `services/core/src/ksi_core/metrics.py` | 자동 전진 결과 카운터 |
| `contracts/api/openapi-core.yaml` | 신설 경로 4종 |
| `apps/dashboard/src/lib/core-api/types.ts` | 신규 enum·응답 타입 미러 |
| `apps/dashboard/src/lib/core-api/sites.ts` · `missions.ts` | 신규 조회 함수 |
| `apps/dashboard/src/app/sites/[siteId]/page.tsx` | 공간모델 상태 표시 |
| `apps/dashboard/src/components/missions/MissionLifecycle.tsx` | 역추정 대신 서버 실행 상태 사용 |

---

## Task 1: 반순환 불변식 회귀 게이트 (ADR-KSI-019 D3)

이 Task 를 **먼저** 하는 이유: 이후 모든 Task 가 "공간모델" 이라는 개념을 서버에 추가한다. 그 과정에서 누군가 임무 발급 경로에 공간모델 조회를 끼워 넣으면 D3 가 조용히 깨진다. 그 순간을 잡는 게이트를 먼저 박는다.

**Files:**
- Create: `tests/contract/test_anti_circularity_gate.py`

**Interfaces:**
- Consumes: `ksi_core.app_assembly.assemble_app`, `ksi_core.mission_plans` 의 `POST /v1/missions/plans`
- Produces: 없음(테스트 전용). 이후 Task 들이 이 파일을 깨지 않아야 한다.

- [ ] **Step 1: 기존 테스트에서 조립 fixture 관용구를 확인한다**

Run:
```bash
cd /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform
sed -n '1,120p' tests/contract/test_mission_plans.py
```
기대: `assemble_app` 또는 `create_app` 으로 앱을 만들고 `TestClient` 로 두드리는 fixture 가 보인다. 이 파일의 fixture 관용구(토큰·서명키·임시 data_dir)를 **그대로 복사해서** 다음 스텝에 쓴다. 새 관용구를 만들지 않는다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/contract/test_anti_circularity_gate.py`:

```python
"""ADR-KSI-019 D3 회귀 게이트 — 최초 매핑 임무는 공간모델 없이 생성 가능해야 한다.

## 왜 이 게이트가 별도 파일인가

"3D/Point Cloud 기반 자율비행"을 목표로 적으면 목표 문장이 순환한다 — 공간모델이
아직 없는 최초 현장에서 3D 를 만들려면 3D 가 먼저 필요해진다(ADR-KSI-019 §1).
2026-08-15 실사 결과 **현재 코드에는 그 순환이 없다**. 경로 생성기(``coverage.py``)
· 계약 발급(``mission_plans.py``) 어디에도 DSM·Point Cloud 입력이 없다.

그래서 이 파일이 지키는 것은 신규 요구가 아니라 **현재 성질의 회귀 금지**다.
AOL-1~3 구현 중 누군가 "지형을 알면 경로가 더 좋아진다"는 이유로 계획 경로에
공간모델 조회를 필수로 끼워 넣으면, 그 순간 최초 현장이 영원히 매핑 불가가 된다.
AOL-3 의 지형 인지 기능은 반드시 **선택적 강화**로 들어가야 하고(D3), 없으면
AOL-1 경로가 그대로 나와야 한다.

## 무엇을 검사하는가

① ``processing_job_store`` 가 조립되지 않은(= 이 현장에 어떤 재구성 epoch 도
있을 수 없는) 앱에서 ``UNMAPPED`` 현장에 ``BASELINE_MAPPING`` 짝 발급이 201 로
성공한다. ② 발급 응답이 실제로 웨이포인트와 KMZ digest 를 담는다 — 201 만 보고
넘어가면 "빈 경로를 성공이라 부르는" 회귀를 놓친다.
"""
```

그리고 본문:

```python
from __future__ import annotations

# (fixture import 는 Step 1 에서 확인한 test_mission_plans.py 관용구를 그대로 따른다)


def test_baseline_mapping_pair_issues_without_any_spatial_model(
    client_without_processing_jobs, mapping_plan_request
) -> None:
    """[핵심] 재구성 원장이 아예 없는 조립에서도 최초 매핑 임무가 발급된다."""
    response = client_without_processing_jobs.post(
        "/v1/missions/plans", json=mapping_plan_request
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["waypointCount"] > 0, "경로가 비어 있으면 발급 성공이 거짓말이다"
    assert body["kmzSha256"], "KMZ 가 없으면 DJI 가 읽을 비행파일이 없다"


def test_mission_planning_package_does_not_import_spatial_model_modules() -> None:
    """경로 계획 패키지가 공간모델·처리작업 모듈에 의존하기 시작하면 실패한다.

    런타임 호출을 못 잡는 대신 **의존 방향**을 잡는다 — 계획기가 재구성 산출물
    모듈을 import 하는 순간이 D3 가 깨지기 시작하는 지점이다.
    """
    import pathlib

    planning_src = pathlib.Path("packages/mission-planning/src")
    forbidden = ("ksi_core.processing_jobs", "ksi_core.spatial_model", "processing_artifact")

    offenders: list[str] = []
    for path in planning_src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path}: {needle}")

    assert not offenders, (
        "경로 계획 패키지가 공간모델/재구성 모듈에 의존한다 — ADR-KSI-019 D3 위반: "
        f"{offenders}"
    )
```

`client_without_processing_jobs` fixture 는 `assemble_app` 을 `evidence_storage=None` 으로 부른다 — 그러면 `processing_job_store` 가 `None` 이 되어 재구성 원장 자체가 존재하지 않는 조립이 된다(`app_assembly.py` 참조). `mapping_plan_request` 는 `test_mission_plans.py` 가 이미 쓰는 요청 본문을 재사용한다.

- [ ] **Step 3: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_anti_circularity_gate.py -v`
기대: fixture 미정의로 ERROR. (아직 fixture 를 안 붙였다면 그게 정상 실패다.)

- [ ] **Step 4: fixture 를 붙여 통과시킨다**

`test_mission_plans.py` 에서 확인한 fixture 를 이 파일로 복사해 넣는다. 공유 conftest 로 빼지 않는다 — 이 게이트는 다른 테스트의 fixture 변경에 영향받지 않고 독립적으로 서 있어야 한다.

- [ ] **Step 5: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_anti_circularity_gate.py -v`
기대: 2 passed

- [ ] **Step 6: 커밋**

```bash
git add tests/contract/test_anti_circularity_gate.py
git commit -m "test(core): add ADR-KSI-019 D3 anti-circularity regression gate

최초 매핑 임무가 공간모델 없이 발급되는 현재 성질을 회귀 게이트로 고정한다.
AOL-1~3 구현 중 계획 경로에 공간모델을 필수 입력으로 끼워 넣는 변경을 잡는다."
```

---

## Task 2: 공간모델 유무·최신도 순수 판정

**Files:**
- Create: `services/core/src/ksi_core/spatial_model.py`
- Test: `tests/contract/test_spatial_model.py`

**Interfaces:**
- Consumes: `ksi_core.processing_jobs.ProcessingJobRecord`, `ksi_event_contracts.processing_job.ProcessingJobStatus`, `ksi_event_contracts.processing_artifact.LineageAuthority`
- Produces:
  - `class SpatialModelState(StrEnum)` — `ABSENT` · `FRESH` · `STALE` · `AGE_POLICY_UNDECLARED`
  - `@dataclass(frozen=True, slots=True) class SpatialModelStatus` — `state: SpatialModelState`, `epoch_job_id: str | None`, `registered_at: datetime | None`, `age_days: float | None`, `max_age_days: int | None`, `source_artifact_count: int`, `succeeded_epoch_count: int`
  - `def evaluate_spatial_model(jobs: Sequence[ProcessingJobRecord], *, now: datetime, max_age_days: int | None) -> SpatialModelStatus`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_spatial_model.py`:

```python
"""현장 공간모델 판정 — 유무·나이·정책 미선언 (ADR-KSI-019 G1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ksi_core.spatial_model import (
    SpatialModelState,
    evaluate_spatial_model,
)

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_no_jobs_means_absent() -> None:
    status = evaluate_spatial_model([], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.ABSENT
    assert status.epoch_job_id is None
    assert status.succeeded_epoch_count == 0


def test_succeeded_job_without_source_artifact_is_not_a_model(
    job_succeeded_derived_only,
) -> None:
    """파생 산출물만 있는 성공은 '모델이 있다'로 세지 않는다(ADR-KSI-003)."""
    status = evaluate_spatial_model(
        [job_succeeded_derived_only], now=_NOW, max_age_days=30
    )

    assert status.state is SpatialModelState.ABSENT
    assert status.source_artifact_count == 0


def test_failed_and_running_jobs_are_not_models(job_running, job_failed) -> None:
    status = evaluate_spatial_model([job_running, job_failed], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.ABSENT


def test_recent_source_backed_success_is_fresh(job_succeeded_with_source) -> None:
    status = evaluate_spatial_model(
        [job_succeeded_with_source], now=_NOW, max_age_days=30
    )

    assert status.state is SpatialModelState.FRESH
    assert status.epoch_job_id == job_succeeded_with_source.job_id
    assert status.age_days == pytest.approx(1.0)


def test_old_source_backed_success_is_stale(job_factory) -> None:
    old = job_factory(updated_at=_NOW - timedelta(days=45), with_source=True)

    status = evaluate_spatial_model([old], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.STALE
    assert status.age_days == pytest.approx(45.0)


def test_undeclared_policy_is_not_reported_as_fresh(job_succeeded_with_source) -> None:
    """[핵심] 나이 기준을 선언하지 않은 현장을 FRESH 로 뭉개지 않는다.

    '판정하지 않았다'와 '판정했더니 최신이다'는 다른 사실이다. 전자를 후자로
    표시하면 화면이 근거 없는 안심을 준다(INV-040 정신).
    """
    status = evaluate_spatial_model(
        [job_succeeded_with_source], now=_NOW, max_age_days=None
    )

    assert status.state is SpatialModelState.AGE_POLICY_UNDECLARED
    assert status.epoch_job_id == job_succeeded_with_source.job_id
    assert status.max_age_days is None


def test_newest_epoch_wins(job_factory) -> None:
    old = job_factory(job_id="j-old", updated_at=_NOW - timedelta(days=40), with_source=True)
    new = job_factory(job_id="j-new", updated_at=_NOW - timedelta(days=2), with_source=True)

    status = evaluate_spatial_model([old, new], now=_NOW, max_age_days=30)

    assert status.state is SpatialModelState.FRESH
    assert status.epoch_job_id == "j-new"
    assert status.succeeded_epoch_count == 2


def test_future_timestamp_does_not_produce_negative_age(job_factory) -> None:
    """시계 어긋남으로 미래 시각이 들어와도 음수 나이를 내지 않는다(0 으로 절단)."""
    ahead = job_factory(updated_at=_NOW + timedelta(hours=3), with_source=True)

    status = evaluate_spatial_model([ahead], now=_NOW, max_age_days=30)

    assert status.age_days == 0.0
    assert status.state is SpatialModelState.FRESH


def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        evaluate_spatial_model([], now=datetime(2026, 8, 15, 12, 0), max_age_days=30)  # noqa: DTZ001
```

fixture `job_factory` 는 같은 파일 안에 둔다:

```python
@pytest.fixture
def job_factory():
    """``ProcessingJobRecord`` 최소 인스턴스 생성기.

    실제 저장소를 거치지 않고 dataclass 를 직접 만든다 — 이 Task 의 검증 대상은
    저장소 동작이 아니라 **판정 함수**다(발급 게이트는 test_processing_jobs.py 소관).
    """
    from ksi_event_contracts.processing_artifact import (
        ArtifactLineage,
        LineageAuthority,
        ProcessingArtifact,
        ProcessingArtifactKind,
    )
    from ksi_event_contracts.processing_job import ProcessingJobStatus
    from ksi_core.processing_jobs import ProcessingJobRecord

    def _make(
        *,
        job_id: str = "mission-a-pj1",
        status: ProcessingJobStatus = ProcessingJobStatus.SUCCEEDED,
        updated_at: datetime = _NOW,
        with_source: bool = False,
        with_derived: bool = False,
    ) -> ProcessingJobRecord:
        artifacts = []
        if with_source:
            artifacts.append(
                ProcessingArtifact(
                    artifactId=f"{job_id}-pc",
                    jobId=job_id,
                    kind=ProcessingArtifactKind.POINT_CLOUD,
                    lineage=ArtifactLineage(
                        authority=LineageAuthority.SOURCE, sourceDigest="sha256:" + "a" * 64
                    ),
                    digest="sha256:" + "b" * 64,
                    format="laz",
                    crs="EPSG:5186",
                )
            )
        if with_derived:
            artifacts.append(
                ProcessingArtifact(
                    artifactId=f"{job_id}-mesh",
                    jobId=job_id,
                    kind=ProcessingArtifactKind.MESH,
                    lineage=ArtifactLineage(
                        authority=LineageAuthority.DERIVED,
                        sourceDigest="sha256:" + "a" * 64,
                        derivedFrom=[f"{job_id}-pc"],
                    ),
                    digest="sha256:" + "c" * 64,
                    format="obj",
                    crs="EPSG:5186",
                )
            )
        return _minimal_record(
            job_id=job_id, status=status, updated_at=updated_at, artifacts=tuple(artifacts)
        )

    return _make
```

`_minimal_record` 는 `tests/contract/test_processing_jobs.py` 가 이미 쓰는 레코드 조립 관용구를 확인해 그대로 맞춘다(`spec`·`data_residency`·`input` 필수 필드). 나머지 fixture(`job_running`·`job_failed`·`job_succeeded_with_source`·`job_succeeded_derived_only`)는 `job_factory` 를 감싸는 한 줄짜리다.

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py -v`
기대: `ModuleNotFoundError: No module named 'ksi_core.spatial_model'`

- [ ] **Step 3: 판정 모듈을 만든다**

`services/core/src/ksi_core/spatial_model.py`:

```python
"""현장의 공간모델 유무·최신도 판정과 그에 따른 현장 상태 자동 전진 (ADR-KSI-019 G1).

## 두 번째 원장을 만들지 않는다

"이 현장에 공간모델이 있는가"는 새 저장소가 아니라 **처리 작업 원장 위의 순수
파생 판정**이다. ``ProcessingJobRecord`` 가 곧 재구성 epoch 이고(ADR-KSI-016 D3,
``processing_jobs.list_for_site`` docstring), 그 옆에 ``SpatialModel`` 레코드를
따로 두면 job 과 1:1 그림자 원장이 생겨 "둘 중 뭐가 진실이냐"가 만들어진다.

그래서 :func:`evaluate_spatial_model` 은 순수 함수다 — 입력은 그 현장의 처리 작업
목록과 시각과 정책값뿐이고 아무것도 쓰지 않는다.

## 무엇을 "공간모델이 있다"로 세는가

``SUCCEEDED`` 이면서 ``lineage.authority == source`` 산출물을 최소 1건 가진 작업만
센다. 이건 INV-051 의 :func:`~ksi_core.processing_jobs.assert_succeeded_is_backed`
게이트가 전이 시점에 이미 강제하는 조건과 같은 조건을 **읽는 쪽에서 다시 확인**하는
것이다 — 게이트가 나중에 완화되거나 손으로 고친 원장이 재생돼도 조회 판정은
독립적으로 성립해야 한다.

파생 산출물(Mesh·정사영상·DSM)만 있는 작업은 세지 않는다: 원본 없이 파생만 있는
상태를 "모델이 있다"로 읽으면 ADR-KSI-003 의 원본/파생 권위 구분이 조회 표면에서
무너진다.

## 나이 기준을 서버가 지어내지 않는다

MASTER_PRD §6.3 은 ``MODEL_STALE`` 이라는 **상태만** 정의하고 며칠이면 낡은
것인지는 정하지 않는다. 서버가 임의의 기본값(예: 30일)을 박으면 근거 없는 숫자가
현장의 자율운영 가능 여부를 가르게 된다.

그래서 나이 기준은 **현장이 선언한다**(``SiteRecord.model_max_age_days``).
선언하지 않은 현장은 ``FRESH`` 로 뭉개지 않고 ``AGE_POLICY_UNDECLARED`` 로 낸다 —
"판정하지 않았다"와 "판정했더니 최신이다"는 다른 사실이고, 전자를 후자로 표시하면
화면이 근거 없는 안심을 준다(INV-040 정신).

## ``registered_at`` 은 "모델이 등록된 시각"이지 "세상을 관측한 시각"이 아니다

나이의 기준점은 그 작업이 ``SUCCEEDED`` 로 전이한 시각(``updated_at``)이다.
정확히는 촬영 시각이 더 옳지만, 촬영 시각을 임무 원장에서 끌어오려면 임무 실행
생애주기(G2)가 먼저 있어야 한다. 필드 이름이 그 한계를 말하게 두고, G2 이후에
촬영 시각 기준으로 좁힐 여지를 남긴다 — 이름을 ``capturedAt`` 으로 붙여놓고
등록 시각을 담는 것이 더 나쁘다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_event_contracts.processing_artifact import LineageAuthority
from ksi_event_contracts.processing_job import ProcessingJobStatus

if TYPE_CHECKING:
    from ksi_core.processing_jobs import ProcessingJobRecord

_SECONDS_PER_DAY = 86400.0


class SpatialModelState(StrEnum):
    """현장의 공간모델 판정 결과 4종."""

    #: 원본 산출물을 가진 성공한 재구성이 하나도 없다.
    ABSENT = "ABSENT"
    #: 최신 epoch 이 현장이 선언한 나이 기준 안이다.
    FRESH = "FRESH"
    #: 최신 epoch 이 현장이 선언한 나이 기준을 넘었다.
    STALE = "STALE"
    #: epoch 은 있는데 현장이 나이 기준을 선언하지 않아 노후를 **판정하지 않았다**.
    AGE_POLICY_UNDECLARED = "AGE_POLICY_UNDECLARED"


@dataclass(frozen=True, slots=True)
class SpatialModelStatus:
    """판정 1건 — 결론과 그 결론이 나온 근거를 함께 들고 다닌다."""

    state: SpatialModelState
    #: 판정 근거가 된 최신 epoch 의 작업 id. ``ABSENT`` 면 ``None``.
    epoch_job_id: str | None
    #: 그 epoch 이 ``SUCCEEDED`` 로 전이한 시각(모듈 docstring 참조).
    registered_at: datetime | None
    #: ``now - registered_at`` (일). 음수는 0 으로 절단한다.
    age_days: float | None
    #: 현장이 선언한 나이 기준. 미선언이면 ``None``.
    max_age_days: int | None
    #: 최신 epoch 의 ``authority=source`` 산출물 수.
    source_artifact_count: int
    #: 이 현장의 원본 뒷받침된 성공 epoch 총수(이력 깊이).
    succeeded_epoch_count: int


def has_source_artifact(record: ProcessingJobRecord) -> bool:
    """이 작업이 원본(SSOT) 산출물을 가졌는가 — 파생만으로는 거짓."""
    return any(
        artifact.lineage.authority is LineageAuthority.SOURCE for artifact in record.artifacts
    )


def is_spatial_model_epoch(record: ProcessingJobRecord) -> bool:
    """이 작업을 "공간모델 1세대"로 셀 수 있는가."""
    return record.status is ProcessingJobStatus.SUCCEEDED and has_source_artifact(record)


def evaluate_spatial_model(
    jobs: Sequence[ProcessingJobRecord],
    *,
    now: datetime,
    max_age_days: int | None,
) -> SpatialModelStatus:
    """이 현장의 공간모델 상태를 판정한다 — 순수 함수, 아무것도 쓰지 않는다.

    Args:
        jobs: 이 현장의 처리 작업 전량(정렬 무관 — 이 함수가 스스로 최신을 고른다).
        now: 판정 시각(tz-aware 필수).
        max_age_days: 현장이 선언한 노후 기준. ``None`` 이면 노후를 판정하지 않는다.

    Raises:
        ValueError: ``now`` 가 naive 일 때.
    """
    if now.tzinfo is None:
        raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")

    epochs = [record for record in jobs if is_spatial_model_epoch(record)]
    if not epochs:
        return SpatialModelStatus(
            state=SpatialModelState.ABSENT,
            epoch_job_id=None,
            registered_at=None,
            age_days=None,
            max_age_days=max_age_days,
            source_artifact_count=0,
            succeeded_epoch_count=0,
        )

    # 같은 시각이면 job_id 로 결정적으로 고른다 — 재생마다 다른 epoch 를 고르면
    # 같은 원장에서 다른 판정이 나온다.
    newest = max(epochs, key=lambda record: (record.updated_at, record.job_id))
    age_days = max(0.0, (now - newest.updated_at).total_seconds() / _SECONDS_PER_DAY)

    if max_age_days is None:
        state = SpatialModelState.AGE_POLICY_UNDECLARED
    elif age_days > max_age_days:
        state = SpatialModelState.STALE
    else:
        state = SpatialModelState.FRESH

    return SpatialModelStatus(
        state=state,
        epoch_job_id=newest.job_id,
        registered_at=newest.updated_at,
        age_days=age_days,
        max_age_days=max_age_days,
        source_artifact_count=sum(
            1
            for artifact in newest.artifacts
            if artifact.lineage.authority is LineageAuthority.SOURCE
        ),
        succeeded_epoch_count=len(epochs),
    )


__all__ = [
    "SpatialModelState",
    "SpatialModelStatus",
    "evaluate_spatial_model",
    "has_source_artifact",
    "is_spatial_model_epoch",
]
```

- [ ] **Step 4: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py -v`
기대: 9 passed

- [ ] **Step 5: 정적 검사**

Run: `uv run ruff check services/core/src/ksi_core/spatial_model.py tests/contract/test_spatial_model.py`
기대: 통과. 새로 만든 두 파일에만 `uv run ruff format <파일>` 을 적용한다(기존 파일은 건드리지 않는다).

- [ ] **Step 6: 커밋**

```bash
git add services/core/src/ksi_core/spatial_model.py tests/contract/test_spatial_model.py
git commit -m "feat(core): judge site spatial-model presence and staleness as a pure derivation

처리 작업 원장 위의 순수 판정으로 공간모델 유무·나이를 낸다. 두 번째 원장을
만들지 않는다(ADR-KSI-016 D3). 나이 기준 미선언은 FRESH 로 뭉개지 않고
AGE_POLICY_UNDECLARED 로 정직하게 낸다."
```

---

## Task 3: 현장의 노후 기준 선언 (`model_max_age_days`)

**Files:**
- Modify: `services/core/src/ksi_core/sites.py`
- Modify: `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_site_transitions.py` (저장소 레벨), `tests/contract/test_sites_api.py` (HTTP 레벨)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `SiteRecord.model_max_age_days: int | None = None`
  - `SiteVerdict.MODEL_AGE_POLICY_SET`
  - `SiteStore.set_model_age_policy(site_id, *, max_age_days: int | None, actor: str, now: datetime) -> SiteResult`
  - `PUT /v1/sites/{site_id}/model-age-policy` (권한 `SITES_WRITE`)
  - `SiteView.model_max_age_days` 노출

- [ ] **Step 1: 기존 현장 저장소 테스트의 fixture 관용구를 확인한다**

Run: `sed -n '1,80p' tests/contract/test_site_transitions.py`
기대: `SiteStore` 를 임시 journal 위에 여는 fixture 와 `SiteFrame` 상수가 보인다. 아래 테스트의 `site_store`·`_FRAME`·`_NOW`·`_open_store` 를 그 파일의 실제 이름에 맞춘다.

**주의**: `SiteStore.register` 의 시그니처는 `register(site_id, name, site_frame, *, aoi=None, data_residency=None, actor, now)` 다 — `actor` 가 키워드 필수다. 아래 스니펫은 그 형태를 지킨다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/contract/test_site_transitions.py` 끝에 추가:

```python
def test_model_age_policy_defaults_to_undeclared(site_store) -> None:
    """[핵심] 이 필드 도입 이전 journal 로 재생된 현장은 미선언이다.

    ``data_residency`` 와 같은 이유 — 구버전 레코드에 없던 필드의 기본값을 임의의
    숫자로 두면 기존 현장 전체가 조용히 어떤 노후 정책을 갖게 된다.
    """
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)

    assert site_store.get("site-a").model_max_age_days is None


def test_model_age_policy_can_be_declared_and_replaced(site_store) -> None:
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)

    first = site_store.set_model_age_policy(
        "site-a", max_age_days=30, actor="op-1", now=_NOW
    )
    assert first.verdict is SiteVerdict.MODEL_AGE_POLICY_SET
    assert site_store.get("site-a").model_max_age_days == 30

    second = site_store.set_model_age_policy(
        "site-a", max_age_days=7, actor="op-1", now=_NOW
    )
    assert second.verdict is SiteVerdict.MODEL_AGE_POLICY_SET
    assert site_store.get("site-a").model_max_age_days == 7


def test_model_age_policy_can_be_withdrawn(site_store) -> None:
    """선언을 되돌리는 경로가 있어야 한다 — 되돌릴 수 없는 정책은 정책이 아니다."""
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op-1", now=_NOW)

    site_store.set_model_age_policy("site-a", max_age_days=None, actor="op-1", now=_NOW)

    assert site_store.get("site-a").model_max_age_days is None


def test_non_positive_age_policy_is_refused(site_store) -> None:
    """0 일·음수는 "매 순간 낡음"이라 정책이 아니라 사고다."""
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)

    result = site_store.set_model_age_policy(
        "site-a", max_age_days=0, actor="op-1", now=_NOW
    )

    assert result.verdict is SiteVerdict.INVALID_SITE


def test_model_age_policy_survives_replay(tmp_path) -> None:
    """journal 재생 후에도 선언이 남는다."""
    store = _open_store(tmp_path)
    store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)
    store.set_model_age_policy("site-a", max_age_days=14, actor="op-1", now=_NOW)

    reopened = _open_store(tmp_path)

    assert reopened.get("site-a").model_max_age_days == 14


def test_unknown_site_age_policy_is_404(site_store) -> None:
    result = site_store.set_model_age_policy(
        "nope", max_age_days=30, actor="op-1", now=_NOW
    )

    assert result.verdict is SiteVerdict.UNKNOWN_SITE
```

`_open_store` / `_FRAME` / `_NOW` / `site_store` 는 그 파일이 이미 쓰는 이름을 그대로 쓴다. 없으면 그 파일의 관용구에 맞춰 만든다.

- [ ] **Step 3: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_site_transitions.py -k model_age -v`
기대: `AttributeError: 'SiteStore' object has no attribute 'set_model_age_policy'`

- [ ] **Step 4: `SiteRecord` 에 필드를 추가한다**

`services/core/src/ksi_core/sites.py` 의 `SiteRecord` 에서 `data_residency` 바로 아래:

```python
    # 이 현장의 공간모델 노후 판정 기준(일). ``None`` 은 **미선언**이고,
    # 미선언은 "최신"이 아니라 "판정하지 않음"으로 읽힌다
    # (:mod:`ksi_core.spatial_model` 의 ``AGE_POLICY_UNDECLARED``).
    # MASTER_PRD §6.3 은 MODEL_STALE 상태만 정의하고 며칠인지는 정하지 않았다 —
    # 서버가 기본값을 박으면 근거 없는 숫자가 자율운영 가능 여부를 가른다.
    model_max_age_days: int | None = None
```

- [ ] **Step 5: verdict·전이 기록·재생을 추가한다**

`SiteVerdict` 에:
```python
    MODEL_AGE_POLICY_SET = "MODEL_AGE_POLICY_SET"
```
`_STATUS` 에:
```python
    SiteVerdict.MODEL_AGE_POLICY_SET: 200,
```
`_replay` 의 `kind` 분기에 `site-model-age-policy-set` 을 추가하고 `_apply_model_age_policy_set` 를 만든다 — `_apply_aoi_set` 을 그대로 본뜬다(미지 site 면 `SiteStoreRecoveryError`).

```python
    def _apply_model_age_policy_set(self, raw: dict[str, Any]) -> None:
        site_id = raw["siteId"]
        current = self._sites.get(site_id)
        if current is None:
            raise SiteStoreRecoveryError(
                f"재생: 등록되지 않은 현장의 노후 기준 선언 — siteId={site_id!r}"
            )
        self._sites[site_id] = replace(
            current,
            model_max_age_days=raw["maxAgeDays"],
            updated_at=_parse_ts(raw["ts"]),
        )
```

- [ ] **Step 6: `set_model_age_policy` 를 만든다**

`set_aoi` 바로 아래:

```python
    def set_model_age_policy(
        self,
        site_id: str,
        *,
        max_age_days: int | None,
        actor: str,
        now: datetime,
    ) -> SiteResult:
        """이 현장의 공간모델 노후 판정 기준(일)을 선언·교체·철회한다.

        ``max_age_days=None`` 은 **철회**다 — 되돌릴 수 없는 정책은 정책이 아니다.
        철회하면 :func:`~ksi_core.spatial_model.evaluate_spatial_model` 이 노후를
        판정하지 않고 ``AGE_POLICY_UNDECLARED`` 를 낸다.

        AOI 와 달리 현장 상태로 잠그지 않는다 — 현장의 변화 속도는 매핑 시작 이후에
        알게 되는 사실이고, 그때 기준을 못 고치면 정책이 첫 추측에 갇힌다.
        """
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        if max_age_days is not None and max_age_days < 1:
            return SiteResult(
                SiteVerdict.INVALID_SITE,
                detail="maxAgeDays 는 1 이상이어야 한다 — 0·음수는 '매 순간 낡음'이라 정책이 아니다",
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            if site_id not in self._sites:
                return SiteResult(SiteVerdict.UNKNOWN_SITE, detail=_SITE_NOT_FOUND_DETAIL)
            raw: dict[str, Any] = {
                "kind": "site-model-age-policy-set",
                "ts": iso_utc(now),
                "actor": actor,
                "siteId": site_id,
                "before": self._sites[site_id].model_max_age_days,
                "maxAgeDays": max_age_days,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return SiteResult(SiteVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL)
            self._apply_model_age_policy_set(raw)
            return SiteResult(
                SiteVerdict.MODEL_AGE_POLICY_SET, record=self._sites[site_id]
            )
```

- [ ] **Step 7: 라우터와 뷰를 붙인다**

`SiteView` 에 `model_max_age_days: int | None = None` 을 추가하고 `_to_view` 에서 채운다. 요청 모델과 라우트:

```python
class ModelAgePolicyRequest(CamelModel):
    """``maxAgeDays=null`` 은 철회다(필드 생략과 같은 뜻이 되지 않게 명시 필수)."""

    max_age_days: int | None = Field(description="공간모델 노후 판정 기준(일). null 이면 철회")
```

```python
    @router.put("/{site_id}/model-age-policy", response_model=SiteMutationResponse)
    def set_site_model_age_policy(
        site_id: str,
        request: ModelAgePolicyRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> SiteMutationResponse:
        result = store.set_model_age_policy(
            site_id,
            max_age_days=request.max_age_days,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        return SiteMutationResponse(
            verdict=result.verdict.value,
            site=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )
```

- [ ] **Step 8: openapi 문서에 경로를 추가한다**

`contracts/api/openapi-core.yaml` 의 `/v1/sites/{site_id}/aoi` 항목 바로 뒤에 같은 모양으로 `/v1/sites/{site_id}/model-age-policy` 를 추가한다. `security` 선언을 반드시 넣는다 — 빠지면 `test_api_contract_sync` 가 깨진다.

```yaml
  /v1/sites/{site_id}/model-age-policy:
    put:
      summary: 현장 공간모델 노후 판정 기준 선언·철회
      description: >-
        maxAgeDays 는 이 현장의 공간모델이 며칠 지나면 낡은 것으로 볼지의 기준이다.
        null 이면 철회이고, 철회된 현장은 노후를 판정하지 않는다(AGE_POLICY_UNDECLARED).
        서버는 기본값을 두지 않는다 — MASTER_PRD §6.3 이 상태만 정의하고 기준은 정하지
        않았기 때문이다.
      security:
        - bearerAuth: []
      parameters:
        - name: site_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [maxAgeDays]
              properties:
                maxAgeDays:
                  type: integer
                  nullable: true
                  minimum: 1
      responses:
        "200":
          description: 선언됨
        "404":
          description: 현장 없음
        "422":
          description: 1 미만
        "503":
          description: 원장 봉인
```

- [ ] **Step 9: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_site_transitions.py tests/contract/test_api_contract_sync.py -q
```
기대: 전부 통과 (신규 6건 포함)

- [ ] **Step 10: 커밋**

```bash
git add services/core/src/ksi_core/sites.py contracts/api/openapi-core.yaml tests/contract/test_site_transitions.py
git commit -m "feat(core): let a site declare its spatial-model staleness threshold

서버가 노후 기준 기본값을 지어내지 않는다. 미선언 현장은 노후를 판정하지 않고
그 사실을 그대로 낸다. 철회 경로를 함께 둔다."
```

---

## Task 4: `GET /v1/sites/{site_id}/spatial-model`

**Files:**
- Modify: `services/core/src/ksi_core/spatial_model.py`
- Modify: `services/core/src/ksi_core/app.py`, `services/core/src/ksi_core/app_assembly.py`
- Modify: `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_spatial_model.py`

**Interfaces:**
- Consumes: Task 2 의 `evaluate_spatial_model`, Task 3 의 `SiteRecord.model_max_age_days`, `ProcessingJobStore.list_for_site`
- Produces:
  - `class SpatialModelView(CamelModel)` — `siteId`, `state`, `epochJobId`, `registeredAt`, `ageDays`, `maxAgeDays`, `sourceArtifactCount`, `succeededEpochCount`, `siteStatus`, `siteStatusMatchesModel`
  - `def build_spatial_model_router(*, site_store, processing_job_store) -> APIRouter`
  - `def mount_spatial_model(app, *, site_store, processing_job_store) -> None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_spatial_model.py` 끝에:

```python
def test_spatial_model_endpoint_reports_absent_for_new_site(api_client) -> None:
    api_client.register_site("site-a")

    body = api_client.get_json("/v1/sites/site-a/spatial-model")

    assert body["state"] == "ABSENT"
    assert body["epochJobId"] is None
    assert body["siteStatus"] == "UNMAPPED"
    assert body["siteStatusMatchesModel"] is True


def test_spatial_model_endpoint_flags_status_model_mismatch(api_client) -> None:
    """[핵심] 현장 상태가 PATROL_READY 인데 모델이 없으면 화면이 그 모순을 본다.

    자동 전진이 막혔거나 사람이 손으로 상태를 올린 경우다. 조용히 넘기면 "모델
    있는 현장"으로 읽힌다.
    """
    api_client.register_site("site-a")
    api_client.advance_site_to("site-a", "PATROL_READY")

    body = api_client.get_json("/v1/sites/site-a/spatial-model")

    assert body["state"] == "ABSENT"
    assert body["siteStatusMatchesModel"] is False


def test_spatial_model_endpoint_is_404_for_unknown_site(api_client) -> None:
    assert api_client.get("/v1/sites/nope/spatial-model").status_code == 404


def test_spatial_model_endpoint_requires_sites_read(api_client) -> None:
    api_client.register_site("site-a")

    assert api_client.get_as_viewer_without_permission(
        "/v1/sites/site-a/spatial-model"
    ).status_code == 403
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py -k endpoint -v`
기대: 404 (라우트 없음)

- [ ] **Step 3: 상태 정합 판정을 추가한다**

`spatial_model.py` 에:

```python
#: 그 현장 상태가 "공간모델이 있다"를 전제로 하는가 — INV-052 의 자율 계열
#: 허용 상태와 같은 집합이다(``mission_gating._AUTONOMOUS_READY`` + MODEL_STALE).
#: MODEL_VALIDATION 도 포함한다: 검증 대상 모델이 없는 검증 상태는 성립하지 않는다.
_STATUSES_THAT_ASSUME_A_MODEL: frozenset[SiteStatus] = frozenset(
    {
        SiteStatus.MODEL_VALIDATION,
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
        SiteStatus.PATROL_ACTIVE,
        SiteStatus.MODEL_STALE,
    }
)


def site_status_matches_model(status: SpatialModelState, site_status: SiteStatus) -> bool:
    """현장 상태가 실제 모델 유무와 앞뒤가 맞는가.

    거짓이면 자동 전진이 막혔거나 사람이 근거 없이 상태를 올린 것이다 — 화면이
    그 모순을 볼 수 있어야 한다. 이 함수는 **판정만** 하고 아무것도 고치지 않는다:
    조회가 상태를 되돌리기 시작하면 원장이 조회 시점에 따라 달라진다.
    """
    if site_status not in _STATUSES_THAT_ASSUME_A_MODEL:
        return True
    return status is not SpatialModelState.ABSENT
```

- [ ] **Step 4: 뷰와 라우터를 만든다**

```python
class SpatialModelView(CamelModel):
    """조회 응답 — 결론과 근거와 현장 상태 정합을 함께 낸다."""

    site_id: str
    state: str
    epoch_job_id: str | None
    registered_at: str | None
    age_days: float | None
    max_age_days: int | None
    source_artifact_count: int
    succeeded_epoch_count: int
    site_status: str
    site_status_matches_model: bool


def build_spatial_model_router(
    *, site_store: SiteStore, processing_job_store: ProcessingJobStore
) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["sites"])

    @router.get("/{site_id}/spatial-model", response_model=SpatialModelView)
    def get_spatial_model(
        site_id: str,
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> SpatialModelView:
        """이 현장의 공간모델 유무·최신도. 저장된 값이 아니라 **매 호출 재계산**이다."""
        site = site_store.get(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="현장을 찾을 수 없다")
        status = evaluate_spatial_model(
            processing_job_store.list_for_site(site_id),
            now=datetime.now(UTC),
            max_age_days=site.model_max_age_days,
        )
        return SpatialModelView(
            site_id=site_id,
            state=status.state.value,
            epoch_job_id=status.epoch_job_id,
            registered_at=(
                status.registered_at.isoformat() if status.registered_at is not None else None
            ),
            age_days=status.age_days,
            max_age_days=status.max_age_days,
            source_artifact_count=status.source_artifact_count,
            succeeded_epoch_count=status.succeeded_epoch_count,
            site_status=site.status.value,
            site_status_matches_model=site_status_matches_model(status.state, site.status),
        )

    return router


def mount_spatial_model(
    app: FastAPI, *, site_store: SiteStore, processing_job_store: ProcessingJobStore
) -> None:
    app.include_router(
        build_spatial_model_router(
            site_store=site_store, processing_job_store=processing_job_store
        )
    )
```

- [ ] **Step 5: `create_app` 에 배선한다**

`services/core/src/ksi_core/app.py` 에서 `processing_job_store` 와 `site_store` 가 **둘 다** 있을 때만 장착한다 — 재구성 원장이 없는 조립에서 이 표면을 열면 모든 현장이 영원히 `ABSENT` 라고 답하는 거짓 표면이 된다.

```python
    if site_store is not None and processing_job_store is not None:
        mount_spatial_model(
            app, site_store=site_store, processing_job_store=processing_job_store
        )
```

`app_assembly.py` 는 이미 두 store 를 `create_app` 에 넘기므로 추가 변경이 없다.

- [ ] **Step 6: openapi 에 경로를 추가한다**

`/v1/sites/{site_id}/processing-jobs` 근처에 같은 모양으로 `/v1/sites/{site_id}/spatial-model` GET 을 추가한다. `security: [bearerAuth: []]` 필수.

- [ ] **Step 7: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py tests/contract/test_api_contract_sync.py tests/contract/test_core_app.py -q
```
기대: 전부 통과

- [ ] **Step 8: 커밋**

```bash
git add services/core/src/ksi_core/spatial_model.py services/core/src/ksi_core/app.py contracts/api/openapi-core.yaml tests/contract/test_spatial_model.py
git commit -m "feat(core): expose per-site spatial-model state over HTTP

매 호출 재계산이고 저장하지 않는다. 현장 상태와 실제 모델 유무가 어긋나면
siteStatusMatchesModel=false 로 그 모순을 조회 표면이 드러낸다."
```

---

## Task 5: 재구성 신호 → 현장 상태 자동 전진

**Files:**
- Modify: `services/core/src/ksi_core/spatial_model.py`
- Modify: `services/core/src/ksi_core/processing_jobs.py`
- Modify: `services/core/src/ksi_core/metrics.py`
- Modify: `services/core/src/ksi_core/app.py`
- Test: `tests/contract/test_spatial_model.py`

**Interfaces:**
- Consumes: `SiteStore.transition`, `ksi_domain.enums.requires_autonomy_approval`, `ProcessingJobStatus`
- Produces:
  - `class SiteAdvanceOutcome(StrEnum)` — `ADVANCED` · `NO_RULE` · `ALREADY_PAST` · `ILLEGAL_FROM_CURRENT` · `UNKNOWN_SITE` · `STORE_UNAVAILABLE`
  - `class SpatialModelLifecycle` — 생성자 `__init__(self, *, site_store: SiteStore, processing_job_store: ProcessingJobStore)`. **`processing_job_store` 는 이 Task 에서 쓰지 않지만 지금 받는다** — Task 10 의 노후 스윕이 필요로 하고, 생성자를 나중에 바꾸면 그때 모든 호출부를 다시 찾아야 한다. 메서드: `advance_for_job_status(site_id, job_status, *, job_id, now) -> SiteAdvanceOutcome`
  - `metrics.SITE_AUTO_ADVANCES: Counter` (라벨 `outcome`, `target_status`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_job_issued_advances_baseline_mapping_to_model_processing(lifecycle, site_store) -> None:
    _advance_site(site_store, "site-a", SiteStatus.BASELINE_MAPPING)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.QUEUED, job_id="site-a-m1-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_PROCESSING


def test_job_succeeded_advances_model_processing_to_model_validation(
    lifecycle, site_store
) -> None:
    _advance_site(site_store, "site-a", SiteStatus.MODEL_PROCESSING)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_VALIDATION


def test_auto_advance_never_crosses_the_autonomy_approval_edge(lifecycle, site_store) -> None:
    """[핵심] 자동 전진이 사람의 승인 간선을 대신 밟지 않는다.

    MODEL_VALIDATION → PROVISIONAL_AUTONOMY 는 SITES_AUTONOMY_APPROVE 전용이다
    (ADR-KSI-015 D2). 재구성 성공 하나로 자율운영이 열리면 그 권한이 장식이 된다.
    """
    _advance_site(site_store, "site-a", SiteStatus.MODEL_VALIDATION)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj2", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ALREADY_PAST
    assert site_store.get("site-a").status is SiteStatus.MODEL_VALIDATION


def test_no_advance_rule_targets_an_autonomy_approval_edge() -> None:
    """전진 규칙표 자체가 승인 간선을 담지 않는다는 구조적 보증."""
    for source, target in _JOB_STATUS_SITE_ADVANCE.values():
        assert not requires_autonomy_approval(source, target), (
            f"자동 전진 규칙이 승인 간선을 담고 있다: {source.value} → {target.value}"
        )


def test_advance_from_wrong_status_is_reported_not_raised(lifecycle, site_store) -> None:
    """UNMAPPED 현장에 재구성 성공이 들어와도 예외를 던지지 않는다.

    전진 실패가 원래 요청(워커의 성공 보고)을 깨뜨리면, 현장 상태가 어긋났다는
    이유로 재구성 결과가 유실된다.
    """
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)

    outcome = lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="x-pj1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
    assert site_store.get("site-a").status is SiteStatus.UNMAPPED


def test_failed_and_cancelled_jobs_do_not_move_the_site(lifecycle, site_store) -> None:
    _advance_site(site_store, "site-a", SiteStatus.MODEL_PROCESSING)

    for status in (ProcessingJobStatus.FAILED, ProcessingJobStatus.CANCELLED):
        assert (
            lifecycle.advance_for_job_status("site-a", status, job_id="x", now=_NOW)
            is SiteAdvanceOutcome.NO_RULE
        )
    assert site_store.get("site-a").status is SiteStatus.MODEL_PROCESSING


def test_advance_writes_a_system_actor_into_the_site_journal(lifecycle, site_store) -> None:
    """누가 옮겼는지가 원장에 남는다 — 자동 전이도 감사 대상이다."""
    _advance_site(site_store, "site-a", SiteStatus.MODEL_PROCESSING)

    lifecycle.advance_for_job_status(
        "site-a", ProcessingJobStatus.SUCCEEDED, job_id="site-a-m1-pj1", now=_NOW
    )

    entries = _read_site_journal(site_store)
    last = entries[-1]
    assert last["actor"] == "system:spatial-model-lifecycle"
    assert "site-a-m1-pj1" in last["evidence"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py -k advance -v`
기대: `ImportError` / `AttributeError`

- [ ] **Step 3: 전진 규칙과 오케스트레이터를 만든다**

`spatial_model.py` 에 추가:

```python
class SiteAdvanceOutcome(StrEnum):
    """자동 전진 1회의 결과 — 실패도 typed 로 돌려주고 예외를 던지지 않는다."""

    ADVANCED = "ADVANCED"
    #: 이 작업 상태에 대응하는 전진 규칙이 없다(FAILED·CANCELLED 등).
    NO_RULE = "NO_RULE"
    #: 규칙의 출발 상태가 아니다 — 이미 그 지점을 지났다.
    ALREADY_PAST = "ALREADY_PAST"
    #: 규칙의 출발 상태도 아니고 뒤쪽도 아니다 — 상태머신이 허용하지 않는다.
    ILLEGAL_FROM_CURRENT = "ILLEGAL_FROM_CURRENT"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


#: SSOT — 처리 작업 상태가 현장을 어디서 어디로 밀어야 하는가. (출발, 도착) 쌍이라
#: **출발 상태가 아닌 현장은 건드리지 않는다**: 상태머신이 허용한다는 이유로 아무
#: 데서나 밀면 자동화가 사람의 판단을 덮어쓴다.
#:
#: 이 표에 자율운영 승인 간선(``requires_autonomy_approval`` 참)을 넣지 않는다 —
#: 그 검증은 테스트가 구조적으로 강제한다.
_JOB_STATUS_SITE_ADVANCE: dict[ProcessingJobStatus, tuple[SiteStatus, SiteStatus]] = {
    # 재구성 작업이 만들어졌다 = 처리가 시작됐다.
    ProcessingJobStatus.QUEUED: (SiteStatus.BASELINE_MAPPING, SiteStatus.MODEL_PROCESSING),
    # 원본 산출물을 가진 성공 = 공간모델이 생겼다. **검증까지 자동으로 하지 않는다** —
    # MODEL_VALIDATION 이 종착이고 그 다음은 사람의 승인이다.
    ProcessingJobStatus.SUCCEEDED: (
        SiteStatus.MODEL_PROCESSING,
        SiteStatus.MODEL_VALIDATION,
    ),
}

_SYSTEM_ACTOR = "system:spatial-model-lifecycle"


class SpatialModelLifecycle:
    """재구성 신호를 받아 현장 상태를 전진시킨다 — 라우터 계층에서만 호출한다.

    ## 왜 저장소 안이 아니라 여기인가

    ``ProcessingJobStore`` 안에서 ``SiteStore`` 를 부르면 두 잠금을 겹쳐 쥐게 되고,
    그 순간 잠금 순서가 아키텍처 제약이 된다. 여기서는 작업 저장소 호출이 **끝난
    뒤** 별도로 부르므로 겹치지 않는다.

    ## 전진 실패는 원래 요청을 깨뜨리지 않는다

    모든 실패를 :class:`SiteAdvanceOutcome` 으로 돌려주고 예외를 던지지 않는다.
    현장 상태가 어긋났다는 이유로 워커의 재구성 성공 보고가 500 이 되면, 되돌릴 수
    없는 계산 결과가 유실된다. 대신 결과를 metric 으로 세고 비정상만 로그로 남긴다.
    """

    def __init__(
        self, *, site_store: SiteStore, processing_job_store: ProcessingJobStore
    ) -> None:
        self._site_store = site_store
        # 이 Task 에서는 안 쓴다 — Task 10 의 노후 스윕이 쓴다. 생성자를 나중에
        # 바꾸면 그때 모든 호출부를 다시 찾아야 하므로 지금 받는다.
        self._processing_job_store = processing_job_store

    def advance_for_job_status(
        self,
        site_id: str,
        job_status: ProcessingJobStatus,
        *,
        job_id: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        rule = _JOB_STATUS_SITE_ADVANCE.get(job_status)
        if rule is None:
            return self._record(SiteAdvanceOutcome.NO_RULE, target=None)
        source, target = rule

        site = self._site_store.get(site_id)
        if site is None:
            return self._record(SiteAdvanceOutcome.UNKNOWN_SITE, target=target)
        if site.status is not source:
            outcome = (
                SiteAdvanceOutcome.ALREADY_PAST
                if _is_at_or_past(site.status, target)
                else SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
            )
            if outcome is SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT:
                logger.warning(
                    "자동 전진 건너뜀 — site=%s 현재=%s 규칙=%s→%s (job=%s)",
                    site_id,
                    site.status.value,
                    source.value,
                    target.value,
                    job_id,
                )
            return self._record(outcome, target=target)

        return self._transition(
            site_id,
            target,
            evidence=f"processingJob={job_id} status={job_status.value}",
            reason="재구성 신호에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )

    def _transition(
        self,
        site_id: str,
        target: SiteStatus,
        *,
        evidence: str,
        reason: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        """전이 호출 하나 — 세 진입점(작업 상태·임무 배포·노후 스윕)이 공유한다."""
        result = self._site_store.transition(
            site_id,
            target,
            evidence=evidence,
            reason=reason,
            actor=_SYSTEM_ACTOR,
            now=now,
        )
        if result.verdict is SiteVerdict.TRANSITIONED:
            return self._record(SiteAdvanceOutcome.ADVANCED, target=target)
        if result.verdict is SiteVerdict.STORE_UNAVAILABLE:
            return self._record(SiteAdvanceOutcome.STORE_UNAVAILABLE, target=target)
        return self._record(SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT, target=target)

    @staticmethod
    def _record(outcome: SiteAdvanceOutcome, *, target: SiteStatus | None) -> SiteAdvanceOutcome:
        SITE_AUTO_ADVANCES.inc(
            outcome=outcome.value, target_status=target.value if target else "none"
        )
        return outcome
```

`_is_at_or_past` 는 상태머신 위상 순서를 쓰지 않고, "목표 상태에서 출발 상태로 되돌아가는 경로가 없으면 이미 지난 것"이라는 판정을 쓴다:

```python
#: 매핑 진행 축의 선형 순서 — "이미 지났다"를 판정하는 데만 쓴다.
#: SUSPENDED·REMAP_REQUIRED 는 축 밖이라 포함하지 않는다(둘 다 ILLEGAL 로 읽힌다).
_PROGRESS_ORDER: tuple[SiteStatus, ...] = (
    SiteStatus.UNMAPPED,
    SiteStatus.BASELINE_MAPPING,
    SiteStatus.MODEL_PROCESSING,
    SiteStatus.MODEL_VALIDATION,
    SiteStatus.PROVISIONAL_AUTONOMY,
    SiteStatus.PATROL_READY,
    SiteStatus.PATROL_ACTIVE,
)


def _is_at_or_past(current: SiteStatus, target: SiteStatus) -> bool:
    """``current`` 가 매핑 진행 축에서 ``target`` 이후인가 — 축 밖이면 거짓."""
    if current not in _PROGRESS_ORDER or target not in _PROGRESS_ORDER:
        return False
    return _PROGRESS_ORDER.index(current) >= _PROGRESS_ORDER.index(target)
```

- [ ] **Step 4: metric 을 추가한다**

`services/core/src/ksi_core/metrics.py` 에서 `PROCESSING_JOB_TRANSITIONS` 옆:

```python
SITE_AUTO_ADVANCES = Counter(
    "ksi_site_auto_advances_total",
    "재구성·임무 실행 신호에 따른 현장 상태 자동 전진 시도 결과",
)
```
그리고 `_ALL_METRICS` 와 `__all__` 에 추가한다.

- [ ] **Step 5: 처리작업 라우터에 훅을 건다**

`processing_jobs.py` 의 `build_processing_jobs_router`(정확한 이름은 파일에서 확인) 시그니처에 선택 인자를 추가한다:

```python
    site_lifecycle: SpatialModelLifecycle | None = None,
```

발급 라우트에서 201 성공 직후:

```python
        if site_lifecycle is not None and result.verdict is ProcessingJobVerdict.ISSUED:
            # 전진 실패는 이 응답에 영향을 주지 않는다 — 결과는 metric·로그로 남는다.
            site_lifecycle.advance_for_job_status(
                result.record.site_id,
                ProcessingJobStatus.QUEUED,
                job_id=result.record.job_id,
                now=datetime.now(UTC),
            )
```

전이 라우트에서 `TRANSITIONED` 직후 같은 모양으로 `request.target_status` 를 넘긴다. `ProcessingJobVerdict.ISSUED` 의 실제 멤버명은 파일에서 확인해 맞춘다.

- [ ] **Step 6: `create_app` 에서 lifecycle 을 만들어 주입한다**

```python
    site_lifecycle = (
        SpatialModelLifecycle(
            site_store=site_store, processing_job_store=processing_job_store
        )
        if site_store is not None and processing_job_store is not None
        else None
    )
```
그리고 처리작업 라우터 장착 지점에 넘긴다.

- [ ] **Step 7: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py tests/contract/test_processing_jobs.py tests/contract/test_core_app.py -q
```
기대: 전부 통과. 기존 `test_processing_jobs.py` 가 깨지면 훅이 응답을 바꿨다는 뜻이므로 훅을 고친다(테스트를 고치지 않는다).

- [ ] **Step 8: 커밋**

```bash
git add services/core/src/ksi_core/spatial_model.py services/core/src/ksi_core/processing_jobs.py services/core/src/ksi_core/metrics.py services/core/src/ksi_core/app.py tests/contract/test_spatial_model.py
git commit -m "feat(core): advance site status automatically on reconstruction signals

재구성 작업 발급이 BASELINE_MAPPING→MODEL_PROCESSING 을, 원본 뒷받침된 성공이
MODEL_PROCESSING→MODEL_VALIDATION 을 자동 전진시킨다. 자율운영 승인 간선은
자동 전진이 절대 밟지 않으며 그 보증을 규칙표 구조 테스트가 강제한다."
```

---

## Task 6: 임무 실행 상태 도메인 enum

**Files:**
- Modify: `packages/domain/src/ksi_domain/enums.py`
- Test: `tests/contract/test_mission_execution.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `class MissionExecutionStatus(StrEnum)` — `ISSUED` · `DISPATCHED` · `ACTIVATED` · `COMPLETED` · `ENDED_INCOMPLETE` · `CANCELLED`
  - `class IllegalMissionExecutionTransitionError(ValueError)`
  - `def assert_mission_execution_transition(cur, nxt) -> None`
  - `def can_mission_execution_transition(cur, nxt) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_mission_execution.py`:

```python
"""임무 실행 생애주기 — 전이표·원장·API·훅 (ADR-KSI-019 G2)."""

from __future__ import annotations

import pytest
from ksi_domain.enums import (
    IllegalMissionExecutionTransitionError,
    MissionExecutionStatus,
    assert_mission_execution_transition,
    can_mission_execution_transition,
)

_ME = MissionExecutionStatus


def test_forward_path_is_allowed() -> None:
    for cur, nxt in (
        (_ME.ISSUED, _ME.DISPATCHED),
        (_ME.DISPATCHED, _ME.ACTIVATED),
        (_ME.ACTIVATED, _ME.COMPLETED),
    ):
        assert_mission_execution_transition(cur, nxt)


def test_skipping_forward_is_allowed() -> None:
    """[핵심] 중간 단계를 건너뛴 완료 보고를 거부하지 않는다.

    운영자가 KMZ 를 손으로 옮겨 날린 임무는 DISPATCHED·ACTIVATED 신호가 아예
    없다(ADR-KSI-019 G3 — 실기 확인 전까지 수동 이관이 공식 경로). 그 임무의
    커버리지 보고를 실행 상태 때문에 거부하면 INV-010 의 완료 판정 권위가
    이 필드로 넘어간다.
    """
    assert_mission_execution_transition(_ME.ISSUED, _ME.COMPLETED)
    assert_mission_execution_transition(_ME.ISSUED, _ME.ENDED_INCOMPLETE)


def test_backward_transition_is_refused() -> None:
    with pytest.raises(IllegalMissionExecutionTransitionError):
        assert_mission_execution_transition(_ME.ACTIVATED, _ME.DISPATCHED)


def test_completion_states_may_correct_each_other() -> None:
    """COMPLETED ↔ ENDED_INCOMPLETE 는 양방향이다.

    완료 판정의 권위는 CoverageReport 원장이고(INV-010) 이 필드는 그 원장의
    **투영**이다. 나중에 접수된 보고가 결론을 바꾸면 투영도 따라가야 한다 —
    따라가지 않으면 두 표면이 서로 다른 완료를 말한다.
    """
    assert_mission_execution_transition(_ME.COMPLETED, _ME.ENDED_INCOMPLETE)
    assert_mission_execution_transition(_ME.ENDED_INCOMPLETE, _ME.COMPLETED)


def test_cancelled_is_terminal() -> None:
    for nxt in _ME:
        assert not can_mission_execution_transition(_ME.CANCELLED, nxt)


def test_transition_table_covers_every_member() -> None:
    """표 완전성 — 새 멤버가 추가됐는데 표를 안 고치면 여기서 드러난다."""
    from ksi_domain.enums import _ALLOWED_MISSION_EXECUTION_TRANSITIONS

    assert set(_ALLOWED_MISSION_EXECUTION_TRANSITIONS) == set(MissionExecutionStatus)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py -v`
기대: `ImportError: cannot import name 'MissionExecutionStatus'`

- [ ] **Step 3: enum 과 전이표를 만든다**

`packages/domain/src/ksi_domain/enums.py` 의 `SiteStatus` 블록 뒤:

```python
class MissionExecutionStatus(StrEnum):
    """임무 1건의 실행 생애주기 (ADR-KSI-019 G2).

    ``MissionRecord`` 는 **발급 기록**이라 "이 임무가 실제로 날았는가"에 답하지
    못했다. 이 enum 이 그 축을 연다.

    ## 없는 상태가 있다 — ``IN_FLIGHT``

    KSI 는 비행 중 텔레메트리를 받지 않는다(INV-001 — 서버는 프레임별 제어·수신
    주체가 아니다). 그래서 "지금 날고 있다"는 서버가 아는 사실이 아니다.
    ``ACTIVATED`` (Edge 가 계약을 활성화했다고 서명해 보고한 시점)가 완료 이전
    구간에서 **서버가 실제로 아는 가장 앞선 사실**이고, 그 앞에 없는 상태를
    지어내지 않는다.
    """

    #: 계약·경로가 발급됐다. 실행 레코드가 아직 없는 임무의 기본값이다.
    ISSUED = "ISSUED"
    #: 기체 쪽으로 넘어갔다 — Edge 가 envelope 을 pull 했거나, 운영자가 KMZ 를
    #: 손으로 옮겼다고 신고했다(수동 이관이 아직 공식 경로다, ADR-KSI-019 G3).
    DISPATCHED = "DISPATCHED"
    #: Edge 가 activation receipt 를 서명해 보고했다.
    ACTIVATED = "ACTIVATED"
    #: CoverageReport 가 ``COMPLETED`` 로 접수됐다(INV-010 게이트 통과).
    COMPLETED = "COMPLETED"
    #: CoverageReport 가 접수됐지만 완료가 아니다(COMPLETED_WITH_GAPS·ABORTED_SAFE·FAILED).
    ENDED_INCOMPLETE = "ENDED_INCOMPLETE"
    #: 사람이 이 임무를 접었다.
    CANCELLED = "CANCELLED"


class IllegalMissionExecutionTransitionError(ValueError):
    """허용되지 않은 MissionExecutionStatus 전이 시도 시 발생."""


_MES = MissionExecutionStatus

# 허용 전이표(SSOT). 세 가지가 다른 상태머신들과 다르다:
#
# ① **앞으로 건너뛰기를 허용한다.** 운영자가 KMZ 를 손으로 옮겨 날린 임무는
#    DISPATCHED·ACTIVATED 신호가 아예 없다 — 그 임무의 완료 보고를 실행 상태
#    때문에 거부하면 INV-010 의 완료 판정 권위가 이 필드로 넘어간다. 이 축은
#    게이트가 아니라 **관측 기록**이다.
# ② **COMPLETED ↔ ENDED_INCOMPLETE 는 양방향이다.** 완료 판정의 권위는
#    CoverageReport 원장이고 이 필드는 그 원장의 투영이다. 나중에 접수된 보고가
#    결론을 바꾸면 투영도 따라가야 한다 — 안 따라가면 두 표면이 서로 다른 완료를
#    말한다.
# ③ **CANCELLED 만 진짜 종단이다.** 사람이 접은 임무를 시스템 신호가 되살리지
#    않는다. 되살려야 하면 새 임무를 발급한다.
_ALLOWED_MISSION_EXECUTION_TRANSITIONS: dict[
    MissionExecutionStatus, set[MissionExecutionStatus]
] = {
    _MES.ISSUED: {
        _MES.DISPATCHED,
        _MES.ACTIVATED,
        _MES.COMPLETED,
        _MES.ENDED_INCOMPLETE,
        _MES.CANCELLED,
    },
    _MES.DISPATCHED: {
        _MES.ACTIVATED,
        _MES.COMPLETED,
        _MES.ENDED_INCOMPLETE,
        _MES.CANCELLED,
    },
    _MES.ACTIVATED: {_MES.COMPLETED, _MES.ENDED_INCOMPLETE, _MES.CANCELLED},
    _MES.COMPLETED: {_MES.ENDED_INCOMPLETE},
    _MES.ENDED_INCOMPLETE: {_MES.COMPLETED},
    _MES.CANCELLED: set(),
}

if set(_ALLOWED_MISSION_EXECUTION_TRANSITIONS) != set(MissionExecutionStatus):
    raise AssertionError(
        "_ALLOWED_MISSION_EXECUTION_TRANSITIONS 가 MissionExecutionStatus 전 멤버를 커버하지 않는다"
    )


def can_mission_execution_transition(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> bool:
    """``cur → nxt`` 전이 허용 여부를 예외 없이 bool 로 반환한다."""
    return nxt in _ALLOWED_MISSION_EXECUTION_TRANSITIONS.get(cur, set())


def assert_mission_execution_transition(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    """``cur → nxt`` 전이가 허용되는지 검증한다.

    Raises:
        IllegalMissionExecutionTransitionError: 표에 없는 전이일 때.
    """
    if not can_mission_execution_transition(cur, nxt):
        allowed = ", ".join(
            sorted(s.value for s in _ALLOWED_MISSION_EXECUTION_TRANSITIONS.get(cur, set()))
        ) or "없음"
        raise IllegalMissionExecutionTransitionError(
            f"허용되지 않은 임무 실행 상태 전이: {cur.value} → {nxt.value} (허용: {allowed})"
        )
```

`__all__` 이 있으면 네 이름을 추가한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py -v`
기대: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add packages/domain/src/ksi_domain/enums.py tests/contract/test_mission_execution.py
git commit -m "feat(domain): add mission execution lifecycle status and transition table

앞으로 건너뛰기를 허용하고 COMPLETED↔ENDED_INCOMPLETE 를 양방향으로 둔다 —
이 축은 게이트가 아니라 CoverageReport 원장의 투영이기 때문이다(INV-010).
IN_FLIGHT 는 만들지 않는다: 서버가 아는 사실이 아니다."
```

---

## Task 7: 임무 실행 원장 (`MissionExecutionStore`)

**Files:**
- Create: `services/core/src/ksi_core/mission_execution.py`
- Modify: `services/core/src/ksi_core/app_assembly.py`
- Test: `tests/contract/test_mission_execution.py`

**Interfaces:**
- Consumes: `DurableJournal`, `MissionStore`, Task 6 의 `assert_mission_execution_transition`
- Produces:
  - `class MissionExecutionVerdict(StrEnum)` — `TRANSITIONED` · `UNKNOWN_MISSION` · `ILLEGAL_TRANSITION` · `STORE_UNAVAILABLE`
  - `MISSION_EXECUTION_HTTP_STATUS: dict[MissionExecutionVerdict, int]`
  - `@dataclass class MissionExecutionRecord` — `mission_id`, `status`, `updated_at`, `updated_by`, `detail`
  - `@dataclass class MissionExecutionResult` — `verdict`, `record`, `detail`
  - `class MissionExecutionStore` — `status_of(mission_id) -> MissionExecutionStatus | None` (기록된 상태, 없으면 `None`), `effective_status(mission_id) -> MissionExecutionStatus` (기록 없음을 `ISSUED` 로 읽음), `mission_exists(mission_id) -> bool`, `history(mission_id) -> list[MissionExecutionRecord]`, `transition(mission_id, target, *, detail, actor, now) -> MissionExecutionResult`, `sealed_reason`
  - `class MissionExecutionRecoveryError(RuntimeError)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_mission_with_no_record_reads_as_issued(execution_store, mission_store) -> None:
    """[핵심] 레코드 부재가 ISSUED 다 — 발급 경로를 건드리지 않는다.

    발급 시점에 실행 레코드를 함께 쓰면 ADR-KSI-008 §3 의 "durable 기록 전 201
    금지" 경로에 두 번째 원장 쓰기가 끼어들어, 그 쓰기가 실패할 때 발급 자체가
    실패하게 된다. 발급은 이미 성립한 계약이므로 그럴 이유가 없다.
    """
    _issue_mission(mission_store, "m-1", site_id="site-a")

    assert execution_store.status_of("m-1") is None
    assert execution_store.effective_status("m-1") is MissionExecutionStatus.ISSUED


def test_transition_records_and_projects(execution_store, mission_store) -> None:
    _issue_mission(mission_store, "m-1", site_id="site-a")

    result = execution_store.transition(
        "m-1", MissionExecutionStatus.DISPATCHED, detail="RC 로 이관", actor="op-1", now=_NOW
    )

    assert result.verdict is MissionExecutionVerdict.TRANSITIONED
    assert execution_store.effective_status("m-1") is MissionExecutionStatus.DISPATCHED
    assert execution_store.history("m-1")[-1].updated_by == "op-1"


def test_unknown_mission_is_refused(execution_store) -> None:
    """발급된 적 없는 임무의 실행 상태는 받지 않는다(coverage_reports 와 같은 원칙)."""
    result = execution_store.transition(
        "nope", MissionExecutionStatus.DISPATCHED, detail=None, actor="op-1", now=_NOW
    )

    assert result.verdict is MissionExecutionVerdict.UNKNOWN_MISSION


def test_illegal_transition_is_typed_not_raised(execution_store, mission_store) -> None:
    _issue_mission(mission_store, "m-1", site_id="site-a")
    execution_store.transition(
        "m-1", MissionExecutionStatus.CANCELLED, detail=None, actor="op-1", now=_NOW
    )

    result = execution_store.transition(
        "m-1", MissionExecutionStatus.COMPLETED, detail=None, actor="sys", now=_NOW
    )

    assert result.verdict is MissionExecutionVerdict.ILLEGAL_TRANSITION


def test_replay_reconstructs_status(tmp_path, mission_store) -> None:
    store = _open_execution_store(tmp_path, mission_store)
    _issue_mission(mission_store, "m-1", site_id="site-a")
    store.transition("m-1", MissionExecutionStatus.DISPATCHED, detail=None, actor="o", now=_NOW)
    store.transition("m-1", MissionExecutionStatus.ACTIVATED, detail=None, actor="o", now=_NOW)

    reopened = _open_execution_store(tmp_path, mission_store)

    assert reopened.effective_status("m-1") is MissionExecutionStatus.ACTIVATED
    assert len(reopened.history("m-1")) == 2


def test_replay_refuses_an_illegal_sequence(tmp_path, mission_store) -> None:
    """[핵심] 손으로 고친 원장이 불법 전이를 되살릴 수 없다.

    sites._apply_transitioned·processing_jobs._replay_transition 과 같은 원칙 —
    재생도 live 와 같은 전이표를 다시 태운다.
    """
    _write_raw_journal(
        tmp_path,
        [
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "ISSUED", "after": "CANCELLED", "ts": _TS, "actor": "o", "detail": None},
            {"kind": "mission-execution-transitioned", "missionId": "m-1",
             "before": "CANCELLED", "after": "COMPLETED", "ts": _TS, "actor": "o", "detail": None},
        ],
    )

    with pytest.raises(MissionExecutionRecoveryError):
        _open_execution_store(tmp_path, mission_store)


def test_sealed_journal_reports_store_unavailable(execution_store_sealed) -> None:
    result = execution_store_sealed.transition(
        "m-1", MissionExecutionStatus.DISPATCHED, detail=None, actor="o", now=_NOW
    )

    assert result.verdict is MissionExecutionVerdict.STORE_UNAVAILABLE
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py -v`
기대: `ModuleNotFoundError: No module named 'ksi_core.mission_execution'`

- [ ] **Step 3: 저장소를 만든다**

`services/core/src/ksi_core/mission_execution.py` — `mission_records.py` 의 store 관용구를 그대로 따른다(`threading.Lock`, `_replay`, `sealed_reason`, typed verdict, `_STATUS` 표).

모듈 docstring 의 핵심 문단:

```python
"""임무 실행 생애주기 원장 (ADR-KSI-019 G2).

``MissionRecord`` 는 **발급 기록**이라 "이 임무가 실제로 날았는가"에 답하지 못한다.
이 모듈이 그 축을 별도 원장으로 연다.

## 레코드 부재 = ``ISSUED``

발급 시점에 실행 레코드를 함께 쓰지 않는다. 그러면 ADR-KSI-008 §3 의 "durable
기록 전 201 금지" 경로에 두 번째 원장 쓰기가 끼어들고, 그 쓰기가 실패할 때 이미
성립한 계약 발급이 실패한다. 대신 :meth:`MissionExecutionStore.effective_status`
가 "레코드 없음"을 ``ISSUED`` 로 읽는다 — ``SiteRecord.aoi`` 가 ``None`` 을
"아직 설정 안 함"으로 읽는 것과 같은 관용구다.

## 이 축은 게이트가 아니다 (INV-010)

완료 판정의 권위는 CoverageReport 하나다. 이 상태를 커버리지 접수·재구성 발급·
소스미디어 등록의 **전제조건으로 쓰지 않는다.** 쓰기 시작하면 완료 판정의 권위가
조용히 이 필드로 옮겨온다. 여기서 강제하는 것은 전이표뿐이고, 전이표조차 앞으로
건너뛰기를 허용한다(``ksi_domain.enums`` 참조).

## 재생은 fail-closed

live 와 같은 전이표를 다시 태운다 — journal 을 손으로 고쳐 CANCELLED 를
COMPLETED 로 바꿀 수 없다(``processing_jobs._replay_transition`` 과 동일 원칙).
"""
```

`transition` 본문 골자:

```python
    def transition(
        self,
        mission_id: str,
        target: MissionExecutionStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
    ) -> MissionExecutionResult:
        if now.tzinfo is None:
            raise ValueError("now 는 tz-aware 여야 한다 — naive datetime 거부")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return MissionExecutionResult(
                    MissionExecutionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            if self._mission_store.get(mission_id) is None:
                return MissionExecutionResult(
                    MissionExecutionVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            current = self._effective_status_locked(mission_id)
            try:
                assert_mission_execution_transition(current, target)
            except IllegalMissionExecutionTransitionError as exc:
                return MissionExecutionResult(
                    MissionExecutionVerdict.ILLEGAL_TRANSITION, detail=str(exc)
                )
            raw: dict[str, Any] = {
                "kind": "mission-execution-transitioned",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "before": current.value,
                "after": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return MissionExecutionResult(
                    MissionExecutionVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._apply_locked(raw)
            MISSION_EXECUTION_TRANSITIONS.inc(target_status=target.value)
            return MissionExecutionResult(
                MissionExecutionVerdict.TRANSITIONED, record=record
            )
```

`MISSION_EXECUTION_TRANSITIONS` Counter 를 `metrics.py` 에 추가한다(Task 5 의 `SITE_AUTO_ADVANCES` 와 같은 자리).

- [ ] **Step 4: 조립에 배선한다**

`app_assembly.py` 에서 `mission_store` 생성 직후:

```python
    mission_execution_store = MissionExecutionStore(
        journal("mission-execution.jsonl"), mission_store=mission_store
    )
```
그리고 `create_app(..., mission_execution_store=mission_execution_store, ...)` 로 넘긴다. `create_app` 시그니처에도 `mission_execution_store: MissionExecutionStore | None = None` 을 추가한다.

- [ ] **Step 5: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py tests/contract/test_core_app_assembly.py tests/contract/test_dev_assembly.py -q
```
기대: 전부 통과

- [ ] **Step 6: 커밋**

```bash
git add services/core/src/ksi_core/mission_execution.py services/core/src/ksi_core/app.py services/core/src/ksi_core/app_assembly.py services/core/src/ksi_core/metrics.py tests/contract/test_mission_execution.py
git commit -m "feat(core): persist mission execution lifecycle as its own journal

레코드 부재를 ISSUED 로 읽어 발급 경로를 건드리지 않는다. 재생은 live 와 같은
전이표를 다시 태운다. 이 축은 완료 판정의 게이트가 아니라 투영이다(INV-010)."
```

---

## Task 8: 임무 실행 상태 API

**Files:**
- Modify: `services/core/src/ksi_core/mission_execution.py`
- Modify: `services/core/src/ksi_core/app.py`, `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_mission_execution.py`

**Interfaces:**
- Consumes: Task 7 의 `MissionExecutionStore`
- Produces:
  - `POST /v1/missions/{mission_id}/execution-transitions` (사람이 선언 가능한 상태만)
  - `GET /v1/missions/{mission_id}/execution`
  - `class MissionExecutionView(CamelModel)` — `missionId`, `status`, `updatedAt`, `updatedBy`, `detail`, `history`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_operator_can_declare_dispatched(api_client) -> None:
    """운영자가 KMZ 를 손으로 옮겼다는 사실을 서버가 기록할 수 있어야 한다.

    실기 확인 전까지 수동 이관이 공식 경로다(ADR-KSI-019 G3). 그 경로를 서버가
    기록하지 못하면 임무 원장에 "날았는지 모른다"만 남는다.
    """
    api_client.issue_mission("m-1", site_id="site-a")

    response = api_client.post_json(
        "/v1/missions/m-1/execution-transitions",
        {"targetStatus": "DISPATCHED", "detail": "RC Plus 2 로 KMZ 이관"},
    )

    assert response.status_code == 200
    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "DISPATCHED"


def test_operator_cannot_declare_completed(api_client) -> None:
    """[핵심] 사람이 완료를 손으로 찍을 수 없다.

    COMPLETED 는 CoverageReport 접수가 만드는 사실이다(INV-010). 사람이 찍을 수
    있으면 그 상태는 근거가 아니라 주장이 된다 — processing_jobs 의
    "PROCESSING_WORK 는 어느 Role 에도 없다"와 같은 원칙이다.
    """
    api_client.issue_mission("m-1", site_id="site-a")

    response = api_client.post_json(
        "/v1/missions/m-1/execution-transitions", {"targetStatus": "COMPLETED"}
    )

    assert response.status_code == 403


def test_operator_cannot_declare_activated(api_client) -> None:
    """ACTIVATED 는 Edge 의 서명 receipt 가 만드는 사실이다."""
    api_client.issue_mission("m-1", site_id="site-a")

    assert (
        api_client.post_json(
            "/v1/missions/m-1/execution-transitions", {"targetStatus": "ACTIVATED"}
        ).status_code
        == 403
    )


def test_get_execution_returns_issued_for_untouched_mission(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a")

    body = api_client.get_json("/v1/missions/m-1/execution")

    assert body["status"] == "ISSUED"
    assert body["history"] == []


def test_get_execution_is_404_for_unknown_mission(api_client) -> None:
    assert api_client.get("/v1/missions/nope/execution").status_code == 404


def test_viewer_cannot_declare_transitions(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a")

    assert (
        api_client.post_json_as_viewer(
            "/v1/missions/m-1/execution-transitions", {"targetStatus": "CANCELLED"}
        ).status_code
        == 403
    )
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py -k api -v`
기대: 404

- [ ] **Step 3: 사람이 선언 가능한 상태 표를 만든다**

```python
#: SSOT — 사람이 직접 선언할 수 있는 실행 상태와 그에 필요한 권한.
#: 표에 **없는 상태는 누구도 선언할 수 없다**(403). ``processing_jobs`` 의
#: ``_TRANSITION_PERMISSION`` 과 같은 관용구다 — "정의되지 않은 전이를 할 권한"은
#: 누구에게도 없다.
#:
#: ACTIVATED 가 없는 이유: Edge 의 서명 activation receipt 가 만드는 사실이다.
#: COMPLETED·ENDED_INCOMPLETE 가 없는 이유: CoverageReport 접수가 만드는 사실이고
#: (INV-010), 사람이 찍을 수 있으면 그 상태는 근거가 아니라 주장이 된다.
_HUMAN_DECLARABLE: dict[MissionExecutionStatus, Permission] = {
    MissionExecutionStatus.DISPATCHED: Permission.MISSIONS_ISSUE,
    MissionExecutionStatus.CANCELLED: Permission.MISSIONS_ISSUE,
}
```

- [ ] **Step 4: 라우터를 만든다**

```python
def build_mission_execution_router(store: MissionExecutionStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post("/{mission_id}/execution-transitions", response_model=MissionExecutionView)
    def declare_execution_transition(
        mission_id: str,
        request: MissionExecutionTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_principal()),  # noqa: B008
    ) -> MissionExecutionView:
        required = _HUMAN_DECLARABLE.get(request.target_status)
        if required is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{request.target_status.value} 는 사람이 선언할 수 없다 — "
                    "장비 보고·커버리지 접수가 만드는 사실이다"
                ),
            )
        if required not in principal_permissions(principal):
            raise HTTPException(
                status_code=403, detail=f"{request.target_status.value} 선언 권한이 없다"
            )
        result = store.transition(
            mission_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = MISSION_EXECUTION_HTTP_STATUS[result.verdict]
        return _to_view(mission_id, store, detail=result.detail)

    @router.get("/{mission_id}/execution", response_model=MissionExecutionView)
    def get_execution(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> MissionExecutionView:
        if not store.mission_exists(mission_id):
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        return _to_view(mission_id, store, detail=None)

    return router
```

`MISSION_NOT_FOUND_DETAIL` 는 `ksi_core.mission_records` 가 이미 public 으로 노출한다 — 새 문구를 만들지 않는다(레코드 부재를 두 라우터가 다른 말로 알리면 사용자 혼란).

- [ ] **Step 5: 배선과 문서**

`create_app` 에서 `mission_execution_store is not None` 일 때 라우터를 장착하고, openapi 에 두 경로를 추가한다(`security` 필수).

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py tests/contract/test_api_contract_sync.py -q
```

- [ ] **Step 7: 커밋**

```bash
git add services/core/src/ksi_core/mission_execution.py services/core/src/ksi_core/app.py contracts/api/openapi-core.yaml tests/contract/test_mission_execution.py
git commit -m "feat(core): expose mission execution status and operator declarations

사람은 DISPATCHED·CANCELLED 만 선언할 수 있다. ACTIVATED·COMPLETED 는 장비 보고와
커버리지 접수가 만드는 사실이라 표에 없고, 표에 없는 상태는 누구도 선언할 수 없다."
```

---

## Task 9: 실행 상태 자동 결선 (dispatch · activation · coverage)

**Files:**
- Modify: `services/core/src/ksi_core/edge_dispatch.py`, `services/core/src/ksi_core/coverage_reports.py`
- Modify: `services/core/src/ksi_core/app.py`
- Test: `tests/contract/test_mission_execution.py`

**Interfaces:**
- Consumes: Task 7 의 `MissionExecutionStore.transition`
- Produces: 라우터 생성 함수 3곳의 선택 인자 `mission_execution_store: MissionExecutionStore | None = None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_edge_pull_marks_mission_dispatched(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")

    api_client.get_as_device("/v1/edge-sync/missions/next", device="dev-1")

    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "DISPATCHED"


def test_activation_receipt_marks_mission_activated(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")
    envelope = api_client.get_as_device("/v1/edge-sync/missions/next", device="dev-1").json()

    api_client.post_activation_receipt(envelope, device="dev-1")

    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "ACTIVATED"


def test_completed_coverage_report_marks_mission_completed(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")

    api_client.submit_coverage_report("m-1", completion_state="COMPLETED")

    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "COMPLETED"


def test_aborted_coverage_report_marks_mission_ended_incomplete(api_client) -> None:
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")

    api_client.submit_coverage_report("m-1", completion_state="ABORTED_SAFE")

    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "ENDED_INCOMPLETE"


def test_rejected_coverage_report_does_not_move_execution_status(api_client) -> None:
    """[핵심] 거부된 보고는 실행 상태를 옮기지 않는다.

    RECORDED 만 완료 판정 권위를 가진다(coverage_reports._reject docstring).
    거부된 주장이 실행 상태를 옮기면 화면에서 사실처럼 읽힌다.
    """
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")

    response = api_client.submit_coverage_report(
        "m-1", completion_state="COMPLETED", cells=[]  # 증거 0건 → NO_COVERAGE_EVIDENCE
    )

    assert response.status_code == 422
    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "ISSUED"


def test_execution_hook_failure_does_not_break_coverage_acceptance(
    api_client_with_sealed_execution_journal,
) -> None:
    """[핵심] 실행 상태 원장이 봉인돼도 커버리지 접수는 201 이다.

    완료 판정의 권위는 CoverageReport 원장이다(INV-010). 그 접수가 투영 원장의
    가용성에 좌우되면 권위가 뒤집힌다.
    """
    client = api_client_with_sealed_execution_journal
    client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")

    response = client.submit_coverage_report("m-1", completion_state="COMPLETED")

    assert response.status_code == 201


def test_cancelled_mission_is_not_resurrected_by_a_device_pull(api_client) -> None:
    """사람이 접은 임무를 장비 신호가 되살리지 않는다 — 전이표가 막고, 접수는 계속된다."""
    api_client.issue_mission("m-1", site_id="site-a", assigned_device_id="dev-1")
    api_client.post_json(
        "/v1/missions/m-1/execution-transitions", {"targetStatus": "CANCELLED"}
    )

    api_client.get_as_device("/v1/edge-sync/missions/next", device="dev-1")

    assert api_client.get_json("/v1/missions/m-1/execution")["status"] == "CANCELLED"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py -k "dispatch or activation or coverage or cancelled" -v`
기대: 실행 상태가 `ISSUED` 로 남아 실패

- [ ] **Step 3: 커버리지 훅을 만든다**

`coverage_reports.py` 의 `build_coverage_reports_router` 에 선택 인자를 추가하고, 접수 라우트에서 `RECORDED` 직후:

```python
        if (
            mission_execution_store is not None
            and result.verdict is CoverageReportVerdict.RECORDED
            and result.report is not None
        ):
            # 완료 판정의 권위는 이 접수(원장)이고, 실행 상태는 그 투영이다 —
            # 투영 쓰기가 실패해도 접수 응답은 바뀌지 않는다(INV-010).
            mission_execution_store.transition(
                mission_id,
                (
                    MissionExecutionStatus.COMPLETED
                    if result.report.summary.completion_state is CompletionState.COMPLETED
                    else MissionExecutionStatus.ENDED_INCOMPLETE
                ),
                detail=f"coverageReport completionState={result.report.summary.completion_state.value}",
                actor="system:coverage-report",
                now=datetime.now(UTC),
            )
```

- [ ] **Step 4: dispatch·activation 훅을 만든다**

`edge_dispatch.py` 의 `build_edge_dispatch_router`(정확한 이름은 파일에서 확인)에 같은 선택 인자를 추가한다.

`next_mission` 라우트에서 envelope 을 돌려주기 직전:
```python
        if mission_execution_store is not None:
            mission_execution_store.transition(
                result.envelope["missionId"],
                MissionExecutionStatus.DISPATCHED,
                detail=f"edge pull dispatchId={result.envelope['dispatchId']}",
                actor=f"system:edge-dispatch:{edge.device_id}",
                now=datetime.now(UTC),
            )
```

`record_activation` 라우트에서 `ACTIVATED`/`ALREADY_ACTIVATED` 직후 같은 모양으로 `MissionExecutionStatus.ACTIVATED` 를 넘긴다.

세 훅 모두 반환값을 검사하지 않는다 — 실패는 metric 에 잡히고 원래 응답은 바뀌지 않는다. 이 "의도적으로 무시한다"를 각 호출부 주석에 명시한다.

- [ ] **Step 5: 배선한다**

`create_app` 에서 세 라우터 장착 지점에 `mission_execution_store` 를 넘긴다.

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_mission_execution.py tests/contract/test_coverage_reports.py tests/contract/test_edge_dispatch_api.py -q
```
기대: 전부 통과. 기존 커버리지·dispatch 테스트가 하나도 깨지지 않아야 한다 — 깨지면 훅이 응답을 바꾼 것이다.

- [ ] **Step 7: 커밋**

```bash
git add services/core/src/ksi_core/coverage_reports.py services/core/src/ksi_core/edge_dispatch.py services/core/src/ksi_core/app.py tests/contract/test_mission_execution.py
git commit -m "feat(core): wire dispatch, activation and coverage into mission execution status

세 신호가 실행 상태를 자동으로 옮긴다. 거부된 커버리지 보고는 옮기지 않고,
투영 원장이 봉인돼도 커버리지 접수는 201 을 유지한다(INV-010 권위 보존)."
```

---

## Task 10: 매핑 임무 배포 → 현장 매핑 시작 + 노후 스윕

**Files:**
- Modify: `services/core/src/ksi_core/spatial_model.py`, `services/core/src/ksi_core/mission_execution.py`
- Modify: `packages/domain/src/ksi_domain/mission_gating.py`
- Test: `tests/contract/test_spatial_model.py`

**Interfaces:**
- Consumes: Task 5 의 `SpatialModelLifecycle`, Task 6 의 `MissionExecutionStatus`
- Produces:
  - `ksi_domain.mission_gating.MAPPING_FROM_SCRATCH_MISSION_TYPES: frozenset[MissionType]` (기존 `_MAPPING_FROM_SCRATCH` 와 대칭되는 임무타입 쪽 집합, public 승격)
  - `SpatialModelLifecycle.advance_for_mission_dispatched(site_id, mission_type, *, mission_id, now) -> SiteAdvanceOutcome`
  - `SpatialModelLifecycle.sweep_staleness(site_id, *, now) -> SiteAdvanceOutcome`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_mapping_mission_dispatch_starts_baseline_mapping(lifecycle, site_store) -> None:
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.BASELINE_MAPPING, mission_id="m-1", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.BASELINE_MAPPING


def test_remap_required_also_starts_baseline_mapping(lifecycle, site_store) -> None:
    _advance_site(site_store, "site-a", SiteStatus.REMAP_REQUIRED)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.SURVEY_GRADE_MAPPING, mission_id="m-2", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.BASELINE_MAPPING


def test_patrol_mission_dispatch_does_not_move_the_site(lifecycle, site_store) -> None:
    """[핵심] 순찰 임무 배포는 현장을 매핑 시작으로 되돌리지 않는다."""
    _advance_site(site_store, "site-a", SiteStatus.PATROL_READY)

    outcome = lifecycle.advance_for_mission_dispatched(
        "site-a", MissionType.AUTONOMOUS_PATROL, mission_id="m-3", now=_NOW
    )

    assert outcome is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_staleness_sweep_moves_patrol_ready_to_model_stale(lifecycle, site_store, aged_epoch) -> None:
    _advance_site(site_store, "site-a", SiteStatus.PATROL_READY)
    site_store.set_model_age_policy("site-a", max_age_days=30, actor="op", now=_NOW)

    outcome = lifecycle.sweep_staleness("site-a", now=_NOW)

    assert outcome is SiteAdvanceOutcome.ADVANCED
    assert site_store.get("site-a").status is SiteStatus.MODEL_STALE


def test_staleness_sweep_does_nothing_without_a_declared_policy(
    lifecycle, site_store, aged_epoch
) -> None:
    """[핵심] 노후 기준을 선언하지 않은 현장을 서버가 임의로 낡았다고 하지 않는다."""
    _advance_site(site_store, "site-a", SiteStatus.PATROL_READY)

    outcome = lifecycle.sweep_staleness("site-a", now=_NOW)

    assert outcome is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.PATROL_READY


def test_staleness_sweep_does_not_touch_unmapped_sites(lifecycle, site_store) -> None:
    site_store.register("site-a", "A", _FRAME, actor="op-1", now=_NOW)
    site_store.set_model_age_policy("site-a", max_age_days=1, actor="op", now=_NOW)

    assert lifecycle.sweep_staleness("site-a", now=_NOW) is SiteAdvanceOutcome.NO_RULE
    assert site_store.get("site-a").status is SiteStatus.UNMAPPED
```

`aged_epoch` fixture 는 그 현장에 45일 된 `authority=source` 성공 작업 1건을 넣는다.

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py -k "dispatch or staleness" -v`
기대: `AttributeError`

- [ ] **Step 3: 임무타입 집합을 public 으로 올린다**

`packages/domain/src/ksi_domain/mission_gating.py` 에:

```python
#: "지도를 처음부터 만든다" 계열 임무타입 — ``_MAPPING_FROM_SCRATCH`` 현장 상태
#: 집합의 짝이다. 이 임무의 배포가 현장을 ``BASELINE_MAPPING`` 으로 밀어야 하는지
#: 판정하는 곳(``ksi_core.spatial_model``)이 이 집합을 읽는다 — 그 판정이
#: 임무타입 목록을 자기 파일에 복사하면 새 매핑 계열 타입이 추가될 때 한쪽만 갱신된다.
MAPPING_FROM_SCRATCH_MISSION_TYPES: frozenset[MissionType] = frozenset(
    mission_type
    for mission_type, statuses in MISSION_TYPE_ALLOWED_SITE_STATUSES.items()
    if _ST.UNMAPPED in statuses and mission_type is not _MT.INCIDENT_SURVEY
)
```

`INCIDENT_SURVEY` 를 빼는 이유를 주석으로 남긴다: 사고조사는 `UNMAPPED` 에서도 허용되지만 지도를 만드는 임무가 아니다(그 허용은 FINAL_DECISION_LEDGER DEC-013 의 보수적 추론이며 대표자 재검토 대상, INV-052 참조).

`__all__` 에 추가한다.

- [ ] **Step 4: 두 메서드를 만든다**

`SpatialModelLifecycle` 에:

```python
    def advance_for_mission_dispatched(
        self,
        site_id: str,
        mission_type: MissionType,
        *,
        mission_id: str,
        now: datetime,
    ) -> SiteAdvanceOutcome:
        """매핑 계열 임무가 기체로 넘어갔다 = 그 현장의 매핑이 시작됐다.

        발급이 아니라 **배포**가 기준이다 — 발급만 하고 안 날린 임무가 현장 상태를
        옮기면, 계획 단계의 문서가 관측 사실을 참칭한다.
        """
        if mission_type not in MAPPING_FROM_SCRATCH_MISSION_TYPES:
            return self._record(SiteAdvanceOutcome.NO_RULE, target=None)
        site = self._site_store.get(site_id)
        if site is None:
            return self._record(
                SiteAdvanceOutcome.UNKNOWN_SITE, target=SiteStatus.BASELINE_MAPPING
            )
        if site.status not in (SiteStatus.UNMAPPED, SiteStatus.REMAP_REQUIRED):
            return self._record(
                (
                    SiteAdvanceOutcome.ALREADY_PAST
                    if _is_at_or_past(site.status, SiteStatus.BASELINE_MAPPING)
                    else SiteAdvanceOutcome.ILLEGAL_FROM_CURRENT
                ),
                target=SiteStatus.BASELINE_MAPPING,
            )
        return self._transition(
            site_id,
            SiteStatus.BASELINE_MAPPING,
            evidence=f"mission={mission_id} type={mission_type.value} dispatched",
            reason="매핑 계열 임무 배포에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )

    def sweep_staleness(self, site_id: str, *, now: datetime) -> SiteAdvanceOutcome:
        """모델이 현장이 선언한 나이 기준을 넘었으면 ``MODEL_STALE`` 로 옮긴다.

        선언이 없으면(``AGE_POLICY_UNDECLARED``) 아무것도 하지 않는다 — 서버가
        기준을 지어내 자율운영을 끊지 않는다.

        ``PATROL_READY``·``PATROL_ACTIVE`` 에서만 동작한다: 그 둘이 "이 모델을
        믿고 자율로 돈다"를 뜻하는 상태이고, 나머지 상태에서는 노후가 이미
        진행 중인 작업으로 표현돼 있다.
        """
        site = self._site_store.get(site_id)
        if site is None:
            return self._record(SiteAdvanceOutcome.UNKNOWN_SITE, target=SiteStatus.MODEL_STALE)
        if site.status not in (SiteStatus.PATROL_READY, SiteStatus.PATROL_ACTIVE):
            return self._record(SiteAdvanceOutcome.NO_RULE, target=None)
        status = evaluate_spatial_model(
            self._processing_job_store.list_for_site(site_id),
            now=now,
            max_age_days=site.model_max_age_days,
        )
        if status.state is not SpatialModelState.STALE:
            return self._record(SiteAdvanceOutcome.NO_RULE, target=None)
        return self._transition(
            site_id,
            SiteStatus.MODEL_STALE,
            evidence=(
                f"epoch={status.epoch_job_id} age={status.age_days:.1f}d "
                f"maxAge={status.max_age_days}d"
            ),
            reason="공간모델 노후 판정에 따른 자동 전진(ADR-KSI-019 G1)",
            now=now,
        )
```

두 메서드 모두 Task 5 가 만든 `_transition` 헬퍼와 `_processing_job_store` 를 그대로 쓴다 — 생성자·헬퍼를 여기서 다시 고치지 않는다.

- [ ] **Step 5: 배포 훅에서 부른다**

Task 9 의 `edge_dispatch` 훅과 Task 8 의 운영자 `DISPATCHED` 선언 라우트 **양쪽**에서, 실행 상태 전이가 `TRANSITIONED` 이고 목표가 `DISPATCHED` 일 때 `advance_for_mission_dispatched` 를 부른다. 임무타입·siteId 는 `MissionStore.get(mission_id)` 에서 읽는다.

노후 스윕은 이 계획에서 **스케줄러를 만들지 않는다** — `GET /v1/sites/{site_id}/spatial-model` 호출 시 자동 실행하지도 않는다(조회가 원장을 바꾸면 조회 시점에 따라 상태가 달라진다). 대신 명시적 표면 하나를 둔다:

```python
    @router.post("/{site_id}/spatial-model/staleness-sweep", response_model=SpatialModelView)
    def sweep_site_staleness(...):
        """노후 판정을 지금 적용한다 — 운영자·배치 잡이 부르는 명시적 표면."""
```
권한은 `SITES_WRITE`. openapi 에 추가한다. 주기 실행은 배포 운영의 몫으로 남기고, 그 사실을 라우트 docstring 에 적는다.

- [ ] **Step 6: 통과를 확인한다**

Run:
```bash
ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py tests/contract/test_mission_execution.py tests/contract/test_mission_site_status_gate.py tests/contract/test_api_contract_sync.py -q
```

- [ ] **Step 7: 커밋**

```bash
git add packages/domain/src/ksi_domain/mission_gating.py services/core/src/ksi_core/spatial_model.py services/core/src/ksi_core/mission_execution.py contracts/api/openapi-core.yaml tests/contract/test_spatial_model.py
git commit -m "feat(core): start baseline mapping on dispatch and sweep model staleness

발급이 아니라 배포가 매핑 시작의 기준이다. 노후 스윕은 현장이 기준을 선언한
경우에만 동작하고, 조회가 아니라 명시적 표면이 부른다."
```

---

## Task 11: 촬영 자동 ingest 트리거

**중요 — ADR-KSI-019 G4 의 서술을 좁힌다.** `tools/upload_source_bundle.py` (533줄, `tests/contract/test_upload_source_bundle.py` 로 검증됨)가 이미 등록·업로드·봉인·재구성 발행을 브라우저 없이 수행한다. 남은 구멍은 **그 도구를 부를 주체**다: 지금은 사람이 임무 id 를 손으로 넣고 명령을 친다. 이 Task 는 새 업로더를 만들지 않고 **트리거**만 만든다.

**Files:**
- Create: `tools/ingest_watch.py`
- Test: `tests/contract/test_ingest_watch.py`

**Interfaces:**
- Consumes: `tools/upload_source_bundle.py` 의 `run_sync`·`SyncOutcome` (Step 1 에서 정확한 시그니처 확인)
- Produces:
  - `def discover_pending(root: Path) -> list[PendingCapture]`
  - `@dataclass class PendingCapture` — `mission_id: str`, `directory: Path`
  - `def run_once(...) -> WatchReport`
  - `def main() -> int`

- [ ] **Step 1: 기존 업로더의 진입점을 확인한다**

Run: `sed -n '380,460p' tools/upload_source_bundle.py`
기대: `run_sync(...)` 의 정확한 매개변수와 반환형(`SyncOutcome`)이 보인다. 다음 스텝은 그 시그니처에 맞춘다. **재구현하지 않는다.**

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/contract/test_ingest_watch.py`:

```python
"""촬영 디렉터리 감시 → ingest 트리거 (ADR-KSI-019 G4).

이 파일이 검증하는 것은 업로드 자체가 아니다(그건 test_upload_source_bundle.py
소관) — **언제 트리거되고, 두 번 트리거되지 않고, 하나가 실패해도 나머지가
계속되는가**다.
"""


def test_discovers_mission_directories_by_name(tmp_path) -> None:
    """디렉터리 이름이 곧 임무 id 다 — 사람이 명령마다 id 를 타이핑하지 않는다."""
    (tmp_path / "m-alpha").mkdir()
    (tmp_path / "m-beta").mkdir()
    (tmp_path / "not-a-mission.txt").write_text("x")

    pending = discover_pending(tmp_path)

    assert {p.mission_id for p in pending} == {"m-alpha", "m-beta"}


def test_ignores_directories_without_images(tmp_path) -> None:
    """빈 디렉터리를 임무로 착각해 빈 번들을 봉인하지 않는다."""
    (tmp_path / "m-alpha").mkdir()
    (tmp_path / "m-beta" / "sub").mkdir(parents=True)
    (tmp_path / "m-beta" / "DJI_0001.JPG").write_bytes(b"x")

    assert [p.mission_id for p in discover_pending(tmp_path)] == ["m-beta"]


def test_ignores_directory_still_being_written(tmp_path, fake_clock) -> None:
    """[핵심] 복사가 진행 중인 디렉터리를 건드리지 않는다.

    SD카드 오프로드 중에 봉인하면 절반만 든 번들이 원본으로 굳는다. 마지막
    수정 시각이 정지 유예(quiet period)를 넘긴 디렉터리만 대상으로 삼는다.
    """
    directory = tmp_path / "m-alpha"
    directory.mkdir()
    (directory / "DJI_0001.JPG").write_bytes(b"x")

    assert discover_pending(tmp_path, quiet_seconds=60, now=fake_clock.just_now()) == []
    assert len(discover_pending(tmp_path, quiet_seconds=60, now=fake_clock.minutes_later(5))) == 1


def test_marks_done_and_does_not_retrigger(tmp_path, fake_uploader) -> None:
    """성공한 임무를 다시 올리지 않는다 — 서버 멱등성에 매번 기대지 않는다."""
    _make_capture(tmp_path, "m-alpha")

    first = run_once(tmp_path, uploader=fake_uploader, state_dir=tmp_path / ".state")
    second = run_once(tmp_path, uploader=fake_uploader, state_dir=tmp_path / ".state")

    assert first.succeeded == ["m-alpha"]
    assert second.succeeded == []
    assert fake_uploader.call_count == 1


def test_one_failure_does_not_stop_the_others(tmp_path, failing_uploader) -> None:
    _make_capture(tmp_path, "m-bad")
    _make_capture(tmp_path, "m-good")

    report = run_once(tmp_path, uploader=failing_uploader, state_dir=tmp_path / ".state")

    assert report.succeeded == ["m-good"]
    assert [f.mission_id for f in report.failed] == ["m-bad"]


def test_failed_mission_is_retried_next_run(tmp_path, flaky_uploader) -> None:
    """실패는 완료로 기록하지 않는다 — 다음 실행에서 다시 시도한다."""
    _make_capture(tmp_path, "m-alpha")

    run_once(tmp_path, uploader=flaky_uploader, state_dir=tmp_path / ".state")
    report = run_once(tmp_path, uploader=flaky_uploader, state_dir=tmp_path / ".state")

    assert report.succeeded == ["m-alpha"]


def test_report_lists_skipped_reasons(tmp_path, fake_uploader) -> None:
    """[핵심] 건너뛴 것을 조용히 지우지 않는다 — 무엇을 왜 안 했는지 보고한다."""
    (tmp_path / "m-empty").mkdir()
    _make_capture(tmp_path, "m-alpha")

    report = run_once(tmp_path, uploader=fake_uploader, state_dir=tmp_path / ".state")

    assert [(s.mission_id, s.reason) for s in report.skipped] == [("m-empty", "NO_IMAGES")]
```

- [ ] **Step 3: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_ingest_watch.py -v`
기대: `ModuleNotFoundError` 또는 `ImportError`

- [ ] **Step 4: 감시 러너를 만든다**

`tools/ingest_watch.py` — docstring 골자:

```python
#!/usr/bin/env python3
"""촬영 디렉터리를 훑어 임무별 ingest 를 한 번씩 트리거한다 (ADR-KSI-019 G4).

## 이 도구가 닫는 구멍 — 그리고 닫지 않는 것

``upload_source_bundle.py`` 가 이미 "디렉터리 하나를 서버까지 보내는" 일을
사람 손 없이 한다(ADR-KSI-018 P1). 남은 사람 손은 **그 명령을 임무마다 치는
것**이다. 이 도구가 그 한 겹을 걷어낸다 — 업로드 로직은 한 줄도 다시 쓰지 않고
``run_sync`` 를 그대로 부른다.

닫지 않는 것은 그 앞이다: 기체에서 지상으로 사진을 내리는 경로. ADR-KSI-013
D1/D2 가 확정한 대로 실기 검증 전까지 SD카드 회수·수동 오프로드가 정상 경로이며,
이 도구의 입력은 그 절차가 채운 디렉터리다.

## 임무 id 는 디렉터리 이름이다

``<root>/<missionId>/`` 규약 하나만 둔다. 파일 EXIF 에서 임무를 추론하지 않는다 —
추론이 틀리면 다른 임무의 원본이 섞이고, 그건 계보(``jobId = f(missionId, seq)``)가
조용히 거짓이 되는 사고다. 규약이 틀리면 그 디렉터리는 서버가 ``UNKNOWN_MISSION``
으로 거부하고, 이 도구는 그 실패를 보고에 남긴다.

## 복사 중인 디렉터리를 건드리지 않는다

디렉터리 안 최신 수정 시각이 ``--quiet-seconds`` 를 넘겨야 대상이 된다. 오프로드
중에 봉인하면 절반만 든 번들이 원본으로 굳고, 봉인은 되돌릴 수 없다.

## 완료 표시는 속도 장치이지 정합성 장치가 아니다

``--state-dir`` 에 성공한 임무 id 를 남겨 다시 올리지 않는다. 이 파일을 잃어도
결과는 같다(서버가 멱등하다) — 다시 전량 확인할 뿐이다. **실패는 기록하지 않는다**:
실패를 완료로 남기면 재시도 경로가 사라진다.

## 한 번 실행이 기본이다

기본 동작은 1회 스캔 후 종료다(``--once``, 기본값). systemd timer·cron 이 주기를
소유하는 편이 이 프로세스가 데몬으로 사는 것보다 운영에서 관측 가능하다.
``--interval-seconds`` 를 주면 그 간격으로 반복한다.
"""
```

핵심 구현:

```python
_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".JPG", ".JPEG", ".dng", ".DNG"})


@dataclass(frozen=True, slots=True)
class PendingCapture:
    mission_id: str
    directory: Path


@dataclass(frozen=True, slots=True)
class SkippedCapture:
    mission_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class FailedCapture:
    mission_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class WatchReport:
    succeeded: list[str]
    failed: list[FailedCapture]
    skipped: list[SkippedCapture]


def discover_pending(
    root: Path, *, quiet_seconds: float = 0.0, now: float | None = None
) -> list[PendingCapture]:
    """``<root>/<missionId>/`` 중 사진이 있고 정지 유예를 넘긴 디렉터리."""
    ...


def run_once(
    root: Path,
    *,
    uploader: Callable[[str, Path], None],
    state_dir: Path,
    quiet_seconds: float = 0.0,
    now: float | None = None,
) -> WatchReport:
    """대상 임무를 하나씩 처리한다 — 하나가 실패해도 나머지를 계속한다."""
    ...
```

`main()` 은 `argparse` 로 `--root`·`--core-url`·`--token`·`--state-dir`·`--quiet-seconds`·`--interval-seconds` 를 받고, `uploader` 를 `upload_source_bundle.run_sync` 를 `--seal --start-reconstruction` 상당으로 감싼 클로저로 만든다. 종료 코드는 실패가 하나라도 있으면 1.

`tools/` 는 `sys.path` 조작 없이 서로를 import 할 수 있어야 한다 — `upload_source_bundle.py` 가 `from _digest import sha256_file` 로 형제 모듈을 부르는 관용구를 그대로 따른다.

- [ ] **Step 5: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_ingest_watch.py -v`
기대: 7 passed

- [ ] **Step 6: 실제로 한 번 돌려본다**

Run:
```bash
uv run python tools/ingest_watch.py --help
```
기대: 사용법이 나오고 예외가 없다. 이 스텝은 "테스트는 통과하는데 CLI 는 import 에서 죽는" 경우를 잡는다.

- [ ] **Step 7: 커밋**

```bash
git add tools/ingest_watch.py tests/contract/test_ingest_watch.py
git commit -m "feat(tools): trigger source-media ingest per mission directory

업로드 로직은 upload_source_bundle 을 그대로 쓴다 — 이 도구는 트리거만 만든다.
복사 중인 디렉터리는 정지 유예로 거르고, 실패는 완료로 기록하지 않아 재시도된다."
```

---

## Task 12: 대시보드 반영

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/types.ts`, `sites.ts`, `missions.ts`, `labels.ts`
- Modify: `apps/dashboard/src/app/sites/[siteId]/page.tsx`
- Modify: `apps/dashboard/src/components/missions/MissionLifecycle.tsx`
- Test: `apps/dashboard/test/mission-lifecycle.test.ts`, `apps/dashboard/test/spatial-model.test.ts` (신규)

**Interfaces:**
- Consumes: Task 4 의 `GET /v1/sites/{siteId}/spatial-model`, Task 8 의 `GET /v1/missions/{missionId}/execution`
- Produces:
  - `export const SPATIAL_MODEL_STATES = [...] as const`
  - `export const MISSION_EXECUTION_STATUSES = [...] as const`
  - `getSpatialModel(siteId)` · `getMissionExecution(missionId)`
  - `deriveMissionStages` 가 서버 실행 상태를 받는다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`apps/dashboard/test/spatial-model.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { spatialModelSummary } from "@/lib/core-api/labels";

describe("공간모델 상태 표시의 정직성", () => {
  it("노후 기준 미선언을 '최신'으로 표시하지 않는다", () => {
    const summary = spatialModelSummary({
      state: "AGE_POLICY_UNDECLARED",
      ageDays: 400,
      maxAgeDays: null,
      siteStatusMatchesModel: true,
    });

    expect(summary.tone).toBe("waiting");
    expect(summary.label).not.toContain("최신");
    expect(summary.detail).toContain("기준");
  });

  it("현장 상태와 모델 유무가 어긋나면 확인 필요로 표시한다", () => {
    const summary = spatialModelSummary({
      state: "ABSENT",
      ageDays: null,
      maxAgeDays: 30,
      siteStatusMatchesModel: false,
    });

    expect(summary.tone).toBe("warning");
  });

  it("모델이 없는 현장을 오류로 표시하지 않는다", () => {
    const summary = spatialModelSummary({
      state: "ABSENT",
      ageDays: null,
      maxAgeDays: 30,
      siteStatusMatchesModel: true,
    });

    expect(summary.tone).toBe("waiting");
  });
});
```

`apps/dashboard/test/mission-lifecycle.test.ts` 에 추가:

```typescript
it("서버가 실행 상태를 주면 하위 산출물로 역추정하지 않는다", () => {
  const stages = deriveMissionStages({
    execution: { status: "DISPATCHED", updatedAt: "2026-08-15T00:00:00Z" },
    coverage: { kind: "not-reported" },
    bundle: null,
    latestJob: null,
    hasComparisonReport: false,
  });

  expect(stages[1]).toMatchObject({ title: "실행", detail: "기체로 전달됨" });
});

it("실행 상태가 없으면 예전처럼 아무것도 단정하지 않는다", () => {
  const stages = deriveMissionStages({
    execution: null,
    coverage: { kind: "not-reported" },
    bundle: null,
    latestJob: null,
    hasComparisonReport: false,
  });

  expect(stages.slice(1).map((s) => s.tone)).not.toContain("done");
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd apps/dashboard && npm run test`
기대: `spatialModelSummary` 미정의 · `deriveMissionStages` 시그니처 불일치로 실패

- [ ] **Step 3: 타입 미러를 추가한다**

`types.ts` 에:

```typescript
export const SPATIAL_MODEL_STATES = [
  "ABSENT",
  "FRESH",
  "STALE",
  "AGE_POLICY_UNDECLARED",
] as const;
export type SpatialModelState = (typeof SPATIAL_MODEL_STATES)[number];

export const MISSION_EXECUTION_STATUSES = [
  "ISSUED",
  "DISPATCHED",
  "ACTIVATED",
  "COMPLETED",
  "ENDED_INCOMPLETE",
  "CANCELLED",
] as const;
export type MissionExecutionStatus = (typeof MISSION_EXECUTION_STATUSES)[number];

export interface SpatialModelView { /* 서버 응답과 1:1 */ }
export interface MissionExecutionView { /* 서버 응답과 1:1 */ }
```

- [ ] **Step 4: Python SSOT ↔ TS 미러 대조 테스트를 확장한다**

`tests/contract/test_domain_enums_dashboard_sync.py` 의 `_ENUM_ARRAY_MAP` 에 두 줄을 추가한다:

```python
    ("MISSION_EXECUTION_STATUSES", MissionExecutionStatus),
```

`SPATIAL_MODEL_STATES` 는 `ksi_domain` 이 아니라 `ksi_core.spatial_model` 소유라 이 파일의 import 원칙(도메인 패키지만)과 어긋난다. 같은 파일 안에 **별도 테스트**로 둔다:

```python
def test_spatial_model_states_mirror_matches_core_ssot() -> None:
    """``SpatialModelState`` 는 도메인 패키지가 아니라 Core 소유라 별도로 대조한다."""
    from ksi_core.spatial_model import SpatialModelState

    ts_arrays = _parse_const_arrays(_DASHBOARD_TYPES.read_text(encoding="utf-8"))
    assert ts_arrays.get("SPATIAL_MODEL_STATES") == {m.value for m in SpatialModelState}
```

- [ ] **Step 5: 라벨과 조회 함수를 만든다**

`labels.ts` 에 `spatialModelSummary` 와 `MISSION_EXECUTION_STATUS_LABEL` 을 추가한다. 라벨 문구 원칙 — **한국어 일상어로 쓰고 내부 상태값을 그대로 노출하지 않는다**:

| 상태 | 라벨 | 설명 |
|---|---|---|
| `ABSENT` | 공간모델 없음 | 아직 이 현장의 3차원 모델이 만들어지지 않았습니다 |
| `FRESH` | 최신 | 마지막 재구성이 이 현장이 정한 기준 안입니다 |
| `STALE` | 오래됨 | 마지막 재구성이 이 현장이 정한 기준을 넘겼습니다 |
| `AGE_POLICY_UNDECLARED` | 판정 안 함 | 며칠이면 오래된 것으로 볼지 기준이 정해지지 않았습니다 |
| `ISSUED` | 발급됨 | 계약과 비행파일이 만들어졌습니다 |
| `DISPATCHED` | 기체로 전달됨 | — |
| `ACTIVATED` | 기체가 확인함 | — |
| `COMPLETED` | 완료 보고됨 | — |
| `ENDED_INCOMPLETE` | 완료되지 않고 끝남 | — |
| `CANCELLED` | 취소됨 | — |

`sites.ts` 에 `getSpatialModel`, `missions.ts` 에 `getMissionExecution` 을 기존 함수 관용구대로 추가한다.

- [ ] **Step 6: 화면에 붙인다**

`sites/[siteId]/page.tsx` 의 현장 상태 배지 옆에 공간모델 요약 한 줄을 추가하고, `siteStatusMatchesModel === false` 면 확인 필요 배지를 함께 낸다. `MissionLifecycle` 의 두 번째 단계를 서버 실행 상태로 교체하되, `execution === null` 이면 기존 동작(아무것도 단정하지 않음)을 유지한다.

- [ ] **Step 7: 통과를 확인한다**

Run:
```bash
cd apps/dashboard && npm run test && npm run lint && npm run build
cd - && ulimit -n 8192 && uv run pytest tests/contract/test_domain_enums_dashboard_sync.py -v
```
기대: 전부 통과

- [ ] **Step 8: 커밋**

```bash
git add apps/dashboard tests/contract/test_domain_enums_dashboard_sync.py
git commit -m "feat(dashboard): show spatial-model state and server-reported mission execution

노후 기준 미선언을 '최신'으로 표시하지 않는다. 임무 진행은 하위 산출물 역추정
대신 서버가 보고한 실행 상태를 쓰되, 서버가 모르면 예전처럼 단정하지 않는다."
```

---

## Task 13: AOL-1 소프트웨어 종단 1회

**Files:**
- Create: `tests/e2e/test_aol1_mapping_autonomy.py`
- Modify: `docs/architecture/ADR-KSI-019-autonomous-observation-loop.md` (§4 GAP 표 갱신)

**Interfaces:**
- Consumes: Task 1~12 전부
- Produces: 없음(종단 검증)

- [ ] **Step 1: 종단 테스트를 쓴다**

```python
"""AOL-1 매핑 자율 — 소프트웨어 종단 1회 (ADR-KSI-019 §5 5번).

경계 → 매핑 임무 → 배포 → 실행 → 촬영 회수 → 재구성 → 공간모델 등록까지
**사람이 현장 상태를 손으로 옮기는 단계 없이** 한 번 통과하는지 본다.

실기는 이 테스트의 범위 밖이다 — 커버리지 보고와 재구성 워커는 계약대로 행동하는
대역이 대신한다. 그래서 이 테스트가 증명하는 것은 "실제로 날 수 있다"가 아니라
"서버 쪽 결선에 끊긴 곳이 없다"이고, 그 구분을 파일 이름과 이 docstring 이 진다.
"""


def test_mapping_loop_completes_without_manual_site_transitions(aol1_client) -> None:
    c = aol1_client

    # 1. 현장 등록 + 경계 저장 + 노후 기준 선언
    c.register_site("site-a")
    c.set_aoi("site-a", _SQUARE_AOI)
    c.set_model_age_policy("site-a", max_age_days=30)
    assert c.site_status("site-a") == "UNMAPPED"
    assert c.spatial_model("site-a")["state"] == "ABSENT"

    # 2. 매핑 임무 짝 발급 — 공간모델 없이 성립해야 한다(ADR-KSI-019 D3)
    plan = c.issue_mapping_pair("site-a", mission_id="m-1", device_id="dev-1")
    assert plan["waypointCount"] > 0
    assert plan["kmzSha256"]

    # 3. 기체로 전달 — 여기서 현장이 스스로 매핑 시작으로 간다
    c.pull_mission_as_device("dev-1")
    assert c.mission_execution("m-1")["status"] == "DISPATCHED"
    assert c.site_status("site-a") == "BASELINE_MAPPING"

    # 4. 기체가 계약을 활성화
    c.post_activation_receipt("dev-1")
    assert c.mission_execution("m-1")["status"] == "ACTIVATED"

    # 5. 비행 후 커버리지 보고 — 완료 판정의 권위(INV-010)
    c.submit_coverage_report("m-1", completion_state="COMPLETED")
    assert c.mission_execution("m-1")["status"] == "COMPLETED"

    # 6. 촬영 회수 — 감시 러너가 디렉터리를 발견해 등록·봉인·재구성 발행까지
    report = c.run_ingest_watch()
    assert report.succeeded == ["m-1"]
    # 재구성 작업 발급이 현장을 처리중으로 민다
    assert c.site_status("site-a") == "MODEL_PROCESSING"

    # 7. 워커가 원본 산출물을 등록하고 성공 보고
    job_id = c.latest_job_id("m-1")
    c.worker_run_and_succeed(job_id)

    # 8. 공간모델이 생겼고, 현장이 스스로 검증 단계로 갔다
    model = c.spatial_model("site-a")
    assert model["state"] == "FRESH"
    assert model["epochJobId"] == job_id
    assert model["sourceArtifactCount"] >= 1
    assert c.site_status("site-a") == "MODEL_VALIDATION"

    # 9. 그리고 거기서 멈춘다 — 자율운영은 사람의 승인이다
    assert c.site_status("site-a") != "PROVISIONAL_AUTONOMY"


def test_no_site_transition_in_this_loop_was_made_by_a_human(aol1_client) -> None:
    """[핵심] 이 루프에서 사람이 현장 상태를 옮긴 기록이 하나도 없어야 한다.

    G1 의 완료 판정이다 — 화면 버튼 한 번이라도 남아 있으면 "자동 판정"이 아니다.
    """
    _run_the_loop(aol1_client)

    actors = [entry["actor"] for entry in aol1_client.site_journal("site-a")
              if entry["kind"] == "site-transitioned"]

    assert actors, "전이가 하나도 없으면 이 테스트는 공허하다"
    assert all(a.startswith("system:") for a in actors), (
        f"사람이 옮긴 현장 전이가 남아 있다: {actors}"
    )


def test_stale_model_moves_a_patrol_ready_site_on_sweep(aol1_client) -> None:
    """모델이 기준을 넘기면 노후 스윕이 자율운영을 끊는다."""
    _run_the_loop(aol1_client)
    aol1_client.approve_autonomy("site-a")  # 사람의 승인 — MODEL_VALIDATION → … → PATROL_READY
    aol1_client.advance_clock(days=45)

    aol1_client.sweep_staleness("site-a")

    assert aol1_client.site_status("site-a") == "MODEL_STALE"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/e2e/test_aol1_mapping_autonomy.py -v`
기대: fixture 미정의로 ERROR

- [ ] **Step 3: fixture 를 만든다**

`aol1_client` 는 `assemble_app` 으로 조립한 실제 앱 + `TestClient` + 세 종류 principal(운영자 ADMIN, EDGE_DEVICE `dev-1`, PROCESSING_WORKER)을 들고, 위에서 부른 헬퍼 메서드를 얇게 감싼다. **HTTP 를 거친다** — store 를 직접 부르면 라우터에 건 훅이 검증에서 빠진다.

`run_ingest_watch` 는 `tools/ingest_watch.run_once` 를 부르되 `uploader` 를 `TestClient` 로 서버를 두드리는 클로저로 바꾼다(presigned URL 대신 테스트 스토리지에 직접 넣는 경로는 `test_upload_source_bundle.py` 가 이미 쓰는 관용구를 재사용).

`advance_clock` 은 실제 시계를 건드리지 않고, 45일 전 시각으로 작업의 `updated_at` 을 만들어 넣는 방식을 쓴다 — `evaluate_spatial_model` 이 순수 함수라 `now` 만 바꿔 부를 수 있게 설계된 이유가 여기서 쓰인다.

- [ ] **Step 4: 통과를 확인한다**

Run: `ulimit -n 8192 && uv run pytest tests/e2e/test_aol1_mapping_autonomy.py -v`
기대: 3 passed

- [ ] **Step 5: 전체 게이트를 돌린다**

Run:
```bash
ulimit -n 8192
uv run pytest -q
uv run ruff check .
uv run mypy
cd apps/dashboard && npm run test && npm run lint && npm run build
```
기대: 전부 통과. 실패가 있으면 **여기서 멈추고 고친다** — 이 스텝을 건너뛴 커밋은 완료 선언이 아니다.

- [ ] **Step 6: ADR 의 GAP 표를 실측으로 갱신한다**

`docs/architecture/ADR-KSI-019-autonomous-observation-loop.md` §4 에서:
- G1 · G2 행: 현재 상태를 이 계획이 닫은 내용으로 고치고, 남은 것(노후 스윕의 주기 실행 주체는 배포 운영 소관)을 명시한다.
- G4 행: 서술을 정정한다 — `tools/upload_source_bundle.py` 가 이미 있었고 남은 구멍은 트리거였다는 사실을 적는다. **원래 서술이 틀렸다는 것을 지우지 말고 정정으로 남긴다.**
- §5 의 1·2·3·5번에 완료 표시와 근거 테스트 경로를 적는다.
- 실기 미검증이라는 사실을 §4 상단에 한 줄로 남긴다: 이 계획의 완료 등급은 `Backend Ready` + `Product Ready`(대시보드 표시)이고 `HIL Proven` 이 아니다(ADR-KSI-018 완료 판정 규율).

- [ ] **Step 7: 커밋**

```bash
git add tests/e2e/test_aol1_mapping_autonomy.py docs/architecture/ADR-KSI-019-autonomous-observation-loop.md
git commit -m "test(e2e): complete the AOL-1 mapping autonomy loop in software

경계 → 매핑 임무 → 배포 → 실행 → 촬영 회수 → 재구성 → 공간모델 등록까지 사람이
현장 상태를 손으로 옮기는 단계 없이 통과한다. 실기 검증은 아니다 — 커버리지 보고와
재구성 워커는 계약대로 행동하는 대역이다.

ADR-KSI-019 §4 의 G4 서술을 실측으로 정정한다(업로더는 이미 있었고 구멍은 트리거였다)."
```

---

## 이 계획이 하지 않는 것 (명시)

- **G3 임무 → 기체 자동 배포**: DJI M4D 의 Pilot Cloud 지원 여부가 미확인이라(ADR-KSI-004) 설계할 근거가 없다. 이 계획은 그 대신 **운영자 수동 이관을 서버가 기록할 수 있게** 만든다(Task 8 의 `DISPATCHED` 선언) — 수동 경로를 공식 경로로 정직하게 다루는 것이지 자동화가 아니다.
- **노후 스윕의 주기 실행**: 표면만 만들고 스케줄러는 만들지 않는다. 주기는 배포 운영(systemd timer·cron)이 소유하는 편이 관측 가능하다.
- **촬영 시각 기준 나이 판정**: `registered_at` 은 재구성이 성공한 시각이지 세상을 관측한 시각이 아니다. 필드 이름이 그 한계를 말하게 두고, 촬영 시각으로 좁히는 것은 계획 2 이후로 남긴다.
- **`IN_FLIGHT` 상태**: 서버가 아는 사실이 아니라 만들지 않는다(INV-001).
- **AOL-3 지형 인지**: ADR-KSI-019 D2 가 순서를 고정했다.
