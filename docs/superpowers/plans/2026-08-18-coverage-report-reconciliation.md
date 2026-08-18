# 커버리지 보고 대사(Reconciliation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 칸(Cell) 1개 + 자기신고 비율로 임무 완료 판정을 우회할 수 있던 결함(재현 확인됨)을
닫는다 — 서버가 가진 정보만으로 거짓임이 확정되는 두 검사를 추가하고, 확정되지 않는
나머지 값에는 귀속(누가 신고했나)과 대사(계획과 얼마나 다른가) 정보를 상시 노출한다.

**Architecture:** 두 검사는 성격이 다르다. 검사 1(칸 수<2 이면서 비율이 0~1 사이)은
보고서 자신의 데이터만으로 판정되는 **자체 모순** 계열이라 `judge_report()` 안에
있고 재생(replay) 시에도 재검사된다. 검사 2(계획 커버 추정치 초과)는 다른 원장
(`MissionRecord`)의 값이 필요한 **임무 대조** 계열이라 `CoverageReportStore.record()`의
`SITE_MISMATCH`/`DEVICE_NOT_ASSIGNED`와 같은 자리에 있고 재생 시에는 재검사하지
않는다(그 두 게이트와 동일한 기존 원칙). 새 저장소·새 원장을 만들지 않는다 — 기존
`_reject()` 감사 경로를 그대로 탄다.

**Tech Stack:** Python 3.12(uv workspace), FastAPI, Pydantic v2, pytest / Next.js 16,
React 19, TypeScript, vitest

**Spec:** `docs/superpowers/specs/2026-08-18-coverage-report-reconciliation-design.md`
(자체 검토로 두 번 정정된 버전 — 특히 "화면" 절과 "닫지 못하는 것" 절을 반드시 함께
읽는다)

## Global Constraints

