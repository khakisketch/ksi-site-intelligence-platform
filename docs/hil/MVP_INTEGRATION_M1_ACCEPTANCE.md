# MVP Integration Milestone 1 — zero-touch provider acceptance

> **2026-08-21 ADR-KSI-023 전환:** 이 문서의 v1.2 provider track은 당시 조사와
> raw evidence를 보존하는 역사적 절차다. 최종 채택 단위는 이제 provider 하나가
> 아니라 `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`,
> `MEDIA_UPLOAD` 각각의 정확한 하드웨어·펌웨어·경로 capability다. 아래 §6의
> provider 선택은 runtime feature flag를 켜는 근거로 더 이상 충분하지 않다.
> RC-first 정본 acceptance는 v1.3 manifest를 사용하며 현재 전 항목 `NOT_VERIFIED`다.

## 0. RC-first Connected Edge v1.3 시작점

첫 세션은 `M4D + Manifold 3 + RC Plus 2 + RC Wi-Fi`, Manifold SIM 없음으로 고정한다.
장비나 네트워크를 변경하지 않는 private skeleton 생성·검증 명령은 다음과 같다.

```bash
uv run python tools/hil/prepare_connected_edge_session.py init \
  --operator <operator-id> \
  --aircraft-sn <actual-sn> \
  --edge-device-id <manifold-device-id> \
  --gateway-device-id <rc-device-id>

uv run python tools/hil/prepare_connected_edge_session.py verify \
  hil_raw_logs/<session-id>/integration_manifest.v1.3.json
```

기존 v1.2 manifest를 감사용으로 연결해야 하면 새 출력 파일에 fail-closed migration한다.
기존 provider 판정의 digest는 보존하지만 어떤 v1.3 capability도 자동 승격하지 않는다.

```bash
uv run python tools/hil/prepare_connected_edge_session.py migrate-v12 \
  hil_raw_logs/<legacy-session>/integration_manifest.json \
  hil_raw_logs/<legacy-session>/integration_manifest.v1.3.json
```

다섯 capability는 서로 독립적인 evidence ref를 가져야 하고, `VERIFIED` 전에는 대응
feature flag를 켤 수 없다. Cloud 업링크 성공은 하향 전달이나 media pull 성공의
증거가 아니며, PSDK header/API 존재도 실장비 receipt를 대체하지 않는다.

- 상태: `READY / HIL BLOCKED` (2026-08-20 host preflight)
- 대상: Matrice 4D + RC Plus 2 + Manifold 3
- 요구사항: REQ-ACQ-101/102, REQ-WRK-101, INV-001/002/040/041/050/051/060
- 목표: Cloud 또는 PSDK 중 **실기에서 증명된 한 경로만** `ZeroTouchGateway` provider로 채택한다.

## 1. 현재 판정

| 경로 | 공식 문서가 확인하는 것 | KSI 판정 |
|---|---|---|
| DJI Cloud / Pilot-to-Cloud | Cloud API 공식 product-support 표는 M4D/M4TD를 Dock 3 경로에만 두고, RC Plus 2 + Pilot 2 경로에는 M4E/M4T만 열거한다 | `BLOCKED / UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX` |
| Manifold 3 + PSDK | PSDK는 M4D/4TD Pilot 조합의 Manifold 3 basic/advanced 지원과 camera media list/download API를 문서화한다 | `BLOCKED / MANIFOLD_UNREACHABLE` (aircraft link `UNKNOWN`) |
| MSDK V5 | MSDK V5 지원표에는 M4D/4TD + RC Plus 2가 있다 | `FALLBACK / Pilot 2 coexistence NOT_DOCUMENTED` |

확인일은 2026-08-20이다. 문서상 API 존재는 KSI의 실제 장비 PASS가 아니다. Cloud Track은
standalone M4D + RC Plus 2 조합이 공식 지원표에 추가되거나 DJI의 서면 확인을 받기 전에는
credential 입력이나 우회 실험으로 다시 열지 않는다.

공식 근거:

