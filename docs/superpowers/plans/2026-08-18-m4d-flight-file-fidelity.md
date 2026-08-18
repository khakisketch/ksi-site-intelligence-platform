# M4D 비행파일 신뢰성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 제품이 발급하는 모든 비행파일의 기종·페이로드 값과 대시보드 카메라 기본값을
DJI 공식 문서에서 확인된 M4D 값으로 교체하고, FIELD-0a 실기 검증 킷을 그 값으로 재생성한다.

**Architecture:** 값의 단일 출처를 만든다 — 대시보드는 새 공유 모듈
`apps/dashboard/src/lib/aircraft.ts` 하나에서 기본값을 가져오고, Python 쪽 참고표
(`wpml.py:KNOWN_DRONE_ENUM_VALUES`)는 공식 표 근거로 확장한다. KMZ 생성기 자체는
바꾸지 않는다(호출자가 값을 소유하는 설계 유지).

**Tech Stack:** Next.js 대시보드(TypeScript/vitest), Python(pytest), 기존 `wpml.py` KMZ 빌더.

**Spec:** `docs/superpowers/plans/2026-08-18-system-completion-roadmap.md` §S1 +
`docs/hil/FIELD_0A_CHECKLIST.md` + 리스크 `mission-drone-enum-value-is-not-m4d`·
`mapping-camera-constants-are-not-m4d` (.ksi/goals.json).

## 확정된 사실 (2026-08-18 웹 조사 — 이 계획의 근거)

| 값 | 확정 내용 | 출처 |
|---|---|---|
| droneEnumValue | **M4D/M4TD = 100** (sub 0/1), M4E/M4T = 99 (sub 0/1) | DJI Cloud API Product Support "Enumeration Values of Aircraft, RC and Dock" — WPML common-element 문서가 이 표를 정본으로 참조 |
| payloadEnumValue | **M4D 카메라 = 98** (98-0-0), M4TD = 99 | 같은 페이지 "Enumeration Values of Camera" |
| 카메라 | 4/3 CMOS 유효 20MP, 최대 5280×3956, FOV 84°, 35mm 환산 24mm, 기계식 셔터 2-1/2000s | enterprise.dji.com/dock-3/specs (영문 아카이브 2026-07-24 대조) |
| 실초점거리 | **공식 미기재** — 환산 24mm ÷ 크롭 2.0 ≈ 12.0mm(유도), FOV 84°와 교차 일치 | 유도값. 실기 EXIF(FIELD-0a 절차 C)가 대체 |
| 기존 저장소 가설 | PSDK `dji_typedef.h` 매핑 → M4D=1000 은 **폐기** (WPML enum ≠ PSDK aircraft type) | 위 공식 표와 모순 |

현재 제품 값(둘 다 위저드 기본값): droneEnumValue **99**(=M4E), payloadEnumValue
**65534**(placeholder), 카메라 13.2mm/8.8mm/5472×3648(1인치 20MP급 대체값).
GSD 관성: 교체 전 13.2/(8.8×5472)=2.741e-4, 교체 후 17.3/(12.0×5280)=2.730e-4
— 0.4% 차이라 간격 계산이 급변하지 않는다.

## Global Constraints

- 완료 등급은 **Backend/Product Ready 까지만** 주장한다 — 실기 수용(Pilot 2 임포트)과
  카메라 실측은 FIELD-0a(`field-0a-kmz-acceptance`) 소관으로 남는다.
- KMZ 형식 차이 8건(FIELD_0A_CHECKLIST §3 표)은 **이번 범위가 아니다** — 실기 임포트
  증거로 판정한다는 기존 결정을 유지한다. 이 계획은 공식 문서로 확정된 값만 반영한다.
- 유도값(실초점거리 12.0mm, 센서 폭 17.3mm 공칭)은 코드 주석에 유도임을 명시한다.
- `references/repos/` 수정 금지.
- 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` + Claude-Session 링크.

## 착수 준비 (Task 1 시작 전 1회)

- [ ] `git fetch origin && git checkout -b fix/m4d-flight-file-fidelity origin/main`
- [ ] 로드맵·이 계획 문서 커밋:

```bash
git add docs/superpowers/plans/2026-08-18-system-completion-roadmap.md \
        docs/superpowers/plans/2026-08-18-m4d-flight-file-fidelity.md
