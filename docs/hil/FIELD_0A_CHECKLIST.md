# FIELD-0a 체크리스트 — 비행파일 수용성 + 카메라 실측

> 목표 원장: `field-0a-kmz-acceptance` · 근거: ADR-KSI-020 §5
>
> **비행하지 않는다. 매니폴드도 필요 없다.** 기체·조종기 전원만 있으면 된다.
> 이 세션이 FIELD-1(첫 실제 매핑 비행)의 **유일한 전제**다.
>
> **PASS 증거는 `$HOME/.local/share/ksi-field-evidence`의 사용자 전용 로컬 저장소에
> 둔다.** canonical root와 세션 디렉터리는 0700, 원본과 attestation은 0600이어야 한다.
> symlink, 다른 사용자 소유, world/group-readable 경로, 재인코딩된 사진만으로는
> FIELD-0a를 시작하거나 PASS로 기록하지 않는다.

## 0. 이 세션에서 절대 하지 않는 것

- **이륙시키지 않는다.** 임포트가 성공해도 실행하지 않는다.
- **프로펠러를 장착하지 않는다.** 임무를 실은 상태에서 실수로 시작 버튼을 누르는
  표면을 물리적으로 없앤다.
- 매니폴드·PSDK 는 이 세션의 대상이 아니다(그건 FIELD-0b, `HARDWARE_SESSION_PLAYBOOK.md` 10단계).

## 1. 준비물

| 항목 | 비고 |
|---|---|
| Matrice 4D + RC Plus 2 | 프로펠러 제거 |
| USB 저장매체 또는 조종기 파일 전송 경로 | KMZ 3개를 옮긴다 |
| `$HOME/.local/share/ksi-field-evidence` | 사용자 소유 로컬 root 0700, 세션 전용 0700 디렉터리 |
| `docs/hil/field0a-kit/KSI-FIELD0A-A-droneEnum-100-payload-98.kmz` | **현재 제품이 실제로 발급하는 값**(공식 표 근거) |
| `docs/hil/field0a-kit/KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz` | 직전 제품값(2026-08-18 이전 발급분과 동일) |
| `docs/hil/field0a-kit/KSI-FIELD0A-C-droneEnum-100-wpml-1.0.3.kmz` | A 와 같고 **형식 버전만** 1.0.3(DJI 공식 샘플의 버전) |

각 비교 쌍은 **하나의 실험 변수만** 다르다 — 나머지는 완전히 같다(경로 80 웨이포인트,
고도 40m, 격자 18m, 촬영 간격 8m, 촬영 액션 포함).

- A↔B: 기체/페이로드 **프로파일**(`droneEnumValue`·`payloadEnumValue`)
- A↔C: 형식 버전(`xmlns:wpml` 의 `1.0.2`↔`1.0.3`)

거부됐을 때 **무엇을 바꿔야 하는지**를 현장에서 바로 알기 위한 배치다. 한 파일만
가져가면 거부의 이유를 모른 채 세션을 다시 잡아야 한다.

재생성은 `uv run python tools/build_field0a_kit.py`(재현 가능 — 같은 입력이면 바이트 동일).
생성 직후 `field0a-kit/SHA256SUMS`에 세 파일의 SHA-256이 기록된다. 조종기로 옮기기
전에 `cd docs/hil/field0a-kit && sha256sum -c SHA256SUMS`로 전송 대상이 이
체크리스트의 정확한 실험 파일인지 확인한다.

### Private evidence preflight

세션을 시작하기 전에 canonical local root를 만들고 소유권·권한·symlink 여부를 확인한다.
어느 하나라도 다르면 **기체를 조작하지 않고 중단**한다. 이 단순 로컬 정책은 별도 NAS가
없는 단일 운영자 FIELD-0a를 위한 것이며, 디스크 고장 시 증거가 함께 사라질 수 있다는
운영 위험을 수용한다.

```bash
ksi_field_root="${HOME}/.local/share/ksi-field-evidence"
install -d -m 700 "$ksi_field_root"
test ! -L "$ksi_field_root"
test "$(stat -c '%U' "$ksi_field_root")" = "$(id -un)"
test "$(stat -c '%a' "$ksi_field_root")" = "700"
```

