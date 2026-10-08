# `edge/psdk-app` — Manifold 3 Shadow DPK

Manifold 3에서 공식 DJI PSDK를 통해 RGB Liveview와 FC telemetry를 받는 실제
`.dpk` 실행 진입점이다. 이 앱은 **Shadow-only**다. KSI source에는 DJI Flight Control
header·직접 호출이 없고, 어떤 `ActionIntent`도 비행 명령으로 바꾸지 않는다.
다만 링크하는 DJI static archive에는 미사용 FlightController 정의가 남을 수 있으므로,
최종 ELF의 strict zero-symbol gate는 별도 미해결 항목으로 보고한다.

빌드 뒤에는 다음 gate를 반드시 실행한다. 기본 모드는 KSI source·미해결 symbol·실제
ELF direct call을 실패로 처리하고, vendor archive의 정의 잔존은 경고로 분리한다. strict
zero-symbol 결과가 필요한 수용 단계에서는 두 번째 명령도 실행해야 하며, 현재 PSDK 3.16.0
archive에서는 의도적으로 실패한다. 정의만 strip/rename해 통과시키는 것은 허용하지 않는다.

```bash
uv run python tools/edge/check_shadow_flight_boundary.py \
  build-manifold3-app/ksi_psdk_app \
  edge/psdk-app/src edge/manifold-runtime/src edge/manifold-runtime/include

uv run python tools/edge/check_shadow_flight_boundary.py \
  --require-zero-defined-symbols \
  build-manifold3-app/ksi_psdk_app \
  edge/psdk-app/src edge/manifold-runtime/src edge/manifold-runtime/include
```

## 현재의 안전 상태

앱은 다음을 수행한다.

- `DjiLiveview_StartImageStream(..., PIXFMT_RGB_PACKED, ...)`로 RGB 프레임을 받는다.
- 프레임 콜백은 monotonic 수신 시각을 찍고 선할당 `BoundedFrameQueue`에 byte copy만 한다.
- FC `POSITION_VO`·`VELOCITY`·`POSITION_FUSED`·NO.1 `GIMBAL_ANGLES`(각 50 Hz),
  `GPS_DETAILS`(5 Hz), `HARD_SYNC`(400 Hz)를 구독한다. 각 callback은 정렬 안전한 local
  copy와 짧은 seqlock cache만 갱신한다. HardSync는 coherent position/velocity snapshot,
  FRD→NED Hamilton quaternion, fresh WGS84/accuracy/gimbal inputs를 `TelemetryTimeline`에
  try-lock 방식으로 기록하며 inference·파일 I/O·네트워크·대기는 하지 않는다.
- velocity도 callback 수신시각을 보존한다. 나중에 sensor-timed RGB가 공급되더라도
  오래된 FC velocity를 새 frame의 predicted RiskField에 재사용하지 않는다.
- RGB 콜백에 sensor timestamp가 없다는 사실을 보존한다. 수신시각 근접성은
  `SENSOR_ALIGNED`로 승격되지 않는다.
- PSDK의 별도 `DjiPerceptionImageCallback`에는 visual-perception **grayscale** frame의
  `timeStamp`가 있지만, 이는 `DjiLiveview` payload RGB와 frame identity를 공유한다는
  계약이 아니다. 이 앱은 그 timestamp를 RGB queue에 복사하거나 수신시각으로 matching하지
  않는다. 해당 stream을 장래 timing input으로 채택하려면 raw clock domain·camera
  calibration·model input의 M4D HIL 실증이 먼저 필요하다.

아직 다음 입력이 등록되지 않은 경우 worker는 frame을 capture-only로 drain하고
`RiskField`·`EventBundle`·`SHADOW_ACCEPTED`를 전혀 만들지 않는다.

1. digest가 등록된 TensorRT D-FINE engine과 signed `tensorRtDifferential` evidence
   (`PASS`, exact ONNX/preprocessor/corpus digest, sampleCount ≥ 10)
2. site frame·camera calibration·관측 장비 크기·공분산을 제공하는 projector