git commit -m "docs: 시스템 완성 로드맵 + M4D 비행파일 신뢰성 계획"
```

---

### Task 1: `wpml.py` 참고표에 M4 시리즈 공식 값 반영

**Files:**
- Modify: `packages/mission-planning/src/ksi_mission_planning/wpml.py:19-22` (docstring), `:43-50` (표)
- Test: `tests/contract/test_mission_planning.py`

**Interfaces:**
- Consumes: 없음
- Produces: `KNOWN_DRONE_ENUM_VALUES` dict 에 키 99·100 추가 (참고표 — 런타임 검증에 쓰지 않음)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/contract/test_mission_planning.py` 에 추가
  (파일 상단 import 에 `KNOWN_DRONE_ENUM_VALUES` 를 더한다):

```python
def test_known_drone_enum_table_covers_the_m4_series() -> None:
    """M4 시리즈 공식 값(DJI Cloud API Product Support 표, 2026-08-18 확인)이 참고표에 있다."""
    assert KNOWN_DRONE_ENUM_VALUES[100] == "Matrice 4D/4TD (sub 0=4D, 1=4TD)"
    assert KNOWN_DRONE_ENUM_VALUES[99] == "Matrice 4E/4T (sub 0=4E, 1=4T)"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/contract/test_mission_planning.py::test_known_drone_enum_table_covers_the_m4_series -q`
Expected: FAIL (`KeyError: 100`)

- [ ] **Step 3: 구현** — `wpml.py:43-50` 을 다음으로 교체:

```python
# droneEnumValue 참고표 — 정본은 DJI Cloud API Product Support 페이지의
# "Enumeration Values of Aircraft, RC and Dock" 표다(WPML common-element 문서가
# 그 표를 참조하라고 명시, 2026-08-18 확인).
# https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html
KNOWN_DRONE_ENUM_VALUES = {
    60: "Matrice 300 RTK",
    89: "Matrice 350 RTK",
    67: "Matrice 30/30T",
    77: "Mavic 3E/3T/3M",
    91: "Matrice 3D/3TD",
    99: "Matrice 4E/4T (sub 0=4E, 1=4T)",
    100: "Matrice 4D/4TD (sub 0=4D, 1=4TD)",
}
```

그리고 모듈 docstring 의 해당 단락(`wpml.py:19-22`)을 다음으로 교체:

```
**기체 enum 을 하드코딩하지 않는다** — :class:`DroneProfile` 로 호출자가 명시한다.
M4 시리즈 값은 2026-08-18 DJI Cloud API Product Support 표에서 확인했다
(M4D/M4TD=100(sub 0/1)·M4E/M4T=99(sub 0/1)·M4D 카메라 payload=98). 과거의
PSDK ``dji_typedef.h`` 매핑 가설(M4D=1000)은 폐기한다 — WPML enum 과 PSDK
aircraft type 은 다른 체계다. 실기 수용 확정은 FIELD-0a(Pilot 2 임포트)로 남는다.
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/contract/test_mission_planning.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add packages/mission-planning/src/ksi_mission_planning/wpml.py tests/contract/test_mission_planning.py
git commit -m "docs(mission-planning): droneEnumValue 참고표에 M4 시리즈 공식 값을 싣는다"
```

---

### Task 2: 대시보드 기본값 — 공유 상수 모듈 + 두 위저드 교체

**Files:**
- Create: `apps/dashboard/src/lib/aircraft.ts`
- Modify: `apps/dashboard/src/app/sites/new/SiteRegistrationWizard.tsx` (DEFAULT_CAMERA 정의부 :68-76, INITIAL_FORM 의 세 값 :98-100)
- Modify: `apps/dashboard/src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx` (DEFAULT_CAMERA 정의부 :162-170, INITIAL_DRAFT 의 세 값 :215-217)
- Test: `apps/dashboard/test/aircraft.test.ts` (새 파일)

**Interfaces:**
- Consumes: 없음
- Produces: `M4D_DRONE: { droneEnumValue: 100; droneSubEnumValue: 0; payloadEnumValue: 98 }`,
  `M4D_WIDE_CAMERA: { sensorWidthMm: 17.3; focalLengthMm: 12.0; imageWidthPx: 5280; imageHeightPx: 3956 }`
  — 이후 화면(예: S3 지도 UI)도 이 모듈을 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성** — `apps/dashboard/test/aircraft.test.ts`
  (소스 문자열 검사는 `coverage-report-section.test.ts` 의 기존 방식을 그대로 따른다 —
  경로 해석 idiom 이 다르면 그 파일 것을 복사):