확인 뒤 root 바로 아래에 세션 하나만 만들고 owner-only로 둔다. 이 경로가 후속
attestation의 `raw_evidence_root`다. `umask 077`을 먼저 적용하고, 파일명에는
serial·GPS·고객 현장명을 넣지 않는다.

```text
$HOME/.local/share/ksi-field-evidence/
  field0a-<UTC-session-id>/          # mode 0700
    pilot-import-A.png               # mode 0600, 또는 A/B/C의 실제 화면 증거
    pilot-native-mapping.kmz         # mode 0600, Pilot 2가 직접 export한 원본 bytes
    m4d-wide-original.jpg|mpo        # mode 0600, 재인코딩하지 않은 원본
    field0a-session-attestation.json # mode 0600
    field0a-readiness.json           # mode 0600
```

### USB가 없을 때: 임시 Tailnet 증거 수신기

USB 동작을 다시 증명할 필요는 없다. RC Plus 2/Pilot 2의 파일 선택기가 허용하면,
원본을 외부 Cloud가 아닌 이 워크스테이션의 owner-private session으로 직접 보낼 수 있다.
이 수신기는 제품의 정상 파일 전달 경로나 DJI Cloud API가 아니라 FIELD-0a 증거 회수를
위한 임시 전문가 도구다. 기존 read-only JSBridge probe와 별도 프로세스로 실행하며 DJI
함수를 호출하거나 기체·조종기에 쓰지 않는다.

먼저 위 규칙대로 새 session 디렉터리를 0700으로 만든다. 그다음 워크스테이션의 Tailnet
주소에만 bind한다. RC와 워크스테이션의 Tailnet IP만 `--short-client`로 허용하면
`http://<workstation-tailnet-ip>:8081/`의 짧은 주소에서 고정 증거 메뉴가 열린다. 메뉴가
capability link를 내부에서 구성하므로 운영자가 긴 token URL을 입력하거나 복사하지 않는다.

```bash
ksi_field_session_name="field0a-<UTC-session-id>"
ksi_tailnet_ip="$(tailscale ip -4 | head -n 1)"
ksi_rc_tailnet_ip="<RC-Plus-2-Tailnet-IPv4>"
uv run --locked python tools/hil/field0a_evidence_receiver.py \
  --session "$ksi_field_session_name" \
  --bind "$ksi_tailnet_ip" \
  --port 8081 \
  --short-client "$ksi_tailnet_ip" \
  --short-client "$ksi_rc_tailnet_ip"
```

출력된 짧은 URL은 허용된 RC에서만 연다. 다른 Tailnet peer의 루트 메뉴 요청은 404로
거부하며, 실제 업로드 endpoint는 계속 in-memory capability token을 검증한다. 메뉴는 다음
고정 슬롯만 한 번씩 받으며 원래 파일명은 저장하지 않는다.

- `pilot-import-a/b/c` → 실제 시도한 A/B/C 화면. A가 성공하면 A만 올린다.
- `pilot-export` → Pilot 2가 직접 내보낸 원본 KMZ.
- `m4d-original` → 재인코딩하지 않은 M4D JPEG/MPO.

각 파일은 server-fixed 이름과 0600 권한으로 저장되고 SHA-256·byte 수만 화면에 반환된다.
다운로드·목록·외부 전송·덮어쓰기는 제공하지 않는다. 잘못된 파일을 올렸으면 기존 파일을
지우거나 덮어쓰지 말고 새 session에서 다시 시작한다. 수집이 끝나면 `Ctrl-C`로 프로세스를
종료해 capability URL을 폐기한다.

Pilot 2 WebView에서 파일 선택기가 열리지 않으면 이를
`PILOT_WEBVIEW_FILE_PICKER_NOT_AVAILABLE`로 기록하고 중단한다. 그 결과는 Cloud API나
Wayline/Media 미지원 증거가 아니며, 다른 로컬 전송 경로를 선택해야 한다.

## 2. 절차 A — 우리 비행파일을 Pilot 2 가 받는가

**이게 이 세션의 핵심이다.** 지금까지 우리 KMZ 를 실기가 읽어본 적이 0회다.