따라서 이 디렉터리의 소프트웨어 빌드 성공은 **PSDK ingress 배선**만 뜻한다. Hardware
verified나 production supported를 뜻하지 않는다.

### HIL-1S PSDK/MOP Edge uplink companion

`KSI_PSDK_APP_ENABLE_EDGE_UPLINK_COMPANION=ON`은 한 개의 비작동
`PSDK_MANIFOLD / EDGE_UPLINK` 경로만 추가한다. 실제 vendored PSDK 3.16의
`DjiMopChannel_Init/Create/Bind/Accept/SendData/RecvData/Close/Destroy`를 사용하며,
Waypoint·FlightController·motor·gimbal·camera·media API를 호출하지 않는다. 고정된
로컬 endpoint는 `/run/ksi/psdk.sock`이고 배포자가 현재 DPK 사용자 소유의 private
`/run/ksi` directory를 먼저 만들어야 한다.

`ROUTE_STATUS_V1`의 AVAILABLE 조건은 정확히 다음 conjunction이다.

```text
DjiCore_ApplicationStart succeeded
AND exact reliable MOP channel is currently accepted
AND exact EDGE_BUNDLE_UPLOAD handler/listener is registered
```

process liveness, CMake configuration, 과거 연결은 AVAILABLE 근거가 아니다. MOP receive
monitor가 peer close/error를 관찰하면 즉시 disconnected로 바꾸고 같은 bound channel에서
다음 `Accept`를 기다린다. Unix request는 64 KiB의 단일 JSON+EOF frame이며 exact
operation/field/scope/port/hash만 허용한다. `EDGE_BUNDLE_UPLOAD`은 검증된 EdgeBundle
metadata frame을 MOP에 보내는 것 외에 어떤 device action도 수행하지 않는다.

각 companion instance는 생성 시 Linux kernel에서 128-bit random incarnation ID를 얻어
`psdk-route-<32hex>-<generation>-<sequence>` signal ID를 만든다. 안전한 entropy를
얻지 못하면 listener 생성 전에 fail-closed하며 시간/0 기본값으로 대체하지 않는다.
이 값은 Gateway observation 멱등성·추적 전용이고 어떤 capability/Mission/deployment
권위에도 참여하지 않는다.

```bash
cmake -S edge/psdk-app -B build-manifold3-app \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
  -DKSI_PSDK_APP_ENABLE_EDGE_UPLINK_COMPANION=ON \
  -DKSI_PSDK_APP_EDGE_UPLINK_ORGANIZATION_ID=<trusted_org> \
  -DKSI_PSDK_APP_EDGE_UPLINK_SITE_ID=<trusted_site> \
  -DKSI_PSDK_APP_EDGE_DEVICE_ID=<exact_edge_device> \
  -DKSI_PSDK_APP_EDGE_UPLINK_SUBJECT_PORT_ID=<approved_subject_port> \
  -DKSI_PSDK_APP_EDGE_UPLINK_MOP_CHANNEL_ID=<approved_1_to_65535>
cmake --build build-manifold3-app --target ksi_psdk_app -j
```

Host 진단 빌드는 `-DKSI_PSDK_APP_BUILD_TESTS=ON
-DKSI_PSDK_APP_ENABLE_SANITIZERS=ON`으로 ASan+UBSan을 재현할 수 있다. TSan은
`KSI_PSDK_APP_ENABLE_THREAD_SANITIZER=ON`의 상호배타적 별도 진단이다. 둘 다 기본
OFF이며 sanitized host PASS는 unsanitized aarch64 device artifact의 실기 검증을
대체하지 않는다. 정확한 명령은 `docs/hil/HIL_1S_PSDK_RUNTIME_COMPANION.md`에 있다.

이 빌드와 host Unix interoperability test는 소프트웨어 준비 근거일 뿐이다. 실제 M4D,
Manifold 3, peer MOP client, firmware identity, disconnect/reconnect raw log가 확보되기 전에는
`VERIFIED_HIL`로 표시할 수 없다. 더구나 핀된 PSDK 3.16은 Manifold의 `Accept`
server를 PSDK `Connect` client가 주소화할 수 있음을 문서화하지 않는다. 현재 route는
`BLOCKED_HARDWARE_TOPOLOGY`이며 정확한 근거와 entry condition은
`docs/hil/HIL_1R_PHYSICAL_READINESS.md`에 있다.