```typescript
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { M4D_DRONE, M4D_WIDE_CAMERA } from "../src/lib/aircraft";

describe("M4D 기본값 단일 출처", () => {
  it("기종·페이로드는 공식 표 값이다 (Cloud API Product Support, 2026-08-18)", () => {
    expect(M4D_DRONE).toEqual({
      droneEnumValue: 100,
      droneSubEnumValue: 0,
      payloadEnumValue: 98,
    });
  });

  it("카메라는 공식 스펙 유도값이고 GSD 는 교체 전 대비 0.5% 이내다", () => {
    expect(M4D_WIDE_CAMERA.imageWidthPx).toBe(5280);
    expect(M4D_WIDE_CAMERA.imageHeightPx).toBe(3956);
    const before = 13.2 / (8.8 * 5472);
    const after =
      M4D_WIDE_CAMERA.sensorWidthMm /
      (M4D_WIDE_CAMERA.focalLengthMm * M4D_WIDE_CAMERA.imageWidthPx);
    expect(Math.abs(after - before) / before).toBeLessThan(0.005);
  });

  for (const wizard of [
    "src/app/sites/new/SiteRegistrationWizard.tsx",
    "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx",
  ]) {
    it(`${wizard} 는 공유 상수를 쓰고 구 값을 하드코딩하지 않는다`, () => {
      const source = readFileSync(join(__dirname, "..", wizard), "utf8");
      expect(source).toContain('from "@/lib/aircraft"');
      expect(source).not.toMatch(/droneEnumValue:\s*99/);
      expect(source).not.toMatch(/payloadEnumValue:\s*65534/);
      expect(source).not.toMatch(/sensorWidthMm:\s*13\.2/);
    });
  }
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd apps/dashboard && npx vitest run test/aircraft.test.ts`
Expected: FAIL (`Cannot find module '../src/lib/aircraft'`)

- [ ] **Step 3: 공유 모듈 구현** — `apps/dashboard/src/lib/aircraft.ts`:

```typescript
/**
 * 운용 기체(DJI Matrice 4D) 기본값 — 위저드들이 공유하는 단일 출처.
 *
 * 기종·페이로드 값 정본: DJI Cloud API Product Support "Enumeration Values"
 * (2026-08-18 확인) — M4D: droneEnumValue 100/sub 0, 광각 카메라 payloadEnumValue 98.
 * https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html
 * 실기 Pilot 2 가 이 값을 수용하는지는 FIELD-0a 에서 확정한다.
 */
export const M4D_DRONE = {
  droneEnumValue: 100,
  droneSubEnumValue: 0,
  payloadEnumValue: 98,
} as const;

/**
 * M4D 광각 카메라 — DJI 공식 스펙(4/3 CMOS 20MP, 5280×3956, FOV 84°, 35mm 환산
 * 24mm — enterprise.dji.com/dock-3/specs, 2026-08-18 확인)에서 유도한 값.
 * 실초점거리는 공식 미기재라 환산 24mm ÷ 크롭 2.0 ≈ 12.0mm 유도값이고 센서 폭
 * 17.3mm 는 4/3형 공칭값이다 — 실기 EXIF 실측(FIELD-0a 절차 C)이 이 유도값을
 * 대체한다. 그때는 이 파일 하나만 갱신하면 된다(간격은 서버가 다시 계산한다).
 */
export const M4D_WIDE_CAMERA = {
  sensorWidthMm: 17.3,
  focalLengthMm: 12.0,
  imageWidthPx: 5280,
  imageHeightPx: 3956,
} as const;
```

- [ ] **Step 4: SiteRegistrationWizard.tsx 교체**

import 블록에 추가:

```typescript
import { M4D_DRONE, M4D_WIDE_CAMERA } from "@/lib/aircraft";
```

`:68-76` 의 주석+`DEFAULT_CAMERA` 정의를 다음으로 교체(파일 내 기존 사용처는
`DEFAULT_CAMERA` 이름 그대로 두기 위해 별칭만 남긴다):