1. A 파일(100)을 조종기로 옮겨 Pilot 2 항로 목록에서 임포트한다.
2. 결과를 셋 중 하나로 기록한다.
   - **임포트 성공 + 지도에 항로 표시** → 화면 사진을 남긴다(웨이포인트 수·고도가
     맞는지 눈으로 대조).
   - **임포트 성공 + 표시 이상**(웨이포인트 수 다름·고도 다름·기체 프로파일이
     다른 기종으로 뜸) → 무엇이 어떻게 다른지 적는다.
   - **거부** → **오류 메시지를 그대로 옮겨 적는다.** 이 문장이 다음 작업을 정한다.
3. **A 가 성공하면 B·C 는 건너뛴다.** 답이 이미 나왔다.
4. A 가 거부되면 B 파일(99)로 같은 과정을 반복한다 — 결과가 갈리면 기종값 문제가
   확정된다(risk `mission-drone-enum-value-is-not-m4d`).
5. B 도 거부되면 C 파일(형식 버전 1.0.3)로 반복한다 — 여기서 성공하면 원인이
   형식 버전이고, 생성기의 네임스페이스 한 줄만 고치면 된다.
6. 셋 다 거부면 기종값도 버전도 아닌 **구조** 문제다. 절차 B(Pilot 2 가 내보낸
   파일 회수)가 그 답을 통째로 가져다준다.

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

**절차 A 가 성공하든 실패하든 반드시 한다.** 이 파일 하나가 남은 형식 미확정
항목을 한 번에 정리한다.

1. Pilot 2 에서 **직접** 매핑(격자) 임무를 하나 만든다 — 아무 작은 구역이면 된다.
   고도·겹침을 우리 값과 비슷하게(40m 내외) 두면 대조가 쉽다.
2. 그 임무를 **KMZ 로 내보내기** 한다.
3. 그 파일을 회수해 온다. **이게 이 세션의 가장 값진 산출물이다.**

돌아오면 서버 쪽에서 태그 단위로 대조한다. 2026-08-18 에 핀된 PSDK 의 공식 샘플과
전수 대조해 **빠져 있던 요소는 모두 채웠고 요소 순서도 샘플에 맞췄다** — 그래서
이 표는 8개에서 3개로 줄었다. 남은 셋은 증거가 서로 어긋나거나 우리 기체 사정이
달라 **일부러 남긴 차이**다.

| # | 확인할 것 | 지금 우리 상태 | 왜 남았나 |
|---|---|---|---|
| 1 | `xmlns:wpml` 버전 | `1.0.2` | Cloud API 문서는 1.0.2, 공식 샘플은 1.0.3 — C 파일이 이걸 가른다 |
| 2 | `waypointHeadingPathMode` | **우리만 있음** | 공식 표는 "무조건 필수", 샘플엔 없음. 표를 따랐다 |
| 3 | `payloadLensIndex` | **우리만 있음** | 샘플은 렌즈를 지정하지 않는다. M4D 는 렌즈가 여럿이라 지정이 필요하다 |

회수한 파일로 셋을 확인하고, **그 밖에 우리가 아직 모르는 차이가 있는지**도 본다 —
공식 샘플은 다른 기종·다른 버전에서 나온 파일이라 M4D 기준이 아니다.

그리고 **M4D 의 실제 `droneEnumValue`·`payloadEnumValue`·`payloadSubEnumValue` 가
그 파일 안에 적혀 있다** — 절차 A 의 답이 여기서 확정된다.

> 우리 생성기와 공식 샘플의 차이는 이제 테스트가 지킨다
> (`tests/contract/test_kmz_official_sample_fidelity.py`). 새 차이가 생기면
> "근거를 적어라"며 실패하므로, 이 표가 조용히 낡지 않는다.

## 4. 절차 C — 사진 1장으로 카메라 실측

**비행하지 않는다. 지상에서 한 장 찍으면 된다.**

1. 기체 카메라로 사진 1장을 촬영한다(광각 렌즈, 기본 설정).
2. 그 원본 파일을 회수한다. **압축·리사이즈·평탄화하지 않는다** — 메타데이터가 사라진다.
   M4D는 `.jpg` 확장자 안에 두 frame을 가진 MPO를 저장할 수 있다. 이는 손상이 아니라 원본
   container이므로 JPEG로 다시 저장하지 않는다.