### HIL-1P PSDK/MOP peer receiver

`KSI_PSDK_APP_ENABLE_MOP_PEER_RECEIVER=ON`은 HIL-1S `Accept` server와 상호배타적인
별도 client mode다. 조직·Site·Edge·subject port·channel과 remote PSDK server address를
모두 CMake로 명시해야 하며, address는 `PAYLOAD_PORT_NO1..NO3` 또는
`EXTENSION_PORT_V2_NO1..NO8`만 허용한다. RC/Cloud target과 local self-connect는 허용하지
않는다. `DjiCore_ApplicationStart` 뒤 worker가 `Connect`/`RecvData`를 소유하고 close/error
뒤 재연결하며, shutdown은 `DjiCore_DeInit` 전에 `Close`로 receive를 해제하고 join한다.

수신 frame은 existing `EDGE_BUNDLE_UPLOAD` metadata schema만 strict하게 검증한다. 이
protocol에는 acknowledgement가 정의되어 있지 않으므로 `DjiMopChannel_SendData`를 호출하지
않으며 payload는 실행·device action으로 dispatch되지 않는다.

```bash
cmake -S edge/psdk-app -B build-manifold3-peer \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_ENABLE_MOP_PEER_RECEIVER=ON \
  -DKSI_PSDK_APP_MOP_PEER_ORGANIZATION_ID=<trusted_org> \
  -DKSI_PSDK_APP_MOP_PEER_SITE_ID=<trusted_site> \
  -DKSI_PSDK_APP_MOP_PEER_EDGE_DEVICE_ID=<exact_edge_device> \
  -DKSI_PSDK_APP_MOP_PEER_SUBJECT_PORT_ID=<approved_subject_port> \
  -DKSI_PSDK_APP_MOP_PEER_CHANNEL_ID=<approved_1_to_65535> \
  -DKSI_PSDK_APP_MOP_PEER_ADDRESS=<approved_payload_or_extension_port>
cmake --build build-manifold3-peer --target ksi_psdk_app -j
```

이 build는 client 쪽 DPK만 만든다. server companion build와 서로 다른 물리 PSDK
endpoint에 별도로 배치해야 하며, 같은 binary에서 두 mode를 함께 켜면 CMake가 거부한다.
이는 compile/lifecycle hypothesis일 뿐이다. 벤더가 문서화한 Manifold 대상 address가
없으므로 두 PSDK endpoint를 준비했다는 사실만으로 물리 연결 가능성을 주장하지 않는다.

### Phase 3B WaypointV3 upload-only candidate

`src/flight_execution/waypoint_v3_upload_only.cpp`는 기본 DPK에 링크되지 않는 S1
candidate다. 승인된 HIL build에서만 다음 옵션과 committed exact allowlist를 사용한다.
이 표면은 `Init → UploadKmzFile → DeInit`만 호출하며 `Action/START`나 callback을 갖지 않는다.

```bash
cmake -S edge/psdk-app -B <manifold3-build-dir> \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_ENABLE_WAYLINE_UPLOAD_ONLY=ON \
  -DKSI_PSDK_APP_WAYLINE_UPLOAD_ALLOWLIST="$PWD/edge/flight-execution-upload-only-allowlist.v1.json"
```

빌드 후 source/ELF gate가 자동 실행된다. 실제 호출은 HIL v1.4 approval의 session,
device IDs, DPK digest, `WAYLINE_UPLOAD_NO_START`, expiry가 모두 맞을 때만 수행한다.
업로드 성공은 비행 가능, FIELD-0a, camera, battery/RTH capability 증거가 아니다.