- DJI Cloud API product support: <https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html>
- DJI Cloud API supported products/firmware: <https://developer.dji.com/doc/cloud-api-tutorial/en/>
- DJI FlightHub 2 product/FAQ: <https://enterprise.dji.com/flighthub-2>, <https://enterprise.dji.com/flighthub-2/faq>
- PSDK Manifold capabilities: <https://developer.dji.com/doc/payload-sdk-tutorial/en/manifold-quick-start/psdk-capabilities-overview.html>
- PSDK camera management: <https://developer.dji.com/doc/payload-sdk-tutorial/en/function-overview/advanced-function/basic-camera-management.html>
- PSDK API reference: <https://developer.dji.com/doc/payload-sdk-api-reference/en/>
- MSDK V5 supported products/release notes: <https://developer.dji.com/doc/mobile-sdk-tutorial/en/>

## 2. 공통 안전·보안 경계

- 프로펠러를 제거하고 비행·route start·gimbal·camera delete·storage format을 수행하지 않는다.
- 이 문서의 현장 capture/착륙 단계는 별도 FIELD 세션에서 사용자가 명시적으로 승인한 뒤에만 수행한다.
  현재 Milestone 1 preflight는 작업·경로 검토까지만 허용하고 실행하지 않는다.
- 계정 비밀번호, OTP, DJI App key/license, bearer token, cookie, private key는 사용자가 화면이나
  장비의 비추적 보안 파일에 직접 입력한다. 명령행·JSON·스크린샷·로그·저장소에 쓰지 않는다.
- 원본 JPEG를 이동·변경·삭제하지 않는다. PSDK downloader rights는 시험 후 반드시 release하고
  Pilot 2 album 접근이 복구됐는지 확인한다.
- GPS·기체 SN·원본 media가 포함된 raw evidence는 `hil_raw_logs/`에만 두고 커밋하지 않는다.
- 외부 Cloud/LLM 반출은 해당 site의 egress policy가 명시적으로 허용할 때만 한다.
- 조직·site·work order·mission·media 식별자를 한 evidence chain으로 보존한다.
- capability는 모든 항목과 구체 evidence ref가 충족되기 전까지 `NOT_VERIFIED` 또는 `BLOCKED`다.

## 3. 세션 준비

다음 명령은 장비나 네트워크를 건드리지 않고 private evidence skeleton만 만든다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py init \
  --operator <operator-id> \
  --aircraft-sn PENDING-SN
```

생성되는 `integration_manifest.json`은 secret-like 필드를 거부하고 Cloud는 공식 지원표 근거로
`BLOCKED`, PSDK는 `NOT_VERIFIED`에서 시작한다. 사람이 실측 evidence를 채운 뒤 다음 명령으로
fail-closed 검증한다.

manifest schema v1.2에서 각 check는 `passed`와 자기 `evidence_refs`를 가진다. 서로 다른 passed
check가 같은 파일을 재사용할 수 없고, check별 허용 stage도 고정된다. `VERIFIED`에는 실제 aircraft
SN, 종료 UTC, 각 check의 세션 내부 0600 evidence 파일, 모든 evidence의 SHA-256/size를 고정한
`13_provider_decision/` decision record가 모두 필요하다. `BLOCKED`도 blocker code와 별도 evidence
파일 없이는 성립하지 않는다. 초기화 시 Cloud 공식 지원표 판정 파일이 자동 생성된다.

미채택 v1.1 session은 다음 명령으로 v1.2에 올린다. 이미 provider가 채택됐다고 주장하는 legacy
v1.1 session은 decision digest를 추측해 만들 수 없으므로 `verify`와 자동 upgrade 모두 거부한다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py upgrade \
  hil_raw_logs/<session-id>/integration_manifest.json
```

```bash
uv run python tools/hil/prepare_mvp_integration_session.py verify \
  hil_raw_logs/<session-id>/integration_manifest.json
```

Manifold가 연결된 뒤 host에서 다음 read-only preflight를 먼저 실행한다. 결과는 0600 JSON으로
`09_mvp_provider_preflight/`에 기록되고 manifest의 PSDK blocker evidence에 자동 연결된다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py preflight \
  hil_raw_logs/<session-id>/integration_manifest.json \
  --target 172.30.1.33 \
  --interface enP7s7