돌아오면 사진 파일 정보에서 다음을 읽는다.

| 읽을 값 | 쓰이는 곳 |
|---|---|
| 초점거리 (`FocalLength`) | 격자 간격·촬영 간격 계산 |
| 35mm 환산 초점거리 (`FocalLengthIn35mmFilm`) | 센서 크기 역산 |
| 이미지 가로·세로 픽셀 | GSD·촬영 폭 |
| 센서/렌즈 정보 (XMP `drone-dji:*`) | 대조 |
| **촬영 시각 (`DateTimeOriginal`)** | 공간모델 최신도의 기준점 |
| **타임존 (`OffsetTimeOriginal`)** | 위 값이 현지시각인지 UTC 인지 — 없으면 그 사실이 답이다 |
| **GPS 시각 (`GPSDateStamp` + `GPSTimeStamp`)** | 타임존이 없을 때의 대체 기준(UTC 확정) |

**왜 필요한가**: 제품은 2026-08-18부터 공식 스펙 유도값(센서 17.3mm 공칭·초점
12.0mm 유도·5280×3956)을 쓴다(`apps/dashboard/src/lib/aircraft.ts`). 유도값이므로
실측 EXIF 로 초점거리·센서를 확정해야 한다 — 이 값이 **모든 매핑 임무의 사진
밀도**를 정한다(risk `mapping-camera-constants-are-not-m4d`).

> DJI 개발도구에는 촬영 카메라의 내부 수치를 읽는 기능이 없다 —
> `dji_camera_manager.h` 는 초점·줌 조작뿐이고 내부파라미터는 장애물 인지용
> 스테레오 카메라(`dji_perception.h`)에만 있다. 그래서 사진 EXIF 가 가장 확실한 경로다.

**촬영 시각 세 줄을 왜 같이 읽는가**(2026-08-17 추가): 지금 공간모델의 "최신도"는
재구성 작업이 **성공한 시각**으로 계산된다. 3일 전에 찍은 사진을 오늘 재처리하면
그 모델이 "오늘 만든 최신 모델"로 보인다 — `spatial_model.py` 자신이 그 한계를
docstring 에 적어뒀다("등록된 시각이지 세상을 관측한 시각이 아니다").
그걸 고치려면 사진에서 촬영 시각을 읽어야 하는데, **M4D 가 그 필드를 어떤 형식으로
쓰는지(타임존을 붙이는지, GPS 시각이 있는지)를 모르면 설계를 시작할 수 없다.**
회수하는 사진에 이미 들어 있는 값이므로 **추가 세션도 추가 촬영도 필요 없다** —
표에 세 줄이 없어서 아무도 안 읽던 것뿐이다.

## 5. 회수 목록 (이것만 가져오면 된다)

1. 절차 A 결과 — 파일별 성공/실패 + **거부 시 오류 문구 원문** + 화면 사진
2. 절차 B 산출물 — **Pilot 2 가 내보낸 KMZ 파일**
3. 절차 C 산출물 — **원본 사진 1장**

## 6. 세션 후

- 원본 화면·Pilot-native KMZ·M4D 사진을 위 owner-only session directory에 먼저 둔다.
  다른 임시 저장소에서 복사했다면 원본과 private-store 복사본의 SHA-256을 다시 대조하고,
  audit에는 **private-store 복사본 경로만** 준다. raw KMZ·사진·화면·serial·GPS를 Git에 넣지
  않는다.
- `hil_raw_logs/<session_id>/` 규약의 무결성·비공개 원칙을 따른다
  (`RAW_LOG_CONVENTIONS.md`). FIELD-0a의 private 경로는 이 실행에서는
  `$HOME/.local/share/ksi-field-evidence/<session-id>/`다.