현재 핀된 PSDK 3.16 arm64 archive는 `UploadKmzFile`과 public
`DjiWaypointV3_Action`을 동일한 `dji_waypoint_v3.c.o`에 포함한다. 따라서 위 option의
configure-time archive preflight가 member 단위 동거를 먼저 탐지해 의도적으로 실패한다.
향후 안전한 archive가 제공되더라도 post-build strict gate를 다시 통과해야 한다.
vendor 정의를 allowlist에 추가하거나 archive를 strip/rewrite해 숨기지 않는다. 별도의 DJI 제공
upload-only artifact나 검토된 격리 방법이 확보되기 전 판정은
`CODE_READY / SDK_BUILD_BLOCKED / NOT_VERIFIED`다.

현재 blocker는 다음 read-only 명령으로 재현한다. JSON에는 핀 archive digest,
선택되는 member와 초과 Waypoint 심볼이 기록되며 비행·camera write 값은 항상 false다.

```bash
uv run --locked python tools/edge/check_psdk_waypoint_archive.py --format json
```

### Native activation handoff

`ksi_mission_contracts.edge_activation`가 Mission Dispatch와 내부 Mission Contract를
모두 검증한 뒤 activation state directory에 다음 record를 원자적으로 쓴다.

- `active-dispatch.json`: 운영자·복구용 JSON record
- `active-edge-runtime-profile.native.v1`: signed model/calibration/profile handoff
- `active-dispatch.native.v1`: DPK가 시작 시와 worker 주기마다 읽는 activation marker

profile은 marker보다 먼저 publish된다. 따라서 전원 손실 시 profile만 남아도 activation은
생기지 않고 capture-only다. marker에는 dispatch/device/runtime binding, contract·policy
digest, TTL, 그리고
검증된 `RiskPolicyPack`의 장비별 수치가 들어 있다. C++는 파일 소유자·`0700` directory
·`0600` regular file·no-symlink·exact field set을 모두 요구한다. handoff가 없어지거나
변조/만료/장비·runtime mismatch가 나면 기존 activation도 즉시 deactive되어
capture-only로 돌아간다. C++가 Ed25519을 다시 구현하지 않는 이유는 상류 검증기를
중복하지 않기 위해서다.

### Core pull → verified activation → receipt companion

`ksi-edge-dispatch-sync`는 한 번의 activation-time control-plane 시도를 수행한다.
`GET /v1/edge-sync/missions/next`의 exact JSON bytes를 위의 기존 verifier에 넘긴 뒤,
성공했을 때만 같은 dispatch의 `ActivationReceiptV1`을 Core에 POST한다. HTTPS origin,
제공된 CA bundle, Core SPKI pin, `0600` owner-only bearer file, response byte bound를 모두
요구하며 redirect를 따르지 않는다. TLS SPKI는 bearer HTTP header보다 먼저 검증한다.
`204`는 mission 없음이고, receipt의 네트워크/5xx 실패는 정상 activation을 되돌리지
않는다. 다음 supervised one-shot 실행이 Core에 남은 같은 dispatch와 receipt를 멱등
재시도한다.

```bash
# Python 3.12 activation companion; token value를 command line/로그에 넣지 않는다.
ksi-edge-dispatch-sync \
  --core-base-url https://<core_origin> \
  --tls-ca-bundle <reviewed_ca_bundle> \
  --core-spki-pin sha256//<core_spki_pin> \
  --bearer-token-file <private_0600_edge_token> \
  --keys-dir <public_verification_key_directory> \
  --state-dir <same_private_0700_activation_state_dir> \
  --edge-device-id <device_id> \
  --runtime-version <runtime_version>
```

이 companion은 PSDK callback, native frame/safety worker, 또는 `.dpk` payload 안에서
실행하지 않는다. 현재 `.dpk`는 native executable만 package하고, 실측 Manifold 기본
Python은 3.8.10인 반면 companion은 Python 3.12를 요구한다. 그러므로 native activation을
실제로 켜기 전에는, 별도 검토된 non-root Python 3.12 control-plane runtime이 **DPK가 읽는
바로 그 private state directory**에 원자적으로 쓸 수 있는지(또는 동등한 승인된 atomic
handoff가 있는지)를 HIL에서 증명해야 한다. 이 runtime/volume/permission/TLS 배치는 아직
software test만으로 검증됐으며, 이를 우회하려고 Python을 callback에 넣거나 stock 3.8에
백포트하지 않는다.