- **완료 주장에만 검사를 건다.** `completion_state`가 `COMPLETED`가 아닌 보고는 이
  계획이 추가하는 어떤 검사도 타지 않는다(기존 `judge_report` 구조 그대로 — "공백을
  정직하게 신고한 보고서를 거부하면 신고를 안 하게 만든다").
- **임의 상수를 지어내지 않는다.** 칸 크기·개수 가정, 근거 없는 임계값 금지 — 노후
  판정(`AGE_POLICY_UNDECLARED`)이 임의 기본값을 거부한 전례를 따른다.
- **계획값 숫자를 UI에 반복하지 않는다.** `apps/dashboard/src/app/missions/[missionId]/page.tsx:239`
  주석이 "비행 결과" 섹션을 "계획 커버리지" 필드와 절대 나란히 두지 않는다고 이미
  명시한다 — API 응답에는 숫자를 남기되(`plannedGeneralCoverageRatio`), 임무 상세
  UI 캡션은 "확인했는가/왜 못 했는가"만 말한다.
- **재비행/누적 판정 없음.** 하한·대사는 개별 보고 단위로만 본다. 중간(비완료) 보고는
  검사 대상이 아니다.
- **저장하지 않는다.** 대사 정보는 `site_status_matches_model`과 같은 이유로 매 호출
  재계산한다 — 저장하면 그 값과 원장이 갈라질 수 있다.
- **거부된 숫자는 조회 표면에 안 싣는다.** 기존 `RejectedCoverageReport`·
  `CoverageRejectionView` 관례 그대로 — 사유와 시각만.
- **정적 검사**: `uv run ruff check .` · `uv run mypy packages services tests tools`.
  대시보드는 `cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build`.
- **테스트 실행**: `ulimit -n 8192 && uv run pytest <path> -v`.
- **새 `/v1/*` 경로 없음** — 기존 엔드포인트 둘(`POST/GET .../coverage-report`,
  `GET .../coverage-report/rejections`)만 응답 모델을 확장한다. 계약 변경은
  `contracts/api/openapi-core.yaml`의 `CoverageReportView` 컴포넌트에 반영하고
  `tests/contract/test_api_contract_sync.py`가 통과하는지 반드시 확인한다(openapi
  컴포넌트·pydantic 모델·대시보드 `types.ts`의 필드 이름·타입이 셋 다 정확히 일치해야
  한다).
- **커밋**: 각 Task 끝에서 커밋한다. 커밋 직전에 그 Task의 테스트를 실제로 돌려
  통과를 확인한다.

---

## File Structure

**수정**

| 파일 | 무엇을 |
|---|---|
| `packages/event-contracts/src/ksi_event_contracts/coverage_report.py` | 검사 1(`has_impossible_fractional_ratio`) 추가 |
| `services/core/src/ksi_core/coverage_reports.py` | 새 verdict 2개, 검사 2, `CoverageReportView` 확장, `planned_general_ratio()` 조회 메서드 |
| `contracts/api/openapi-core.yaml` | `CoverageReportView` 컴포넌트 필드 3개 추가, POST 422 설명 갱신 |
| `apps/dashboard/src/lib/core-api/types.ts` | `CoverageReportView` 필드 3개 추가, `CoverageRejectionView`/`CoverageRejectionListView` 신설 |
| `apps/dashboard/src/lib/core-api/missions.ts` | `getCoverageRejections()` 클라이언트 함수 |
| `apps/dashboard/src/components/missions/CoverageReportSection.tsx` | 귀속 캡션 + 거부 이력 절 |
| `apps/dashboard/src/app/missions/[missionId]/page.tsx` | 거부 이력 조회 배선 |
| `apps/dashboard/src/app/field/field-stages.ts` | 현장 화면 거부 신호 표시 |
| `apps/dashboard/src/app/field/[missionId]/page.tsx` | 현장 화면 거부 조회 배선 |
| `docs/product/DOMAIN_INVARIANTS.md` | INV-010 항목에 새 검사 반영 |

**테스트**

| 파일 | 무엇을 |
|---|---|
| `tests/contract/test_coverage_reports.py` | 검사 1·2, 응답 확장, 재생 분리 |
| `apps/dashboard/test/coverage.test.ts` | (필요시) 신규 헬퍼 테스트 |
| `apps/dashboard/test/coverage-report-section.test.ts` | 귀속 캡션 상시 렌더 확인(신설) |

---

## Task 1: 검사 1 — 산술적으로 불가능한 비율(자체 모순 계열)

**닫는 결함:** 재현한 그 사례 — 칸 1개 + 비율 1.0/1.0/0.96 → 지금 `RECORDED`.

**왜 이 검사가 안전한가:** 칸 총수가 2개 미만이면 분수 k/d(d≤전체 칸 수)로 만들 수
있는 값은 0.0과 1.0뿐이다 — 카테고리별 칸 수를 몰라도 성립하는 순수 산술이고(서버는
그 분류를 갖고 있지 않다, INV-010), 카테고리 배정에 대한 어떤 가정도 필요 없다.

**Files:**
- Modify: `packages/event-contracts/src/ksi_event_contracts/coverage_report.py`
  (`CoverageReport` 클래스, `contradicts_full_coverage` 메서드 뒤 132행 부근)
- Modify: `services/core/src/ksi_core/coverage_reports.py`
  (`CoverageReportVerdict` 87-102행, `_STATUS` 105-118행, `judge_report` 155-163행 사이)
- Test: `tests/contract/test_coverage_reports.py`

**Interfaces:**
- Produces: `CoverageReport.has_impossible_fractional_ratio() -> bool`,
  `CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_coverage_reports.py`에 추가한다. 이 파일의 기존 헬퍼만 쓴다 —
`_report_payload`(94행), `store` 픽스처(158행), `_client`(167행), `_auth` 관례.
먼저 파일에서 `_auth` 헬퍼의 정확한 사용법을 확인하고(다른 테스트 함수를 참고),
같은 형태로 쓴다.

```python
def test_a_single_cell_cannot_support_a_fractional_ratio(store: CoverageReportStore) -> None:
    """[핵심] 재현한 그 결함 — 칸 1개 + 비율 0.96 은 산술적으로 불가능하다.

    관찰 칸이 1개뿐이면 그 카테고리의 분모가 몇이든 1 이하다 — 분수로 만들 수
    있는 값은 0.0과 1.0뿐이다. 카테고리별 칸 수를 몰라도(서버는 위험구역/자산/
    일반 분류를 갖고 있지 않다) 이 논증은 성립한다.
    """
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[{"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"}],
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "INSUFFICIENT_CELLS_FOR_RATIO"


def test_a_single_fully_observed_cell_is_not_flagged(store: CoverageReportStore) -> None:
    """칸 1개여도 비율이 정확히 1.0 이면 이 검사에 안 걸린다(정상 케이스 보존).

    이 사례는 waypoint_count=75·planned_coverage_ratio=1.0 인 기본 _mission_store
    픽스처를 그대로 쓰므로 검사 2(계획 초과)도 걸리지 않는다 — 순수하게 검사 1만
    분리해서 확인한다.
    """
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[{"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"}],
        ),
    )
    assert response.status_code == 201
    assert response.json()["verdict"] == "RECORDED"


def test_two_cells_with_a_fractional_ratio_is_not_flagged(store: CoverageReportStore) -> None:
    """칸이 2개면 이 검사가 안 걸린다 — 0.5 같은 값이 산술적으로 가능해진다."""
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201
```

> 실행자 주의: 세 테스트 모두 `general` 비율을 1.0으로 두거나(2·3번째) 칸을 2개로
> 늘려(3번째) 검사 2(계획 초과, Task 2에서 추가)를 우연히 안 건드리게 설계했다.
> 이 파일의 기본 `_mission_store`가 `planned_coverage_ratio=1.0`이므로 `general<=1.0`인
> 값은 검사 2를 절대 안 탄다 — Task 1 단독 테스트로 유효하다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v -k "single_cell_cannot_support or fully_observed_cell_is_not_flagged or two_cells_with_a_fractional"
```
기대: 첫 번째 FAIL(지금은 201/RECORDED가 나온다 — 이게 재현한 결함이다), 나머지 둘 PASS.

- [ ] **Step 3: 계약 레이어에 순수 메서드를 추가한다**

`packages/event-contracts/src/ksi_event_contracts/coverage_report.py`의
`contradicts_full_coverage` 메서드(161-174행) 뒤에 추가. 파일 상단(29-42행)에
이미 있는 임계 상수들 옆에 엡실론도 추가한다:

```python
# 26행 아래(MANDATORY_HAZARD_MIN 등 세 상수 뒤)에 추가:
# 부동소수 직렬화 잔차 허용치 — mission_plans.py 의 "+ 1e-9" 관례와 동일.
_RATIO_EPS = 1e-9
```

`CoverageReport` 클래스 안, `contradicts_full_coverage` 바로 뒤:

```python
    def has_impossible_fractional_ratio(self) -> bool:
        """칸 총수가 2개 미만인데 비율이 0과 1 사이(양 끝 제외)면 산술적으로
        불가능하다.

        분수 k/d(d ≤ 전체 칸 수)로 표현 가능한 값 중 d<2 일 때 만들 수 있는 건
        0.0과 1.0뿐이다 — **카테고리별 칸 수를 몰라도 성립하는 순수 산술**이다
        (서버는 위험구역/자산/일반 분류를 갖고 있지 않다, INV-010). 카테고리 배정을
        전제하는 더 정밀한 판정(칸 수 ≥ 2인 경우의 Farey 분수 도달 가능성)은
        연속값으로 계산된 실사용 비율에 대해 false positive 위험이 커 채택하지
        않는다 — 이 함수가 닫는 건 이 경계 사례 하나다.
        """
        if len(self.cells) >= 2:
            return False
        ratios = (
            self.summary.mandatory_hazard_ratio,
            self.summary.mandatory_asset_ratio,
            self.summary.accessible_general_ratio,
        )
        return any(_RATIO_EPS < r < 1.0 - _RATIO_EPS for r in ratios)
```

- [ ] **Step 4: `judge_report`에 새 판정을 추가한다**

`services/core/src/ksi_core/coverage_reports.py`의 `CoverageReportVerdict`(87-102행),
`SELF_CONTRADICTORY_SUMMARY` 다음에 추가:

```python
    SELF_CONTRADICTORY_SUMMARY = "SELF_CONTRADICTORY_SUMMARY"
    # 칸 총수<2 인데 비율이 0과 1 사이 — has_impossible_fractional_ratio() 참조.
    INSUFFICIENT_CELLS_FOR_RATIO = "INSUFFICIENT_CELLS_FOR_RATIO"
```

`_STATUS` 딕셔너리(105-118행), 같은 자리에:

```python
    CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY: 422,
    CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO: 422,
```

`judge_report`(132-181행) 안, `contradicts_full_coverage` 검사 블록(155-163행) 바로 뒤,
`meets_completion_thresholds` 검사 앞:

```python
    if report.has_impossible_fractional_ratio():
        summary = report.summary
        return (
            CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO,
            f"칸이 {len(report.cells)}개인데 위험구역 {summary.mandatory_hazard_ratio:.4f}·"
            f"자산 {summary.mandatory_asset_ratio:.4f}·일반영역 "
            f"{summary.accessible_general_ratio:.4f} 중 하나가 0과 1 사이다 — 칸이 2개 "
            "미만이면 0.0/1.0 외의 비율은 산술적으로 만들 수 없다",
        )
```

- [ ] **Step 5: 테스트를 다시 돌려 통과 확인**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v
```
기대: 신규 3건 PASS + 파일 전체(기존 테스트 포함) PASS. 재생 테스트
(`test_replay_restores_history` 계열이 있다면)도 함께 통과해야 한다 — 검사 1은
`judge_report` 안에 있어 자동으로 재생 시에도 적용된다.

- [ ] **Step 6: 정적 검사**

```bash
uv run ruff check . && uv run mypy packages services tests tools
```

- [ ] **Step 7: 리스크 원장에 등록·해소한다**

```bash
python3 ~/.claude/scripts/ksi-goals.py risk-add --id coverage-report-single-cell-fractional-ratio \
  --title "커버리지 보고 완료 판정이 칸 1개 + 자기신고 비율로 우회 가능" \
  --lens gaming --severity high \
  --note "관찰 칸 1개만 담고 비율을 1.0/1.0/0.96 으로 신고하면 judge_report() 가 RECORDED 를 냈다(contradicts_full_coverage 는 세 비율이 전부 1.0 일 때만 걸려 이 사례를 피해 간다). 2026-08-18 재현 확인."

python3 ~/.claude/scripts/ksi-goals.py risk-resolve --id coverage-report-single-cell-fractional-ratio \
  --evidence-ref "has_impossible_fractional_ratio() 추가 — 칸 총수<2 이면서 비율이 0과 1 사이면 422 INSUFFICIENT_CELLS_FOR_RATIO 로 거부. 회귀 테스트 tests/contract/test_coverage_reports.py::test_a_single_cell_cannot_support_a_fractional_ratio 로 고정, 실행 확인 PASS."
```

- [ ] **Step 8: 커밋**

```bash
git add packages/event-contracts/src/ksi_event_contracts/coverage_report.py \
  services/core/src/ksi_core/coverage_reports.py tests/contract/test_coverage_reports.py \
  .ksi/goals.json .ksi/ledger.jsonl
git commit -m "fix(core): 칸 총수<2 인데 비율이 0과 1 사이면 커버리지 완료 보고를 거부한다

칸 1개 + 비율 1.0/1.0/0.96 으로 완료 판정을 우회할 수 있었다(재현 확인).
분수 k/d(d≤전체 칸 수)로 표현 가능한 값 중 d<2 일 때 만들 수 있는 건 0.0과
1.0뿐이다 — 카테고리별 칸 수를 몰라도 성립하는 순수 산술이라 서버가 가진
정보만으로 거짓임이 확정되는 경우다(기존 contradicts_full_coverage 와 같은
지위). 재생 시에도 재검사된다(judge_report 안에 있으므로).

risk: coverage-report-single-cell-fractional-ratio"
```

---

## Task 2: 검사 2 — 계획 커버 추정치 초과(임무 대조 계열)

**닫는 것:** 발급 시점 lawnmower 경로 생성기가 계산한 `plannedCoverageRatio`(이상적
촬영 조건 가정 상한)를 실제 보고의 `accessibleGeneralRatio`가 초과하는 경우 —
계획된 경로만 날았다는 전제 하에 불가능하다.

**Files:**
- Modify: `services/core/src/ksi_core/coverage_reports.py`
  (`CoverageReportVerdict`, `_STATUS`, `CoverageReportStore.record()` 289-372행)
- Test: `tests/contract/test_coverage_reports.py`

**Interfaces:**
- Consumes: `MissionRecord.planned_coverage_ratio: float | None`
  (`services/core/src/ksi_core/mission_records.py:213`)
- Produces: `CoverageReportVerdict.EXCEEDS_PLANNED_COVERAGE`,
  `_exceeds_planned_coverage(report: CoverageReport, mission: MissionRecord) -> bool`

- [ ] **Step 1: 테스트 헬퍼를 확장한다 — 다른 계획값을 가진 미션을 만들 수 있게**

`tests/contract/test_coverage_reports.py`의 `_mission_store`(123-145행)에 파라미터를
추가한다. 기본값을 기존과 동일하게 유지해 다른 테스트를 깨지 않는다:

```python
def _mission_store(
    tmp_path: Path,
    *,
    site_id: str = _SITE_ID,
    assigned_device_id: str | None = None,
    journal_name: str = "missions.jsonl",
    planned_coverage_ratio: float | None = 1.0,
) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / journal_name))
    plan_request = {"route": {"altitudeM": 40.0}}
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=site_id,
                mission_type="BASELINE_MAPPING",
                artifact_kind="pair",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256="deadbeef",
                route_pattern="lawnmower",
                waypoint_count=75,
                planned_coverage_ratio=planned_coverage_ratio,
                issued_at=_NOW,
                issued_by="do-1",
                plan_request=plan_request,
                plan_request_digest=None,
                assigned_device_id=assigned_device_id,
            )
        ).value
        == "RECORDED"
    )
    return store
```
(원래 시그니처에 `planned_coverage_ratio: float | None = 1.0` 키워드 인자 하나만
추가하고 본문의 `planned_coverage_ratio=1.0` 리터럴을 그 인자로 바꾼 것이다.)

- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
def test_reported_general_ratio_cannot_exceed_the_planned_estimate(tmp_path: Path) -> None:
    """[핵심] 계획 커버 추정치(0.85)를 초과한 일반영역 관찰(0.96)은 불가능하다.

    plannedCoverageRatio 는 이상적 촬영 조건을 가정한 상한이다(mission_plans.py
    가 발급 시점에 이미 이 값을 accessibleGeneralCoverage 요구치와 대조한다).
    계획된 경로만 날았다는 전제 하에, 실제 관찰이 그 상한을 넘을 수 없다.
    """
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.85),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.96,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == "EXCEEDS_PLANNED_COVERAGE"