- `field0a-session-attestation.json`은 현재 사용자가 소유한 0600 일반 JSON 파일이어야
  한다. `build_commit`은 **software gate를 통과한 기능 커밋**으로 고정하고, 모든
  artifact에는 같은 `session_id`, `operator_id`, UTC 관찰 시각, private root 아래 상대 경로와
  SHA-256을 쓴다. safety scope는 `device_contact=true`, `device_write=true`,
  `propellers_removed=true`, `flight_or_motor_action=false`만 허용한다.

  ```json
  {
    "schema_version": "1.0",
    "session_id": "field0a-<UTC-session-id>",
    "operator_id": "<operator-alias>",
    "operator_attested": true,
    "build_commit": "<git-rev-parse-HEAD>",
    "started_at_utc": "<UTC>",
    "ended_at_utc": "<UTC>",
    "safety_scope": {
      "device_contact": true,
      "device_write": true,
      "propellers_removed": true,
      "flight_or_motor_action": false
    },
    "raw_evidence_root": "/home/ksi/.local/share/ksi-field-evidence/field0a-<UTC-session-id>",
    "pilot_imports": [
      {
        "variant": "A",
        "result": "IMPORTED_AND_MAPPED",
        "session_id": "field0a-<UTC-session-id>",
        "operator_id": "<operator-alias>",
        "observed_at_utc": "<UTC>",
        "raw_evidence_path": "pilot-import-A.png",
        "sha256": "<sha256>"
      }
    ],
    "pilot_export": {
      "session_id": "field0a-<UTC-session-id>",
      "operator_id": "<operator-alias>",
      "observed_at_utc": "<UTC>",
      "raw_evidence_path": "pilot-native-mapping.kmz",
      "sha256": "<sha256>"
    },
    "m4d_original": {
      "session_id": "field0a-<UTC-session-id>",
      "operator_id": "<operator-alias>",
      "observed_at_utc": "<UTC>",
      "raw_evidence_path": "m4d-wide-original.jpg",
      "sha256": "<sha256>"
    }
  }
  ```

  A가 거부돼 B/C도 시험했다면 실제 순서대로 각 화면 증거를 `pilot_imports`에 추가한다.
  아래 audit 명령에도 각 증거 파일마다 `--pilot-import-evidence <private-path>`를 한 번씩
  추가해야 한다. attestation 배열 순서와 명령 인자 순서는 동일해야 한다.
  A/B/C 모두 거부 또는 표시 이상이면 `result: "REJECTED"`와 원문 오류 문구를 raw
  evidence에 보존하고, audit 결과를 억지로 PASS로 바꾸지 않는다.
- 다음 명령이 `FIELD-0a PASS`인지 typed blocker인지 판정한다. 이는 실제 Pilot 2
  import/export provenance와 M4D 원본을 확인하는 도구이지, 비행·모터·Phase 3
  capability를 승인하는 도구가 아니다.

  ```bash
  ksi_field_session="${HOME}/.local/share/ksi-field-evidence/<session-id>"
  uv run --locked python tools/hil/audit_phase3_readiness.py \
    --pilot-import-evidence "$ksi_field_session/pilot-import-A.png" \
    --pilot-export-kmz "$ksi_field_session/pilot-native-mapping.kmz" \
    --m4d-jpeg "$ksi_field_session/m4d-wide-original.jpg" \
    --field0a-session-attestation "$ksi_field_session/field0a-session-attestation.json" \
    --output "$ksi_field_session/field0a-readiness.json"
  ```

- Git에는 session ID, local absolute path, raw file name, raw bytes, serial, GPS를 기록하지 않는다. 비민감
  digest·판정·필요한 WPML/XML 비교 결과만 목표 원장,
  Phase Registry, `.ai` handoff에 남긴다.
- 결과를 목표 `field-0a-kmz-acceptance` 의 attempt 증거로 기록한다.
- EXIF 실측값이 유도값과 다르면 `apps/dashboard/src/lib/aircraft.ts` 하나만 갱신하고,
  기존 커버리지 계약 시험이 그대로 통과하는지 확인한다.
- 촬영 시각 세 필드가 실제로 무엇이었는지 기록한다(있음/없음/형식). 그것이
  `aol-1-spatial-model-lifecycle` 의 남은 완료기준("현장 조회 응답에 촬영시각이
  실린다")을 어떻게 닫을지의 **설계 입력**이다 — 값이 없으면 그 사실 자체가
  "판정불가(fail-closed)로 둔다"는 결론의 근거가 된다.