DPK에 이 소비를 켜려면 세 non-secret deployment input을 명시해야 한다. 누락한 기본
빌드는 안전하게 capture-only다.

```bash
# Add the usual KSI_TARGET_MANIFOLD3 / PSDK header inputs from the build section below.
cmake -S edge/psdk-app -B build-manifold3-app \
  -DKSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION=ON \
  -DKSI_PSDK_APP_EDGE_DEVICE_ID=edge-001 \
  -DKSI_PSDK_APP_ACTIVATION_STATE_DIR=/private/ksi-edge-state \
  -DKSI_PSDK_APP_RUNTIME_VERSION=manifold3-edge-shadow-0.2.0
```

`/private/ksi-edge-state`는 DPK 실행 사용자만 접근 가능한 실제 온보드 directory여야
한다. DPK manager의 실행 사용자·지속 volume 위치는 HIL에서 확인할 항목이며, 이 문서의
예시 경로를 실기 사실로 해석하면 안 된다.

### Signed perception profile

`KSI_PSDK_APP_ENABLE_PERCEPTION=ON`은 capture-only보다 엄격한 deployment tier다.
반드시 native activation, Manifold target, TensorRT/CUDA, 서로 분리된 private directory,
그리고 Core가 서명한 `EdgeRuntimeProfile`가 필요하다. profile 외부의 ONNX path,
equipment size, camera identity transform, 또는 sensor-timing 예외는 받지 않는다.

```bash
cmake -S edge/psdk-app -B build-manifold3-perception \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_ENABLE_NATIVE_ACTIVATION=ON \
  -DKSI_PSDK_APP_EDGE_DEVICE_ID=<device_id> \
  -DKSI_PSDK_APP_ACTIVATION_STATE_DIR=<private_0700_activation_dir> \
  -DKSI_PSDK_APP_ENABLE_PERCEPTION=ON \
  -DKSI_PSDK_APP_PERCEPTION_STATE_DIR=<private_0700_journal_dir> \
  -DKSI_PSDK_APP_MODEL_ARTIFACT_DIR=<private_0700_onnx_dir>
```

