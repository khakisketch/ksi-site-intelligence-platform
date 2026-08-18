# 착수 가능 잔여 작업 — 미해소 리스크·표기 정직성·원장 정합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실기 하드웨어도 대표자 결정도 필요 없이 지금 닫을 수 있는 잔여 항목 — 미해소
리스크 4건, 화면 표기 정직성 2건, 게이트 스코프 1건, 문서·원장 불일치 7건, 미이행 검증
게이트 3건 — 을 전부 닫아, "무엇이 안 닫혔는지"가 하드웨어 관문 하나로만 남게 한다.

**Architecture:** 새 서브시스템을 만들지 않는다. 이 계획의 모든 변경은 (a) **이미 서버가
계산해 놓고 아무도 안 읽는 값을 읽게 하거나**(Task 1·2), (b) **검사가 안 돌았다는 사실을
초록불과 구분되게 만들거나**(Task 3·4), (c) **이미 있는 컴포넌트·API를 화면에 잇거나**
(Task 5), (d) **이름을 내용에 맞추는 것**(Task 6)이다. 새 Core 라우터 0개, 새 계약 필드
0개, 새 화면 0개다.

**Tech Stack:** Python 3.12 (uv workspace), FastAPI, Pydantic v2, pytest, C++17 (edge
manifold-runtime, CMake), Next.js 16 / React 19 / TypeScript / vitest

**Spec:** 이 계획은 단일 spec 문서가 아니라 **저장소의 리스크 원장(`.ksi/goals.json`의
`risks` 배열) + 2026-08-17 전수 조사**를 근거로 한다. 각 Task 가 닫는 리스크 ID를 명시했고,
그 ID로 원장을 대조할 수 있다.

---

## Global Constraints

이 절의 값은 저장소에서 그대로 옮긴 것이다. 모든 Task 의 요구사항에 암묵적으로 포함된다.

- **언어 규약**: 코드 식별자는 영어, docstring·주석은 한국어. 기존 파일의 밀도와 어조를
  그대로 따른다.
- **테스트 실행**: `ulimit -n 8192` 를 먼저 올린 뒤 `uv run pytest`. FD 기본값 1024 로는
  전체 스위트가 인프라 사유로 깨진다.
- **정적 검사(CI 명령 그대로)**: `uv run ruff check .` · `uv run mypy packages services tests tools`.
  **`mypy .` 가 아니다** — CI(`.github/workflows/ci.yml:47-48`)는 스코프를 지정해 부른다.
  `ruff format --check` 는 이 저장소의 게이트가 **아니다**(CI 가 안 돌리고 기존 파일 다수가
  통과 못 한다). 새로 만드는 파일에만 `uv run ruff format <새 파일>` 을 적용하고,
  **기존 파일을 통째로 재포맷하지 않는다.**
- **대시보드**: `cd apps/dashboard && npm run test` · `npm run lint` · `npx tsc --noEmit` ·
  `npm run build`.
- **새 `/v1/*` 경로 없음**: 이 계획은 경로를 신설하지 않는다. 단 Task 1 이 기존 operation 의
  `responses` 에 409 를 추가하므로 `contracts/api/openapi-core.yaml` 을 고치고,
  `tests/contract/test_api_contract_sync.py` 가 통과하는지 반드시 확인한다.
- **응답 스키마 필드를 늘리지 않는다**: `test_api_contract_sync.py::test_documented_response_schemas_match_implementation_fields`
  가 openapi components 와 pydantic 모델의 필드·required 완전 일치를 강제하고,
  `test_dashboard_types_match_contract_schemas` 가 `apps/dashboard/src/lib/core-api/types.ts`
  까지 묶는다. 필드를 하나 더하면 세 곳을 함께 고쳐야 한다 — 이 계획은 그 경로를 피한다.
- **`references/repos/` 금지**: runtime import 금지, 수정 금지.
- **ADR-KSI-020 §5 동결 준수**: "FIELD-0a 이전에 새 기능을 만들지 않는다." 이 계획의 어느
  Task 도 새 제품 기능을 만들지 않는다. Task 5·6 이 화면을 건드리지만 각각 **이미 있는
  컴포넌트 재사용**과 **이름 교정**이며, 없는 기능을 만들어 이름을 맞추지 않는다.
- **커밋**: 각 Task 끝에서 커밋한다. 커밋 직전에 그 Task 의 테스트를 **실제로 돌려** 통과를
  확인한다. 자기보고를 근거로 커밋하지 않는다.

---

## 범위 — 무엇을 넣고 무엇을 뺐는가

2026-08-17 전수 조사 결과, 미완료 목표 24건의 성격은 다음과 같다.

| 성격 | 건수 | 이 계획에 |
|---|---|---|
| 실기 하드웨어가 있어야 닫힘 | 14 | **제외** |
| 대표자 결정이 선행돼야 함 | 6 | **제외** |
| 소프트웨어만으로 진행 가능 | 4 | 포함(그중 3건은 개발이 끝나 검증만 남음 → Task 9) |

리스크 원장 미해소 15건 중:

| 성격 | 건수 | 이 계획에 |
|---|---|---|
| 코드로 닫을 수 있음 | 4 | **Task 1~4** |
| 실기 검증이 있어야 닫힘 | 8 | 제외 |
| 대표자 결정이 있어야 닫힘 | 3 | 제외 |

### 제외한 것과 그 이유 (실행자가 "왜 이건 없지?"를 다시 묻지 않도록)

**1. severity high 리스크 2건 — 값은 실기로만 고칠 수 있다. 다만 "미검증임을 알리는 것"은
지금 할 수 있고, 그것이 Task 10 이다.**

- `mapping-camera-constants-are-not-m4d`: 두 위저드가 M4D 실측이 아닌 대체 카메라 상수
  (`sensorWidthMm=13.2, focalLengthMm=8.8, 5472x3648`)를 기본값으로 넣어, 모든 매핑 임무의
  사진 밀도·GSD·격자 간격이 미검증 상수 위에 선다.
  위치: `SiteRegistrationWizard.tsx` (DEFAULT_CAMERA, 주석 `:69-70`),
  `SurveyWizard.tsx` (DEFAULT_CAMERA, 주석 `:162-164`).
- `mission-drone-enum-value-is-not-m4d`: 발급되는 모든 KMZ/WPML 이 `droneEnumValue=99`
  (M4T 추정)를 싣는데 실제 기체는 M4D(추정 1000)다.
  실제 위치는 **대시보드 두 곳**이다 — `SurveyWizard.tsx:215`, `SiteRegistrationWizard.tsx:98`.
  **`wpml.py` 는 이 리스크의 위치가 아니다** — 오히려 가장 정직한 쪽이다: 파일에 `99` 가
  없고(호출자가 `DroneProfile` 로 주입), 모듈 docstring `:19-22` 가 "기체 enum 을 하드코딩하지
  않는다 … 추측으로 박으면 Pilot 2 가 조용히 거부/오해석할 수 있으므로"라 적었으며,
  `:43-50` 에 `KNOWN_DRONE_ENUM_VALUES` 참고표와 "M4D 시리즈 값은 미확인(H4)" 주석이 있다.

**값 자체**는 정답을 실측하기 전에는 고칠 수 없다. FIELD-0a(사진 1장 EXIF + KMZ 임포트)가
정확히 이 두 값을 확정하는 세션이다. 지금 다른 추정값으로 바꾸는 것은 미검증 상수를 다른
미검증 상수로 바꾸는 것이라 상태가 나아지지 않고, "고쳤다"는 인상만 남긴다.

**그러나 "값을 바꾸는 것"과 "미검증임을 알리는 것"은 다르다.** 후자는 소프트웨어만으로
가능하고, 지금 빠져 있다 — 상세는 Task 10.

**2. 새 Core 라우터가 필요한 화면들 — ADR-KSI-020 §5 동결 대상.**
`/coming-soon/fleet`(장비 등록부·연결 상태), `/coming-soon/data`(데이터셋·모델 레지스트리),
`/assets` 의 자산대장, `/reports` 의 보고서 카탈로그·발행 이력, `/settings` 의 계정·조직·역할
설정, `/world` 의 3D 뷰 — 전부 Core 에 라우터 자체가 없다. 만드는 순간 "새 기능"이라
동결에 걸린다. **다만 이 화면들은 지금 mock 으로 위장하고 있지 않다**(INV-040 준수 확인:
미구현을 명시 고지 + 대체 행동 링크 제공 + 가짜 데이터 0건). 즉 지금 상태가 정직하며,
동결 해제 전까지 손대지 않는 것이 옳다.

**3. `/settings` 장비 승급·강등 UI — 동결 경계에 가장 가까워 뺐다.**
Core 에 `POST /v1/equipment-support`·`PATCH /v1/equipment-support/{class_id}` 가 이미 있고
클라이언트 함수만 없어 "API 불필요, 화면만"으로 보인다. 그러나 화면 코드 주석이 그 부재
이유를 **"EQUIPMENT_SUPPORT_APPROVE(ADMIN 전용) 권한 표면이고 증거 첨부 흐름과 함께
별도로 설계해야 한다"** 고 밝히고 있다 — 근거 있는 의도적 유보다. 증거 첨부 흐름 설계
없이 승급 버튼만 붙이는 것이 동결이 막으려는 바로 그 종류의 일이다.

### 이 계획이 끝나도 남는 것 — 그리고 진짜 다음 관문

이 계획을 전부 끝내도 제품이 "완성"되지 않는다. 남는 것은 **FIELD-0a 하나에 걸린 사슬**이다:

```
FIELD-0a (조종기만 있으면 됨 · 비행 없음 · 매니폴드 불필요)
  ├→ high 리스크 2건(카메라 상수 · droneEnumValue) 닫힘
  └→ FIELD-1(첫 실제 매핑 비행) 열림
       └→ FIELD-2(현장 폐루프 실증) → FIELD-3(지형추종)
```

`ADR-KSI-020 §5`가 "FIELD-0a는 조종기만 있으면 오늘 할 수 있고, FIELD-1의 유일한
전제"라고 명시한다. **소프트웨어 작업으로는 이 사슬을 앞당길 수 없다.**

---

## File Structure

**신규 생성**

| 파일 | 책임 |
|---|---|
| `apps/dashboard/test/evidence-panel-wiring.test.ts` | 분할뷰가 전체 화면과 같은 증거 컴포넌트를 쓰는지 고정 |

**수정**

| 파일 | 무엇을 |
|---|---|
| `services/core/src/ksi_core/evidence.py` | `EvidenceVerdict.CONTENT_DIGEST_MISMATCH` 추가 |
| `services/core/src/ksi_core/events.py` | 확정 digest 되읽기 + 열람 전 재검증 |
| `services/core/src/ksi_core/source_media.py` | claim 기반 digest 진입점 추가(매니페스트 SSOT 유지) |
| `tools/upload_source_bundle.py` | 재실행 수렴 판정을 장수 → 내용 digest 로 |
| `edge/manifold-runtime/tests/edge_runtime_tests.cpp` | skip 집계 + 요약 출력 + 강제 스위치 |
| `edge/manifold-runtime/CMakeLists.txt` | `KSI_REQUIRE_SQLITE` 옵트인 스위치 |
| `services/change-detection/src/ksi_change_detection/region_extraction.py` | 도달 불가 방어분기임을 docstring·pragma 로 명시 |
| `apps/dashboard/src/app/events/EventDetailPanel.tsx` | 자리표시 → `EvidencePanel` 재사용 |
| `apps/dashboard/src/components/nav/nav-items.ts` | assets·settings 라벨을 내용에 맞춤 |
| `apps/dashboard/src/components/nav/page-title.ts` | 위 라벨과 동기화 |
| `apps/dashboard/src/app/coming-soon/[section]/page.tsx` | 도달 불가 죽은 설명 문자열 정리 |
| `apps/dashboard/src/lib/core-api/labels.ts` | 새 오류 코드 사람 말 라벨 |
| `contracts/api/openapi-core.yaml` | 증거 열람 GET 에 409 응답 문서화 |
| `pyproject.toml` | mypy exclude 에 `^design/` 추가 |
| `docs/goals/REMAINING_WORK_PLAN.md` · `docs/goals/PHASE_REGISTRY.yaml` | 원장과 어긋난 서술 정정 |
| `apps/dashboard/test/nav-items.test.ts` | 라벨 문자열 고정 → key 고정으로 전환 |
| `tests/contract/test_evidence.py` · `tests/contract/test_upload_source_bundle.py` · `services/change-detection/tests/test_region_extraction.py` | 회귀 테스트 추가 |

---

## Task 1: 확정된 증거 바이트가 교체되면 열람을 거부한다

**닫는 리스크:** `evidence-artifact-content-not-bound-to-registration` (severity medium, open)

**왜 지금 하나:** CRITICAL 확정은 RiskField 원문 바이트를 읽어 SHA-256 을 계산하고
`evidenceSnapshot.riskFieldVerification.contentSha256` 에 못박는다
(`events.py:624-644` → `:1250`). 그런데 **그 값을 되읽는 production 코드가 한 줄도 없다** —
grep 결과 reader 는 테스트 단언 2곳(`tests/contract/test_evidence.py:462,517`)뿐이다.
동시에 열람 경로(`events.py:1787` `view_evidence`)는 `object_key` 만 꺼내 presigned GET URL
을 발급한다. 결과: 확정 이후 같은 object_key 의 바이트가 교체되면 열람 경로는 교체본을
"확정된 CRITICAL 증거"로 계속 내준다.

**지키는 불변식:** INV-021(불확실성 포함해도 위험조건 유지될 때만 Confirmed 승격 — 확정
근거가 확정 순간의 바이트에 계속 묶여야 그 판정이 사후에 달라지지 않는다),
INV-040(fail-closed — digest 불일치를 조용히 통과시키는 현재 동작이 always-go 다).

**Files:**
- Modify: `services/core/src/ksi_core/evidence.py` (`EvidenceVerdict`, 약 58-68행)
- Modify: `services/core/src/ksi_core/events.py` (`_EVIDENCE_STATUS` 180-189행,
  `_verify_critical_evidence` 뒤 653행 앞, `view_evidence` 1787-1814행, `__all__` 1826행)
- Modify: `apps/dashboard/src/lib/core-api/labels.ts` (약 289행 증거 경로 블록)
- Modify: `contracts/api/openapi-core.yaml` (1101-1131행 GET 블록)
- Test: `tests/contract/test_evidence.py`

**Interfaces:**
- Consumes: `EventStore.get_evidence`, `EvidenceStorage.get_bytes`/`presigned_get`,
  `EventRecord.transitions` (확정 전이 레코드의 `evidenceSnapshot.riskFieldVerification`)