```

이 명령은 `ip`, neighbor, route, ICMP, host USB inventory만 읽는다. remote SSH, DPK, camera,
aircraft, storage를 호출하지 않으며 aircraft link는 항상 `UNKNOWN`으로 남긴다.

`PENDING-SN` session은 host preflight까지만 사용한다. read-only identity에서 실제 SN을 확인하면
그 SN으로 새 acceptance session을 `init --aircraft-sn <actual-sn>`하여 identity evidence를 다시
수집한다. 디렉터리명과 manifest를 수동 리네임·편집하지 않는다.

장비 runner가 만든 raw log/JPEG/lineage 파일을 해당 private stage에 저장하고 0600으로 제한한다.
운영자가 화면·장비 상태와 아래 필수 assertion을 직접 확인한 뒤 `attest-check`를 실행한다. 도구는
외부 파일을 복사하거나 내용을 출력하지 않고, raw artifact의 SHA-256/size를 가진 PASS envelope를
만든 뒤 동일 validator로 check를 기록한다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py attest-check \
  hil_raw_logs/<actual-sn-session>/integration_manifest.json \
  --track psdk_manifold \
  --check camera_media_list_read \
  --raw-evidence 11_psdk_camera_media/<UTC_ts>__media_list_raw.log \
  --attest-required-assertions
```

runner가 schema v1.0 PASS envelope를 직접 생성하는 경우에만 `record-check --evidence <envelope.json>`을
사용한다. 빈 JSON, 잘못된 check/stage/session/SN, 필수 assertion 누락, raw digest/size 불일치,
symlink·외부 경로·권한이 열린 파일은 모두 거부한다.

실패는 해당 check와 evidence를 함께 `BLOCKED`로 기록한다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py record-blocker \
  hil_raw_logs/<actual-sn-session>/integration_manifest.json \
  --track psdk_manifold \
  --check camera_media_list_read \
  --code CAMERA_MEDIA_LIST_FAILED \
  --evidence 11_psdk_camera_media/<UTC_ts>__media_list_failure.json
```

다섯 check가 서로 다른 실제 evidence로 통과하면 track은 `READY_FOR_DECISION`이 된다. 그 상태에서만
다음 명령이 decision record를 만들고 SHA-256/size를 다시 계산해 `VERIFIED`와 provider selection을
한 번에 기록한다. 이후 evidence가 바뀌거나 decision record가 사라지면 `verify`가 실패한다.

```bash
uv run python tools/hil/prepare_mvp_integration_session.py select-provider \
  hil_raw_logs/<actual-sn-session>/integration_manifest.json \
  --track psdk_manifold \
  --reason "PSDK M1 real-device acceptance passed"