`PERCEPTION_STATE_DIR`는 activation directory와 달라야 한다. runtime은 signed ONNX
artifact ID만 이 private model directory 아래에서 읽고, digest를 검증한 engine만 별도
private engine vault에 저장한다. `tensorRtDifferential`의 profile ID, ONNX digest,
`rtdetr-rgb-bilinear-1over255-v1` preprocessing contract/config digest, corpus digest/count,
`PASS` status와 tolerances는 Python→native handoff parser 및 이 activation boundary가
모두 fail-closed로 확인한다. Core가 서명한 exact evidence digest가 없으면 engine build와
TensorRT가 설치되어 있어도 `TENSORRT_DIFFERENTIAL_REQUIRED`로 남는다. evidence 생성 절차는
[`edge/manifold-runtime` README](../manifold-runtime/README.md#tensorrt--onnx-differential-evidence)에
있다. 현재 RGB callback은 sensor timestamp를 주지 않으므로
이 옵션을 실제로 켜도 `SENSOR_ALIGNMENT_REQUIRED` drop만 가능하다. sensor timestamp
source와 M4D calibration convention의 실기 증거가 생기기 전에는 event producer 또는
hardware completion으로 해석하면 안 된다. Perception grayscale의 `timeStamp`만
발견한 상태는 이 조건을 만족하지 않는다.

signed perception이 실제로 `CANDIDATE`를 durable하게 만든 경우에만, 같은 worker는
candidate ID와 active Mission Contract digest에서 deterministic한 좌표 없는 `HOLD`
`ActionIntent`를 만든다. 이어서 현재 dispatch의 contract/policy digest·TTL·heartbeat를
`ShadowFlightSupervisor`로 다시 검사하고, `artifacts/shadow-action-<sha256(commandId)>.json`
immutable record가 fsync된 뒤에만 `SHADOW_ACCEPTED`를 통계로 기록한다. 이 record는
Core에 EventBundle으로 승격되지 않고 DJI API에도 전달되지 않는다. journal 부재·I/O
실패·policy mismatch·clock rollback·같은 command ID의 뒤늦은 divergent replay는 모두
shadow rejection이며 비행 동작이 아니다.

같은 durable candidate 직후 worker는 private perception vault에
`artifacts/event-timing-<sha256(candidateIdempotencyKey)>.json`도 fsync한다. 이는 RGB
callback의 `CLOCK_MONOTONIC` 수신시각부터 SQLite candidate/evidence transaction 완료까지
정수 ns로 측정한 HIL/replay artifact다. stdout 통계의
`candidateTimingArtifacts durable/failures/duplicateRetries/last`가 이를 드러낸다.
`DUPLICATE` SQLite retry는 새 candidate latency가 아니므로 표본으로 쓰지 않고, timestamp
rollback/부재는 `NOT_MEASURED`로 남는다. 이 record는 EventBundle evidence count를 사후
변경하지 않으며, 사용자 로컬 경보나 Core 사용자 알림을 측정한 것이 아니다.

## Edge evidence sync capability

별도 `riskfield-daemon`을 설치하는 구조가 아니다. 이 DPK의 `ksi_psdk_app`이 유일한
production service host이며, RGB/telemetry callback을 받는 프로세스 안에서
`EdgePipeline` worker와 `StoreForwardSyncDriver`/`CoreRestSyncTransport` worker를 함께
구동한다. perception과 sync는 같은 SQLite WAL과 artifact vault를 공유한다. 앱 종료 시
두 worker를 모두 정지·join한 뒤 상태를 읽으므로, 백그라운드 write가 남은 채 DPK가
종료되지 않는다. 이 조립은
`tests/contract/test_edge_riskfield_production_wiring.py`가 회귀 방지한다.

Core의 `POST /v1/edge-sync/events/{eventKey}/evidence` 응답은 `uploadUrl`과
`requiredUploadHeaders`를 하나의 짧은 수명 capability로 준다. native
`CoreRestSyncTransport`는 candidate `JournalEntry` ACK 뒤에만 durable payload의
`eventId`와 authenticated `edgeDeviceId`로 `eventKey`를 만들고 등록한다. `Content-Type`과
`x-amz-checksum-sha256`은 Core 응답 값을 **그대로** 객체 스토리지 PUT에 전달한다. Core
bearer는 절대로 presigned URL에 붙지 않는다. URL/headers는 SQLite에 저장하지 않으며,
프로세스 재시작 뒤에는 evidence registration을 멱등 재시도해 새 capability를 받는다.

DPK에 이 경계를 켜려면 `KSI_PSDK_APP_ENABLE_CORE_SYNC=ON`과 다음 deployment input이
모두 필요하다.

- `KSI_PSDK_APP_EDGE_DEVICE_ID`, `KSI_PSDK_APP_SYNC_STATE_DIR` — sync directory는 DPK
  실행 사용자가 **사전에** 만든 `0700` real directory여야 하며 activation handoff
  directory와 달라야 한다. perception을 함께 켜면 sync와 perception state directory는
  같아야 하며 하나의 SQLite WAL/artifact vault를 공유한다.
- `KSI_PSDK_APP_CORE_BASE_URL`, `KSI_PSDK_APP_TLS_CA_BUNDLE`, Core/storage 각각의
  `sha256//...` SPKI pin.
- `KSI_PSDK_APP_CORE_BEARER_TOKEN_FILE` — 실제 token은 package/CMake/로그에 넣지 않는다.
  runtime은 owner-only `0600`, regular file, no-symlink만 읽는다.
- `KSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID`와
  `KSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE` — 운영자가 Core registry와
  함께 provision한 Ed25519 키 식별자와 외부 절대경로다. private key 파일은
  owner-only `0600`, regular file, no-symlink, single-link여야 하며 DPK·CMake 값·로그·
  journal에 키 바이트를 넣지 않는다. 등록 요청은 정확히 7개 canonical 필드
  (`deviceId`, `siteId`, `missionId`, `eventKey`, `artifactId`, `contentType`,
  `contentDigest`)를 서명한 unpadded base64url만 보낸다.
- `KSI_ENABLE_CURL_EDGE_TRANSPORT=ON`에 필요한 reviewed static libcurl와 모든 static
  transitive archive (`KSI_CURL_STATIC_EXTRA_LIBRARIES`). shared libcurl과 동적 보조
  라이브러리는 target ABI gate가 거부한다.
- `KSI_ENABLE_OPENSSL_EVIDENCE_ATTESTATION=ON`은 OpenSSL EVP Ed25519를 사용하며
  `libcrypto.a`만 허용한다. `libcrypto.so*`가 최종 ELF `NEEDED`에 남으면 ABI gate가
  실패한다. Ubuntu 20.04의 OpenSSL 1.1.1은 OpenSSL/Original SSLeay notice 의무가
  있으므로 DPK 배포 전 third-party notice와 SBOM 생성은 별도 release gate다.

예시는 의도적으로 secret/pin 값을 비워 둔다.

```bash
cmake -S edge/psdk-app -B build-manifold3-app \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_ENABLE_CORE_SYNC=ON \
  -DKSI_PSDK_APP_EDGE_DEVICE_ID=<device_id> \
  -DKSI_PSDK_APP_SYNC_STATE_DIR=<private_0700_state_dir> \
  -DKSI_PSDK_APP_CORE_BASE_URL=https://<core_origin> \
  -DKSI_PSDK_APP_CORE_BEARER_TOKEN_FILE=<private_0600_token_file> \
  -DKSI_PSDK_APP_TLS_CA_BUNDLE=<absolute_ca_bundle> \
  -DKSI_PSDK_APP_CORE_TLS_PIN=sha256//<core_spki> \
  -DKSI_PSDK_APP_STORAGE_TLS_PIN=sha256//<storage_spki> \
  -DKSI_PSDK_APP_EVIDENCE_ATTESTATION_KEY_ID=<device_key_id> \
  -DKSI_PSDK_APP_EVIDENCE_ATTESTATION_PRIVATE_KEY_FILE=<external_private_0600_ed25519_pem> \
  -DCURL_LIBRARY=<reviewed_static_libcurl.a> \
  -DKSI_CURL_STATIC_EXTRA_LIBRARIES='<absolute_static_dep_1.a;...>'
```

이 옵션은 pending journal을 별도 worker에서 sync할 뿐, TensorRT engine과 calibrated
projector가 없는 현재 DPK를 event producer로 승격하지 않는다. 정적 bundle·Core/storage
integration·실기 HIL을 통과하기 전까지 실제 장비 업로드 capability는 `NOT_VERIFIED`다.
위 production-host 조립 테스트의 PASS도 DPK 설치, 장비 key provisioning, bearer/TLS
연결 또는 object-storage PUT 성공을 대신하지 않는다.

## 매핑 원본 자동 반출은 현재 production에서 차단

`KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD=ON`은 configure 단계에서 의도적으로 실패한다. 기존
`edge/manifold-runtime`에는 권한 marker, SQLite 원장, bounded spool, digest 검증과 Core
upload conveyor가 있고 호스트 테스트용 `FakeMediaSourcePort`도 남아 있다. 그러나 packaged
`ksi_psdk_app`에는 아직 실제 `DjiCameraManager_*` adapter와 검증된 DJI 완료 신호/baseline
provider가 없다. PSDK-independent 계층에는 이제 완료 또는 운영자 one-shot 증거, 임무 전
SD 목록 baseline, exact `fileIndex + fileName + fileSize`, 결정적 selection digest가 구현돼 있다.
다만 이를 실기 DJI source에 배선하지 않은 상태이므로 production capability는 그대로 차단한다.

활성 dispatch의 `missionId`만 보고 `DownloadFileList` 결과를 전량 결속하면 이전 임무나 다른
현장의 사진까지 현재 `SourceMediaBundle`로 잘못 봉인할 수 있다. 따라서 Fake source를 production
main loop에 배선하지 않으며, 다음 항목을 모두 통과하기 전에는 option을 열지 않는다.

- 실제 DJI 임무 완료 또는 운영자 승인 one-shot trigger provider 배선
- 임무 시작 전 Camera Manager baseline snapshot의 durable 획득
- 실제 adapter의 list/download 및 크기 상한 배선
- M4D 지상 JPEG 한 장의 list/download/SHA-256, downloader rights release, Pilot 2 album 복구 HIL
- M4D에서 두 임무의 파일이 서로 섞이지 않는 cross-mission HIL negative test

그 전의 정상 제품 경로는 ADR-KSI-013과 civil v1 결정대로
`기체 SD/저장매체 → 현장 PC → KSI 웹 업로드`다. 이 경로는 임시 실패가 아니라 검증 전 공식
fallback이며, 자동 반출 관련 소프트웨어 테스트는 DJI capability를 `VERIFIED`로 승격하지 않는다.

## 공용 PSDK platform glue

`edge/psdk-platform/psdk_platform.cmake`가 `edge/psdk-tap/src/platform`의 OSAL, socket,
USB bulk, console glue를 두 앱이 같은 소스에서 링크하도록 한다. USB bulk `2/4/3`
매핑은 이 변경에서 새로 추측하거나 변경하지 않았다. 공식 DPK 안에서 관측하기 전까지
그 값은 HIL 차단 요인이다.

## 빌드 입력

- PSDK 3.16.0 pin: `tools/edge/fetch_psdk.py`로 받는 `edge/third_party/psdk/`
- DJI 앱 credential header: `config/dji_sdk_app_info.h.example`을 참고하되 실제 파일은
  untracked 상태로 두거나 repository 밖의 안전한 경로를
  `-DKSI_PSDK_APP_INFO_HEADER=...`로 넘긴다.
- DPK의 `user_app_id`: DJI에서 발급된 값을 configure 시에만
  `-DKSI_PSDK_APP_DPK_USER_APP_ID=...`로 넘긴다. 패키지와 실제 자격증명은 커밋하지 않는다.

Manifold-compatible 컨테이너 또는 온보드에서 다음과 같이 빌드한다.

```bash
cmake -S edge/psdk-app -B build-manifold3-app \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_INFO_HEADER=/secure/dji_sdk_app_info.h
cmake --build build-manifold3-app -j
```

공식 DPK만 생성하려면 DJI app ID를 명시적으로 추가한다.

```bash
cmake -S edge/psdk-app -B build-manifold3-app \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchain-manifold3.cmake \
  -DKSI_TARGET_MANIFOLD3=ON \
  -DKSI_PSDK_APP_INFO_HEADER=/secure/dji_sdk_app_info.h \
  -DKSI_PSDK_APP_BUILD_DPK=ON \
  -DKSI_PSDK_APP_DPK_USER_APP_ID=<DJI_issued_id>
cmake --build build-manifold3-app --target ksi_psdk_app_dpk
```

생성된 `.dpk`는 `build-manifold3-app/dpk/out/`에만 두고 `scripts/manifold/manifoldctl`
경유로 `dji_app_ctl install/start`한다. OS 변경·root 설치·PSDK 소스 수정은 배포 경로가
아니다.

## HIL gate

순서는 `8(DPK install/start) → 3(telemetry) → 4(RGB frame) → 7(timing)`이다. 성공 증거는
레포 밖 raw HIL log와 durable URI가 있어야 한다. 다음을 실제 장비에서 충족하기 전에는
hardware 완료라고 표기하지 않는다.

- DPK 설치·재시작 뒤 정상 기동
- telemetry 연속 30초
- RGB frame 연속 10초와 해상도/fps 기록
- frame–telemetry 표본 100개 이상, 실제 sensor timestamp 기준 p95 ≤ 50 ms

이 세션에서는 실제 비행·Yaw·FlyTo·Hold·Rejoin을 수행하지 않는다.