def test_reported_ratio_within_the_planned_estimate_is_recorded(tmp_path: Path) -> None:
    """계획값 이하의 신고는 이 검사에 안 걸린다(정상 케이스 보존)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.85),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.80,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


def test_missing_planned_ratio_skips_the_check_instead_of_rejecting(tmp_path: Path) -> None:
    """계획 추정치가 없는 임무(예: perimeter 패턴)는 이 검사를 건너뛴다 — 거부하지
    않는다(설계 결정: null이면 대사 불가로 표시할 뿐 막지 않는다)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=None),
    )
    client = _client(store)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=1.0,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201


def test_the_check_does_not_apply_to_hazard_or_asset_ratios(tmp_path: Path) -> None:
    """검사 2는 accessibleGeneralRatio 하나에만 걸린다 — 위험구역·자산 비율은
    plannedCoverageRatio 와 다른 계산 기반이라 대상이 아니다(설계 결정)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=0.5),
    )
    client = _client(store)
    # hazard·asset 은 1.0(plannedCoverageRatio 0.5 를 크게 초과)이지만 거부되지
    # 않아야 한다 — general 만 0.5 이하로 맞춘다.
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            hazard=1.0,
            asset=1.0,
            general=0.5,
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
        ),
    )
    assert response.status_code == 201
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v -k "exceed_the_planned or within_the_planned or missing_planned_ratio or does_not_apply_to_hazard"
```
기대: 첫 번째만 FAIL(지금은 201이 나온다), 나머지 셋 PASS(아직 검사 자체가 없으니
당연히 안 걸린다).

- [ ] **Step 4: 검사 헬퍼와 verdict를 추가한다**

`services/core/src/ksi_core/coverage_reports.py`의 `CoverageReportVerdict`, Task 1에서
추가한 `INSUFFICIENT_CELLS_FOR_RATIO` 다음:

```python
    INSUFFICIENT_CELLS_FOR_RATIO = "INSUFFICIENT_CELLS_FOR_RATIO"
    # accessibleGeneralRatio 가 발급 경로의 plannedCoverageRatio(이상적 조건 상한)
    # 를 넘는다 — 계획대로만 날았다는 전제 하에 불가능하다.
    EXCEEDS_PLANNED_COVERAGE = "EXCEEDS_PLANNED_COVERAGE"
```

`_STATUS`에:

```python
    CoverageReportVerdict.EXCEEDS_PLANNED_COVERAGE: 422,
```

`judge_report` 함수 뒤, `RecordedCoverageReport` 클래스(184행) 앞에 헬퍼를 추가한다.
`MissionRecord`를 import해야 한다 — 파일 상단 `TYPE_CHECKING` 블록(76-80행)에 이미
`from ksi_core.mission_records import MissionStore`가 있으니 그 옆에 `MissionRecord`도
추가:

```python
if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.mission_records import MissionRecord, MissionStore
```

헬퍼 함수(모듈 최상위, `judge_report` 바로 뒤):

```python
# 부동소수 직렬화 잔차 허용치 — packages/event-contracts 의 _RATIO_EPS 와 동일한
# 값이지만 독립 상수로 둔다(이 모듈이 그 패키지의 사설 상수를 import 하지 않는다).
_PLANNED_COVERAGE_EPS = 1e-9


def _exceeds_planned_coverage(report: CoverageReport, mission: MissionRecord) -> bool:
    """계획 커버 추정치를 초과한 일반영역 관찰을 주장하는가.

    ``mission.planned_coverage_ratio`` 는 발급 시점에 lawnmower 경로 생성기가
    이상적 촬영 조건을 가정해 계산한 **상한**이다(``mission_plans.py`` 가 발급
    게이트에서 이미 이 값을 ``accessibleGeneralCoverage`` 요구치와 대조해 뒀다).
    계획된 경로만 날았다는 전제 하에, 실제 관찰이 그 상한을 넘는
    ``accessibleGeneralRatio`` 를 주장하면 불가능하다.

    hazard/asset 비율에는 적용하지 않는다 — 그 둘은 서버가 Cell 분류를 갖고
    있지 않아 이 추정치와 다른 계산 기반이다(``CoverageSummary`` docstring).

    ``planned_coverage_ratio`` 가 ``None`` 이면(perimeter 패턴·계약 전용 발급)
    ``False`` 를 돌려준다 — 유도 불가는 거부 사유가 아니다.
    """
    if mission.planned_coverage_ratio is None:
        return False
    return report.summary.accessible_general_ratio > (
        mission.planned_coverage_ratio + _PLANNED_COVERAGE_EPS
    )
```

- [ ] **Step 5: `record()`에 검사를 배선한다**

`CoverageReportStore.record()`(289-372행)의 `DEVICE_NOT_ASSIGNED` 거부 블록
(333-348행) 뒤, `judge_report(report)` 호출(349행) 앞에 삽입:

```python
            if report.summary.completion_state is CompletionState.COMPLETED and (
                _exceeds_planned_coverage(report, mission)
            ):
                # 이건 임무 원장(다른 원장)의 값과의 대조라 SITE_MISMATCH·
                # DEVICE_NOT_ASSIGNED 와 같은 "수신 시점 게이트" 지위다 — 재생 시에는
                # 재검사하지 않는다(아래 _replay 는 그대로 둔다, 이미 그 두 게이트를
                # 재생하지 않는 것과 동일 원칙).
                return self._reject(
                    report,
                    now,
                    reported_by,
                    CoverageReportVerdict.EXCEEDS_PLANNED_COVERAGE,
                    "COMPLETED 주장의 accessibleGeneralRatio"
                    f"({report.summary.accessible_general_ratio:.4f})가 발급 경로의 "
                    f"plannedCoverageRatio({mission.planned_coverage_ratio:.4f})를 "
                    "초과한다 — 계획된 경로로는 도달할 수 없다",
                )
            verdict, detail = judge_report(report)
```

> 실행자 주의: `_replay()`(242-283행)는 **수정하지 않는다** — 이 검사는 임무 원장이
> 필요한데 재생 경로는 의도적으로 임무 대조를 재검사하지 않는다(기존 주석 268-275행
> 참조). 새 코드를 `_replay`에 추가하면 이 원칙이 깨진다.

- [ ] **Step 6: 테스트를 다시 돌려 통과 확인**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v
```
기대: 신규 4건 PASS + 파일 전체 PASS(Task 1의 테스트 포함, 여전히 통과해야 한다).

- [ ] **Step 7: 정적 검사**

```bash
uv run ruff check . && uv run mypy packages services tests tools
```

- [ ] **Step 8: 커밋**

```bash
git add services/core/src/ksi_core/coverage_reports.py tests/contract/test_coverage_reports.py
git commit -m "fix(core): 계획 커버 추정치를 초과한 커버리지 완료 주장을 거부한다

plannedCoverageRatio 는 이상적 촬영 조건을 가정한 상한이다. 계획된 경로만
날았다는 전제 하에 실제 accessibleGeneralRatio 가 그 상한을 넘으면 불가능하다.
hazard/asset 비율에는 적용하지 않는다 — 서버가 그 분류를 갖고 있지 않아 다른
계산 기반이다. 임무 원장 대조가 필요해 SITE_MISMATCH·DEVICE_NOT_ASSIGNED 와
같은 '수신 시점 게이트' 지위로 두고 재생 시에는 재검사하지 않는다."
```

---

## Task 3: 조회 응답에 귀속·대사 정보를 추가한다

**Files:**
- Modify: `services/core/src/ksi_core/coverage_reports.py`
  (`CoverageReportView` 448-459행, `get_coverage_report` 라우트 577-592행,
  `CoverageReportStore` 클래스에 조회 메서드 추가)
- Modify: `contracts/api/openapi-core.yaml` (`CoverageReportView` 컴포넌트 4248-4267행)
- Modify: `apps/dashboard/src/lib/core-api/types.ts` (`CoverageReportView` 306-319행)
- Test: `tests/contract/test_coverage_reports.py`, `tests/contract/test_api_contract_sync.py`(회귀 확인만)

**Interfaces:**
- Produces: `CoverageReportStore.mission_planned_general_ratio(mission_id: str) -> float | None`,
  `CoverageReportView.ratio_attribution_note: str`,
  `CoverageReportView.planned_general_coverage_ratio: float | None`,
  `CoverageReportView.planned_general_coverage_unavailable_reason: str | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_view_always_carries_the_attribution_note(store: CoverageReportStore) -> None:
    """[핵심] 귀속 캡션은 대사 가능 여부와 무관하게 항상 채워진다."""
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(f"/v1/missions/{_MISSION_ID}/coverage-report")
    body = response.json()
    assert body["ratioAttributionNote"]
    assert "기체" in body["ratioAttributionNote"]


def test_view_carries_the_planned_ratio_when_available(store: CoverageReportStore) -> None:
    """기본 픽스처는 planned_coverage_ratio=1.0 이므로 그 값이 그대로 나온다."""
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(f"/v1/missions/{_MISSION_ID}/coverage-report")
    body = response.json()
    assert body["plannedGeneralCoverageRatio"] == pytest.approx(1.0)
    assert body["plannedGeneralCoverageUnavailableReason"] is None


def test_view_explains_when_the_planned_ratio_is_unavailable(tmp_path: Path) -> None:
    """계획 추정치가 없는 임무는 null + 이름 붙인 사유를 낸다("—" 가 아니다)."""
    store = CoverageReportStore(
        DurableJournal(tmp_path / "coverage.jsonl"),
        mission_store=_mission_store(tmp_path, planned_coverage_ratio=None),
    )
    client = _client(store)
    client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_report_payload(
            cells=[
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ]
        ),
    )
    response = client.get(f"/v1/missions/{_MISSION_ID}/coverage-report")
    body = response.json()
    assert body["plannedGeneralCoverageRatio"] is None
    assert body["plannedGeneralCoverageUnavailableReason"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v -k "attribution_note or planned_ratio_when_available or unavailable"
```
기대: 3건 모두 FAIL(`KeyError` 또는 필드 없음 — 응답 모델에 아직 필드가 없다).

- [ ] **Step 3: 조회 메서드를 `CoverageReportStore`에 추가한다**

`services/core/src/ksi_core/coverage_reports.py`, `latest_recorded` 메서드(421-425행)
뒤에 추가:

```python
    def mission_planned_general_ratio(self, mission_id: str) -> float | None:
        """이 임무의 계획 일반영역 커버 추정치 — 없으면 ``None``(대사 불가)."""
        with self._lock:
            mission = self._mission_store.get(mission_id)
            return mission.planned_coverage_ratio if mission is not None else None
```

- [ ] **Step 4: `CoverageReportView`에 필드를 추가한다**

`CoverageReportView` 클래스(448-459행) 전체를 아래로 교체:

```python
_RATIO_ATTRIBUTION_NOTE = (
    "이 세 비율은 기체가 계산해 신고한 값입니다. 서버는 구역 분류(위험구역/자산/"
    "일반)를 갖고 있지 않아 재계산하지 못합니다(INV-010)."
)


class CoverageReportView(CamelModel):
    """조회 응답 — 최신 보고 + 이 임무에 대해 몇 건이 접수됐는지 + 누가 보고했는지."""

    mission_id: str
    report_count: int
    latest: dict[str, Any]
    # 제출한 Principal id(대개 장비 id) — 없으면(구 journal 재생 등) null(독립 재검토 B-3).
    reported_by: str | None
    # Coverage Recovery 권고(MASTER_PRD §15.2) — CoverageReport.needs_coverage_recovery().
    # 자동 재발급을 트리거하지 않는다: 운영자/오퍼레이터가 이 신호를 보고 원본 site
    # AOI 로 SPATIAL_REFRESH 임무를 POST /v1/missions/plans 에 재발급한다.
    recovery_recommended: bool
    # 귀속 — 이 비율이 기체 신고값이라는 사실은 항상 참이라 항상 채워진다.
    ratio_attribution_note: str
    # 대사 — 계획 커버 추정치. 없으면(perimeter 패턴·계약 전용 발급) None 이고
    # planned_general_coverage_unavailable_reason 이 대신 채워진다. UI 는 이 원 숫자를
    # "비행 결과" 캡션에 반복하지 않는다(page.tsx:239 의 기존 원칙 — 계획과 실측을
    # 나란히 두지 않는다) — 프로그램적 소비(추후 감사·내보내기)를 위해 API 에는 남긴다.
    planned_general_coverage_ratio: float | None
    planned_general_coverage_unavailable_reason: str | None
```

- [ ] **Step 5: `get_coverage_report` 라우트에서 값을 채운다**

`build_coverage_reports_router` 안 `get_coverage_report`(577-592행)의 반환문을
교체:

```python
    @router.get("/{mission_id}/coverage-report", response_model=CoverageReportView)
    def get_coverage_report(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> CoverageReportView:
        """그 임무의 **최신** 보고. 이력 건수를 함께 낸다(덮어쓰지 않으므로)."""
        recorded = store.latest_recorded(mission_id)
        if recorded is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        planned_ratio = store.mission_planned_general_ratio(mission_id)
        return CoverageReportView(
            mission_id=mission_id,
            report_count=len(store.history(mission_id)),
            latest=recorded.report.model_dump(by_alias=True, mode="json", exclude_none=True),
            reported_by=recorded.reported_by,
            recovery_recommended=recorded.report.needs_coverage_recovery(),
            ratio_attribution_note=_RATIO_ATTRIBUTION_NOTE,
            planned_general_coverage_ratio=planned_ratio,
            planned_general_coverage_unavailable_reason=(
                None
                if planned_ratio is not None
                else "이 임무의 발급 경로에 계획 커버 추정치가 없습니다"
                " (perimeter 경로이거나 계약 단독 발급일 수 있습니다)"
            ),
        )
```

- [ ] **Step 6: 테스트를 다시 돌려 통과 확인**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_coverage_reports.py -v
```
기대: 신규 3건 PASS + 파일 전체 PASS.

- [ ] **Step 7: openapi 계약을 갱신한다**

`contracts/api/openapi-core.yaml`의 `CoverageReportView` 컴포넌트(4248-4267행)를
아래로 교체:

```yaml
    CoverageReportView:
      description: 그 임무의 최신 보고 + 접수 건수 + 누가 보고했는지 + Coverage Recovery 권고 + 귀속·대사.
      type: object
      required:
        [
          missionId,
          reportCount,
          latest,
          reportedBy,
          recoveryRecommended,
          ratioAttributionNote,
          plannedGeneralCoverageRatio,
          plannedGeneralCoverageUnavailableReason,
        ]
      properties:
        missionId: { type: string }
        reportCount: { type: integer }
        # 구조 정본은 contracts/schemas/coverage-report.v1.1.json.
        latest: { type: object, additionalProperties: true }
        reportedBy:
          type: [string, 'null']
          description: 제출한 Principal id(보통 장비 id). 구 journal 재생 등으로 없으면 null.
        recoveryRecommended:
          type: boolean
          description: >-
            Coverage Recovery 권고(MASTER_PRD §15.2) — completionState 가
            COMPLETED 가 아니거나(COMPLETED_WITH_GAPS/ABORTED_SAFE/FAILED 전부)
            사유있는 미관찰 Cell 이 남아 있으면 true. 자동 재발급을 트리거하지
            않는다 — 운영자가 원본 site AOI 로 SPATIAL_REFRESH 임무를
            POST /v1/missions/plans 에 재발급하라는 신호일 뿐이다.
        ratioAttributionNote:
          type: string
          description: >-
            "이 세 비율은 기체가 신고한 값이고 서버는 재계산하지 못한다"는
            사실 — 항상 채워진다(대사 가능 여부와 무관, INV-010).
        plannedGeneralCoverageRatio:
          type: [number, 'null']
          description: >-
            발급 시점 lawnmower 경로 생성기가 계산한 일반영역 커버 상한 추정치.
            perimeter 패턴·계약 단독 발급이면 null 이고
            plannedGeneralCoverageUnavailableReason 이 대신 채워진다.
        plannedGeneralCoverageUnavailableReason:
          type: [string, 'null']
          description: plannedGeneralCoverageRatio 가 null 일 때만 채워지는 이름 붙인 사유.
```

- [ ] **Step 8: 계약 동기화 테스트를 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_api_contract_sync.py -v
```
기대: 전부 PASS. 실패하면 `CoverageReportView` 의 필드 이름·required 집합이
Python 모델과 openapi 사이에 어긋난 것이다 — 정확히 일치시킨다.

- [ ] **Step 9: 대시보드 타입을 확장한다**

`apps/dashboard/src/lib/core-api/types.ts`의 `CoverageReportView` 인터페이스
(306-319행)를 아래로 교체:

```ts
export interface CoverageReportView {
  missionId: string;
  reportCount: number;
  latest: CoverageReport;
  /** 제출한 Principal id(보통 장비 id). 구 journal 재생 등으로 없으면 null. */
  reportedBy: string | null;
  /**
   * Coverage Recovery 권고(MASTER_PRD §15.2) — completionState 가 COMPLETED 가
   * 아니거나(COMPLETED_WITH_GAPS/ABORTED_SAFE/FAILED 전부) 사유있는 미관찰 Cell 이
   * 남아 있으면 true. 자동 재발급을 트리거하지 않는다 — 운영자가 원본 site AOI 로
   * SPATIAL_REFRESH 임무를 재발급하라는 신호일 뿐이다.
   */
  recoveryRecommended: boolean;
  /**
   * "이 세 비율은 기체가 신고한 값이고 서버는 재계산하지 못한다" — 항상 채워진다.
   * 대사 가능 여부와 무관하게 상시 노출한다(귀속과 대사를 분리, 2026-08-18 설계).
   */
  ratioAttributionNote: string;
  /**
   * 발급 시점 계획 커버 상한 추정치. UI 는 이 원 숫자를 "비행 결과" 캡션에
   * 반복하지 않는다 — 발급 메타 패널의 "계획 커버리지" 필드와 나란히 두지
   * 않는다는 기존 원칙(missions/[missionId]/page.tsx) 때문이다.
   */
  plannedGeneralCoverageRatio: number | null;
  /** plannedGeneralCoverageRatio 가 null 일 때만 채워지는 이름 붙인 사유. */
  plannedGeneralCoverageUnavailableReason: string | null;
}
```

- [ ] **Step 10: 정적 검사**

```bash
uv run ruff check . && uv run mypy packages services tests tools
cd apps/dashboard && npx tsc --noEmit
```

- [ ] **Step 11: 커밋**

```bash
git add services/core/src/ksi_core/coverage_reports.py contracts/api/openapi-core.yaml \
  apps/dashboard/src/lib/core-api/types.ts tests/contract/test_coverage_reports.py
git commit -m "feat(core): 커버리지 조회 응답에 귀속·대사 정보를 싣는다

귀속(이 비율은 기체 신고값이다)은 항상 채워진다. 대사(계획 커버 추정치)는
계산 가능하면 원 숫자를, 아니면 null + 이름 붙인 사유를 낸다. 저장하지 않고
매 호출 재계산한다(site_status_matches_model 과 같은 이유). UI 는 이 숫자를
'비행 결과' 캡션에 반복하지 않는다 — 발급 메타 패널과 나란히 두지 않는다는
기존 원칙(page.tsx:239) 때문이다. API 응답에는 프로그램적 소비를 위해 남긴다."
```

---

## Task 4: 거부 이력 대시보드 클라이언트

**닫는 구멍:** `GET .../coverage-report/rejections`가 이미 프로덕션에 있지만 대시보드가
한 번도 부르지 않는다(확인됨) — 서버가 근거 없는 완료 주장을 막았다는 사실이 운영자에게
끝내 도달하지 않는다.

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/types.ts` (`CoverageRejectionView`/
  `CoverageRejectionListView` 신설, `CoverageReportView` 뒤에 추가)
- Modify: `apps/dashboard/src/lib/core-api/missions.ts` (`getCoverageRejections` 추가)

**Interfaces:**
- Produces: `CoverageRejectionView`, `CoverageRejectionListView`,
  `getCoverageRejections(missionId: string): Promise<CoverageRejectionListView>`

- [ ] **Step 1: 대시보드 타입을 추가한다**

`apps/dashboard/src/lib/core-api/types.ts`의 `CoverageReportView` 인터페이스
(Task 3에서 확장한 버전) 바로 뒤에 추가 — Core의 `CoverageRejectionView`·
`CoverageRejectionListView`(`services/core/src/ksi_core/coverage_reports.py:462-480`)를
그대로 미러한다:

```ts
/** 서버가 거부한 보고 1건 — 무엇을, 왜, 누가, 언제(본문은 싣지 않는다). */
export interface CoverageRejectionView {
  verdict: string;
  detail: string | null;
  reportedBy: string | null;
  rejectedAt: string;
}

/**
 * 그 임무에 대해 서버가 거부한 보고들. 0건은 빈 배열이지 오류가 아니다 —
 * "거부가 없었다"는 그 자체로 답이다.
 */
export interface CoverageRejectionListView {
  missionId: string;
  rejectionCount: number;
  rejections: CoverageRejectionView[];
}
```

- [ ] **Step 2: 클라이언트 함수를 추가한다**

`apps/dashboard/src/lib/core-api/missions.ts`의 `getCoverageReport`(33-37행) 뒤에
추가. import 목록(4-9행)에 두 타입을 더한다:

```ts
import type {
  CoverageReportView,
  CoverageRejectionListView,
  MissionExecutionStatus,
  MissionExecutionView,
  MissionRecordResponse,
} from "./types";
```

```ts
/**
 * 서버가 이 임무에 대해 거부한 완료 주장 이력 — "서버가 근거 없는 완료를
 * 막았다"는 사실 자체가 감사 입력이다(coverage_reports.py 모듈 docstring).
 * 거부 0건은 빈 배열이지 404 가 아니다.
 */
export async function getCoverageRejections(missionId: string): Promise<CoverageRejectionListView> {
  return coreFetch<CoverageRejectionListView>(
    `/v1/missions/${encodeURIComponent(missionId)}/coverage-report/rejections`,
  );
}
```

- [ ] **Step 3: 타입 검사로 확인한다**

```bash
cd apps/dashboard && npx tsc --noEmit
```
기대: 통과. 이 Task는 아직 UI에서 안 쓰이므로(Task 5·6에서 배선) 런타임 테스트는 없다 —
타입이 서버 응답 모양과 맞는지가 이 Task의 검증 전부다.

- [ ] **Step 4: 커밋**

```bash
git add apps/dashboard/src/lib/core-api/types.ts apps/dashboard/src/lib/core-api/missions.ts
git commit -m "feat(dashboard): 커버리지 거부 이력 조회 클라이언트를 추가한다

GET .../coverage-report/rejections 는 이미 프로덕션에 있지만 대시보드가 한 번도
부르지 않았다 — 서버가 근거 없는 완료 주장을 막았다는 사실이 운영자에게 끝내
도달하지 않는 구멍이었다. 타입과 클라이언트 함수만 추가한다(UI 배선은 다음 Task)."
```

---

## Task 5: 임무 상세 화면 — 귀속 캡션 + 거부 이력

**Files:**
- Modify: `apps/dashboard/src/components/missions/CoverageReportSection.tsx`
- Modify: `apps/dashboard/src/app/missions/[missionId]/page.tsx`
  (108-134행 Promise.all 배열, 242행 `CoverageReportSection` 사용부)
- Test: `apps/dashboard/test/coverage-report-section.test.ts`(신설)

**Interfaces:**
- Consumes: `CoverageRejectionListView`(Task 4), `CoverageReportView`
  확장분(Task 3), `getCoverageRejections`(Task 4)
- Produces: `CoverageReportSection` 의 새 prop `rejections: CoverageRejectionListView | null`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`apps/dashboard/test/coverage-report-section.test.ts` 신설. 이 저장소는 화면 배선을
소스 문자열 대조로 고정하는 관례가 있다(`test/evidence-panel-wiring.test.ts`) —
같은 방식을 쓴다:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SECTION = readFileSync(
  join(process.cwd(), "src/components/missions/CoverageReportSection.tsx"),
  "utf8",
);

describe("커버리지 귀속·대사 표시", () => {
  it("[핵심] 귀속 캡션을 상시 렌더한다(대사 가능 여부와 무관)", () => {
    expect(SECTION).toContain("ratioAttributionNote");
  });

  it("계획값 숫자를 비행 결과 캡션에 반복하지 않는다", () => {
    // page.tsx:239 의 기존 원칙 — 발급 메타의 '계획 커버리지' 필드와 나란히
    // 두지 않는다. plannedGeneralCoverageRatio 를 읽어서 조건 분기에는 쓰되
    // 화면에 그 숫자를 그대로 찍지는 않는다.
    expect(SECTION).not.toMatch(/plannedGeneralCoverageRatio\}/);
  });

  it("거부 이력이 있으면 비율 타일보다 먼저 렌더한다", () => {
    expect(SECTION).toContain("rejections");
    const tilesIndex = SECTION.indexOf("필수 위험구역");
    const rejectionsIndex = SECTION.indexOf("거부");
    expect(rejectionsIndex).toBeGreaterThan(-1);
    expect(rejectionsIndex).toBeLessThan(tilesIndex);
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
cd apps/dashboard && npx vitest run test/coverage-report-section.test.ts
```
기대: 3건 모두 FAIL.

- [ ] **Step 3: `CoverageReportSection.tsx`를 수정한다**

전체 파일을 아래로 교체한다(기존 import·`Tile` 함수는 그대로 두고 본문만 바뀐다):

```tsx
import type { ReactNode } from "react";

import { humanizeApiError } from "@/lib/core-api/labels";
import { summarizeCoverageCells } from "@/lib/core-api/coverage";
import type { CoreApiError } from "@/lib/core-api/client";
import type { CoverageReportView, CoverageRejectionListView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatKoreanDateTime } from "@/lib/datetime";

import { formatRatio } from "@/app/missions/format";
import { CELL_STATE_LABEL, COMPLETION_STATE_LABEL } from "@/app/missions/mission-labels";

/** 임무 상세 화면의 "비행 결과" 섹션이 받는 조회 결과 — 서버 판정 그대로다. */
export type CoverageReportResult =
  | { kind: "reported"; report: CoverageReportView }
  | { kind: "not-reported" }
  | { kind: "error"; error: CoreApiError };

function Tile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3">
      <span className="break-keep text-[11px] font-semibold text-ink-2">{label}</span>
      <span className="num text-[19px] leading-tight font-bold tracking-tight">{value}</span>
    </div>
  );
}

/**
 * 거부 이력 — 이 임무에 한 건이라도 있으면 비율 타일보다 먼저 보여준다.
 * `site_status_matches_model` 관례: 모순(여기서는 "이 장비가 전에 근거 없는
 * 완료를 주장했다가 막혔다")이 결론보다 먼저 읽혀야 한다. 숫자는 안 싣는다 —
 * CoverageRejectionView 자체가 이미 숫자를 갖고 있지 않다.
 */
function RejectionHistory({ rejections }: { rejections: CoverageRejectionListView }) {
  if (rejections.rejectionCount === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-line-strong bg-sunk p-3">
      <p className="text-[12px] font-semibold break-keep text-ink-1">
        이 임무에서 서버가 거부한 완료 주장 {rejections.rejectionCount}건
      </p>
      <ul className="flex flex-col gap-1">
        {rejections.rejections.map((r, i) => (
          <li key={i} className="text-[11.5px] break-keep text-ink-2">
            {formatKoreanDateTime(r.rejectedAt, { dateStyle: "medium", timeStyle: "short" })} ·{" "}
            {r.detail ?? r.verdict}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 임무 상세의 "비행 결과" — CoverageReport 의 존재와 서버 판정을 그대로 보여준다
 * (INV-010, PRD §15.5). 대시보드는 완료 여부를 재계산하지 않는다.
 *
 * ``not-reported`` 를 "—"로 조용히 넘기지 않는다 — 발급됐지만 아직 비행 전인지,
 * 비행했는데 보고가 아직 도착하지 않았는지는 이 화면만으로 구분되지 않는다는
 * 사실 자체가 운영자에게 필요한 정보다.
 *
 * 귀속(비율은 기체 신고값)과 대사(계획 대비 초과 확인)를 분리한다(2026-08-18) —
 * 귀속은 항상 표시하고, 계획값 원 숫자는 이 캡션에 반복하지 않는다(발급 메타
 * 패널의 "계획 커버리지" 필드와 나란히 두지 않는다는 기존 원칙, page.tsx:239).
 */
export function CoverageReportSection({
  result,
  rejections,
}: {
  result: CoverageReportResult;
  rejections: CoverageRejectionListView | null;
}) {
  if (result.kind === "error") {
    const { error } = result;
    return (
      <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
    );
  }

  if (result.kind === "not-reported") {
    return (
      <>
        {rejections && <RejectionHistory rejections={rejections} />}
        <EmptyState
          title="아직 비행 보고가 도착하지 않았습니다"
          description="이 임무가 아직 비행 전이거나, 비행했지만 보고가 서버에 아직 도착하지 않았을 수 있습니다 — 이 화면만으로는 둘을 구분할 수 없습니다. 커버리지 보고는 비행한 장비만 올릴 수 있습니다."
        />
      </>
    );
  }

  const {
    latest,
    reportCount,
    reportedBy,
    recoveryRecommended,
    ratioAttributionNote,
    plannedGeneralCoverageRatio,
    plannedGeneralCoverageUnavailableReason,
  } = result.report;
  const completion = COMPLETION_STATE_LABEL[latest.summary.completionState];
  const cells = summarizeCoverageCells(latest.cells);

  return (
    <div className="flex flex-col gap-3">
      {rejections && <RejectionHistory rejections={rejections} />}

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge label={completion.label} tone={completion.tone} />
        {recoveryRecommended && <StatusBadge label="재커버 권고" tone="caution" />}
        <span className="text-[12.5px] break-keep text-ink-muted">
          {formatKoreanDateTime(latest.timestamp, { dateStyle: "medium", timeStyle: "short" })} 보고 · 보고
          장비 {reportedBy ?? "확인 불가"}
        </span>
      </div>

      {recoveryRecommended && (
        <p className="text-[11.5px] break-keep text-ink-muted">
          이 임무는 미관찰 구역이 남았거나 공백이 있는 채로 종료됐습니다 — 원본 구역으로
          공간 모델 갱신(SPATIAL_REFRESH) 임무를 재발급하는 것을 고려하세요. 자동으로
          재발급되지 않습니다.
        </p>
      )}

      <div className="grid grid-cols-3 gap-2">
        <Tile label="필수 위험구역" value={formatRatio(latest.summary.mandatoryHazardRatio)} />
        <Tile label="필수 자산" value={formatRatio(latest.summary.mandatoryAssetRatio)} />
        <Tile label="접근가능 일반영역" value={formatRatio(latest.summary.accessibleGeneralRatio)} />
      </div>

      {/* 귀속·대사 — 상시 텍스트(툴팁 아님). 계획값 원 숫자는 여기 안 찍는다 —
          위 "발급 메타" 패널의 "계획 커버리지" 필드를 본다(page.tsx:239 원칙). */}
      <div className="rounded-lg border border-line bg-sunk p-3">
        <p className="text-[11.5px] break-keep text-ink-2">{ratioAttributionNote}</p>
        <p className="mt-1 text-[11.5px] break-keep text-ink-muted">
          {plannedGeneralCoverageRatio !== null
            ? "계획 대비 초과 여부를 서버가 확인했습니다 — 이상 없음."
            : `대사 불가 — ${plannedGeneralCoverageUnavailableReason}`}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Tile label="관찰됨" value={`${cells.observed} / ${cells.total}`} />
        <Tile label="미관찰(사유 있음)" value={cells.explainedGap} />
        <Tile label="미관찰(사유 없음)" value={cells.unexplainedGap} />
      </div>

      {cells.byState.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {cells.byState.map(({ state, count }) => (
            <li
              key={state}
              className="rounded-[4px] border border-line bg-sunk px-1.5 py-0.5 text-[11px] break-keep text-ink-2"
            >
              {CELL_STATE_LABEL[state]} <span className="num font-semibold">{count}</span>
            </li>
          ))}
        </ul>
      )}

      {reportCount > 1 && (
        <p className="text-[11.5px] break-keep text-ink-muted">
          이 임무에 총 <span className="num">{reportCount}</span>건의 보고가 접수됐습니다 —
          위 내용은 그중 최신 보고 기준입니다.
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 테스트를 다시 돌려 통과 확인**

```bash
cd apps/dashboard && npx vitest run test/coverage-report-section.test.ts
```
기대: 3건 PASS.

> 실행자 주의: "거부 이력이 있으면 비율 타일보다 먼저" 테스트는 소스 문자열의 순서를
> 대조한다 — `RejectionHistory` 함수 정의가 파일 앞쪽에 있고 "거부"라는 단어가
> "필수 위험구역"보다 먼저 등장하면 통과한다(함수 정의부의 문자열도 포함되므로,
> `RejectionHistory` 함수 자체가 `Tile` 사용부보다 앞에 있는 한 이 assertion은
> 성립한다 — 위 코드가 이미 그 순서다). 이 assertion이 실제 렌더 순서를 완벽히
> 보증하지는 않는다(소스 텍스트 순서일 뿐) — 더 엄격한 검증이 필요하면 계획 실행 중
> 렌더 테스트(React Testing Library)로 승격할지 판단한다.

- [ ] **Step 5: 임무 상세 페이지에서 거부 이력을 조회해 넘긴다**

`apps/dashboard/src/app/missions/[missionId]/page.tsx`. import 목록(18행 부근)에
`getCoverageRejections` 추가:

```tsx
import { getCoverageReport, getCoverageRejections, getMission, getMissionExecution } from "@/lib/core-api/missions";
```

`fetchCoverageResult` 함수(43-52행) 근처에 사촌 함수를 추가:

```tsx
/**
 * 거부 이력은 항상 부가 정보다 — 조회 실패해도 "비행 결과" 섹션 자체는 보여야
 * 한다(fetchCoverageResult 와 같은 원칙). rejectionCount=0 도 유효한 성공 응답이라
 * catch 블록이 아니라 null 로만 실패를 표시한다.
 */
async function fetchCoverageRejections(missionId: string): Promise<CoverageRejectionListView | null> {
  try {
    return await getCoverageRejections(missionId);
  } catch {
    return null;
  }
}
```
import에 `CoverageRejectionListView` 타입 추가(파일 상단 types import 목록).

Promise.all 배열(113행 부근)의 destructure 목록에 `rejectionsResult`를
`coverageResult` 바로 뒤에 추가하고, 대응하는 promise를 배열에 같은 위치로 추가:

```tsx
  const [
    site,
    execution,
    coverageResult,
    rejectionsResult,
    canIssue,
    sourceBundle,
    jobs,
    hasComparison,
    siteJobs,
    comparisonPolicy,
    latestComparison,
    designSurfaces,
    latestDesignRequest,
    designConformance,
    workAreas,
  ] = await Promise.all([
    getSite(mission.siteId).catch(() => null),
    getMissionExecution(mission.missionId).catch(() => null),
    fetchCoverageResult(mission.missionId),
    fetchCoverageRejections(mission.missionId),
    whoAmI()
      .then((who) => who.permissions.includes("MISSIONS_ISSUE"))
      .catch(() => false),
    // ...(나머지 항목은 그대로 둔다)
```

`CoverageReportSection` 사용부(242행):

```tsx
        <CoverageReportSection result={coverageResult} rejections={rejectionsResult} />
```

- [ ] **Step 6: 전체 게이트**

```bash
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```

- [ ] **Step 7: 실제 화면으로 확인한다**

```bash
uv run python scripts/run_core_dev.py --host 0.0.0.0 --port 8010 &
cd apps/dashboard && npm run dev -- --hostname 0.0.0.0 --port 3000 &
```
임무 상세 화면에서 귀속 캡션이 항상 보이는지, 거부 이력이 있는 임무(테스트로
하나 만들어 확인)에서 그 절이 비율 타일보다 먼저 나오는지 눈으로 확인한다.

- [ ] **Step 8: 커밋**

```bash
git add apps/dashboard/src/components/missions/CoverageReportSection.tsx \
  apps/dashboard/src/app/missions/\[missionId\]/page.tsx \
  apps/dashboard/test/coverage-report-section.test.ts
git commit -m "feat(dashboard): 임무 상세에 커버리지 귀속 캡션과 거부 이력을 노출한다

귀속(기체 신고값이라는 사실)은 상시 텍스트로, 대사(계획 대비 확인 여부)는
숫자를 반복하지 않고 결과만 낸다(발급 메타 패널과 나란히 두지 않는 기존
원칙, page.tsx:239). 거부 이력이 있으면 비율 타일보다 먼저 배치한다 —
'이 장비가 전에 근거 없는 완료를 주장했다가 막혔다'는 사실이 최신 접수
보고만 보여주면 묻힌다."
```

---

## Task 6: 현장 화면 — 거부 시 재비행 판단 신호

**Files:**
- Modify: `apps/dashboard/src/app/field/field-stages.ts`
  (`FieldCoverageInput` 타입, `resultStage` 함수)
- Modify: `apps/dashboard/src/app/field/[missionId]/page.tsx` (`fetchCoverage` 함수)

**Interfaces:**
- Consumes: `getCoverageRejections`(Task 4)
- Produces: `FieldCoverageInput`에 `rejectedMoreRecentlyThanLatestReport: boolean` 필드 추가

- [ ] **Step 1: `FieldCoverageInput` 타입을 확장한다**

`apps/dashboard/src/app/field/field-stages.ts`의 실제 정의(32-35행)를 확인했다:

```ts
export type FieldCoverageInput =
  | { kind: "reported"; completionState: CompletionState; recoveryRecommended: boolean }
  | { kind: "not-reported" }
  | { kind: "error" };
```

`not-reported` 분기에만 필드를 추가한다 — "reported"(이미 접수된 보고가 있다)는
결과가 확정된 것이라 재비행 판단이 필요 없고(거부는 그 이전 시도에 대한 것),
"error"는 거부 여부를 알 방법이 없으므로 그대로 둔다:

```ts
export type FieldCoverageInput =
  | { kind: "reported"; completionState: CompletionState; recoveryRecommended: boolean }
  | { kind: "not-reported"; hasPendingRejection: boolean }
  | { kind: "error" };
```

- [ ] **Step 2: `resultStage`에서 거부 신호를 반영한다**

`resultStage` 함수의 `not-reported` 분기(현재는 항상 "보고 없음" 중립 톤)를 아래로
교체:

```ts
  if (coverage.kind === "not-reported") {
    return coverage.hasPendingRejection
      ? {
          key: "result",
          title: "결과",
          auto: {
            label: "방금 제출이 접수되지 않았습니다",
            detail: "서버가 완료 보고를 거부했습니다 — 재비행이 필요할 수 있습니다. 자세한 사유는 임무 상세 화면에서 확인하세요.",
            tone: "caution",
          },
          manual: null,
        }
      : {
          key: "result",
          title: "결과",
          auto: { label: "보고 없음", detail: "비행 결과 보고가 아직 도착하지 않았습니다.", tone: "neutral" },
          manual: null,
        };
  }
```

- [ ] **Step 3: 현장 페이지에서 거부 이력을 조회해 반영한다**

`apps/dashboard/src/app/field/[missionId]/page.tsx`의 `fetchCoverage` 함수를 아래로
교체(거부 조회를 병행하고, 접수된 보고가 없을 때만 거부 유무를 반영한다):

```tsx
async function fetchCoverage(
  missionId: string,
): Promise<{ input: FieldCoverageInput; report: CoverageReportView | null }> {
  try {
    const report = await getCoverageReport(missionId);
    return {
      input: {
        kind: "reported",
        completionState: report.latest.summary.completionState,
        recoveryRecommended: report.recoveryRecommended,
      },
      report,
    };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      // 접수된 보고가 없다 — 그래도 "거부된 시도"가 있었을 수 있다(예: 방금
      // 근거 없는 완료 보고를 냈다가 막혔다). 조종사가 지금 재비행 여부를
      // 판단해야 하는 자리라 그 사실만 확인한다(숫자는 보지 않는다).
      const hasPendingRejection = await getCoverageRejections(missionId)
        .then((r) => r.rejectionCount > 0)
        .catch(() => false);
      return { input: { kind: "not-reported", hasPendingRejection }, report: null };
    }
    if (error instanceof CoreApiError) return { input: { kind: "error" }, report: null };
    throw error;
  }
}
```
import 목록에 `getCoverageRejections` 추가(`"@/lib/core-api/missions"`에서).

> 실행자 주의: 여기서는 "거부 존재 여부"만 본다(가장 최근 접수 보고의 timestamp와
> 비교하는 정교한 로직은 채택하지 않는다) — 애초에 `getCoverageReport`가 404를
> 던지는 시점(=접수된 RECORDED 보고가 아예 없음)에만 이 분기를 타므로, 그 상태에서
> 거부 이력이 하나라도 있으면 "방금 제출이 접수 안 됐다"는 신호로 충분히 유효하다.
> 이미 RECORDED 보고가 있는 임무의 과거 거부 이력은 임무 상세 화면(Task 5)에서
> 확인한다 — 현장 화면은 "지금 재비행할지"만 판단하면 된다.

- [ ] **Step 4: 전체 게이트**

```bash
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```

- [ ] **Step 5: 커밋**

```bash
git add apps/dashboard/src/app/field/field-stages.ts apps/dashboard/src/app/field/\[missionId\]/page.tsx
git commit -m "feat(dashboard): 현장 화면이 방금 거부된 완료 제출을 알린다

접수된 보고가 없는 상태(404)에서 거부 이력이 있으면 '보고 없음'이 아니라
'방금 제출이 접수되지 않았습니다 — 재비행이 필요할 수 있습니다'로 바꾼다.
귀속·대사 정보는 현장 화면에 안 넣는다(조종사가 이미 아는 사실이고
ADR-KSI-017 이 이 화면의 범위를 이륙 전/착륙 후 판단으로 좁혀 뒀다)."
```

---

## Task 7: 문서·리스크 마무리

**Files:**
- Modify: `docs/product/DOMAIN_INVARIANTS.md` (INV-010 항목, 23-36행)

- [ ] **Step 1: INV-010 항목에 새 검사를 반영한다**

`docs/product/DOMAIN_INVARIANTS.md`의 INV-010 강제 목록(29-34행)에 항목을 추가한다.
기존 "미완" 문장(35-36행)은 **지우지 않는다** — 여전히 사실이다(서버는 Cell 분류를
갖고 있지 않다는 한계 자체는 이 계획으로 안 없어진다):

```markdown
- **INV-010** 임무 완료 기준: 필수 위험구역 100% · 필수 자산/표면 100% · 접근가능 일반영역
  ≥95%. 경로 완료 ≠ 임무 완료. 모든 미관찰 Cell은 원인코드와 후속처리를 가진다.
  **완료 판정의 권위는 비행 후 CoverageReport 하나다** — 발급 시점의
  `plannedCoverageRatio` 는 스와스 가정 하의 계획 추정치이고 완료 근거가 아니다
  (MASTER_PRD §15.5). 서버가 계획값으로 완료를 주장하면 실제 관찰(가림·접근불가·
  배터리 한계·이벤트 분기 공백)이 기록에서 사라진다.
  _강제: `ksi_core.coverage_reports` — 비행 후 보고 수신 시 ① COMPLETED 주장이
  요약 비율로 뒷받침되는지 ② 사유 없는 미관찰 Cell 이 없는지 ③ 관찰 증거가 있는지
  ④ 요약이 자체 모순인지(전 구역 100% 인데 미관찰 Cell 존재) ⑤ 칸 총수<2 인데
  비율이 0과 1 사이(산술적 불가능, 2026-08-18) ⑥ 발급된 임무·site 일치인지 ⑦
  accessibleGeneralRatio 가 발급 경로의 plannedCoverageRatio(이상적 조건 상한)를
  초과하지 않는지(2026-08-18)를 검사한다. **재생은 ①~⑤만 재검사한다** — ⑥⑦(임무
  대조)은 수신 시점의 게이트이고, 이미 받은 기록을 나중에 부정하지 않는다(임무
  원장이 따로 회전·보관 정책을 타므로 재생 시점에 없을 수 있다). 발급 전 사전
  점검은 `mission_plans` 소관.
  **미완**: Cell 분류(위험구역/자산/일반)를 서버가 갖고 있지 않아 요약 비율 자체를
  재계산하지는 못한다 — 기체 보고를 검증하되 재현하지는 않는다. 칸을 충분히
  만들고 비율을 계획 안쪽으로 조작하면 여전히 통과한다(2026-08-18 설계 문서
  "닫지 못하는 것" 참조) — 이 계획이 막는 건 산술적으로 불가능한 주장뿐이다._
```

- [ ] **Step 2: 출력물 전파 범위 밖 사실을 리스크로 등록한다**

```bash
python3 ~/.claude/scripts/ksi-goals.py risk-add --id coverage-reconciliation-not-in-print-or-csv \
  --title "커버리지 귀속·대사 정보가 인쇄 보고서·CSV 에는 전파되지 않는다" \
  --lens role --severity low \
  --note "2026-08-18 설계로 임무 상세 화면·현장 화면에는 귀속·대사·거부 이력이 노출되지만, 인쇄 보고서(/sites/{siteId}/report)와 CSV 내보내기에는 커버리지 숫자 자체가 아예 없다. 발주처가 받는 문서는 화면보다 계속 확신에 차 있는 상태로 남는다 — '이 보고서가 무엇에 관한 문서인가'를 먼저 정해야 하는 별도 설계가 선행돼야 한다."
```

- [ ] **Step 3: 전체 회귀를 마지막으로 한 번 더 돌린다**

```bash
ulimit -n 8192 && uv run pytest -q
uv run ruff check .
uv run mypy packages services tests tools
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```
기대: 전부 PASS, 파이썬 테스트 건수가 이 계획이 추가한 만큼(Task 1: +3, Task 2: +4,
Task 3: +3 = 총 +10) 기준선보다 늘어 있어야 한다.

- [ ] **Step 4: 커밋**

```bash
git add docs/product/DOMAIN_INVARIANTS.md .ksi/goals.json .ksi/ledger.jsonl
git commit -m "docs: INV-010 에 새 검사 2건을 반영하고 남은 범위를 리스크로 남긴다

강제 목록에 ⑤(산술적 불가능)⑥(임무 대조, 기존 임무·site 일치를 번호만 밀림)
⑦(계획 초과)을 추가한다. '미완' 문장은 지우지 않는다 — Cell 분류 재계산
불가라는 근본 한계는 이 계획으로 안 없어진다. 인쇄 보고서·CSV 전파는 범위
밖으로 남겨 별도 리스크로 등록한다.

risk: coverage-reconciliation-not-in-print-or-csv (open, 별도 설계 필요)"
```

---

## Self-Review

**Spec coverage:**
- "막는 선" 원칙(서버가 가진 정보만으로 확정) → Task 1·2가 정확히 이 형태로 구현.
- "완료 주장에만" → Task 1은 `judge_report` 안(이미 COMPLETED 게이트 뒤), Task 2는
  명시적으로 `completion_state is COMPLETED` 조건.
- "귀속·대사 분리, 저장 안 함" → Task 3의 `mission_planned_general_ratio()`가 매 호출
  재계산, `CoverageReportView`가 저장 없이 응답에만 실림.
- "귀속은 임무 상세에만, 현장은 거부 시만" → Task 5(임무 상세 상시)·Task 6(현장
  거부 시만)로 분리 구현.
- "출력물 범위 밖" → Task 7에서 리스크로 명시 등록.
- "계획값 숫자를 UI에 반복 안 함" → Task 5의 캡션 문구와 Task 5의 테스트
  (`not.toMatch(/plannedGeneralCoverageRatio\}/)`)가 함께 고정.
- 재생 분리(검사1 재검사/검사2 미재검사) → Task 1 Step 5, Task 2 Step 5 주석과
  `_replay()` 비수정으로 구현.

**Placeholder 스캔:** 전체 재확인 — "TBD"·"적절히"류 없음. Task 6의 `FieldCoverageInput`
정의도 자체 검토 중 실제 파일(field-stages.ts:32-35)을 다시 열어 확정값으로
교체했다(추정이 아니라 실측).

**타입 일관성:** `CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO`·
`EXCEEDS_PLANNED_COVERAGE`(Task 1·2) → `_STATUS` 매핑 → 테스트의 `verdict` 문자열
대조까지 동일 이름 사용 확인. `ratioAttributionNote`·`plannedGeneralCoverageRatio`·
`plannedGeneralCoverageUnavailableReason`(Task 3 Python) ↔ 동일 camelCase(Task 3
openapi·TS) ↔ Task 5 구조분해 변수명까지 일치 확인. `getCoverageRejections`(Task 4)
↔ Task 5·6 import 및 호출 일치 확인.

**Scope check:** 7개 Task, 파일 약 12개 수정 — 이전 하드닝 계획(10 Task)과 비슷한
규모다. 프론트엔드(Task 5·6)와 백엔드(Task 1~3)가 명확히 분리되고 각 Task가 독립
커밋·독립 검증을 갖는다. 단일 계획으로 적절하다.
