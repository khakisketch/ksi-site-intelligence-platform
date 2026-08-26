# Phase 3 RC-first 승인 제한형 HIL 준비 체크리스트

Status: `BLOCKED` — 물리 장비 세션과 명시적 승인 전 실행 금지.

Phase 2 synthetic staging PASS는 장비 연결을 요구하지 않았다. 아래 항목은 다음 단계의 준비물과
중지 조건을 고정할 뿐, 현재 capability를 지원한다고 주장하지 않는다.

## 2026-08-26 장비 없는 사전검증 결과

- FIELD-0a A/B/C kit의 SHA-256, 안전한 KMZ member 집합, 80개 waypoint, 80개 촬영 action,
  40m execute height가 모두 PASS다.
- 기존 Pilot 2 화면 증거에서 A 파일 이름, 80개 waypoint·80개 사진과 지도 표시를 다시
  확인했다. 실행 control은 누르지 않았고, 이 관찰을 비행 가능 증거로 사용하지 않는다.
- 기존 M4D WideCamera 원본은 `.jpg` 확장자의 2-frame MPO이며 5280×3956, 12.29mm,
  35mm 환산 24mm와 검증 가능한 촬영시각을 보존한다. MPO를 평탄화하거나 재인코딩하지 않는다.
- Pilot 2가 직접 export한 mapping KMZ와 회수 출처 증거는 현재 파일에서 찾지 못했다.
  따라서 formal FIELD-0a는 계속 `BLOCKED`다. FIELD-0a는 Phase 3B HIL 이후의 별도
  gate이며, 이 결손을 Phase 3A candidate 구현 금지로 다시 해석하지 않는다.
- private audit manifest는 ignored `.dev-data/phase3-readiness/field0a-readiness-20260826.json`
  에 0700/0600으로 저장했다. GPS와 장치 serial은 manifest에 쓰지 않았다.
- 2026-08-26 재접속 확인에서 Tailnet의 RC Plus 2는 5일째 offline이고 Manifold peer는
  관찰되지 않았다. 따라서 새 물리 세션과 device-bound approval 없이 Phase 3B로 넘어가지 않는다.
- 핀된 PSDK 3.16 arm64 archive는 `Init/UploadKmzFile/DeInit`과 public `Action`을 같은
  `dji_waypoint_v3.c.o`에 보존한다. member 단위 preflight가 이를
  `ACTION_COLOCATED_WITH_UPLOAD`으로 차단한다. archive strip/rewrite는 증거가 아니다.

재검증 명령은 장비·네트워크를 호출하지 않는다.

```bash
uv run --locked python tools/hil/audit_phase3_readiness.py \
  --pilot-import-evidence <pilot-import-screen-1> \
  --pilot-import-evidence <pilot-import-screen-2> \
  --m4d-jpeg <original-m4d-jpeg-or-mpo> \
  --output <private-ignored-output.json>
```

나중에 Pilot-export KMZ가 확보돼도 `--pilot-export-kmz`의 byte 검사만으로 FIELD-0a를
자동 PASS시키지 않는다. Pilot 2 export 동작·회수 경로·UTC·운영자 attestation이 별도로 필요하다.

## SDK 입력 사전검증

PSDK archive 검사는 핀 SHA-256과 정적 linker가 실제 선택할 member의 전체 Waypoint
심볼을 기록한다. 현재 정상 결과는 exit 2와 `BLOCKED`이며 이를 억지로 0으로 만들지 않는다.

```bash
umask 077
set +e
uv run --locked python tools/edge/check_psdk_waypoint_archive.py --format json \
  > <private-session>/02_sample_build/psdk-waypoint-archive.json
status=$?
set -e
test "$status" -eq 2
```

MSDK Android project와 Dock OpenAPI는 외부 또는 gitignored 입력으로만 검사한다.
license/EULA 파일과 고정 버전 build input의 digest만 기록하며 credential 값·경로·digest는
출력하지 않는다. credential file은 현재 사용자 소유 0600 일반 파일이어야 한다.