```typescript
// 기체 카메라 — 단일 출처는 @/lib/aircraft (공식 스펙 유도값, EXIF 실측 대체 예정).
const DEFAULT_CAMERA = M4D_WIDE_CAMERA;
```

`INITIAL_FORM` 의 세 줄(:98-100)을 교체:

```typescript
  droneEnumValue: M4D_DRONE.droneEnumValue,
  droneSubEnumValue: M4D_DRONE.droneSubEnumValue,
  payloadEnumValue: M4D_DRONE.payloadEnumValue,
```

- [ ] **Step 5: SurveyWizard.tsx 교체** — 같은 방식: import 추가, `:162-170` 의
  주석+정의를 위 별칭 두 줄로 교체, `INITIAL_DRAFT` 의 세 줄(:215-217)을 위와
  동일하게 교체.

- [ ] **Step 6: 통과 확인 + 대시보드 게이트**

Run: `cd apps/dashboard && npx vitest run && npm run lint && npx tsc --noEmit`
Expected: 전부 PASS (기존 338 + 신규)

- [ ] **Step 7: 커밋**

```bash
git add apps/dashboard/src/lib/aircraft.ts apps/dashboard/test/aircraft.test.ts \
        apps/dashboard/src/app/sites/new/SiteRegistrationWizard.tsx \
        "apps/dashboard/src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx"
git commit -m "fix(dashboard): 기종·페이로드·카메라 기본값을 M4D 공식 값으로 교체한다"
```

참고: Python 계약·e2e 테스트의 `{"droneEnumValue": 99, ..., "payloadEnumValue": 65534}`
페이로드는 호출자 임의값으로 여전히 유효하므로 **바꾸지 않는다**(서버는 값을 소유하지 않는다).

---

### Task 3: FIELD-0a 킷 재생성 + 체크리스트 갱신

**Files:**
- Create: `tools/build_field0a_kit.py`
- Rename: `docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-99.kmz` → `KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz`
- Delete: `docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-1000.kmz` (가설 폐기)
- Create(스크립트 산출물): `docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz`
- Modify: `docs/hil/FIELD_0A_CHECKLIST.md`

**Interfaces:**
- Consumes: Task 1 이전과 무관 — `wpml.py` 의 기존 공개 API(`DroneProfile`,
  `WaylineMissionConfig`, `build_kmz`)와 `coverage.py` 의 `RouteWaypoint(lat_deg, lon_deg, altitude_m)`
- Produces: 재현 가능한 킷 생성 스크립트(고정 zip 타임스탬프라 같은 입력이면 바이트 동일)

- [ ] **Step 1: 파일 정리(rename·delete)**

```bash
git mv docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-99.kmz \
       docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz
git rm docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-1000.kmz
```

- [ ] **Step 2: 생성 스크립트 작성** — `tools/build_field0a_kit.py`:

```python
"""FIELD-0a 킷 재생성 — 기존 킷의 경로·설정은 그대로, 기종·페이로드 값만 바꾼다.

B 파일(직전 제품값 99/0/65534)에서 경로·속도·고도를 읽어 A 파일(현행 제품값
100/0/98)을 만든다. 촬영 액션 포함, 나머지 내용은 두 파일이 완전히 같다.
zip 타임스탬프가 고정돼 있어(같은 입력 → 같은 바이트) 재현 가능하다.

실행: uv run python tools/build_field0a_kit.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ksi_mission_planning.coverage import RouteWaypoint
from ksi_mission_planning.wpml import DroneProfile, WaylineMissionConfig, build_kmz

KIT_DIR = Path(__file__).resolve().parent.parent / "docs" / "hil" / "field0a-kit"
SOURCE = KIT_DIR / "KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz"
TARGET = KIT_DIR / "KSI-FIELD0A-A-droneEnum-100-payload-98.kmz"

WPML = "{http://www.dji.com/wpmz/1.0.2}"
KML = "{http://www.opengis.net/kml/2.2}"

# 현행 제품값 — 정본: DJI Cloud API Product Support 표(2026-08-18 확인).
M4D = DroneProfile(drone_enum_value=100, drone_sub_enum_value=0, payload_enum_value=98)


def _text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    if node is None or node.text is None:
        raise SystemExit(f"원본 킷에서 {path} 를 찾지 못했다")
    return node.text


def main() -> None:
    with zipfile.ZipFile(SOURCE) as archive:
        waylines = ET.fromstring(archive.read("wpmz/waylines.wpml"))

    route: list[RouteWaypoint] = []
    for placemark in waylines.iter(f"{KML}Placemark"):
        lon, lat = _text(placemark, f"{KML}Point/{KML}coordinates").split(",")
        height = _text(placemark, f"{WPML}executeHeight")
        route.append(
            RouteWaypoint(lat_deg=float(lat), lon_deg=float(lon), altitude_m=float(height))
        )

    config = WaylineMissionConfig(
        auto_flight_speed_ms=float(_text(waylines, f".//{WPML}autoFlightSpeed")),
        takeoff_security_height_m=float(_text(waylines, f".//{WPML}takeOffSecurityHeight")),
        global_transitional_speed_ms=float(_text(waylines, f".//{WPML}globalTransitionalSpeed")),
    )

    TARGET.write_bytes(build_kmz(route, drone=M4D, config=config, capture_at_waypoints=True))
    print(f"생성: {TARGET.name} (웨이포인트 {len(route)}개)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 실행 + 차이 검증** — A·B 가 기종·페이로드 값만 다른지 확인:

```bash
uv run python tools/build_field0a_kit.py
cd docs/hil/field0a-kit && python3 - <<'EOF'
import difflib, zipfile
def lines(name, member):
    text = zipfile.ZipFile(name).read(member).decode().replace("><", ">\n<")
    return text.splitlines()
