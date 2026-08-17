# FIELD-0a 체크리스트 — 비행파일 수용성 + 카메라 실측

> 목표 원장: `field-0a-kmz-acceptance` · 근거: ADR-KSI-020 §5
>
> **비행하지 않는다. 매니폴드도 필요 없다.** 기체·조종기 전원만 있으면 된다.
> 이 세션이 FIELD-1(첫 실제 매핑 비행)의 **유일한 전제**다.

## 0. 이 세션에서 절대 하지 않는 것

- **이륙시키지 않는다.** 임포트가 성공해도 실행하지 않는다.
- **프로펠러를 장착하지 않는다.** 임무를 실은 상태에서 실수로 시작 버튼을 누르는
  표면을 물리적으로 없앤다.
- 매니폴드·PSDK 는 이 세션의 대상이 아니다(그건 FIELD-0b, `HARDWARE_SESSION_PLAYBOOK.md` 10단계).

## 1. 준비물

| 항목 | 비고 |
|---|---|
| Matrice 4D + RC Plus 2 | 프로펠러 제거 |
| USB 저장매체 또는 조종기 파일 전송 경로 | KMZ 2개를 옮긴다 |
| `docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz` | **현재 제품이 실제로 발급하는 값**(공식 표 근거) |
| `docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz` | 직전 제품값(2026-08-18 이전 발급분과 동일) |

두 파일은 **기종값(`droneEnumValue` 100↔99)과 페이로드값(`payloadEnumValue`
98↔65534)만 다르고** 나머지는 완전히 같다
(경로 80 웨이포인트, 고도 40m, 격자 18m, 촬영 간격 8m, 촬영 액션 포함).
재생성은 `uv run python tools/build_field0a_kit.py`(재현 가능 — 같은 입력이면 바이트 동일).

## 2. 절차 A — 우리 비행파일을 Pilot 2 가 받는가

**이게 이 세션의 핵심이다.** 지금까지 우리 KMZ 를 실기가 읽어본 적이 0회다.

1. A 파일(100)을 조종기로 옮겨 Pilot 2 항로 목록에서 임포트한다.
2. 결과를 셋 중 하나로 기록한다.
   - **임포트 성공 + 지도에 항로 표시** → 화면 사진을 남긴다(웨이포인트 수·고도가
     맞는지 눈으로 대조).
   - **임포트 성공 + 표시 이상**(웨이포인트 수 다름·고도 다름·기체 프로파일이
     다른 기종으로 뜸) → 무엇이 어떻게 다른지 적는다.
   - **거부** → **오류 메시지를 그대로 옮겨 적는다.** 이 문장이 다음 작업을 정한다.
3. B 파일(99)로 같은 과정을 반복한다.
4. **두 파일의 결과가 갈리면 기종값 문제가 확정된다**(risk
   `mission-drone-enum-value-is-not-m4d`). 둘 다 거부면 기종값이 아니라 형식
   문제이므로 절차 B 가 답을 준다.

> 참고: M4 시리즈의 WPML 값은 DJI Cloud API Product Support 표에서 확인됐다
> (2026-08-18): M4D/M4TD=100(sub 0/1), M4E/M4T=99(sub 0/1), M4D 광각 카메라
> payload=98. 과거 가설(PSDK `dji_typedef.h` 매핑 → M4D=1000)은 폐기했다 —
> WPML enum 과 PSDK aircraft type 은 다른 체계다. 이 절차가 확정하는 것은 그
> 공식 값이 **실기 Pilot 2 에서도 수용되는가**다. 같은 표는 M4D 의 Cloud API
> 게이트웨이로 Dock 3 만 명시한다(M4E/T 는 "RC Plus 2 + Pilot 2" 로 별도 명시)
> — Pilot-to-Cloud 경로 리스크(`dji-pilot-cloud-wayline-support-conflicting-docs`)
> 와 정합적인 신호다. RC Plus 2 Enterprise 수동 비행 자체는 Dock 3 FAQ 가 명시
> 지원한다.

## 3. 절차 B — Pilot 2 가 내보낸 비행파일을 회수한다 (역방향 대조)