```

허용 evidence stage는 다음과 같다.

| Track/check | Stage |
|---|---|
| Cloud workspace/wayline/operator/media start | `10_cloud_pilot/` |
| Cloud WorkOrder→Mission→Media lineage | `12_gateway_lineage/` |
| PSDK Manifold/aircraft link | `09_mvp_provider_preflight/` |
| PSDK media list/JPEG download/rights release | `11_psdk_camera_media/` |
| PSDK object upload/lineage | `12_gateway_lineage/` |

PSDK 필수 assertion:

| Check | 모두 참이어야 하는 판정 |
|---|---|
| Manifold/aircraft link | Manifold identity, DJI app framework, aircraft link connected, aircraft SN match |
| media list | `DownloadFileList` 성공, media 1개 이상, delete/format 미호출 |
| original JPEG | `DownloadFileByIndex` 성공, 원본 JPEG, 양수 byte, SHA-256 확인, delete/format 미호출 |
| upload/lineage | object upload, source digest, WorkOrder→Mission→Media lineage, egress policy 확인 |
| rights release | downloader rights 획득·해제, Pilot 2 album 접근 복구 |

## 4. Track C — DJI Cloud / Pilot-to-Cloud (`BLOCKED`)

현재 조합은 `UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX`로 차단한다. 아래 다섯 항목은 공식
지원표가 바뀌거나 DJI가 이 조합을 서면 확인했을 때만 다시 수행한다. 공식 지원 밖 조합에서
Cloud credential을 입력하거나 실제 기체로 가능성을 탐색하지 않는다.

아래 다섯 항목을 **동일한 org/site/work order/mission**에서 순서대로 증명한다.

1. Pilot 2에서 KSI workspace/WebView를 열고 로그인 후 작업을 볼 수 있다.
2. KSI가 준비한 wayline이 USB·SD·download/copy 없이 Pilot 2의 library에 나타난다.
3. 운영자가 Pilot 2에서 경로·기체·카메라·안전 상태를 검토할 수 있다. 이 단계에서는 실행하지 않는다.
4. 별도로 승인된 FIELD capture가 끝난 뒤 파일 선택 없이 원본 media upload가 시작되는 provider 상태를 확인한다.
5. 업로드된 원본이 `organizationId/siteId/workOrderId/missionId`와 digest로 연결된다.

각 단계는 화면 캡처, provider operation ID, UTC, firmware/Pilot version, manifest/object reference를
`10_cloud_pilot/`과 `12_gateway_lineage/`에 남긴다. URL query, cookie, token은 제거한다.

**PASS**: 다섯 항목 전부 + 구체 evidence ref.

**BLOCKED**: entitlement/지원 조합/wayline/media/lineage 중 하나라도 실패. 실패 원문과 firmware 조합을 보존한다.

## 5. Track P — Manifold 3 + PSDK camera media

Cloud Track과 독립적으로 다음을 증명한다.

1. `HARDWARE_SESSION_PLAYBOOK.md` 1/3.0/8단계로 Manifold identity, aircraft link, DJI app framework,
   USB bulk mapping을 먼저 확인한다.
2. PSDK가 `DjiCameraManager_DownloadFileList`로 media list를 읽는다.
3. 운영자가 장비 상태 변경을 승인하면, 지정한 지상 촬영 원본 JPEG 한 장에 대해 downloader rights를 얻고,
   `DjiCameraManager_DownloadFileByIndex`로 한 번만 다운로드한다.
4. 크기·촬영시각·로컬 SHA-256을 기록하고 KSI staging object storage에 업로드한 뒤,
   `SourceMediaBundle` 및 work order/mission lineage를 확인한다.
5. downloader rights를 release하고 Pilot 2 album 접근이 정상인지 확인한다.

`DjiCameraManager_DeleteFileByIndex`와 `DjiCameraManager_FormatStorage`는 금지한다. 다운로드 rights를
release하지 못하면 결과가 있어도 PASS가 아니다. raw JPEG는 `11_psdk_camera_media/`에 두되 커밋하지 않는다.

**PASS**: 5항목 전부 + JPEG digest + upload/object reference + lineage + rights release evidence.

**BLOCKED**: Manifold/aircraft link, DPK, camera list/download, upload, lineage, rights release 중 하나라도 실패.

## 6. Provider 채택 규칙

> 아래 규칙은 v1.2 역사적 provider 비교에만 적용한다. ADR-KSI-023 이후 runtime은
> `prepare_connected_edge_session.py` v1.3의 기능별 receipt와 flag만 따른다.

1. Cloud가 공식 지원 조합에서 PASS면 `DJI_CLOUD`를 기본으로 채택하고 PSDK는 capture quality/offline 보조로 제한한다.
2. 현재처럼 Cloud가 BLOCKED이고 PSDK가 PASS면 `PSDK_MANIFOLD`를 media 기본 경로로 채택한다.
3. 둘 다 BLOCKED면 provider 구현을 진행하지 않고 MSDK spike를 별도 결정한다.
4. `ZeroTouchGateway` feature flag는 선택된 track이 `VERIFIED`이고 durable evidence ref가 있을 때만 켠다.
5. 기존 Pilot 2 수동 KMZ와 folder ingest는 모든 경우에 rollback/복구 경로로 유지한다.

## 7. 2026-08-20 host preflight

- actual session: `hil_raw_logs/SESS-20260820T134204Z-PENDING-SN/` (schema v1.2로 upgrade)
- most recent capture: `2026-08-20T14:34:24Z` (`13:42:13Z`, `14:02:47Z` 실패 evidence도 보존)
- `enP7s7`: link up, `172.30.1.43/24`
- `172.30.1.33`: ARP `FAILED`, ICMP 3/3 실패; remote identity/SSH/aircraft link는 호출하지 못함
- host USB: DJI/RC/Manifold 장치 없음. PSDK는 Manifold 내부 USB bulk를 쓰므로 이 사실은
  PSDK blocker가 아니며 MSDK/direct-host fallback 참고 정보로만 남긴다.
- 수행하지 않은 것: credential 입력, DPK install/start, camera/media call, device write, flight/gimbal command

현재 verdict는 Cloud `BLOCKED / UNSUPPORTED_COMBINATION_IN_OFFICIAL_MATRIX`, PSDK
`BLOCKED / MANIFOLD_UNREACHABLE`이며 aircraft link는 `UNKNOWN`이다.