for member in ("wpmz/waylines.wpml", "wpmz/template.kml"):
    diff = list(difflib.unified_diff(
        lines("KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz", member),
        lines("KSI-FIELD0A-A-droneEnum-100-payload-98.kmz", member), lineterm=""))
    changed = [d for d in diff if d.startswith(("+<", "-<"))]
    print(member, "변경 줄:", *changed, sep="\n")
EOF
cd ../../..
```

Expected: 파일마다 변경 줄이 정확히 4줄 — `droneEnumValue` 99→100, `payloadEnumValue`
65534→98 (각각 -/+ 한 쌍). 웨이포인트 80개 출력 확인. 다른 줄이 나오면 **중단하고 원인 조사**.

- [ ] **Step 4: 체크리스트 갱신** — `docs/hil/FIELD_0A_CHECKLIST.md`:

1. §1 준비물 표의 킷 두 줄을 교체:

```markdown
| `docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz` | **현재 제품이 실제로 발급하는 값**(공식 표 근거) |
| `docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz` | 직전 제품값(2026-08-18 이전 발급분과 동일) |
```

2. 표 아래 문장을 교체:

```markdown
두 파일은 **기종값(`droneEnumValue` 100↔99)과 페이로드값(`payloadEnumValue`
98↔65534)만 다르고** 나머지는 완전히 같다
(경로 80 웨이포인트, 고도 40m, 격자 18m, 촬영 간격 8m, 촬영 액션 포함).
```

3. §2 절차 A 의 파일 참조 갱신 — 1번 "A 파일(99)" → "A 파일(100)",
   3번 "B 파일(1000)" → "B 파일(99)". 4번 문장은 유지(두 파일 결과가 갈리면 기종값
   문제 확정 — 이제 A 거부·B 수용이면 공식 표와 실기가 어긋난다는 더 강한 신호다).

4. §2 끝의 참고 블록(PSDK 매핑 가설)을 교체:

```markdown
> 참고: M4 시리즈의 WPML 값은 DJI Cloud API Product Support 표에서 확인됐다
> (2026-08-18): M4D/M4TD=100(sub 0/1), M4E/M4T=99(sub 0/1), M4D 광각 카메라
> payload=98. 과거 가설(PSDK `dji_typedef.h` 매핑 → M4D=1000)은 폐기했다 —
> WPML enum 과 PSDK aircraft type 은 다른 체계다. 이 절차가 확정하는 것은 그
> 공식 값이 **실기 Pilot 2 에서도 수용되는가**다. 같은 표는 M4D 의 Cloud API
> 게이트웨이로 Dock 3 만 명시한다(M4E/T 는 "RC Plus 2 + Pilot 2" 로 별도 명시)
> — Pilot-to-Cloud 경로 리스크(`dji-pilot-cloud-wayline-support-conflicting-docs`)
> 와 정합적인 신호다. RC Plus 2 Enterprise 수동 비행 자체는 Dock 3 FAQ 가 명시
> 지원한다.
```

5. §4 "왜 필요한가" 단락을 교체:

```markdown
**왜 필요한가**: 제품은 2026-08-18부터 공식 스펙 유도값(센서 17.3mm 공칭·초점
12.0mm 유도·5280×3956)을 쓴다(`apps/dashboard/src/lib/aircraft.ts`). 유도값이므로
실측 EXIF 로 초점거리·센서를 확정해야 한다 — 이 값이 **모든 매핑 임무의 사진
밀도**를 정한다(risk `mapping-camera-constants-are-not-m4d`).
```

6. §6 마지막 항목을 교체:

```markdown
- EXIF 실측값이 유도값과 다르면 `apps/dashboard/src/lib/aircraft.ts` 하나만 갱신하고,
  기존 커버리지 계약 시험이 그대로 통과하는지 확인한다.