```bash
uv run --locked python tools/hil/check_dji_sdk_readiness.py \
  --msdk-root <external-or-ignored-android-project> \
  --msdk-license <external-or-ignored-license> \
  --msdk-credential-file <owner-0600-secret> \
  --dock-openapi <external-or-ignored-openapi-v3> \
  --dock-license <external-or-ignored-license> \
  --dock-credential-file <owner-0600-secret>
```

입력이 없는 현재 판정은 MSDK/Dock 모두 `NOT_CONFIGURED`다. 이 결과는 manifest에
`SDK_BUILT`로 기록할 수 없다. PSDK blocker를 현재 세션에 기록할 때는 다음처럼 build와
capability를 각각 차단하고 raw JSON evidence를 참조한다.

```bash
uv run python tools/hil/prepare_connected_edge_session.py record-build \
  <manifest-v1.4> --path PSDK_MANIFOLD --status BLOCKED \
  --code-commit <git-sha> --sdk-version PSDK-3.16.0 \
  --evidence-ref 02_sample_build/psdk-waypoint-archive.json
uv run python tools/hil/prepare_connected_edge_session.py record-blocker \
  <manifest-v1.4> --capability WAYLINE_DELIVERY --path PSDK_MANIFOLD \
  --hardware-model <exact-models> --firmware-version <exact-versions> \
  --blocker-code ACTION_COLOCATED_WITH_UPLOAD \
  --evidence-ref 02_sample_build/psdk-waypoint-archive.json
```

## 세션 전 준비

- Matrice 4D, RC Plus 2, Manifold 3의 실제 식별자와 소유·시험 승인을 기록한다.
- 기체는 지상 안전 상태, propeller/이륙 방지 절차, 충분한 배터리와 담당 안전 인력을 갖춘다.
- RC Wi-Fi 기본 profile을 사용하고 SIM 없음 조건을 별도로 기록한다.
- Manifold의 유선 interface, IP, ARP/ping 결과를 새 raw session에 저장한다.
- read-only inventory를 먼저 끝낸다. DPK install/restart나 제한적 전송은 v1.4 approval
  envelope의 session/device/DPK digest/operation/expiry가 정확히 일치할 때만 시작한다.
- credential은 0600 secret file로만 주입하고 manifest·명령행·로그·스크린샷에 값을 남기지 않는다.
- 기존 DPK 상태와 rollback 담당자를 기록하고, 승인되지 않은 operation이 필요하면 즉시 중단한다.
- 기존 `NOT_VERIFIED` capability registry와 rollback/stop 담당자를 확인한다.

## capability별 최소 증거

| Capability | 승인된 관찰·제한 전송 목표 | 금지된 추론 |
|---|---|---|
| `WAYLINE_DELIVERY` | `Init → UploadKmzFile → DeInit` 응답·식별자 확인 | upload 성공을 비행 가능으로 해석 |
| `EDGE_DOWNLINK` | RC/Core→Manifold 메시지 수신과 lineage | 좌표·명령 실행 |
| `EDGE_UPLINK` | Manifold→RC/Core 상태 수신과 재연결 | telemetry만으로 제어 지원 주장 |
| `MEDIA_PULL` | 승인된 기존 시험 이미지 1건 목록·download·digest 확인 | 카메라 제어·삭제·촬영 |
| `MEDIA_UPLOAD` | 승인된 합성 파일의 경로·digest 관찰 | 고객 media 또는 외부 Cloud 전송 |

각 capability는 서로 독립적으로 PASS/BLOCKED/NOT_VERIFIED를 기록한다. 하나의 성공으로 나머지를
승격하지 않는다.

## 즉시 중지 조건

- 예상하지 않은 이륙, motor, waypoint, gimbal/camera write 표면이 열림.
- 신원·Site·Mission·device binding을 확인할 수 없음.
- raw log의 시간, 요청/응답, digest 또는 담당자 기록이 누락됨.
- Manifold unreachable, 네트워크 경로 불명, 배터리/RTH 동작을 확인해야 하는 상황.
- 실제 고객 데이터나 승인되지 않은 외부 endpoint가 필요함.
- approval의 device/DPK digest/operation/expiry가 현재 실행과 다름.

이 체크리스트만으로 배터리, RTH, avoidance, camera, flight capability는 검증되지 않는다.