- Produces: `PinnedEvidenceContent` dataclass (`artifact_id: str`, `object_key: str`,
  `content_sha256: str`, `content_length_bytes: int`, `pinned_at: str`),
  `EventStore.pinned_evidence_content(event_key: str, artifact_id: str) -> PinnedEvidenceContent | None`,
  `EvidenceVerdict.CONTENT_DIGEST_MISMATCH` → HTTP 409

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_evidence.py` 끝에 추가한다. 이 파일의 기존 픽스처·헬퍼만 쓴다 —
`store`/`storage` 픽스처(`:225-235`), `_project_critical_finding`(`:152`),
`_register_critical_artifacts`(`:195`), `_risk_field_payload`(`:170`), `_client`(`:237`),
`_auth`(`:248`), `payload_digest`. **새 import·새 픽스처 없음**(`json`·`hashlib` 은 이미
이 파일이 import 한다).

```python
def test_confirmed_evidence_is_refused_when_the_bytes_are_swapped_afterwards(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    """[핵심] 확정이 못박은 바이트와 지금 저장소의 바이트가 다르면 열람을 거부한다.

    확정 시점 검증이 아무리 촘촘해도 그 검증은 확정 순간의 바이트에만 결속된다.
    이후 같은 object_key 가 교체되면(스토리지 자격증명 보유자·잘못된 운영 스크립트·
    버킷 정책 사고) 열람 경로는 교체본을 '확정된 CRITICAL 증거'로 계속 내준다.
    스토리지 장애(503)와 바이트 교체(409)는 다른 사실이므로 코드도 달라야 한다.
    """
    _project_critical_finding(store)
    raw = _register_critical_artifacts(store, storage)
    before = store.get("dev-1::evt-1")
    assert before is not None
    client = _client(store, storage, tmp_path)

    confirm = client.post(
        "/v1/events/dev-1::evt-1/transitions",
        json={
            "targetStatus": "CONFIRMED_EVENT",
            "reason": "RiskField 원문과 현장 증거 확인",
            "expectedBundleDigest": payload_digest(before.bundle),
        },
        headers=_auth(),
    )
    assert confirm.status_code == 200

    # 확정 직후에는 열린다 — 재검증이 정상 경로를 막지 않는다는 대조군이다.
    assert client.get("/v1/events/dev-1::evt-1/evidence/risk-1", headers=_auth()).status_code == 200

    # 같은 object_key 의 바이트만 갈아끼운다(길이도 digest 도 달라진다).
    risk_artifact = store.get_evidence("dev-1::evt-1", "risk-1")
    assert risk_artifact is not None
    swapped = json.dumps(
        _risk_field_payload(riskModel={
            "policyId": "critical-person-proximity-v1",
            "severity": 0.11,
            "predictionHorizonSeconds": 5.0,
        }),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert swapped != raw
    storage.put_bytes(risk_artifact.object_key, swapped, content_type="application/json")

    refused = client.get("/v1/events/dev-1::evt-1/evidence/risk-1", headers=_auth())
    assert refused.status_code == 409
    assert refused.json()["detail"] == "CONTENT_DIGEST_MISMATCH"


def test_evidence_without_a_pinned_digest_is_still_viewable(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    """확정된 적 없는(=못박힌 digest 가 없는) 증거는 재검증 대상이 아니다.

    이 재검증은 확정이 실제로 해싱한 artifact 하나에만 걸린다. 확정 전 증거나
    clip 처럼 해싱된 적 없는 증거까지 막으면 정상 열람이 죽는다.
    """
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    # 확정 전이를 부르지 않는다 — evidenceSnapshot 자체가 없다.
    response = _client(store, storage, tmp_path).get(
        "/v1/events/dev-1::evt-1/evidence/clip-01", headers=_auth()
    )
    assert response.status_code == 200
```

> 실행자 주의: `_register_critical_artifacts` 는 `risk-1` 의 바이트만 스토리지에 넣는다
> (`:222-224`). `clip-01` 은 등록만 되고 바이트가 없으므로, 두 번째 테스트가 열람 URL
> 발급 단계에서 `get_bytes` 를 타지 않아야 통과한다 — 못박힌 digest 가 없으면 재검증을
> 아예 건너뛰는 Step 6 의 `if pinned is not None:` 가드가 그 성질을 만든다. 두 번째
> 테스트가 503 을 내면 그 가드가 빠진 것이다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_evidence.py -v -k "bytes_swapped_afterwards or unpinned_evidence"
```
기대: 첫 번째가 FAIL(200 이 나옴 — 지금은 교체본을 그대로 내준다), 두 번째는 PASS.

- [ ] **Step 3: `EvidenceVerdict` 에 새 사유를 추가한다**

`services/core/src/ksi_core/evidence.py` (약 58-68행):

```python
    UNKNOWN_ARTIFACT = "UNKNOWN_ARTIFACT"
    ALREADY_TOMBSTONED = "ALREADY_TOMBSTONED"
    # 확정이 못박은 바이트와 지금 그 자리에 있는 바이트가 다르다 — "없음"도
    # "폐기됨"도 아닌 세 번째 사실이다. 이 셋을 한 코드로 뭉개면 사고 조사에서
    # 스토리지 사고와 증거 조작을 구분할 수 없다.
    CONTENT_DIGEST_MISMATCH = "CONTENT_DIGEST_MISMATCH"
```

- [ ] **Step 4: 상태코드 매핑을 추가한다**

`services/core/src/ksi_core/events.py` `_EVIDENCE_STATUS` (180-189행). 409 는 이 모듈의
"상태 충돌" 관례다(`DUPLICATE_ARTIFACT` 가 이미 409 — `:186`).

**한 줄만** 추가한다(`ALREADY_TOMBSTONED` 앞):

```python
    EvidenceVerdict.CONTENT_DIGEST_MISMATCH: 409,
```

`DUPLICATE_ARTIFACT: 409` 는 **이미 있다**(`:186`) — 다시 적지 마라. 같은 key 를 두 번 쓰면
Python 은 안 깨지고 마지막 값이 이기지만, 리뷰에서 "왜 두 번 있지"를 매번 다시 묻게 된다.

- [ ] **Step 5: 못박힌 digest 를 되읽는 경로를 만든다**

`events.py` 의 `_verify_critical_evidence` 바로 뒤, `class EventStore:`(653행) 앞에 삽입:

```python
@dataclass(frozen=True, slots=True)
class PinnedEvidenceContent:
    """CRITICAL 확정이 못박은 증거 바이트의 신원 — 이후 열람이 대조하는 기준.

    확정 시점 ``evidenceSnapshot.riskFieldVerification`` 에 굳은 값을 그대로
    되읽은 것이다(``_verify_critical_evidence`` 가 쓴 그 자리). 그 값이 기록만
    되고 아무도 읽지 않으면, 같은 object_key 의 바이트가 확정 뒤 교체돼도 열람
    경로는 그것을 확정된 증거로 계속 내준다
    (risk evidence-artifact-content-not-bound-to-registration).
    """

    artifact_id: str
    object_key: str
    content_sha256: str
    content_length_bytes: int
    pinned_at: str


def _pinned_evidence_content(
    record: EventRecord, artifact_id: str
) -> PinnedEvidenceContent | None:
    """확정 전이 레코드에서 이 artifact 에 못박힌 바이트 신원을 되읽는다.

    최신 레코드부터 훑는다 — 확정은 종단이라 사실상 한 건이지만, 거꾸로 읽는
    것이 "마지막으로 확정된 사실"이라는 의미와 맞는다. 형식이 어긋난 스냅샷
    (이 필드가 없던 시절의 원장·오염)은 **없는 것으로 본다**: 여기서 예외를
    던지면 증거 열람 표면 전체가 500 이 되고, 그 실패는 "바이트가 바뀌었다"와
    구분되지 않는다. 대신 재검증에서 빠졌다는 사실을 로그로 남긴다.
    """
    for entry in reversed(record.transitions):
        if entry.get("kind") != "event-transitioned":
            continue
        snapshot = entry.get("evidenceSnapshot")
        if not isinstance(snapshot, dict):
            continue
        verification = snapshot.get("riskFieldVerification")
        if not isinstance(verification, dict) or verification.get("artifactId") != artifact_id:
            continue
        object_key = verification.get("objectKey")
        digest = verification.get("contentSha256")
        length = verification.get("contentLengthBytes")
        pinned_at = verification.get("verifiedAt")
        if not (
            isinstance(object_key, str)
            and isinstance(digest, str)
            and isinstance(length, int)
            and isinstance(pinned_at, str)
        ):
            logger.warning(
                "확정 스냅샷의 형식이 어긋나 재검증에서 제외한다 — artifactId=%s", artifact_id
            )
            return None
        return PinnedEvidenceContent(
            artifact_id=artifact_id,
            object_key=object_key,
            content_sha256=digest,
            content_length_bytes=length,
            pinned_at=pinned_at,
        )
    return None
```

`EventStore` 에 얇은 조회 메서드를 하나 붙인다(라우터가 `EventRecord` 내부 구조를 직접
파헤치지 않게 한다 — 이 모듈의 기존 `get_evidence` 와 같은 층):

```python
    def pinned_evidence_content(
        self, event_key: str, artifact_id: str
    ) -> PinnedEvidenceContent | None:
        """확정이 못박은 바이트 신원 — 없으면 None(재검증 대상 아님)."""
        with self._lock:
            record = self._events.get(event_key)
            if record is None:
                return None
            return _pinned_evidence_content(record, artifact_id)
```

**`with self._lock:` 을 빼지 마라.** 이 클래스의 docstring(`:653-658`)이 "판정+append+메모리
반영을 한 임계구역으로 묶는다"고 명시하고, 기존 읽기 메서드가 전부 그렇게 돼 있다
(`get_evidence:1428-1433`, `get:1437-1440`). CPython 에서 `dict.get` 자체는 원자적이라
당장 깨지지는 않지만, "이 모듈의 읽기는 전부 락 안에서 돈다"는 불변식을 깨면 다음에 이
메서드를 확장하는 사람이 락 없이 여러 필드를 읽는다.

- [ ] **Step 6: 열람 직전 재검증을 넣는다**

`events.py` `view_evidence`(1787-1814행)의 `url = storage.presigned_get(...)` 바로 앞:

```python
        # 확정이 못박은 digest 를 여기서 되읽어 대조한다 — 그 값이 기록만
        # 되고 아무도 읽지 않으면, 같은 object_key 의 바이트가 확정 뒤 교체돼도
        # 열람은 그것을 확정된 증거로 계속 내준다. 대상은 확정이 실제로 해싱한
        # artifact 하나뿐이라 영상·점군을 매 열람마다 읽지 않는다.
        pinned = store.pinned_evidence_content(event_key, artifact_id)
        try:
            if pinned is not None:
                mismatch = _verify_pinned_evidence_content(
                    storage, pinned, object_key=artifact.object_key
                )
                if mismatch is not None:
                    logger.error(
                        "확정된 증거 바이트가 교체됐다 — eventKey=%s artifactId=%s: %s",
                        event_key,
                        artifact_id,
                        mismatch,
                    )
                    raise HTTPException(
                        status_code=_EVIDENCE_STATUS[EvidenceVerdict.CONTENT_DIGEST_MISMATCH],
                        detail=EvidenceVerdict.CONTENT_DIGEST_MISMATCH.value,
                    )
            url = storage.presigned_get(artifact.object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=503, detail="EVIDENCE_STORAGE_UNAVAILABLE") from exc
```

대조 헬퍼는 `_pinned_evidence_content` 바로 뒤에 둔다:

```python
def _verify_pinned_evidence_content(
    storage: EvidenceStorage, pinned: PinnedEvidenceContent, *, object_key: str
) -> str | None:
    """어긋난 사유를 문자열로, 일치하면 None.

    object_key 자체가 바뀐 경우도 잡는다 — 바이트를 읽기 전에 걸러 불필요한
    다운로드를 피한다.
    """
    if object_key != pinned.object_key:
        return f"objectKey 가 다르다: 확정={pinned.object_key} 현재={object_key}"
    raw = storage.get_bytes(object_key)
    if len(raw) != pinned.content_length_bytes:
        return f"길이가 다르다: 확정={pinned.content_length_bytes} 현재={len(raw)}"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pinned.content_sha256:
        return f"digest 가 다르다: 확정={pinned.content_sha256} 현재={digest}"
    return None
```

`__all__`(1826행)에 알파벳 순서상 `"EventVerdict",` 다음에 `"PinnedEvidenceContent",` 추가.

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_evidence.py -v -k "bytes_swapped_afterwards or unpinned_evidence"
```
기대: 둘 다 PASS.

- [ ] **Step 8: 계약 문서와 화면 문구를 맞춘다**

`contracts/api/openapi-core.yaml` (1101-1131행), `responses` 의 `'404'` 와 `'410'` 사이:

```yaml
        '409': { description: CONTENT_DIGEST_MISMATCH — 확정 시점에 못박은 바이트와 다르다 }
```

같은 operation 의 `description` 마지막에:

```yaml
        CRITICAL 확정이 그 바이트의 SHA-256 을 못박은 증거는 **URL 발급 전에 Core 가
        다시 읽어 재해싱**한다 — 확정 이후 같은 object_key 의 바이트가 교체되면
        409(CONTENT_DIGEST_MISMATCH)로 거부하고 열람 URL 을 내주지 않는다.
```

`apps/dashboard/src/lib/core-api/labels.ts` (약 289행 증거 경로 블록):

```ts
  ALREADY_TOMBSTONED: "보관 기간이 지나 폐기된 증거입니다.",
  CONTENT_DIGEST_MISMATCH:
    "확정 당시 기록된 파일과 저장소의 파일이 다릅니다. 이 증거는 열 수 없습니다.",
```

- [ ] **Step 9: 회귀와 정적 검사를 돌린다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_evidence.py tests/contract/test_events_triage.py tests/contract/test_api_contract_sync.py -v
uv run ruff check . && uv run mypy packages services tests tools
cd apps/dashboard && npx tsc --noEmit && npm run test
```
전부 PASS 여야 한다. `test_api_contract_sync.py` 가 깨지면 openapi 편집이 스키마 필드를
건드린 것이다 — 이 Task 는 필드를 추가하지 않으므로 되돌아가 확인한다.

- [ ] **Step 10: 이 수정이 닫지 않는 것을 코드에 남긴다**

`view_evidence` 의 재검증 블록 위 주석에 다음 세 줄을 덧붙인다. 다음 세션이 이 재검증을
"증거 위변조가 전부 막혔다"로 오독하지 않게 하는 것이 목적이다.

```python
        # 남는 창 셋 — 이 재검증이 닫지 않는다:
        #  (1) presigned GET 발급~클라이언트 실제 GET 사이(TTL). Core 가 바이트를
        #      중계하지 않는 한 서버가 없앨 수 없다(ADR-KSI-010 §1).
        #  (2) clips·trajectory·viewpointHistory 는 확정 시점에 해싱되지 않아
        #      못박힌 digest 자체가 없다 → 재검증 대상이 아니다.
        #  (3) 아무도 열지 않으면 교체는 탐지되지 않는다(정기 스윕은 별도 과제).
```

- [ ] **Step 11: 커밋**

```bash
git add services/core/src/ksi_core/evidence.py services/core/src/ksi_core/events.py \
  apps/dashboard/src/lib/core-api/labels.ts contracts/api/openapi-core.yaml \
  tests/contract/test_evidence.py
git commit -m "fix(core): 확정된 증거 바이트가 교체되면 열람을 409로 거부한다

확정이 못박은 contentSha256 을 되읽는 코드가 없어, 같은 object_key 의 바이트가
확정 뒤 교체돼도 열람 경로가 교체본을 확정된 증거로 계속 내주고 있었다.
열람 URL 발급 직전에 재해싱해 대조하고, 어긋나면 CONTENT_DIGEST_MISMATCH 로
fail-closed 한다(INV-021·INV-040).

risk: evidence-artifact-content-not-bound-to-registration"
```

---

## Task 2: 재실행 수렴 판정을 장수에서 내용 지문으로 바꾼다

**닫는 리스크:** `source-media-sealed-bundle-identity-count-only` (severity low, open)

**왜 지금 하나:** 각 미디어의 sha256·화소수·바이트수·contentType 은 **이미 원장에 있고**,
그 전부를 정규 정렬해 해싱한 `sourceBundleDigest` 도 **이미 봉인 시점에 계산돼 조회 API 로
노출돼 있다**. 그런데 `tools/upload_source_bundle.py:251` 의 재실행 수렴 판정만 그 지문을
안 쓰고 `mediaCount` 를 쓴다. 같은 임무에 다른 사진 묶음이 이미 봉인돼 있는데 장수만
우연히 같으면, 재실행이 종료코드 0 으로 "이미 완료"를 보고한다. 그 임무의 재구성은 먼저
봉인된 묶음으로 이미 돌았고 산출물 계보(INV-051)의 앵커도 그 묶음의 digest 인데, 운용자는
방금 넣은 사진이 반영됐다고 믿는다.

**서버 쪽에는 결함이 없다** — 봉인 후 등록은 이미 `BUNDLE_SEALED` 로 거부하고
(`source_media.py:660-664`), 재생도 digest 를 재계산해 위조를 막는다(`:538-546`).
고칠 것은 도구의 판정 기준과, 그 판정에 필요한 정보를 판정 시점까지 끌어오는 순서다.

**Files:**
- Modify: `services/core/src/ksi_core/source_media.py` (`compute_source_bundle_digest` 362행 앞,
  `__all__` 1283-1312행)
- Modify: `tools/upload_source_bundle.py` (import 68행 아래, 모듈 docstring 42행 문단 뒤,
  수렴 판정 251행)
- Test: `tests/contract/test_upload_source_bundle.py`, `tests/contract/test_source_media.py`

**Interfaces:**
- Consumes: `SourceMediaClaim`(`media_id`, `sha256`, `size_bytes`, `width`, `height`,
  `content_type`), `SourceMediaRecord.claim` 프로퍼티(`source_media.py:253-263`),
  `sha256_digest`, `canonical_payload_bytes`
- Produces: `compute_source_bundle_digest_from_claims(mission_id: str, claims: Iterable[SourceMediaClaim]) -> str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/contract/test_upload_source_bundle.py` 의 기존
`test_rerun_with_different_photo_count_stays_a_failure`(466-499행) **바로 뒤**에 넣는다.
그 파일의 모듈 수준 헬퍼만 쓴다 — `_RecordingStorage`(65행), `_StorageUploads`(99행),
`_client`(152행), `_photos`(139행), `_MISSION_ID`(52행), `run_sync`(46-50행 import),
`Image`(43행 import). **새 import·새 픽스처 없음.**

```python
def test_rerun_with_the_same_count_but_different_photos_stays_a_failure(tmp_path: Path) -> None:
    """[핵심] 장수가 같아도 **내용이 다르면** 수렴이 아니라 실패다.

    장수만 대조하면 이 경우가 조용히 "이미 완료"로 성공 보고된다 — 그 임무의 재구성은
    먼저 봉인된 다른 묶음으로 이미 돌았는데, 운용자는 방금 넣은 사진이 반영됐다고
    믿는다. 수렴 판정 기준이 mediaCount 가 아니라 sourceBundleDigest 여야 하는 이유다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    photo_dir = tmp_path / "photos"
    _photos(photo_dir, 3)
    state_dir = tmp_path / "state"

    first = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=photo_dir,
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )
    assert first.sealed is True

    # 같은 3장이 아니라 **다른 3장**으로 갈아끼운다(장수는 그대로 3).
    for path in sorted(photo_dir.iterdir()):
        path.unlink()
    for index in range(3):
        Image.new("RGB", (64, 48), color=(7, index * 30 % 256, 200)).save(
            photo_dir / f"OTHER_{index:04d}.jpg", "JPEG"
        )

    uploads = _StorageUploads(storage)
    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=photo_dir,
        state_dir=state_dir,
        seal=True,
        start_reconstruction=True,
        put_object=uploads,
    )

    assert outcome.already_complete is False
    assert outcome.failures, "장수가 같은 다른 묶음인데도 수렴으로 접혔다"
```

(`SyncOutcome`(`tools/upload_source_bundle.py:117-135`)에는 `exit_code` 필드가 없다 —
실패는 `failures` 가 비어 있지 않은 것으로 표현하고, `ok` 프로퍼티가 `not self.failures` 다.
바로 위 `test_rerun_with_different_photo_count_stays_a_failure:498-499` 가 정확히 이 형태로
단언한다.)

`tests/contract/test_source_media.py` 에는 두 진입점이 같은 digest 를 내는지 고정한다:

```python
def test_the_two_digest_entry_points_agree(...) -> None:
    """레코드 기반과 claim 기반이 같은 digest 를 낸다 — 매니페스트 구성이 한 곳이라는 뜻.

    업로더가 매니페스트를 자기 손으로 다시 짜면 한쪽만 바뀌는 순간 그 대조가
    조용히 무의미해진다. 두 진입점이 같은 함수에 위임하는지 이 테스트가 고정한다.
    """
    assert compute_source_bundle_digest(mission_id, records) == (
        compute_source_bundle_digest_from_claims(mission_id, [r.claim for r in records])
    )
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_upload_source_bundle.py -v -k same_count_but_different_photos
```
기대: FAIL — 지금은 장수가 같아 "이미 완료"로 수렴해 `outcome.failures` 가 비어 있다.

- [ ] **Step 3: claim 기반 digest 진입점을 만든다**

`services/core/src/ksi_core/source_media.py` 의 `compute_source_bundle_digest`(362행)
**바로 앞**에 삽입:

```python
def compute_source_bundle_digest_from_claims(
    mission_id: str, claims: Iterable[SourceMediaClaim]
) -> str:
    """등록 **전** 단계에서도 부를 수 있는 digest — 매니페스트 구성의 SSOT.

    :func:`compute_source_bundle_digest` 가 이 함수에 위임한다. 진입점이 둘인 이유는
    업로더(``tools/upload_source_bundle.py``)가 "내가 들고 있는 이 묶음이 이미 봉인된
    그 묶음인가"를 판정해야 하는데, 그 시점에는 아직 :class:`SourceMediaRecord`
    (객체 키·등록 시각)가 없기 때문이다. 업로더가 매니페스트를 자기 손으로 다시 짜면
    한쪽만 바뀌는 순간 그 대조가 조용히 무의미해진다 — 그래서 **같은 함수**를 부르게
    한다(``compare_measurements`` 를 live·재생 공용 판정으로 둔 것과 같은 이유).
    """
    manifest: dict[str, Any] = {
        "missionId": mission_id,
        "media": sorted(
            (
                {
                    "mediaId": claim.media_id,
                    "sha256": claim.sha256,
                    "bytes": claim.size_bytes,
                    "width": claim.width,
                    "height": claim.height,
                    "contentType": claim.content_type,
                }
                for claim in claims
            ),
            key=lambda entry: entry["mediaId"],
        ),
    }
    return sha256_digest(canonical_payload_bytes(manifest))
```

기존 `compute_source_bundle_digest` 는 **docstring 을 그대로 두고 본문만** 교체
(363-392행의 docstring 유지, 375-392행의 manifest 구성 삭제):

```python
    return compute_source_bundle_digest_from_claims(mission_id, (record.claim for record in media))
```

`__all__`(1283-1312행)에 알파벳 순서대로:

```python
    "compute_source_bundle_digest",
    "compute_source_bundle_digest_from_claims",
```

- [ ] **Step 4: 두 진입점이 같은 digest 를 내는지 먼저 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_source_media.py -v -k two_digest_entry_points_agree
```
기대: PASS. **여기서 실패하면 다음 단계로 가지 않는다** — 위임이 기존 digest 를 바꿨다는
뜻이고, 그러면 이미 봉인된 모든 번들의 지문이 어긋난다.

- [ ] **Step 5: 업로더의 수렴 판정을 내용 digest 로 바꾼다**

`tools/upload_source_bundle.py` import(68행 아래):

```python
import httpx
from _digest import sha256_file
from ksi_core.source_media import SourceMediaClaim, compute_source_bundle_digest_from_claims
```
(`tools/enforce_retention.py:30-32`·`tools/retention_scheduler.py:48-51` 이 이미 `ksi_core`
를 최상위 import 하는 관례다.)

모듈 docstring "멱등성" 절(42행 문단) 뒤에 한 문단:

```
재실행이 "이미 완료"로 접히는 근거는 **봉인된 번들의 ``sourceBundleDigest`` 가 이
디렉터리와 같다**는 것 하나뿐이다. 장수가 같다는 것으로는 부족하다 — 같은 장수의
다른 사진 묶음을 올리려는 재실행이 조용히 성공으로 보고되고, 그 임무의 재구성은 이미
다른 입력으로 돌아 있다.
```

**`_sealed_bundle_matches`(`:232-251`)를 장수 대신 지문으로 판정하게 바꾼다.**
docstring 과 `expected_count` 파라미터를 함께 갈아치운다:

```python
def _sealed_bundle_matches(
    client: httpx.Client, *, mission_id: str, expected_digest: str
) -> bool:
    """서버의 봉인된 번들이 우리가 가진 **그 묶음**인가.

    같으면 "이미 다 올려서 봉인까지 끝난 상태"로 본다. 다르면 그건 수렴이 아니라
    **실제 불일치**다(다른 사진 묶음이 이미 그 임무에 봉인돼 있다) — 그때는 조용히
    넘어가지 않고 실패로 남긴다.

    판정 근거는 ``sourceBundleDigest`` 다. 장수로는 부족하다 — 같은 장수의 다른
    묶음을 올리려는 재실행이 조용히 성공으로 보고되고, 그 임무의 재구성은 이미 다른
    입력으로 돌아 있다(risk source-media-sealed-bundle-identity-count-only).
    """
    try:
        response = client.get(f"/v1/missions/{mission_id}/source-media")
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        bundle = response.json()
    except ValueError:
        return False
    return bool(
        bundle.get("status") == "SEALED"
        and bundle.get("sourceBundleDigest") == expected_digest
    )
```

호출처(`:306-308`)의 주석과 인자를 바꾼다 — 기존 주석이 스스로 "장수가 같아도 내용이 다를
가능성은 남는다"고 적어둔 자리다:

```python
            # 이미 봉인된 번들에 다시 올리려 한 것은 **대개 재실행이 목표 상태에
            # 이미 도달했다는 뜻**이다 — 주기 실행이 첫 성공 이후 영원히 실패로
            # 뜨는 것을 막으려면 이것을 실패로 다루면 안 된다. 다만 "봉인돼 있다"만
            # 으로는 내용이 같다고 말할 수 없어, **번들 지문까지 대조해서 같을 때만**
            # 수렴으로 본다. 장수 대조로는 같은 장수의 다른 묶음을 걸러내지 못했다.
            if _is_bundle_sealed_response(response) and _sealed_bundle_matches(
                client, mission_id=mission_id, expected_digest=local_bundle_digest
            ):
```

**`local_bundle_digest` 를 만드는 순서 변경이 이 Task 의 진짜 작업이다.** 지금
`_register_and_upload` 는 claim 을 **배치 루프 안에서** 만들어(`:270-272`), 첫 배치가 거부되는
시점에 도구가 아는 것은 `outcome.discovered`(개수)뿐이다. 전체 claim 을 루프 **앞에서**
만들어야 지문을 계산할 수 있다.

다행히 `_build_claim`(`:159-168`)이 돌려주는 dict 는 **매니페스트 항목과 정확히 같은 모양**
이다(`mediaId`·`sha256`·`bytes`·`width`·`height`·`contentType`). 그래서 Core 의 claim 기반
digest 함수에 그대로 먹일 수 있다 — `SourceMediaClaim` 은 frozen dataclass 이므로 키 이름만
바꿔 생성한다:

```python
def _local_bundle_digest(mission_id: str, claims: list[dict[str, Any]]) -> str:
    """이 디렉터리가 만들 번들의 지문 — 서버의 sourceBundleDigest 와 같은 규칙이다.

    매니페스트 구성은 Core 함수 하나가 SSOT 다. 여기서 다시 짜면 한쪽만 바뀌는
    순간 이 대조가 조용히 무의미해진다.
    """
    return compute_source_bundle_digest_from_claims(
        mission_id,
        [
            SourceMediaClaim(
                media_id=claim["mediaId"],
                sha256=claim["sha256"],
                size_bytes=claim["bytes"],
                width=claim["width"],
                height=claim["height"],
                content_type=claim["contentType"],
            )
            for claim in claims
        ],
    )
```

> 실행자 주의 셋:
> 1. 루프 앞으로 옮긴 claim 생성이 **기존 배치 업로드 동작을 바꾸면 안 된다.** 특히
>    `_build_claim` 실패 시 "파일 하나의 실패로 배치 전체를 죽이지 않는다"는 기존 처리
>    (`:272-278`)를 그대로 보존한다 — 실패한 파일은 지문 계산에서도 빠지고, 그러면 지문이
>    서버와 달라 수렴하지 않는다. **그것이 옳은 동작이다**(일부만 올라간 묶음을 완료로
>    보지 않는다).
> 2. 순서 변경 후 같은 파일의 기존 테스트 `test_rerun_*` 계열을 **전부** 돌려 확인한다.
> 3. `expected_count` 파라미터가 사라지므로 `outcome.discovered` 를 이 판정에 쓰던 다른
>    자리가 없는지 grep 한다.

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_upload_source_bundle.py tests/contract/test_source_media.py -v
```
기대: 신규 2건 PASS + 기존 전부 PASS(특히 `test_rerun_*` 계열).

- [ ] **Step 7: 정적 검사**

```bash
uv run ruff check . && uv run mypy packages services tests tools
```

- [ ] **Step 8: 커밋**

```bash
git add services/core/src/ksi_core/source_media.py tools/upload_source_bundle.py \
  tests/contract/test_upload_source_bundle.py tests/contract/test_source_media.py
git commit -m "fix(tools): 재실행 수렴 판정을 장수에서 번들 내용 지문으로 바꾼다

같은 임무에 다른 사진 묶음이 봉인돼 있어도 장수만 같으면 재실행이 조용히
'이미 완료'로 성공 보고했다. 판정 근거를 sourceBundleDigest 로 바꾸고,
업로더가 매니페스트를 다시 짜지 않도록 Core 의 digest 함수에 위임한다.

risk: source-media-sealed-bundle-identity-count-only"
```

---

## Task 3: Edge 테스트의 무음 skip 을 초록불과 구분되게 만든다

**닫는 리스크:** `edge-runtime-tests-silently-skip-without-sqlite` (severity low, open)

**왜 지금 하나:** 두 결함이 겹쳐 "검사 미수행"이 "통과"와 구별되지 않는다.
① 러너에 skip 개념이 없다 — `g_checks`/`g_failures` 두 카운터뿐이고 종료코드는
`g_failures == 0` 하나로 결정된다(`edge_runtime_tests.cpp:3929-3934`). 게다가 10개 skip
지점 중 5곳은 `Check(true, "... (skipped on this host)")` 라는 위약 단언으로 **skip 을 통과
카운트로 둔갑**시킨다(`:2613`, `:2759`, `:2958`, `:3024`, `:3076`).
② CMake 가 SQLite 부재를 조용히 삼킨다 — `find_package(SQLite3 QUIET)` + `message(STATUS ...)`
는 `cmake --build` 로그에 남지 않는다(`CMakeLists.txt:154-159`).

이 저장소는 같은 실패 클래스를 이미 두 번 겪었다: 러너에 ripgrep 이 없어 reference 가드가
조용한 no-op 이던 사고(`ci.yml:57-60` 주석), 그리고 실모델 게이트 82건 무음 skip
(`tests/conftest.py` 상단). 후자는 `KSI_REQUIRE_REAL_MODEL=1` 앵커로 이미 해결돼 있다.

**방향 선택 — (b) skip 집계 + 요약 출력 + 옵트인 강제. (a) 빌드 실패는 채택하지 않는다.**

근거 셋:
1. **(a)는 검증 대상 하나를 통째로 없앤다.** `KSI_EDGE_HAVE_SQLITE=0` 경로는 죽은 코드가
   아니라 제품 동작이다 — `store_forward.cpp` 의 `#if KSI_EDGE_HAVE_SQLITE` 분기와
   `kBackendUnavailable` fail-closed 가 그것이고, 현재 4건의 단언이 바로 그 동작을 검증한다
   (`:1462`, `:2101`, `:2006`, `:3500`). CMake 를 REQUIRED 로 바꾸면 그 4건은 어떤 빌드에서도
   컴파일조차 되지 않아 "백엔드 없을 때 fail-closed 한다"는 주장의 근거가 사라진다.
2. **(a)는 명시된 설계 결정을 뒤집는다.** `CMakeLists.txt:155-157` 주석이 "개발 호스트가
   SQLite 개발 헤더를 갖지 않아도 순수 안전 루프 검증은 가능하다"고 근거와 함께 못 박고 있다.
   이 리스크는 severity low 이고, 근거 있는 기존 결정을 뒤집을 사유가 아니다.
3. **(b)는 이 저장소가 이미 쓰는 해법이다.** `KSI_REQUIRE_REAL_MODEL=1` 앵커가 Python
   쪽에서 같은 문제를 정확히 이 형태로 풀었다.

다만 (a)의 강제력은 **옵트인 스위치 `KSI_REQUIRE_SQLITE=ON`** 으로 함께 제공한다 — 게이트
환경은 configure 단계에서 즉시 실패하고, 개발 호스트는 기본값 OFF 로 지금 그대로 빌드된다.

**Files:**
- Modify: `edge/manifold-runtime/tests/edge_runtime_tests.cpp`
- Modify: `edge/manifold-runtime/CMakeLists.txt` (154-159행)

**Interfaces:**
- Produces: `bool SqliteBackendReady(const char* what)` — 준비됐으면 true, 아니면
  `g_skipped_groups` 를 올리고 false. 종료 요약이 skip 개수를 출력하고,
  `KSI_EDGE_TESTS_REQUIRE_SQLITE=1` 이면 skip 이 하나라도 있을 때 非0 종료.

- [ ] **Step 1: 현재 동작을 먼저 관측한다**

먼저 이 저장소에서 edge 테스트를 빌드·실행하는 정확한 명령을 확인한다
(`edge/manifold-runtime/CMakeLists.txt`·`.github/workflows/ci.yml` edge-control-plane job
162행~·`scripts/` 를 읽는다). 그 명령으로 지금 상태를 돌려 **종료코드와 요약 출력**을 기록한다.

```bash
# (확인한 명령으로) 빌드 → 실행
echo "exit=$?"
```
기대(SQLite 헤더 없는 호스트): exit 0, 요약은 `edge runtime tests: N checks passed` 한 줄이고
skip 언급이 없다 — 이것이 고칠 대상이다.

**CI 는 이미 확인됐다(2026-08-17):** `ubuntu-latest` 러너 이미지에 `libsqlite3-dev` 가 들어
있어 edge-control-plane job 은 11개 분기를 **전부 실행한다** — 최신 성공 run 의 configure
로그에 `SQLite3 development package unavailable`(`CMakeLists.txt:159`) 이 한 줄도 없다.
**따라서 이 리스크는 로컬 개발 호스트 한정이다.** 다만 `ci.yml` 에 명시적 apt 설치가 없어
러너 이미지 변경에 노출돼 있다 — Step 5 의 `KSI_REQUIRE_SQLITE=ON` 을 edge-control-plane
configure 스텝에 붙이면 그 노출까지 닫힌다. **이것도 이 Task 에서 함께 한다**(`ci.yml:162-189`
의 configure 스텝에 `-DKSI_REQUIRE_SQLITE=ON` 추가).

- [ ] **Step 2: skip 집계 헬퍼를 추가한다**

`edge/manifold-runtime/tests/edge_runtime_tests.cpp`:

`<string_view>` 도 함께 추가한다 — 현재 include 목록(`:3-22`)에 없고, 이 타깃은
`-Wall -Wextra -Wpedantic -Werror` 로 빌드된다(`CMakeLists.txt:256`). libstdc++ 에서
`<string>` 을 통해 우연히 들어올 수는 있으나 보장이 아니다.

```diff
@@
 #include <cstdio>
+#include <cstdlib>
+#include <string_view>
@@
 int g_failures = 0;
 int g_checks = 0;
+int g_skipped_groups = 0;
@@
 void Check(bool condition, const char* what) {
@@
 }
 
+// SQLite 를 컴파일해 넣지 않은 호스트에서 통째로 건너뛰는 계약 묶음을 집계한다.
+// 조용한 skip 은 "실패 0건"과 종료코드로 구분되지 않아, 초록불이 아무것도 주장하지
+// 않는 상태를 만든다(tests/conftest.py 의 KSI_REQUIRE_REAL_MODEL 앵커와 같은 문제).
+bool SqliteBackendReady(const char* what) {
+    if (ksi::edge::SqliteStoreForward::sqlite_backend_compiled()) {
+        return true;
+    }
+    ++g_skipped_groups;
+    std::fprintf(stderr, "[SKIP] %s — SQLite 백엔드가 이 빌드에 없다\n", what);
+    return false;
+}
```

- [ ] **Step 3: skip 지점 7곳을 바꾼다 — 분기마다 형태가 다르니 일괄 치환 금지**

분기 11곳의 실제 분류(2026-08-17 실측):

| 분류 | 위치 | 처리 |
|---|---|---|
| **제품 fail-closed 검증 3건** — skip 아님 | `:1461/1462`, `:1993→else :2004-2006`, `:3499/3500` | **건드리지 않는다.** CMake 를 REQUIRED 로 바꾸면 안 되는 이유가 이것이다 |
| **자기참조 단언 1건** | `:2100/2101` | 아래 특수 처리 |
| **단순 skip 5건**(위약 단언 포함) | `:2612`, `:2758`, `:2957`, `:3023`, `:3075` | `if (!SqliteBackendReady("<검증하는 성질>")) { return; }` 로 교체 + `Check(true, ...)` 삭제 |
| **긍정형 블록 1건** | `:1730` | 아래 특수 처리 — **`return` 을 넣으면 안 된다** |
| **헬퍼 early-return 1건** | `:2014` | 아래 특수 처리 — 반환형이 `std::string` |

**단순 skip 5건**: `Check(true, "... (skipped on this host)")` 를 삭제하고 조건을 바꾼다.
이 5곳이 파일 전체의 `Check(true` 전부다(`:2613`, `:2759`, `:2958`, `:3024`, `:3076`) —
다섯 곳 모두 바로 뒤에 `return;` 이 있어 함수 전체를 건너뛴다.

**`:1730` 특수 처리 — 여기서 레시피대로 하면 고치려는 결함이 커진다.**
`:1730-1752` 는 `if (sqlite_backend_compiled()) { ... }` **긍정형 블록**이고 `return` 도
`else` 도 없다. 블록이 끝난 `:1754` 부터 SQLite 와 무관한 검사(malformed eventId 거부,
non-canonical digest 거부, presigned URL fail-closed, Bearer 주입 거부 등)가 계속 이어진다.
`if (!SqliteBackendReady(...)) { return; }` 을 넣으면 **SQLite 없는 호스트에서 그 뒤 검사가
전부 조용히 사라진다.** 부정 없이, return 없이 감싼다:

```cpp
    if (SqliteBackendReady("Core REST wire + store-forward 저널 연동")) {
        // 기존 :1731-1751 블록 그대로
    }
    // :1754 이후 검사는 그대로 흐른다 — 여기에 return 을 넣지 마라.
```
`SqliteBackendReady` 는 false 를 돌려줄 때 카운터를 올리므로 이 형태로도 집계는 동작한다.

**`:2014` 특수 처리**: 반환형이 `std::string` 인 헬퍼(`BuildNativeEventPayloadForOracle`)의
early-return 이라 `return;` 이 아니라 **`return {};`** 여야 컴파일된다(`-Werror` 빌드다).

**`:2100/2101` 특수 처리 — 계획 초안이 이걸 "검증"으로 잘못 분류했다.**
`Check(payload.empty(), "native evidence oracle is unavailable without durable SQLite backend")`
가 검사하는 `payload` 는 바로 위 `:2014-2016` 헬퍼가 `if (!sqlite_backend_compiled()) { return {}; }`
로 **무조건 빈 문자열을 돌려준 결과**다. 제품 코드(`NativeCandidateEvidenceBuilder`)는 이
경로에서 한 번도 호출되지 않는다 — 테스트가 자기 픽스처의 early-return 을 단언하는 것이고,
걷어내려는 `Check(true, ...)` 5건과 실질이 같다. `:2014` 와 `:2100` 을 **한 쌍으로 묶어 하나의
skip 그룹으로 집계**하고, `:2101` 의 단언은 삭제한다.

> 초안은 이 4건(`:1462`, `:2006`, `:2101`, `:3500`)을 전부 "제품 검증"이라 적었고, 부정형이
> 아닌 것을 3곳이라 했다. 실측 결과 제품 검증은 3건이고 긍정형은 2곳(`:1730`, `:1993`)이다 —
> `:2014` 는 명백한 부정형이다.

- [ ] **Step 4: 종료 요약과 강제 스위치를 넣는다**

`main` 의 종료 지점(`:3929-3934`). 현재는 이렇다:

```cpp
    if (g_failures == 0) {
        std::printf("edge runtime tests: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "edge runtime tests: %d/%d checks failed\n", g_failures, g_checks);
    return 1;
```

**기존 두 메시지를 없애지 말고** skip 경고를 앞에 끼운다 — CI 가 `--output-on-failure` 로
그 문자열을 본다:

```cpp
    if (g_skipped_groups > 0) {
        std::fprintf(stderr,
                     "[WARN] SQLite 백엔드 없이 %d개 계약 묶음을 건너뛰었다 — "
                     "이 실행은 저장후전달 순서·WAL 복구를 검증하지 않았다.\n",
                     g_skipped_groups);
        if (const char* require = std::getenv("KSI_EDGE_TESTS_REQUIRE_SQLITE");
            require != nullptr && std::string_view(require) == "1") {
            std::fprintf(stderr,
                         "[FAIL] KSI_EDGE_TESTS_REQUIRE_SQLITE=1 인데 건너뛴 묶음이 있다.\n");
            return 1;
        }
    }
    return g_failures == 0 ? 0 : 1;
```

- [ ] **Step 5: CMake 옵트인 스위치를 넣는다 — 삽입 위치가 중요하다**

`edge/manifold-runtime/CMakeLists.txt` 의 실제 구조(2026-08-17 실측):

```
:128  if(KSI_TARGET_MANIFOLD3)
:149  else()
:150      find_package(SQLite3 QUIET)
:151      if(SQLite3_FOUND)
:154      else()
:155-157      # 개발 호스트가 SQLite 개발 헤더를 갖지 않아도 순수 안전 루프 검증은 가능하다. ...
:158          (compile definition)
:159          message(STATUS "ksi_edge_runtime: SQLite3 development package unavailable; ...")
:160      endif()
:161  endif()
```

**초안이 "154-159행 부근"이라 적은 것은 틀렸다** — `find_package` 는 `:150` 이고 154-159 는
안쪽 `else()` 블록이다. 초안 스니펫을 거기 그대로 붙이면 (a) `find_package` 가 중복 호출되고
(b) `option()` 이 `if(KSI_TARGET_MANIFOLD3)` 의 else 분기 **안**에 들어가 `KSI_TARGET_MANIFOLD3=ON`
빌드에서는 옵션이 아예 정의되지 않는다.

**`option()` 은 `:128` 의 if 블록 바깥**(예: `:127` 직전)에 둔다:

```cmake
option(KSI_REQUIRE_SQLITE "SQLite 개발 헤더가 없으면 configure 단계에서 실패한다" OFF)
```

**FATAL_ERROR 검사만** `:154` 의 `else()` 블록 안(기존 주석 `:155-157` 을 **지우지 말고**
그 앞)에 넣는다. 기존 `find_package(SQLite3 QUIET)`(`:150`)를 재사용하고 새로 쓰지 않는다:

```cmake
    else()
      if(KSI_REQUIRE_SQLITE)
        message(FATAL_ERROR
          "KSI_REQUIRE_SQLITE=ON 인데 SQLite3 개발 헤더를 찾지 못했다 — "
          "이 빌드는 저장후전달 순서·WAL 복구 계약을 검증하지 못한다.")
      endif()
      # 개발 호스트가 SQLite 개발 헤더를 갖지 않아도 ... (기존 :155-157 주석 그대로)
```

- [ ] **Step 6: 세 경우를 실제로 돌려 확인한다**

```bash
# (1) SQLite 없음 + 강제 없음 → exit 0, 경고 출력, skipped_groups > 0
<빌드·실행 명령>; echo "exit=$?"

# (2) SQLite 없음 + 강제 → exit 1
KSI_EDGE_TESTS_REQUIRE_SQLITE=1 <실행 명령>; echo "exit=$?"

# (3) CMake 강제 → configure 실패
cmake -S edge/manifold-runtime -B /tmp/ksi-edge-require -DKSI_REQUIRE_SQLITE=ON; echo "exit=$?"
```
기대: (1) exit 0 + `skipped_groups=N` 출력, (2) exit 1, (3) FATAL_ERROR.
SQLite 헤더가 설치된 호스트라면 (1)·(2)는 `skipped_groups=0` 이고 둘 다 exit 0 이며,
(3)은 성공한다 — 그 경우 SQLite 를 일시적으로 감춰 (1)(2)를 재현하거나, 재현할 수 없다면
**그 사실을 커밋 메시지에 적는다**(확인 못 한 것을 확인했다고 하지 않는다).

- [ ] **Step 7: 커밋**

```bash
git add edge/manifold-runtime/tests/edge_runtime_tests.cpp edge/manifold-runtime/CMakeLists.txt
git commit -m "test(edge): SQLite 없는 빌드의 무음 skip 을 초록불과 구분한다

skip 지점이 Check(true, ...) 위약 단언으로 통과 카운트에 섞여 있어, 저장후전달
순서·WAL 복구를 한 번도 검증하지 않은 실행이 exit 0 을 냈다. skip 을 집계해
요약에 출력하고, KSI_EDGE_TESTS_REQUIRE_SQLITE=1 · CMake KSI_REQUIRE_SQLITE=ON
으로 게이트 환경이 강제할 수 있게 한다. 기본값은 그대로라 개발 호스트 빌드는
바뀌지 않는다(백엔드 부재 시 fail-closed 를 검증하는 4건은 그대로 둔다).

risk: edge-runtime-tests-silently-skip-without-sqlite"
```

---

## Task 4: MultiPolygon 결합 분기가 도달 불가 방어코드임을 계약으로 고정한다

**닫는 리스크:** `region-extraction-multipolygon-branch-untested` (severity low, open)

**왜 지금 하나 — 그리고 원 리스크 서술의 정정:** 이 리스크는 "테스트를 안 썼다"로 등재됐지만,
2026-08-17 실측 결과 **`compute_change_regions` 경로에서는 이 분기가 원리적으로 실행되지
않는다.** 근거:

1. 입력 마스크는 항상 단일 8-연결 성분이다 — `mask = labeled == label` 은 `ndimage.label` 이
   낸 한 라벨이고, 4-연결 성분은 8-연결 성분이기도 하다.
2. GDAL(`rasterio.features.shapes`)의 `connectivity=8` 폴리고나이즈는 8-연결 성분 하나를
   **항상 Polygon 하나로** 낸다. 대각선 계단·코너 접촉·도넛·체커보드·300×300 체커보드
   (45,000픽셀, 링 44,403개)·200픽셀 대각선까지 전부 `nshapes=1`. 구멍과 자기접촉은 같은
   Polygon 의 내부 링이 되지 별도 shape 로 갈라지지 않는다.
3. 무작위 탐색 재현 실패 — 4×4~11×11 무작위 마스크 4,000회 × (4-연결/8-연결) 전수 검사에서
   `len(shapes) > 1` **0건**, Polygon 이외 타입 **0건**.

**하류에 숨은 결함은 없다.** 분기를 강제 실행시켜 실측했다(두 조각 마스크: 4픽셀+12픽셀):
`_vectorize_label` → 구조 정상, `_exterior_points` → 10점(두 조각 외곽선 전부, hull 입력으로
올바름), `_try_build_hull` → hull 면적 39.5m², `hull_overcapture_ratio = 2.46875`, WGS84
재투영 성공. 소비자도 안전하다 — 대시보드(`ChangeRegionMapInner.tsx:55`)는 `polygon` 이
아니라 항상 Polygon 인 `convexHullPolygonWgs84` 만 그리고, `region.polygon` 을 구조적으로
파싱하는 소비자는 저장소에 없다.

즉 이건 "커버리지 공백이 결함을 가리고 있던" 경우가 아니라 **도달 불가 방어 코드가
커버리지 구멍으로 보이던** 경우다. 따라서 런타임 변경은 없고, ① 사실을 코드에 남기고
② 그 방어를 직접 호출로 계약 고정한다.

**Files:**
- Modify: `services/change-detection/src/ksi_change_detection/region_extraction.py`
  (`_vectorize_label` docstring 196-204행, 221행 `elif`)
- Test: `services/change-detection/tests/test_region_extraction.py` (파일 끝에 이어붙임)

- [ ] **Step 1: 분기를 직접 실행시키는 테스트를 쓴다**

`services/change-detection/tests/test_region_extraction.py` **맨 끝**에 이어붙인다
(현재 284행, 마지막 테스트는 `test_hull_overcapture_ratio_exceeds_one_for_an_l_shaped_region`).
새 파일을 만들지 않는다 — `_grid`/`_diff`/`_report`/`_policy`/`_TRANSFORM` 이 전부 이 파일에
있다.

```python
def test_the_multipolygon_join_is_defensive_and_stays_correct_downstream() -> None:
    """[핵심] 조각난 마스크가 오면 MultiPolygon 으로 합치고, 하류가 그대로 옳다.

    이 분기는 compute_change_regions 경로로는 실행되지 않는다 — 라벨 마스크는
    4-연결이든 8-연결이든 항상 하나의 8-연결 성분이고, GDAL 은 그런 성분을 Polygon
    하나로 낸다(대각선 계단·코너 접촉·도넛·체커보드 전부 단일 Polygon 임을 실측했다).
    즉 GDAL 동작이 바뀌었을 때를 대비한 방어이고, 여기서 직접 호출해 계약으로 고정한다.
    """
    mask = np.zeros((8, 8), dtype=bool)
    mask[1:3, 1:3] = True   # 4픽셀 조각
    mask[5:8, 5:9] = True   # 9픽셀 조각(5:9 는 8 에서 잘린다) — 위 조각과 8-연결로도 안 닿는다

    geometry = _vectorize_label(mask, _TRANSFORM)

    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2

    # 하류: 두 조각의 외곽선이 전부 hull 입력으로 들어간다.
    points = _exterior_points(geometry)
    assert len(points) == 10
```

> **실행자 주의 — import 를 새로 추가해야 한다.** 헬퍼 5개(`_TRANSFORM:26`, `_policy:30`,
> `_grid:38`, `_diff:44`, `_report:57`)는 이 파일에 이미 있지만, **`_vectorize_label` 과
> `_exterior_points` 는 아직 import 돼 있지 않다** — `:18-22` 의 import 블록은
> `HULL_CONSISTENCY_CHECK_FAILED, RegionExtractionError, compute_change_regions` 셋뿐이다.
> 그 블록에 두 private 함수를 추가한다(Task 1·2 와 달리 여기는 "새 import 없음"이 아니다).
>
> 단언값은 2026-08-17 에 실제로 실행해 확인했다 — `type=MultiPolygon`, `len(coordinates)=2`,
> `len(_exterior_points(...))=10`. 그래도 첫 실행에서 다르게 나오면 실제 값으로 고정한다.

- [ ] **Step 2: 테스트를 돌려 실제 동작을 확인한다**

```bash
ulimit -n 8192 && uv run pytest services/change-detection/tests/test_region_extraction.py -v -k multipolygon_join
```
기대: PASS(이 분기는 이미 올바르게 동작한다 — 테스트가 그 사실을 고정하는 것이 목적이다).
FAIL 이면 좌표·기대값을 실제 출력에 맞춰 고친다.

- [ ] **Step 3: 도달성 사실을 docstring 에 남긴다**

`region_extraction.py` `_vectorize_label` docstring(196-204행)을 교체:

```python
def _vectorize_label(mask: np.ndarray, transform: Any) -> dict[str, Any]:
    """라벨 하나의 boolean 마스크를 GeoJSON 폴리곤으로 벡터화한다.

    ``connectivity=8`` 을 고정한다 — 이 마스크는 이미 한 라벨(scipy 의 연결
    규칙으로 이미 하나의 연결영역)만 True 이므로, 여기서 연결성을 더 관대하게
    잡아도 다른 라벨과 섞일 일이 없다. 대신 같은 라벨 안에서 대각선으로만
    이어진 셀들을 GDAL 이 하나의 폴리곤으로 그리게 해, 불필요하게 조각난
    MultiPolygon 을 피한다.

    그래서 아래 MultiPolygon 결합 분기는 ``compute_change_regions`` 경로에서는
    실행되지 않는다 — 라벨 마스크는 4-연결이든 8-연결이든 항상 하나의 8-연결
    성분이고, GDAL 은 그런 성분을 Polygon 하나로 낸다(대각선 계단·코너 접촉·
    도넛·체커보드 전부 단일 Polygon 으로 나오는 것을 실측했다. 구멍과 자기접촉은
    같은 폴리곤의 내부 링이 되지, 별도 shape 로 갈라지지 않는다). 이 분기는
    그 GDAL 동작이 바뀌었을 때를 대비한 방어이고, 테스트가 이 함수를 직접 불러
    계약으로 고정한다(``test_region_extraction.py``).
    """
```

221행 `elif` 에 pragma 추가 — 아래 `else` 와 같은 이유(GDAL 이 내지 않는 타입)인데
pragma 만 빠져 있다:

```python
        if geom["type"] == "Polygon":
            polygons.append(geom["coordinates"])
        elif geom["type"] == "MultiPolygon":  # pragma: no cover -- features.shapes 는 Polygon 만 낸다
            polygons.extend(geom["coordinates"])
        else:  # pragma: no cover -- GDAL 이 이 두 타입 외에는 내지 않는다
```

- [ ] **Step 4: 회귀와 정적 검사**

```bash
ulimit -n 8192 && uv run pytest services/change-detection/tests/test_region_extraction.py -v
uv run ruff check . && uv run mypy packages services tests tools
```

- [ ] **Step 5: 커밋**

```bash
git add services/change-detection/src/ksi_change_detection/region_extraction.py \
  services/change-detection/tests/test_region_extraction.py
git commit -m "test(change-detection): MultiPolygon 결합이 도달 불가 방어임을 계약으로 고정한다

커버리지 공백으로 등재됐던 분기가 실은 compute_change_regions 경로로 도달
불가였다(라벨 마스크는 항상 단일 8-연결 성분이고 GDAL 은 그것을 Polygon
하나로 낸다 — 무작위 마스크 4,000회 전수 검사 0건). 하류 결함도 없음을
강제 실행으로 확인했다. 사실을 docstring 에 남기고 직접 호출로 고정한다.

risk: region-extraction-multipolygon-branch-untested"
```

---

## Task 5: 이벤트 분할뷰가 전체 화면과 같은 증거 패널을 쓴다

**왜 지금 하나:** 전체 화면(`events/[eventKey]/page.tsx:222-227`)은 `EvidencePanel` 을
렌더하는데, 분할뷰(`events/EventDetailPanel.tsx:190-198`)는 **같은 `getEvent` 응답의
`evidence` 배열을 손에 쥐고도** 점선 자리표시만 그리고 "캡처 영상 열람 경로 준비 중"이라고
말한다. 경로는 이미 있으므로 그 문구가 사실과 다르다.

원인 둘:
1. 파일 헤더 주석(`EventDetailPanel.tsx:23-25`)이 "표시 로직만 복제한다(과제 지시).
   EventActions 는 그대로 import 해 재사용한다"고 적어 **`EvidencePanel` 이 재사용 목록에서
   빠졌다.** 기술적 장벽은 없었다 — `EventDetailPanel` 은 async 서버 컴포넌트이고
   `EvidencePanel` 은 `"use client"` 지만(폴더도 다르다), **서버 컴포넌트가 client 컴포넌트를
   import 하는 것은 Next.js 정상 경로**이며 같은 이유로 이미 `EventActions` 를 `:19` 에서
   import 하고 있다. (초안은 "둘 다 use client, 같은 폴더"라고 잘못 적었다 — 그 근거를
   남기면 다음 세션이 `EventDetailPanel` 을 client 로 오인한다.)
2. `hasBundle`(`:142`)이 다른 것을 잰다 — `Boolean(event.bundle) && Object.keys(event.bundle).length > 0`
   은 원시 번들 dict 의 키 유무이지 증거 개수가 아니다. 증거가 0건이어도 번들 키만 있으면
   "수신돼 있습니다"라 말하고, 5건 있어도 "준비 중"이라 말한다.

**새 API·새 계약 0건** — `/v1/events/{event_key}/evidence` 는 `openapi-core.yaml:1043` 에
이미 있고 대시보드 route handler 도 `src/app/api/events/[eventKey]/evidence/**` 에 이미 있다.
ADR-KSI-020 §5 동결 범위 밖이다(있는 컴포넌트를 있는 데이터에 잇는 것).

**Files:**
- Modify: `apps/dashboard/src/app/events/EventDetailPanel.tsx`
- Test: `apps/dashboard/test/evidence-panel-wiring.test.ts` (신설)

**Interfaces:**
- Consumes: `EvidencePanel`(`./[eventKey]/EvidencePanel`) — props `eventKey: string`,
  `evidence: EvidenceSummary[]`, `canUpload: boolean`
- Produces: 없음(화면 배선만)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`apps/dashboard/test/evidence-panel-wiring.test.ts` 신설. 이 저장소는 "클라이언트 컴포넌트
배선"을 관심사 하나당 파일 하나로 두는 관례가 있다(`test/event-actions-token.test.ts`).
그 파일을 먼저 읽어 소스를 읽어 단언하는 방식을 그대로 따른다.

```ts
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const PANEL = readFileSync(
  join(process.cwd(), "src/app/events/EventDetailPanel.tsx"),
  "utf8",
);

describe("이벤트 분할뷰의 증거 배선", () => {
  it("[핵심] 전체 화면과 같은 EvidencePanel 을 쓴다", () => {
    // 같은 사건의 같은 사실을 두 화면이 다르게 그리면 그중 하나는 반드시 거짓말이 된다.
    expect(PANEL).toContain('from "./[eventKey]/EvidencePanel"');
    expect(PANEL).toContain("<EvidencePanel");
  });

  it("증거 유무를 번들 키 개수로 대신 재지 않는다", () => {
    // hasBundle 은 원시 번들 dict 의 키 유무여서 evidence.length 와 무관하다.
    expect(PANEL).not.toContain("hasBundle");
  });

  it("이미 있는 열람 경로를 '준비 중'이라 말하지 않는다", () => {
    expect(PANEL).not.toContain("열람 경로 준비 중");
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
cd apps/dashboard && npx vitest run test/evidence-panel-wiring.test.ts
```
기대: 3건 전부 FAIL.

- [ ] **Step 3: import 를 추가한다**

`apps/dashboard/src/app/events/EventDetailPanel.tsx` (`:19` 바로 뒤):

```tsx
import { EventActions } from "./[eventKey]/EventActions";
import { EvidencePanel } from "./[eventKey]/EvidencePanel";
```

- [ ] **Step 4: 죽은 `hasBundle` 을 제거한다**

`:140-142`:

```tsx
  const severity = event.severity ? EVENT_SEVERITY_LABEL[event.severity] : SEVERITY_UNSET_LABEL;
```
(주석 한 줄(`:141`)과 `hasBundle` 선언(`:142`)을 지운다. Step 5 이후 유일한 사용처가 사라지므로 남기면
`@typescript-eslint/no-unused-vars` 가 문다.)

- [ ] **Step 5: 자리표시를 실제 패널로 교체한다**

`:190-198`:

```tsx
      {/* 증거는 전체 화면(events/[eventKey]/page.tsx)과 **같은 컴포넌트를 그대로** 쓴다 —
          같은 사건의 같은 사실을 두 화면이 다르게 그리면 그중 하나는 반드시 거짓말이 된다.
          열람 URL 발급·폐기 표시·업로드는 전부 EvidencePanel 안에 있고 여기서 복제하지
          않는다. 캡처 프레임·바운딩박스는 여전히 데이터 경로가 없어 그리지 않는다. */}
      <div className="mx-4 mt-3">
        <EvidencePanel eventKey={event.eventKey} evidence={event.evidence} canUpload={canTriage} />
      </div>
```

> 실행자 주의: `canTriage` 가 이 파일에 실제로 있는 변수명인지 확인한다. 없으면 전체 화면
> (`events/[eventKey]/page.tsx:222-227`)이 `canUpload` 에 무엇을 넘기는지 읽고 **그와 같은
> 권한 판정**을 쓴다. 권한 판정을 새로 지어내지 않는다.

- [ ] **Step 6: 파일 헤더 주석을 정정한다**

`:23-25` 의 "표시 로직만 복제한다(과제 지시). EventActions 는 그대로 import 해 재사용한다"
를 고친다 — 이 주석이 다음 세션에게 다시 복제를 지시하지 않도록:

```tsx
// events/[eventKey]/page.tsx 의 사실 패널과 같은 항목을 보여준다. EventActions 와
// EvidencePanel 은 그대로 import 해 재사용한다 — 처음에는 EvidencePanel 이 재사용
// 목록에서 빠져 자리표시만 그렸고, 그 결과 같은 증거를 두고 한 화면은 "열람 경로
// 준비 중"이라 말했다(2026-08-17 수정). 표시 로직을 복제하면 반드시 갈라진다.
```

- [ ] **Step 7: 테스트와 게이트를 돌린다**

```bash
cd apps/dashboard && npx vitest run test/evidence-panel-wiring.test.ts
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```
기대: 신규 3건 PASS + 기존 전부 PASS + 빌드 성공.

- [ ] **Step 8: 실제 화면으로 확인한다**

Core dev 서버와 대시보드를 띄우고 `/events` 에서 증거가 있는 사건을 골라 분할뷰에 증거
목록이 실제로 렌더되는지 눈으로 본다. 콘솔 오류 0건을 확인한다.

```bash
uv run python scripts/run_core_dev.py --host 0.0.0.0 --port 8010
cd apps/dashboard && npm run dev -- --hostname 0.0.0.0 --port 3000
```

- [ ] **Step 9: 커밋**

```bash
git add apps/dashboard/src/app/events/EventDetailPanel.tsx apps/dashboard/test/evidence-panel-wiring.test.ts
git commit -m "fix(dashboard): 이벤트 분할뷰가 전체 화면과 같은 증거 패널을 쓴다

분할뷰가 같은 응답의 evidence 배열을 쥐고도 자리표시만 그리며 '열람 경로
준비 중'이라 말했다 — 경로는 이미 있어 문구가 사실과 달랐다. EvidencePanel 을
그대로 재사용하고, 증거 유무를 번들 키 개수로 대신 재던 hasBundle 을 없앤다.
새 API·새 계약 0건."
```

---

## Task 6: 화면 이름을 그 화면이 실제로 보여주는 것에 맞춘다

**왜 지금 하나:** 하나의 문자열이 두 역할을 겸하고 있다 — `NAV_ITEMS[].label` 이 (a) PRD §7.1
이 고정한 **정보구조 슬롯의 이름**이자 (b) 사용자가 읽는 **화면 제목**이다
(`components/nav/page-title.ts:8-20` 의 `STATIC_TITLES` 가 라벨을 그대로 복사하고,
`page-title.test.ts:63-70` 이 그 동일성을 강제한다).

2026-08-08 에 Phase 3/4 Core API 가 생기며 두 슬롯이 실동작으로 전환됐는데, **채워 넣은
내용이 슬롯 이름보다 훨씬 좁았다**:
- `자산·시설물` 슬롯 ← 임무 1건의 사진에서 나온 표면 결함 후보 목록(자산 엔티티 0개)
- `설정` 슬롯 ← 장비 클래스별 지원단계 표 1개(계정·조직·권한 0개, 쓰기 조작 0개)

`/assets` 는 그 간극을 **본문 고지문으로 사과**하는 방식으로 덮었고(`assets/page.tsx:84-87`
"현재 이 화면은 자산대장이 아니라…"), `/settings` 는 덮지 않아 그대로 남았다.
**그 고지문의 존재 자체가 제목이 틀렸다는 화면 스스로의 증언이다** — 제목이 맞으면
"이건 X 가 아닙니다"라고 쓸 이유가 없다.

**INV-040 과의 관계(정확히):** 이 2건은 INV-040 의 **문자 그대로의 위반은 아니다** — 두
화면 모두 실데이터를 그리고 mock 을 쓰지 않는다. INV-040 은 "Production 에서
mock/placeholder/static always-go 금지"다(`DOMAIN_INVARIANTS.md:115-116`). 다만 이 저장소는
INV-040 을 "화면이 자기 상태를 정직하게 말한다"의 정신으로 확장 인용해 왔고
(`03_DASHBOARD_UX_GOALS.md:207-208`), 이번 건은 그 정신에 걸린다.
**"INV-040 위반"이 아니라 "INV-040 과 같은 정신의 표기 정직성 결함"으로 적는다.**

**PRD 와의 관계:** `key`·`href`·순서는 **건드리지 않는다.** PRD §7.1 슬롯 자체는 살아
있고, 계정·조직 설정이 실제로 구현되는 날 라벨만 되돌리면 된다. ADR-KSI-020 §5 동결 때문에
없는 기능을 만들어 이름을 맞출 수 없으므로 **이름을 내용에 맞춘다.**

**명칭 제안**

| slot key | PRD §7.1 슬롯 이름 | 제안 라벨 = 제안 h1 | 도출 근거 |
|---|---|---|---|
| `assets` | 자산·시설물 | **결함 후보** | 화면이 부르는 계약이 `GET /v1/missions/{id}/defect-candidates` 하나이고 표 컬럼이 후보 ID·사진·유형·신뢰도·면적·길이다. 화면 docstring(`assets/page.tsx:60`)이 내용을 "표면 결함(균열) 후보"로 서술하고 `nav-items.ts:3-4` 주석도 "결함 후보"라 부른다(단 docstring 첫 줄은 아직 "자산·시설물"로 시작한다 — 이름을 바꾸면 그 줄도 함께 고친다). **"검토"를 안 붙인 이유**: 채택·기각 조작이 없는 읽기 전용 화면이라("mutation 0건" 확인) "검토"는 없는 처리 대기열을 약속한다. 형제 라벨(현장·임무·이벤트)도 전부 명사다. |
| `settings` | 설정 | **장비 지원단계** | 화면이 부르는 계약이 `GET /v1/equipment-support` 하나이고 6단계 승급 사다리와 상용지원 여부만 보여준다. PRD §23.3 절 제목이 "장비 지원표시"이고, 코드가 이미 세 곳에서 이 이름을 쓴다(`nav-items.ts:4` 주석, `phase34.ts:137` docstring, 그리고 **실제 렌더되는 대체 행동 버튼 라벨** `coming-soon/[section]/page.tsx:21` "장비 지원 단계 보기"). |

**Files:**
- Modify: `apps/dashboard/src/components/nav/nav-items.ts` (헤더 주석 1-6행, 23행, 28행)
- Modify: `apps/dashboard/src/components/nav/page-title.ts` (`STATIC_TITLES` 8-20행 — `/assets` 는 15행, `/settings` 는 18행)
- Modify: `apps/dashboard/src/app/assets/page.tsx` (82-88행 고지문 — 제목이 맞아지면 사과문이 불필요)
- Modify: `apps/dashboard/src/app/coming-soon/[section]/page.tsx` (`SECTION_BLURB` 11-18행)
- Test: `apps/dashboard/test/nav-items.test.ts`

- [ ] **Step 1: 어떤 테스트가 깨지는지 먼저 확인한다**

```bash
cd apps/dashboard && npx vitest run test/nav-items.test.ts test/page-title.test.ts
```
지금은 PASS. 판정(조사 결과, 실행자가 재확인할 것):
- `nav-items.test.ts:29-44` — 라벨 문자열 10개를 하드코딩해 `toEqual` 한다 → **깨진다.**
- `nav-items.test.ts:60-69`(MOBILE_TAB_ITEMS) — 대상이 오늘·현장·임무·이벤트·더보기뿐이고
  assets·settings 는 `mobile: false` → **무관, 수정 불필요.**
- `page-title.test.ts:10-21` — `/assets`·`/settings` 가 목록에 없다 → **수정 불필요.**
- `page-title.test.ts:62-70` — 리터럴 없이 `resolvePageTitle(item.href) === item.label` 만
  본다 → nav-items.ts 와 page-title.ts 를 **함께** 고치면 통과하고 한쪽만 고치면 실패한다.
  **이 테스트가 "라벨·h1 어긋남"을 잡는 가드다 — 손대지 말 것.**

- [ ] **Step 2: `nav-items.test.ts` 를 라벨 고정에서 key 고정으로 바꾼다**

원 테스트가 지키는 것은 셋이다: ① 10항목이 하나도 사라지지 않는다 ② 순서가 PRD 순서다
③ 각 항목이 사람이 읽을 이름을 갖는다. ①②는 **key 로 고정하면 그대로 보존**되고, ③은
문자열 하드코딩 대신 "비어 있지 않고 서로 겹치지 않는다"로 고정한다. (라벨 문자열을 새
값으로 갈아끼우기만 하면 테스트가 명칭 결정의 사본이 될 뿐, 다음번 정직한 개명도 똑같이
회귀로 잡는다.)

파일 머리 주석(10-15행) 뒤에:

```ts
// 2026-08-17: 이 파일은 **자리(key)와 순서**를 고정하고, 라벨 문자열은 고정하지 않는다.
// PRD §7.1 은 정보구조 슬롯을 못박은 것이고, 화면에 찍는 이름은 그 슬롯이 지금 실제로
// 보여주는 것을 따라야 한다(assets → "결함 후보", settings → "장비 지원단계";
// 2026-08-13 UI 감사 21·24번). 라벨 문자열을 여기서 못박으면 그 정직한 개명이 회귀로
// 잡히고, key 를 못박으면 이 파일이 원래 막으려던 회귀 — 항목이 조용히 사라지는 것 —
// 만 잡힌다. 라벨↔topbar 제목 동기화는 page-title.test.ts 가 따로 강제한다.
```

29-44행 전체를 교체:

```ts
  it("[핵심] PRD §7.1 이 못박은 데스크톱 10항목이 그대로 있다", () => {
    // 자리와 순서 둘 다 PRD 고정값이다(docs/product/MASTER_PRD_v3.0.md §7.1).
    // 주석의 PRD 이름과 실제 라벨이 다른 두 줄은 그 슬롯이 아직 PRD 범위대로 채워지지
    // 않았다는 뜻이다 — 채워지면 라벨을 PRD 이름으로 되돌린다.
    const grouped = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.key));
    expect(grouped).toEqual([
      "home", // 홈
      "sites", // 현장
      "missions", // 임무
      "events", // 이벤트
      "assets", // PRD "자산·시설물" — 현재 화면은 임무 사진의 결함 후보뿐
      "world", // 2D·3D World
      "reports", // 보고서
      "fleet", // Fleet·Edge
      "data", // Data·AI
      "settings", // PRD "설정" — 현재 화면은 장비 지원단계 표뿐
    ]);
  });

  it("모든 항목이 비어 있지 않고 서로 겹치지 않는 이름을 갖는다", () => {
    const labels = DESKTOP_NAV_GROUPS.flatMap((group) => group.items.map((i) => i.label));
    expect(labels.every((label) => label.trim().length > 0)).toBe(true);
    expect(new Set(labels).size).toBe(labels.length);
  });
```

- [ ] **Step 3: 테스트를 돌려 지금 실패하는지 확인한다**

```bash
cd apps/dashboard && npx vitest run test/nav-items.test.ts
```
기대: PASS(아직 라벨을 안 바꿨으므로 key 기반 테스트는 그대로 통과한다). 이 단계는 테스트
전환이 기존 성질을 깨지 않았음을 확인하는 것이다.

- [ ] **Step 4: 라벨을 바꾼다**

`apps/dashboard/src/components/nav/nav-items.ts` 헤더 주석 뒤에 한 문단 추가:

```ts
// 2026-08-17: **label 은 PRD 슬롯 이름이 아니라 그 자리가 지금 실제로 보여주는 것**을
// 적는다. 실동작 전환 때 두 슬롯이 이름보다 훨씬 좁은 내용으로 채워졌고, 슬롯 이름을
// 그대로 제목으로 쓰면서 화면이 약속하지 않은 범위를 약속했다 — assets 는 자산대장이
// 없는데 "자산·시설물"이었고(본문에 "이 화면은 자산대장이 아닙니다" 고지가 붙어 있었다),
// settings 는 장비 지원단계 표 하나인데 "설정"이었다(2026-08-13 UI 감사 21·24번).
// ADR-KSI-020 §5 동결로 없는 기능을 만들어 이름을 맞출 수 없으므로 이름을 내용에 맞춘다.
// key·href·순서는 그대로다 — 계정·조직 설정이 실제로 생기면 label 만 "설정"으로 되돌린다.
```

23행 / 28행:

```ts
  { key: "assets", label: "결함 후보", href: "/assets", implemented: true, mobile: false },
  { key: "settings", label: "장비 지원단계", href: "/settings", implemented: true, mobile: false },
```

- [ ] **Step 5: `page-title.ts` 를 같이 고친다**

`apps/dashboard/src/components/nav/page-title.ts` 의 `STATIC_TITLES`(**8-20행**, 파일 전체가
45행이다)에서 `/assets`(**15행**)와 `/settings`(**18행**)를 새 라벨과 **정확히 같게** 맞춘다:

```ts
  // Phase 3/4 섹션(2026-08-08) — 사이드바 라벨과 같은 말을 쓴다(NAV_ITEMS 참고).
  "/assets": "결함 후보",
  "/world": "2D·3D World",
  "/reports": "보고서",
  "/settings": "장비 지원단계",
```

`page-title.test.ts:62-70` 이 `resolvePageTitle(item.href) === item.label` 동일성을 강제하므로
한쪽만 고치면 즉시 실패한다 — **그 테스트가 이 어긋남을 잡는 가드다.**

- [ ] **Step 6: 사과문과 죽은 설명 문자열을 정리한다**

`apps/dashboard/src/app/assets/page.tsx:82-88`(사과 문단 자체는 `:84-87`). 사이드바 라벨이 "결함 후보"가 되면
"이건 자산대장이 **아닙니다**"라는 사과는 더 이상 필요 없다 — 제목이 이미 맞는 말을 한다.
다만 **자산대장이 아직 없다는 사실 자체는 여전히 사용자가 알아야 한다.** 사과를 빼고
안내만 남긴다:

```tsx
        <div className="flex flex-col gap-1">
          <h2 className="text-[19px] font-bold tracking-tight break-keep">결함 후보 검토</h2>
          {/* 라벨이 내용과 맞아졌으므로 "이건 자산대장이 아닙니다"라는 사과는 뺀다
              (2026-08-17). 자산대장 자체가 아직 없다는 사실은 남긴다 — 없는 기능을
              있는 것처럼 말하지 않는 것이 이 화면의 규율이다(INV-040 의 정신). */}
          <p className="text-sm break-keep text-ink-2">
            임무를 선택해 그 임무 사진에서 생성된 결함 후보와 근거를 확인하세요.
            자산·시설물 단위로 이력을 쌓는 대장은 아직 없습니다.
          </p>
        </div>
```

`apps/dashboard/src/app/coming-soon/[section]/page.tsx` 의 `SECTION_BLURB`(11-18행)에서
`assets`·`world`·`reports`·`settings` 4개 항목은 **도달 불가능한 죽은 문자열**이다
(`:33-34` 가 `NAV_ITEMS` 에 `/coming-soon/<section>` href 가 없으면 `notFound()` 한다).
그중 `:17` "계정·조직 설정을 관리하는 화면입니다" 는 사용자에게 보인 적이 없지만 **코드를
읽는 다음 구현자에게 settings 슬롯의 정의로 읽힌다.** 4개 항목을 지우고, 남는 `fleet`·
`data` 위에 왜 둘만 남았는지 주석을 단다.

- [ ] **Step 7: 게이트를 돌린다**

```bash
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```
기대: 전부 PASS. `page-title.test.ts` 가 깨지면 Step 5 를 안 했거나 문자열이 어긋난 것이다.

- [ ] **Step 8: 실제 화면으로 확인한다**

대시보드를 띄워 사이드바 라벨·상단 제목·모바일 `/more` 배지가 전부 새 이름으로 일관되게
나오는지 본다.

- [ ] **Step 9: 커밋**

```bash
git add apps/dashboard/src/components/nav/nav-items.ts apps/dashboard/src/components/nav/page-title.ts \
  apps/dashboard/src/app/assets/page.tsx apps/dashboard/src/app/coming-soon/\[section\]/page.tsx \
  apps/dashboard/test/nav-items.test.ts
git commit -m "fix(dashboard): 화면 이름을 그 화면이 실제로 보여주는 것에 맞춘다

PRD §7.1 슬롯 이름이 그대로 화면 제목이 되면서 두 화면이 약속하지 않은 범위를
약속했다 — assets 는 자산대장이 없는데 '자산·시설물'이라 본문에 사과문을 달았고,
settings 는 장비 지원단계 표 하나인데 '설정'이었다. key·href·순서는 그대로 두고
라벨만 내용에 맞춘다(계정·조직 설정이 생기면 되돌린다). nav-items 테스트는
라벨 문자열 고정에서 key 고정으로 바꿔, 정직한 개명이 회귀로 잡히지 않게 한다.

2026-08-13 UI 감사 21·24번 · INV-040 과 같은 정신의 표기 정직성"
```

---

## Task 7: `mypy .` 와 CI 게이트의 스코프를 일치시킨다

**왜 지금 하나:** `uv run mypy .` 는 35개 오류를 내는데 **전부 한 파일**
(`design/ksi-site-intelligence/_build.py`)에 몰려 있고, CI 가 실제로 부르는
`uv run --locked mypy packages services tests tools` 는 334개 파일에서 오류 0건이다.
`pyproject.toml` 의 `[tool.mypy]` exclude 가 `^references/`·`^edge/`·`^apps/`·
`^tools/vector-extraction/` 과 defect-detection `_vendor` 는 빼면서 `design/` 은 안 빼서,
bare `.` 호출만 그 파일을 끌어온다.

**제품 코드 결함이 아니다.** `design/` 은 정적 디자인 사이트 생성기이고 어떤 CI 잡도
타입 검사하지 않는다. 그러나 **두 명령이 다른 답을 내는 상태 자체가 함정**이다 — 다음
세션이 `mypy .` 를 돌려보고 35개 오류를 제품 회귀로 오인한다.

**Files:**
- Modify: `pyproject.toml` (`[tool.mypy]` exclude, 119-135행 부근)

- [ ] **Step 1: 현재 불일치를 관측한다**

```bash
uv run mypy . 2>&1 | tail -3
uv run mypy packages services tests tools 2>&1 | tail -3
```
기대: 앞은 `Found 35 errors in 1 file`, 뒤는 `Success: no issues found in 334 source files`.

- [ ] **Step 2: exclude 에 `design/` 을 추가한다**

`pyproject.toml` `[tool.mypy]` exclude 목록에 기존 항목들과 같은 형식으로:

```toml
  "^design/",  # 정적 디자인 사이트 생성기 — 런타임 제품 코드가 아니고 어떤 CI 잡도
               # 타입 검사하지 않는다. 빼두지 않으면 `mypy .` 만 이 파일을 끌어와
               # CI 게이트와 다른 답을 내고, 그 차이가 제품 회귀로 오인된다.
```

- [ ] **Step 3: 두 명령이 같은 답을 내는지 확인한다**

```bash
uv run mypy . 2>&1 | tail -3
uv run mypy packages services tests tools 2>&1 | tail -3
```
기대: 둘 다 `Success`.

- [ ] **Step 4: 커밋**

```bash
git add pyproject.toml
git commit -m "chore: mypy exclude 에 design/ 을 넣어 bare mypy 와 CI 게이트를 일치시킨다

mypy . 만 design/ksi-site-intelligence/_build.py 를 끌어와 35개 오류를 냈다.
CI 는 스코프를 지정해 부르므로 0건이고, 그 차이가 다음 세션에게 제품 회귀로
오인될 함정이었다. design/ 은 정적 디자인 사이트 생성기다."
```

---

## Task 8: 원장과 어긋난 문서 서술을 정정한다

**왜 지금 하나:** 2026-08-17 전수 조사가 문서·원장 불일치 7건을 찾았다. 그중 **5번이
특히 위험하다** — 문서만 읽으면 정반대 결론에 도달한다.

| # | 불일치 | 정본 |
|---|---|---|
| 1 | `phase-0` — 원장 `completed`, `PHASE_REGISTRY.yaml:35` `IN_PROGRESS` | **불일치가 아니다**(아래 Step 1) |
| 2 | `phase-2` — 원장 `completed`, `PHASE_REGISTRY.yaml:127` `IN_PROGRESS` | **불일치가 아니다**(아래 Step 1) |
| 3 | `phase-5` — 원장 `blocked`, `PHASE_REGISTRY.yaml:286` `PLANNED` | 어휘만 다름 — 레지스트리를 원장 어휘로 |
| 4 | `phase-5` blocked 사유가 2026-08-06 스냅샷으로 굳음("선행 phase-2 PLANNED, phase-3/4 blocked") — 셋 다 지금은 아니다(phase-2=completed, phase-3/4=in_progress) | 원장 사유를 갱신 |
| 5 | **`track-a` 차단 사유 정정이 문서에 반영 안 됨** | 원장이 정본 |
| 6 | `PHASE_REGISTRY.yaml:21-30` `axes` 절이 "H1~H4 전부 장비 조달·승인 대기"라 적었으나, 2026-08-13 정정은 "장비도 자격도 확보. 남은 조달은 H2 하나" | `REMAINING_WORK_PLAN.md:70-81` 이 정본 |
| 7 | **AOL/FIELD/flight-execution 목표군 13건이 두 문서 어디에도 없다** — 현재 실질 최상위 과제(폐루프)가 계획 문서에 부재 | 원장이 정본 |

**5번 상세:** `track-a` 는 2026-08-14 에 "'.dpk 설치 후 psdk_tap 크래시'는 저장소 근거로
뒷받침되지 않는다 … 실제 차단 요인은 매니폴드가 네트워크에 없다"로 정정됐다. 그런데
`REMAINING_WORK_PLAN.md:80`(H3 게이트 열)은 여전히 "실제 관문은 `psdk_tap` 이 `.dpk` 설치
후 SDK 시작 단계에서 크래시하는 것", `:100`(두 축 표)도 "실제 관문은 `psdk_tap` 크래시
해소다 — 디버깅 과제"로 남아 있다. **문서만 읽으면 "디버깅하면 된다"로 읽히는데 원장은
"장비 세션이 없다"로 바뀌었다** — 대응이 완전히 다르다(작업 vs 기다림). 이 문서가 스스로
`:106-108` 에서 "원장의 track-a 사유가 2026-08-04자로 굳어 있어 후자를 전자로 읽고 있었다"
고 경고했던 것과 정확히 방향이 뒤집힌 상태다.

**Files:**
- Modify: `docs/goals/REMAINING_WORK_PLAN.md` (:80 H3 게이트, :100 두 축 표, 마일스톤 표 뒤)
- Modify: `docs/goals/PHASE_REGISTRY.yaml` (:21-30 axes, :35, :127, :286)
- Modify: `.ksi/goals.json` — **헬퍼로만 고친다**(직접 JSON 손편집 금지)

- [ ] **Step 1: 1·2번은 불일치가 아님을 확인하고, 주석 한 줄만 더한다**

> **⚠ 이 계획의 초안은 여기서 틀렸다.** 초안은 phase-0·phase-2 를 "정면 충돌"로 적고
> "원장 쪽이 조기완료라면 `invalidate` 대상"이라고 방향을 잡아줬다. **절대 하지 마라** —
> 정당하게 게이트를 통과한 완료 2건을 어휘 차이로 파괴한다. 2026-08-17 독립 검증이 이
> 지시를 반증했고, 근거는 아래다.

**충돌이 아니라 범위(scope)가 다른 것이고, 그 사실이 양쪽 문서에 이미 명시돼 있다:**

- 원장 goal 제목 자체가 소프트웨어 범위다 — `.ksi/goals.json` 의
  `"Phase 0: Capability & Calibration Foundation (SW)"`.
- 그 goal 의 gate note 가 직접 적고 있다 — "Phase 0 Software Acceptance PASS. 하드웨어
  Spike는 DEFERRED라 phase-0 전체는 IN_PROGRESS 유지". **원장이 레지스트리의 IN_PROGRESS 를
  부정한 적이 없다.**
- 레지스트리도 같은 구분을 갖는다 — `PHASE_REGISTRY.yaml:55-56` 의
  `scope_now: "소프트웨어 기반만 (P0-1~P0-6). 하드웨어 Spike(PSDK/카메라/짐벌)는 장비 세션에서."`
  와 `:65-67` 의 `hardware_deferred:`.

즉 원장은 **소프트웨어 범위**를, 레지스트리는 **하드웨어 포함 전체 phase** 를 추적한다.
두 값이 다른 것이 정상이다.

**할 일은 하나뿐이다** — 다음 세션이 이걸 다시 충돌로 오인하지 않게 레지스트리 status 옆에
한 줄을 단다(`:35`·`:127` 각각):

```yaml
    # 이 IN_PROGRESS 는 하드웨어 포함 전체 phase 기준이다. 소프트웨어 수용은 이미 PASS 이고
    # (원장 goal `phase-0`/`phase-2` 가 그 범위를 추적한다), 두 값이 다른 것이 정상이다 —
    # 충돌로 읽고 원장을 invalidate 하지 말 것(2026-08-17 검증에서 실제로 그 오독이 나왔다).
```

`invalidate` 는 **하지 않는다.**

- [ ] **Step 2: 5번(track-a)을 고친다 — 가장 위험한 항목이므로 먼저**

**자리는 세 곳이다** — 초안은 `:80`·`:100` 둘만 적었는데 `:73-74` 에도 있다:
"남은 것은 조달이 아니라 **실기 디버깅**이다. 이 구분을 흐리면 다음 세션이 다시 '장비가
없어서 못 한다'로 읽는다"(2026-08-13 정정 블록). 2026-08-14 원장 정정이 뒤집은 것이 정확히
이 문장이다.

`docs/goals/REMAINING_WORK_PLAN.md:80` H3 게이트 열:

```
| H3 | Track A PSDK 스파이크: 9항목 SpikeEvidence + 비행상태 topic(ADR-KSI-006) + Frame-Telemetry p95≤50ms | 기체·PSDK 자격 **확보됨**. **[2026-08-14 정정]** 이전에 적혀 있던 "`psdk_tap` 이 `.dpk` 설치 후 크래시"는 저장소 근거로 뒷받침되지 않는다 — `.dpk` 를 실기에 설치한 세션 자체가 없다. 실제 관문은 **매니폴드가 네트워크에 없다는 것 하나**다(172.30.1.33 ARP FAILED). 세션이 열리면 남은 미확정은 USB bulk 채널 번호뿐이고 `scripts/manifold/probe_usb_bulk.sh` 읽기 전용 프로브 1회로 확정된다. |
```

`:100` 두 축 표의 Autonomous Acquisition 행과 **`:73-74`** 도 같은 취지로 고친다 —
"디버깅 과제"를 "장비 세션 부재"로 바꾸되, **원래 문장을 지우지 말고 정정을 덧붙인다**
(`:106-108` 경고 문단에 대해 정한 것과 같은 원칙 — 그 경고가 왜 있었는지가 기록으로 남아야
한다).

- [ ] **Step 3: 6번(axes 절)을 고친다**

`PHASE_REGISTRY.yaml` 의 `autonomous_acquisition` 블록(**:20-29**, note 본문은 **:23-29**)을
고친다 — "H1~H4 전부 장비 조달·PSDK 개발자 승인 대기" → "장비·자격 확보됨. 남은 조달은
H2(동글+유심) 하나이고, 실제 관문은 실기 세션이다".

**정본으로 삼을 범위를 좁힌다** — `REMAINING_WORK_PLAN.md:70-72·:76-81`(장비·자격 확보
사실)만 근거로 쓴다. **`:73-74` 는 정본이 아니다** — 그 문장('실기 디버깅')이 Step 2 에서
고칠 대상이고, 그대로 옮기면 이미 반증된 프레임이 레지스트리로 복제된다.

`updated` 필드도 갱신한다 — **axes 절 안이 아니라 문서 최상위 `:7`** 이다(현재 `"2026-08-08"`).

- [ ] **Step 4: 7번(AOL/FIELD 목표군 누락)을 고친다**

`REMAINING_WORK_PLAN.md` 마일스톤 표는 M4-E(2026-08-14)에서 멈춰 있고, 그 뒤 등록된
목표군이 어디에도 없다(두 문서에 "AOL-"·"FIELD-" grep 0건 — 2026-08-17 확인).
**현재 실질 최상위 과제가 계획 문서에 없는 상태다.**

정확한 구성: `autonomous-acquisition-closed-loop`(부모) 아래 **AOL 6건**(G1~G6) +
**FIELD 5건**(FIELD-0, 0a, 1, 2, 3) = 11건, 그리고 **C2-S1~S4 4건**은 부모가 다르다
(`decision-psdk-flight-execution-authorization`). 합 15건 + 부모 1.

마일스톤 표 뒤에 절을 하나 추가한다. 상태는 복제하지 않는다(이 문서 머리말이 "상태의 SSOT
는 goal-ledger"라 명시) — **구조와 순서만** 적고 상태는 원장을 가리킨다:

```markdown
## AOL / FIELD 트랙 (2026-08-14 등록 — 현재 최상위 과제)

ADR-KSI-019 §5 + ADR-KSI-020 §5 가 정의한 순서다. 상태는 여기 적지 않는다 —
`ksi-goals.py report` 가 SSOT다.

| 단계 | 내용 | 관문 |
|---|---|---|
| AOL-1 G1·G2 | 공간모델 생애주기 · 임무 실행 생애주기 | 없음(소프트웨어 완료, 검증 게이트 대기 → Task 9) |
| AOL-2 G5 | 재관측 계획 심화 | 없음(소프트웨어 완료, 검증 게이트 대기 → Task 9) |
| AOL-1 G4 | 촬영 → 서버 자동 ingest | 구현은 됐으나 실제 촬영물 회수 경로가 걸림 |
| AOL-1 G3 | 임무를 기체까지 보내는 공식 경로 | DJI Pilot Cloud Wayline 지원 여부 실기 확인 |
| AOL-3 G6 | 공간모델 인지 경로계획 | Unit 1만 완료 — Unit 2~5 잔여(소프트웨어) |
| **FIELD-0a** | **비행파일 수용성 + 카메라 실측 — 조종기만 있으면 오늘 할 수 있다** | **없음 — FIELD-1 의 유일한 전제** |
| FIELD-0 | 지상 통합(매니폴드·기체·임무파일 연결) | 매니폴드 전원·네트워크 |
| FIELD-1 | 첫 실제 매핑 비행 | FIELD-0a |
| FIELD-2 | 현장 폐루프 실증 | FIELD-1 |
| FIELD-3 | 지형추종 비행 | `decision-flight-ceiling-reference-split` 대표자 결정 |

(단계 이름은 **원장 id 를 그대로 미러링한다** — 원장에 `field-0b` 는 없고
`field-0-ground-integration` 이다. 이 표의 목적이 원장을 문서에 비추는 것이므로 이름을
지어내면 안 된다.)

**ADR-KSI-020 §5: "FIELD-0a 이전에 새 기능을 만들지 않는다."** 이 동결이 지금
유효하며, 그래서 이 문서의 "지금 추가 투자를 하지 않는 것" 절이 계속 적용된다.
```

- [ ] **Step 5: 3·4번(phase-5)을 원장 헬퍼로 고친다**

`.ksi/goals.json` 을 직접 편집하지 않는다. `phase-5` 의 blocked 사유가 2026-08-06 스냅샷
으로 굳어 있으므로 헬퍼로 갱신한다:

```bash
python3 ~/.claude/scripts/ksi-goals.py block --id phase-5 --reason "[2026-08-17 갱신] 이전 사유는 2026-08-06 스냅샷이 굳은 것이라 선행 단계 서술이 전부 낡았다 — '선행 phase-2 PLANNED, phase-3/4 blocked'라고 적혀 있으나 지금은 phase-2=completed, phase-3/4=in_progress 다(2026-08-07 재개). 관문의 순서를 바로 적는다: (1) 먼저 대표자 동결이다 — ADR-KSI-016 D5 가 phase-5 를 '첫 유료 건설 현장 전까지 동결'로 두었고(PHASE_REGISTRY.yaml investment: FROZEN_UNTIL_FIRST_PAID_SITE), 이건 기술 관문이 아니라 시장 판단이다. (2) 그 동결이 풀린 뒤에야 실물 DJI Dock 하드웨어 검증(Dock 3 + M4D 제3자 payload 제약 실검증, ADR-KSI-004)이 두 번째 관문으로 남는다. 즉 선행 phase 미충족이 아니라 소유자 결정이 첫 관문이다."

`PHASE_REGISTRY.yaml:286` 의 `PLANNED` 를 원장 어휘(`BLOCKED`)로 맞춘다 — 이 레지스트리
스스로 "차단과 강등을 구분한다"고 강조하는 문서인데 정작 phase-5 를 PLANNED 로 두고 있다.

- [ ] **Step 6: 정합성을 재확인한다**

```bash
python3 ~/.claude/scripts/ksi-goals.py report
```
문서와 원장이 이제 같은 이야기를 하는지 눈으로 대조한다. 특히 track-a 항목.

- [ ] **Step 7: 커밋**

```bash
git add docs/goals/REMAINING_WORK_PLAN.md docs/goals/PHASE_REGISTRY.yaml .ksi/goals.json .ksi/ledger.jsonl
git commit -m "docs: 원장과 어긋난 계획 문서 서술을 정정한다

가장 위험했던 것은 track-a 다 — 2026-08-14 에 '실제 차단은 매니폴드가 네트워크에
없다'로 정정됐는데 REMAINING_WORK_PLAN 두 곳은 여전히 'psdk_tap 크래시 = 디버깅
과제'로 남아, 문서만 읽으면 정반대 대응(작업 vs 기다림)에 도달했다.

함께: axes 절의 '전부 조달 대기' 서술을 2026-08-13 실측으로, phase-5 의 2026-08-06
스냅샷 차단 사유를 현재 상태로, 그리고 현재 최상위 과제인 AOL/FIELD 트랙 13건이
계획 문서 어디에도 없던 것을 구조·순서만(상태는 원장이 SSOT) 추가했다."
```

---

## Task 9: 개발이 끝났는데 검증 도장만 없는 목표 3건을 닫는다

**왜 지금 하나:** 세 목표는 구현·자체 시험까지 끝났고 `completion_attempt` 도 올라가 있는데
**`gate_verdict` 이벤트가 원장에 없다**(`ungated_attempts=1`). 남은 일은 개발이 아니라
독립 reviewer 반증 1회다. 이 셋이 열려 있는 한 원장이 "진행 중 9건"으로 보이고, 그중
얼마가 진짜 미완인지 다음 세션이 매번 다시 판정해야 한다.

| goal id | 근거 (건수는 2026-08-17 `--collect-only` 실측) |
|---|---|
| `aol-1-spatial-model-lifecycle` | `services/core/src/ksi_core/spatial_model.py`, `tests/contract/test_spatial_model.py`(54건) |
| `aol-1-mission-execution-lifecycle` | `services/core/src/ksi_core/mission_execution.py`, `tests/contract/test_mission_execution.py`(**40**건) + `test_coverage_reports.py`·`test_edge_dispatch_api.py` 결선 시험 |
| `aol-2-reobservation-planning-depth` | `packages/mission-planning/src/ksi_mission_planning/reobservation.py`, `tests/contract/test_reobservation_capture.py`(**16**건), `tests/e2e/test_aol2_reobservation.py`(2건) |

**실행 시점에 다시 센다** — 위 건수는 증거로 쓰는 값이라 그 사이 바뀌었으면 실제 값을 쓴다.

**`aol-1-capture-auto-ingest`(G4)와 `aol-3-terrain-aware-planning`(G6)은 이번에 닫지 않는다.**
둘 다 `ungated_attempts=1` 로 위 셋과 상태가 같지만 성격이 다르다 — G4 는 `tools/ingest_watch.py`
구현이 끝났어도 완료기준이 "사람 손 업로드 제거"라 실제 촬영물 회수 경로가 걸려 있고, G6 는
증거가 "Unit 1만 착수·완료"라 잔여 소프트웨어 작업(Unit 2~5)이 남아 있다. **둘 다 게이트를
찍을 상태가 아니다** — 억지로 닫으면 조기완료가 된다.

**중요 — 완료 등급을 구분해 기록한다.** 이 셋은 `Backend Ready`(+대시보드 부분은
`Product Ready`)이고 **`HIL Proven` 도 `Field Proven` 도 아니다.** 실기 비행 0회이며 종단
시험의 커버리지 보고·재구성 워커는 계약대로 행동하는 대역이다. gate note 에 이 등급을
명시하지 않으면 다음 세션이 "완료"를 실기 검증으로 오독한다.

- [ ] **Step 1: 각 목표의 완료기준을 원장에서 꺼낸다**

```bash
python3 ~/.claude/scripts/ksi-goals.py report --ids
```
세 목표의 `completion_criteria` 전문을 확보한다. **전체 CI·전체 테스트는 완료 조건이
아니다** — 등록된 기준만 대조 대상이다.

- [ ] **Step 2: 근거 테스트를 실제로 돌린다**

```bash
ulimit -n 8192 && uv run pytest tests/contract/test_spatial_model.py tests/contract/test_mission_execution.py \
  tests/contract/test_reobservation_capture.py tests/e2e/test_aol1_mapping_autonomy.py \
  tests/e2e/test_aol2_reobservation.py tests/contract/test_anti_circularity_gate.py -v
```
결과(통과 건수·실패 여부)를 그대로 기록한다. **자기보고가 아니라 이 출력이 증거다.**

- [ ] **Step 3: 각 목표에 attempt 를 기록한다**

```bash
python3 ~/.claude/scripts/ksi-goals.py attempt --id aol-1-spatial-model-lifecycle --evidence "..."
```
`--evidence` 에 Step 2 의 **명령과 실제 출력**, 구현 파일 경로(file:line)를 넣는다.
"done"·"passes" 는 증거가 아니다.

- [ ] **Step 4: reviewer 를 붙여 반증을 시도한다**

> **초안은 여기서 "`strict` 면 reviewer 를 붙인다"는 조건문을 뒀다. 그 조건문이 가드를
> 무력화한다** — 2026-08-17 실측 결과 세 목표의 실효 강도는 전부 `standard` 이고
> (`kind=product` 기본값, 민감 키워드 미매칭), `ksi-goals.py:834-837` 은 strict 일 때만
> `--reviewer` 를 강제한다. 조건문대로면 "strict 가 아니므로" 메인이 스스로 pass 를 찍는
> 경로가 열리고 헬퍼도 막지 않는다. 또 `verification` 은 **저장 필드가 아니다** —
> 원장에는 `verification_requested`(세 목표 모두 `null`)만 있고 실효값은
> `effective_verification()` 이 매번 재계산한다. 원장에서 꺼내 읽으려 하면 `null` 만 보인다.

**조건 없이 무조건 독립 reviewer 반증을 거친다.** 헬퍼의 하한(`standard`)과 무관하다 —
폐루프 최상위 과제라 자기선언 pass 를 두지 않는다. **메인이 직접 pass 를 찍지 않는다** —
read-only reviewer 를 spawn 해 등록된 `completion_criteria` 대비 그 증거가 완료를 증명하는지
반증하게 하고, 깨려다 못 깨야 pass 다.

reviewer 에게 넘길 것: 목표 id, `completion_criteria` 전문, Step 2 의 명령·출력, 구현 파일
경로. reviewer 는 근거 파일을 직접 다시 열고 self-report 를 믿지 않는다.

특히 다음 두 가지를 반증 대상으로 명시한다:
1. **대역이 계약을 가리지 않았는가** — 종단 시험의 커버리지 보고·재구성 워커가 대역인데,
   그 대역이 실제 계약보다 관대해 통과시킨 것은 아닌가(ADR-KSI-020 §5.3 이 정확히 이
   실패를 기록했다 — `Mock` 봉투가 `altitude_reference` 를 시험에서 가렸다).
2. **완료기준의 각 항이 실제로 대조됐는가** — 통과한 테스트가 그 항을 검증하는 테스트가
   맞는가, 아니면 인접한 다른 성질을 검증하는가.

- [ ] **Step 5: 판정을 기록한다**

reviewer 가 못 깼으면:
```bash
python3 ~/.claude/scripts/ksi-goals.py gate --id <goal-id> --verdict pass \
  --reviewer <검증주체> --evidence-ref <transcript id 또는 아티팩트 경로> \
  --note "완료 등급: Backend Ready (+대시보드 Product Ready). HIL Proven 아님 — 실기 비행 0회, 종단 시험의 커버리지 보고·재구성 워커는 대역이다."
```

reviewer 가 깼으면:
```bash
python3 ~/.claude/scripts/ksi-goals.py gate --id <goal-id> --verdict refuted \
  --reviewer <검증주체> --evidence-ref <ref> --note "<무엇이 반증됐는지>"
```
→ `in_progress` 유지, 증거가 비워지고 새 attempt 가 강제된다. **깨진 것을 통과시키지 않는다.**

rate-limit 등으로 검증이 죽었으면 `--verdict degraded` — pass 금지다.

- [ ] **Step 6: 결과를 확인한다**

```bash
python3 ~/.claude/scripts/ksi-goals.py report
```
"만들고 있는 것" 9건이 줄었는지, 줄지 않았다면 어느 목표가 왜 refuted 인지 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add .ksi/goals.json .ksi/ledger.jsonl
git commit -m "chore(goals): AOL-1 G1·G2 · AOL-2 G5 의 미이행 검증 게이트를 닫는다

구현·자체 시험이 끝났는데 gate_verdict 이벤트가 없어 ungated_attempts 경고가
떠 있던 3건이다. 독립 reviewer 반증을 거쳐 판정을 기록했다.
완료 등급은 Backend Ready(+대시보드 Product Ready)이고 HIL Proven 이 아니다 —
실기 비행 0회, 종단 시험의 커버리지 보고·재구성 워커는 대역이다."
```

---

## Task 10: 미검증 카메라 상수에서 나온 수치를 확정값처럼 보여주지 않는다

**완화하는 리스크:** `mapping-camera-constants-are-not-m4d` (severity high, open) —
**닫지는 못한다.** 값 확정은 FIELD-0a 의 일이다. 이 Task 는 그때까지 사용자가 그 수치를
검증된 값으로 오인하지 않게 한다.

> 이 Task 는 계획 초안에 없었다. 2026-08-17 독립 검증이 "값을 바꾸는 것과 미검증임을
> 알리는 것을 구분하지 않았다"고 지적해 추가했다.

**왜 지금 하나:** 미검증이라는 사실이 **코드 주석에만** 있다.
`SiteRegistrationWizard.tsx:69-70` 이 "**M4D 실측 스펙은 미확정(H4)** 이라 지금은 매핑용
기체 카메라 급 값을 쓴다"고 적고, `SurveyWizard.tsx:162-164` 도 같은 취지다.

**그런데 화면에는 아무 단서가 없다.** 대시보드 전체에서 `sensorWidthMm`/`focalLengthMm` 은
두 위저드의 상수 선언과 `types.ts:385-386` 에만 나오고 **렌더되는 곳이 0곳**이다 — 사용자는
그 값을 보지도 고치지도 못한다. 반면 **그 상수에서 파생된 수치는 확정값처럼 화면에 뜬다** —
`SurveyWizard.tsx:897-915` 가 "격자 간격 (계산됨)", "촬영 간격 (계산됨)", "지상 해상도
{gsd*100}cm/px" 를 아무 단서 없이 표시한다.

바로 그 위 `:896-897` 주석이 스스로 의도를 밝히고 있다 — "서버가 카메라로 계산한 간격 —
**'왜 이 값인가'를 사용자가 볼 수 있어야 나중에 그 값을 다시 검증할 수 있다**". 그 의도가
절반만 구현됐다: 값은 보이는데 **그 값이 무엇에 기대고 있는지**가 안 보인다.

**INV-040 의 정신에 해당한다** — 미검증 상수에서 나온 수치를 검증된 수치와 구분 없이
보여주는 것이 always-go 다. **ADR-KSI-020 §5 동결에 걸리지 않는다** — 새 기능이 아니라
표기 교정이며, Task 6 이 이미 같은 성격의 이름 교정을 동결 안쪽으로 판정했다.

**Files:**
- Modify: `apps/dashboard/src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx` (`:896-915` 표시 블록, `:215` droneEnumValue)
- Modify: `apps/dashboard/src/app/sites/new/SiteRegistrationWizard.tsx` (`:98` droneEnumValue)
- Test: `apps/dashboard/test/` — 아래 Step 1

- [ ] **Step 1: 실패하는 테스트를 쓴다**

Task 5 가 만든 `apps/dashboard/test/evidence-panel-wiring.test.ts` 와 같은 소스 대조 방식을
쓴다(신설 파일 `apps/dashboard/test/unverified-camera-disclosure.test.ts`):

```ts
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SURVEY = readFileSync(
  join(process.cwd(), "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx"),
  "utf8",
);

describe("미검증 카메라 상수 고지", () => {
  it("[핵심] 파생 수치를 보여주는 자리에 근거가 미검증이라는 고지가 함께 있다", () => {
    // 격자 간격·촬영 간격·지상 해상도는 전부 DEFAULT_CAMERA 에서 나온다. 그 상수가
    // M4D 실측이 아니라는 사실이 코드 주석에만 있으면 사용자는 확정값으로 읽는다.
    expect(SURVEY).toContain("지상 해상도");
    expect(SURVEY).toContain("M4D 실측 전");
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

```bash
cd apps/dashboard && npx vitest run test/unverified-camera-disclosure.test.ts
```
기대: FAIL — `"M4D 실측 전"` 문자열이 아직 없다.

- [ ] **Step 3: 파생 수치 블록에 고지를 단다**

`SurveyWizard.tsx` 의 `result.gridBasis` 블록(`:899-915`) **끝**에 한 줄을 더한다. 값은
그대로 두고 근거만 밝힌다:

```tsx
                  {/* 이 세 수치는 전부 DEFAULT_CAMERA 에서 파생된다. 그 상수가 M4D
                      실측이 아니라는 사실이 코드 주석에만 있으면 사용자는 확정값으로
                      읽는다 — 값을 고치는 것은 FIELD-0a 의 일이고, 여기서 할 수 있는
                      것은 무엇에 기대고 있는지 밝히는 것이다(risk
                      mapping-camera-constants-are-not-m4d, INV-040 의 정신). */}
                  <p className="text-ink-muted mt-1 text-[12px] break-keep">
                    이 수치는 M4D 실측 전 대체 카메라 상수를 기준으로 계산됐습니다.
                    실기 확인 후 달라질 수 있습니다.
                  </p>
```

- [ ] **Step 4: 기체 식별번호에도 출처 주석을 단다**

`droneEnumValue: 99` 두 곳(`SurveyWizard.tsx:215`, `SiteRegistrationWizard.tsx:98`)에 근거
주석을 붙인다. `wpml.py:43-50` 이 이미 같은 규율을 지키고 있으니 그 어조를 따른다:

```tsx
  // 99 는 M4T(열화상) 추정값이고 **우리 기체(M4D)의 값이 아니다** — M4D 추정 1000.
  // wpml.py 의 KNOWN_DRONE_ENUM_VALUES 에도 M4D 시리즈 값이 없다(미확인, H4).
  // FIELD-0a 에서 Pilot 2 가 내보낸 KMZ 를 대조해 확정한다
  // (risk mission-drone-enum-value-is-not-m4d, docs/hil/FIELD_0A_CHECKLIST.md).
  droneEnumValue: 99,
```

- [ ] **Step 5: 테스트와 게이트를 돌린다**

```bash
cd apps/dashboard && npx vitest run test/unverified-camera-disclosure.test.ts
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```

- [ ] **Step 6: 실제 화면으로 확인한다**

조사 임무 위저드를 끝까지 진행해 계산 결과 화면에서 고지가 실제로 보이는지 눈으로 본다.

- [ ] **Step 7: 원장에 완화 사실을 기록한다 — 해소로 적지 않는다**

리스크를 `resolved` 로 바꾸지 **않는다.** 값이 여전히 미검증이므로 리스크는 열려 있다.
note 에 완화 사실만 덧붙인다:

```
[2026-08-17 부분 완화] 값은 그대로다(FIELD-0a 전에는 고칠 수 없다). 파생 수치가
확정값처럼 보이던 것만 고쳤다 — SurveyWizard 계산 결과에 근거 고지 추가,
droneEnumValue 두 곳에 출처 주석 추가. 리스크는 open 유지.
```

- [ ] **Step 8: 커밋**

```bash
git add "apps/dashboard/src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx" \
  apps/dashboard/src/app/sites/new/SiteRegistrationWizard.tsx \
  apps/dashboard/test/unverified-camera-disclosure.test.ts
git commit -m "fix(dashboard): 미검증 카메라 상수에서 나온 수치임을 화면에 밝힌다

격자 간격·촬영 간격·지상 해상도가 아무 단서 없이 확정값처럼 표시되고 있었다.
그 근거인 DEFAULT_CAMERA 가 M4D 실측이 아니라는 사실은 코드 주석에만 있었다.
값은 그대로 두고(FIELD-0a 전에는 고칠 수 없다) 무엇에 기대고 있는지만 밝힌다.
droneEnumValue=99 두 곳에도 출처 주석을 단다.

risk: mapping-camera-constants-are-not-m4d (부분 완화, open 유지)
      mission-drone-enum-value-is-not-m4d (부분 완화, open 유지)"
```

---

## 전체 완료 확인

모든 Task 를 마친 뒤 한 번에 돌린다. **여기서 실패하면 완료가 아니다.**

```bash
# Python
ulimit -n 8192 && uv run pytest -q
uv run ruff check .
uv run mypy packages services tests tools
uv run mypy .   # Task 7 이후 이것도 통과해야 한다

# 대시보드
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build

# Edge (Task 3 에서 확인한 명령)
<edge 빌드·실행 명령>; echo "exit=$?"
KSI_EDGE_TESTS_REQUIRE_SQLITE=1 <edge 실행 명령>; echo "exit=$?"

# 원장
python3 ~/.claude/scripts/ksi-goals.py report
```

기준선(2026-08-17 실측): pytest `3445 passed / 23 skipped / 3 xfailed`,
대시보드 vitest `30 files / 334 tests`, ruff·mypy(334 files)·tsc·build 전부 통과.
이 계획이 테스트를 추가하므로 건수는 **늘어야** 한다. 줄면 무언가 깨진 것이다.

리스크 원장에서 4건이 `resolved` 로 바뀌었는지 확인한다:
`evidence-artifact-content-not-bound-to-registration`,
`source-media-sealed-bundle-identity-count-only`,
`edge-runtime-tests-silently-skip-without-sqlite`,
`region-extraction-multipolygon-branch-untested`.

---

## 이 계획이 끝난 뒤의 상태 (정직한 서술)

- 미해소 리스크 15 → **11**. 남는 11건 중 high 2건은 값이 여전히 미검증이라 **open 이다** —
  Task 10 이 그 값을 확정값처럼 보여주던 것만 고쳤고, 닫는 것은 **FIELD-0a 의 일이다.**
- 진행 중 목표 9 → **6**(Task 9 가 3건을 닫는 경우). **남는 6건이 전부 하드웨어·결정 대기는
  아니다** — 2건(G4 촬영 자동 ingest · G6 지형추종 계획)은 소프트웨어 잔여가 있고, 나머지
  4건이 하드웨어·결정 대기다. 이 계획이 G4·G6 를 다루지 않은 이유는 각 Task 9 에 적었다.
- 문서와 원장이 같은 이야기를 한다 — 특히 track-a 의 차단 성격(작업 vs 기다림).
- **제품 기능은 하나도 늘지 않는다.** 그것이 이 계획의 설계다(ADR-KSI-020 §5 동결).
- **다음 관문은 코드가 아니라 FIELD-0a 세션이다** — 조종기만 있으면 되고, 비행도 매니폴드도
  필요 없으며, high 리스크 2건과 FIELD-1 이 동시에 여기 걸려 있다.

---

## 이 계획 자신의 검증 이력

초안(2026-08-17)을 독립 검토자 1명 + 검증 에이전트 3명이 반증했고, **실제 결함 20건이
나왔다.** 그중 계획대로 실행하면 피해가 났을 것들:

- `page-title.ts` 경로가 실재하지 않아 Task 6 의 `git add` 가 통째로 실패했을 것(실제 경로는
  `src/components/nav/`, `src/lib/` 아님).
- Task 8 이 phase-0·phase-2 를 "충돌"로 오독해 **정당하게 완료된 목표 2건을 `invalidate`**
  하도록 유도했을 것. 실제로는 원장(소프트웨어 범위)과 레지스트리(하드웨어 포함 전체)가
  다른 것을 세는 것이고, 양쪽 문서가 이미 그렇게 적고 있다.
- Task 3 의 `:1730` 처리가 `return` 을 넣게 해 **SQLite 없는 호스트에서 그 뒤 검사 전체를
  조용히 없앴을 것** — 고치려는 결함을 키운다.
- Task 9 의 "strict 면 reviewer" 조건문이 가드를 무력화했을 것(세 목표 실효 강도가 전부
  `standard` 라 메인이 자기 pass 를 찍는 경로가 열린다).
- high 리스크 완화 가능성을 놓쳐 Task 10 자체가 없었을 것.

**교훈 하나만 기록한다:** 초안은 서브에이전트 6명의 상세 조사를 근거로 썼는데, 그 조사가
정확했던 부분(예: 지문 위임의 안전성 — 문자 단위 대조로 확인)과 틀렸던 부분(위 5건)이
섞여 있었다. **조사 보고를 그대로 계획에 옮기지 말고, 인용한 file:line 을 최소한 표본으로
직접 열어봐야 한다.**