```

- [ ] **Step 5: 재현성 확인** — 스크립트를 한 번 더 실행해 바이트 동일 확인:

```bash
sha256sum docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz
uv run python tools/build_field0a_kit.py
sha256sum docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz
```

Expected: 두 해시 동일.

- [ ] **Step 6: 커밋**

```bash
git add tools/build_field0a_kit.py docs/hil/field0a-kit/ docs/hil/FIELD_0A_CHECKLIST.md
git commit -m "fix(hil): FIELD-0a 킷을 공식 M4D 값(100/98)으로 재생성한다"
```

---

### Task 4: 리스크 원장 반영 + 전체 게이트

**Files:**
- Modify: `.ksi/goals.json` (헬퍼 경유 — 손편집 금지)

**Interfaces:**
- Consumes: Task 1~3 의 커밋 결과
- Produces: 리스크 `mission-drone-enum-value-is-not-m4d` resolved

- [ ] **Step 1: 기종값 리스크 해소** (카메라 리스크는 **열어 둔다** — 유도값이지 실측이
  아니므로 "사진 밀도가 실측되지 않은 상수 위에 있다"는 여전히 참):

```bash
python3 ~/.claude/scripts/ksi-goals.py risk-resolve --id mission-drone-enum-value-is-not-m4d \
  --evidence-ref "DJI Cloud API Product Support 표(2026-08-18): M4D=100/sub0, payload 98 — apps/dashboard/src/lib/aircraft.ts 로 발급 기본값 교체, FIELD-0a 킷 A/B 재생성(tools/build_field0a_kit.py). 실기 임포트 수용 확정은 field-0a-kmz-acceptance criteria 에 이미 포함"
```

- [ ] **Step 2: 원장 렌더 확인**

Run: `python3 ~/.claude/scripts/ksi-goals.py risk-list | head -40`
Expected: high 리스크에서 `mission-drone-enum-value-is-not-m4d` 사라짐,
`mapping-camera-constants-are-not-m4d` 는 open 유지.

- [ ] **Step 3: 전체 게이트**

```bash
ulimit -n 8192 && uv run pytest -q
uv run ruff check . && uv run mypy packages/mission-planning/src/ksi_mission_planning/wpml.py tools/build_field0a_kit.py
cd apps/dashboard && npm run test && npm run lint && npx tsc --noEmit && npm run build
```

Expected: 전부 PASS (Python 3455+1, dashboard 338+4 수준).

- [ ] **Step 4: 커밋**

```bash
git add .ksi/
git commit -m "chore(risk): 기종값 리스크를 공식 표 근거로 해소한다"
```

---

## Self-Review 기록

- 범위 대조: 로드맵 §S1 의 세 항목 중 "KMZ 형식 8건 차이"는 의도적으로 제외
  (Global Constraints 명시 — 실기 증거로 판정한다는 기존 결정 유지). 나머지 두
  리스크는 Task 1~4 가 전부 다룬다.
- 타입 일관성: `M4D_DRONE`·`M4D_WIDE_CAMERA` 키 이름은 위저드 폼 필드·
  `MissionPlanRequest` 의 camelCase 계약(`droneEnumValue` 등)과 일치.
- placeholder 스캔: 없음. 모든 코드 블록은 그대로 적용 가능한 완성 코드다.
- 남는 것(정직): 실기 수용성·EXIF 실측은 이 계획으로 닫히지 않는다 —
  `field-0a-kmz-acceptance` 의 기존 완료 기준이 그대로 담당한다.