**절차 A 가 성공하든 실패하든 반드시 한다.** 이 파일 하나가 형식 미확정 항목
8개를 한 번에 정리한다.

1. Pilot 2 에서 **직접** 매핑(격자) 임무를 하나 만든다 — 아무 작은 구역이면 된다.
   고도·겹침을 우리 값과 비슷하게(40m 내외) 두면 대조가 쉽다.
2. 그 임무를 **KMZ 로 내보내기** 한다.
3. 그 파일을 회수해 온다. **이게 이 세션의 가장 값진 산출물이다.**

돌아오면 서버 쪽에서 태그 단위로 대조한다(risk
`kmz-format-never-diffed-against-dji-sample` 의 8개 항목):

| # | 확인할 것 | 지금 우리 상태 |
|---|---|---|
| 1 | `xmlns:wpml` 네임스페이스 버전 | `1.0.2` (DJI 샘플은 `1.0.3`) |
| 2 | `payloadSubEnumValue` | 없음 |
| 3 | `template.kml` 웨이포인트의 `height`·`ellipsoidHeight` | 없음(전역고도만) |
| 4 | `positioningType` | 없음 |
| 5 | `createTime`·`updateTime` | 없음 |
| 6 | `waylines.wpml` 의 `distance`·`duration` | 없음 |
| 7 | heading 하위 4개(`waypointHeadingAngle` 등) | 없음 |
| 8 | `waypointHeadingPathMode` | **우리만 있음** — 코드는 "필수"라 적었으나 DJI 샘플엔 없다 |

그리고 **M4D 의 실제 `droneEnumValue`·`payloadEnumValue` 가 그 파일 안에 적혀
있다** — 절차 A 의 답이 여기서 확정된다.

## 4. 절차 C — 사진 1장으로 카메라 실측

**비행하지 않는다. 지상에서 한 장 찍으면 된다.**

1. 기체 카메라로 사진 1장을 촬영한다(광각 렌즈, 기본 설정).
2. 그 원본 파일을 회수한다. **압축·리사이즈하지 않는다** — 메타데이터가 사라진다.

돌아오면 사진 파일 정보에서 다음을 읽는다.

| 읽을 값 | 쓰이는 곳 |
|---|---|
| 초점거리 (`FocalLength`) | 격자 간격·촬영 간격 계산 |
| 35mm 환산 초점거리 (`FocalLengthIn35mmFilm`) | 센서 크기 역산 |
| 이미지 가로·세로 픽셀 | GSD·촬영 폭 |
| 센서/렌즈 정보 (XMP `drone-dji:*`) | 대조 |

**왜 필요한가**: 제품은 2026-08-18부터 공식 스펙 유도값(센서 17.3mm 공칭·초점
12.0mm 유도·5280×3956)을 쓴다(`apps/dashboard/src/lib/aircraft.ts`). 유도값이므로
실측 EXIF 로 초점거리·센서를 확정해야 한다 — 이 값이 **모든 매핑 임무의 사진
밀도**를 정한다(risk `mapping-camera-constants-are-not-m4d`).

> DJI 개발도구에는 촬영 카메라의 내부 수치를 읽는 기능이 없다 —
> `dji_camera_manager.h` 는 초점·줌 조작뿐이고 내부파라미터는 장애물 인지용
> 스테레오 카메라(`dji_perception.h`)에만 있다. 그래서 사진 EXIF 가 가장 확실한 경로다.

## 5. 회수 목록 (이것만 가져오면 된다)

1. 절차 A 결과 — 파일별 성공/실패 + **거부 시 오류 문구 원문** + 화면 사진
2. 절차 B 산출물 — **Pilot 2 가 내보낸 KMZ 파일**
3. 절차 C 산출물 — **원본 사진 1장**

## 6. 세션 후

- `hil_raw_logs/<session_id>/` 규약대로 남긴다(`RAW_LOG_CONVENTIONS.md`).
- 결과를 목표 `field-0a-kmz-acceptance` 의 attempt 증거로 기록한다.
- EXIF 실측값이 유도값과 다르면 `apps/dashboard/src/lib/aircraft.ts` 하나만 갱신하고,
  기존 커버리지 계약 시험이 그대로 통과하는지 확인한다.
