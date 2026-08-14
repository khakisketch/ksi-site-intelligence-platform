# `edge/manifold-runtime`

Manifold 3 Edge shadow slice의 순수 C++17 runtime이다. PSDK callback은 이 라이브러리의
bounded queue/timeline에 바이트와 timestamp만 기록하고, inference·tracking·risk·증거
계획·SQLite WAL store-and-forward는 worker 경계에서 수행한다.

## 안전 경계

- `MissionDispatchEnvelope`의 서명·키 상태·TTL 검증은 기존 Python Mission Contract
  consumer가 담당한다. 성공한 뒤에만 private native handoff를 쓰며, C++는
  device/runtime/digest/TTL/policy 형상을 다시 확인한다. 별도
  `active-edge-runtime-profile.native.v1`는 active marker보다 먼저 publish되며,
  ONNX digest·tensor contract·등록 장비 형상·WGS84→ENU→site rigid transform·camera
  calibration을 marker의 dispatch/mission/policy binding에 묶는다. 어느 handoff든
  부재·변조·만료·불일치면 capture-only다.
- `TensorRtDfineInference`는 `KSI_ENABLE_TENSORRT=ON`에서만 빌드된다. 등록 ONNX
  digest와 engine digest가 일치하고 고정 tensor contract가 맞아야 load하며, CPU fallback은
  없다. 그보다 앞서 signed `tensorRtDifferential` attestation이 정확한 ONNX digest,
  `rtdetr-rgb-bilinear-1over255-v1` 전처리 contract/config digest, 10개 이상 raw-RGB
  corpus, 허용오차, `PASS` evidence digest를 모두 묶어야 한다. native handoff parser와
  PSDK 활성화 경계가 이 record를 각각 다시 검사하므로 tensor shape만 맞춘 in-memory
  profile로는 perception을 시작할 수 없다. ONNX/engine 파일도 current user 소유,
  no-symlink/no-hardlink, group/other unreadable 상태가 아니면 읽지 않는다.
- `ProfiledGroundPlaneProjector`는 sensor-aligned RGB timestamp, fresh WGS84 position,
  accuracy, gimbal, velocity를 모두 요구한다. receiver time만 있거나 stale velocity,
  비정규 rigid transform, 미등록 class면 `RiskField` 대신 typed drop을 낸다.
- `ConservativeRiskEngine`은 등록되지 않은 장비, 누락 형상·공분산·calibration을 typed
  failure로 처리한다. 측정 형상은 signed policy footprint보다 작아질 수 없고, occlusion은
  field를 줄이지 않고 margin만 키운다.
- `ShadowFlightSupervisor`는 contract/policy digest, TTL, wall-clock rollback, heartbeat를
  모두 통과하고 **immutable local journal**이 `RECORDED` 또는 exact `DUPLICATE`를
  반환한 intent만 `SHADOW_ACCEPTED`로 기록한다. journal 부재·충돌·I/O 실패는 별도
  typed 거부이며 DJI flight-control header/call은 이 runtime에 없다.
- `EdgePipeline`은 candidate/evidence SQLite transaction이 `ACCEPTED` 또는 exact
  `DUPLICATE`가 된 뒤에만 최소 causal ID와 RiskPolicyPack digest를 worker에게
  돌려준다. PSDK owner는 이 결과에서 좌표 없는 `HOLD` shadow intent 하나만 만들고,
  `ArtifactVaultShadowActionJournal`이 `shadow-action-<sha256(commandId)>.json`을 fsync한
  뒤에만 승인 수를 올린다. 이 private record는 Core evidence/flight command가 아니며,
  같은 command ID를 나중에 다른 시각으로 재생하면 immutable artifact conflict로
  fail-closed 한다.
- 새 candidate가 SQLite transaction에서 `ACCEPTED` 된 직후에는
  `EventTimingArtifactWriter`가
  `artifacts/event-timing-<sha256(candidateIdempotencyKey)>.json`을 immutable private
  artifact로 fsync한다. 이 record는 callback의 `CLOCK_MONOTONIC` 수신시각부터 SQLite
  candidate/evidence durability까지의 정수 ns만 측정한다. duplicate retry는 새 표본이
  아니므로 명시적으로 skip하며, clock rollback/부재는 `NOT_MEASURED` artifact가 된다.
  이 slice에는 사용자 로컬 경보나 Core의 사용자 알림 단계가 없으므로, 그 시간을
  `EventBundle.timing.localAlertLatencyMs` 또는 `serverNotificationLatencyMs`로 꾸며
  넣지 않는다.
- `StoreForwardSyncDriver`는 각 device sequence를 다음 candidate보다 먼저 candidate ACK
  → evidence registration → checksum-bound PUT → durable completion까지 끝낸 뒤 prune한다.
  등록 뒤 재시작된 artifact는 같은 candidate의 새 artifact보다도 먼저 fresh capability로
  재시도한다. URL과 required upload headers는 SQLite에 저장하지 않는다.

`CoreRestSyncTransport`는 실제 Core wire를 좁게 구현한다. candidate는
`JournalEntry`로 `POST /v1/edge-sync/event-bundles`에 보내고, durable payload에서
`eventId`를 다시 읽어 device-scoped evidence route를 만든다. payload는 Python
offline-sync digest와 같은 key-sort/minimal-separator native JSON이어야 하며, raw
digest·canonical form·event identity가 하나라도 다르면 네트워크 전 거부한다. Core bearer는
Core route에만 붙고, presigned PUT에는 Core가 준 checksum-bound header만 전달한다.

실제 TLS executor는 `KSI_ENABLE_CURL_EDGE_TRANSPORT=ON`일 때의
`CurlHttpsRequestExecutor`다. HTTPS-only, CA 검증, redirect 금지, Core/storage 별도 SPKI
pin, bounded response를 강제한다. DPK 제약 때문에 shared libcurl은 configure에서 거부하고,
reviewed static libcurl 및 **모든** static transitive archive를
`KSI_CURL_STATIC_EXTRA_LIBRARIES`로 명시해야 한다. 현재 컨테이너의 distro `libcurl.a`는
동적 보조 라이브러리를 요구하므로 이 조건을 만족하지 않는다. 즉 source/wire adapter는
있지만, 검증된 정적 TLS bundle이 공급되기 전 standard DPK는 network-enabled라고 주장하지
않는다.

현재 작업 환경에는 registered ONNX/TensorRT library, signed runtime profile, calibrated
M4D convention, 또는 RGB sensor timestamp source가 제공되지 않았다. 따라서 profile
assembly 코드가 있어도 표준 DPK는 event producer가 아니라 capture-only다. 이 상태를
end-to-end network, hardware, 또는 production support로 해석하면 안 된다.

## 검증

일반 C++ 계약 테스트:

```bash
cmake -S edge/manifold-runtime -B build-edge
cmake --build build-edge -j
ctest --test-dir build-edge --output-on-failure
```

`tools/edge/verify_native_artifact_oracle.py`는 native WorldEntity/RiskField/EventBundle
fixture를 Python 계약 모델로 재검증하고,
`tools/edge/verify_native_activation_bridge.py`는 Python serializer가 쓴 실제 native
handoff를 C++ parser로 다시 읽는다. 두 도구 모두 replay oracle이며 Manifold HIL 증거를
대체하지 않는다.

### Candidate durability timing evidence

DPK가 실제 perception profile로 candidate를 만든 뒤, private perception state directory의
`artifacts/event-timing-*.json`만 HIL raw-log directory로 복사한다(artifact 원본은 git에
넣지 않는다). 다음 validator는 schema/stage/clock domain, integer duration 재계산,
candidate ID 중복, 손상 JSON, `NOT_MEASURED` record를 fail-closed로 검사한다.

```bash
uv run python tools/hil/summarize_event_candidate_timing.py summarize \
  --in-dir hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__candidate_durable_timing \
  --out hil_raw_logs/$SESSION_ID/07_frame_telemetry_timing/<UTC_ts>__candidate_durable_timing_summary.json \
  --session-id "$SESSION_ID" \
  --build-commit "$(git rev-parse HEAD)"
```

The fixed profile `ksi-edge-candidate-durability-v1` reports a within-budget
result only when every valid measured sample is at most 1,000 ms. It is a
strictly narrower measurement than the full Critical 1s/2s/5s product SLO: a
HIL session must additionally prove that its input set is Critical and must
separately measure the absent local-alert and server-notification products.
Therefore this report cannot itself make the DPK hardware-verified or
production-supported.

### TensorRT ↔ ONNX differential evidence

`tensorrt_differential_runner`는 CTest와 함께 빌드되는 **offline** companion binary다.
`KSI_ENABLE_TENSORRT=ON`인 Manifold/동일 ABI 환경에서만 실제 engine build·load·추론을
수행하며, PSDK callback이나 DPK 런타임에 설치되지 않는다. Python oracle은 raw RGB를
native와 같은 center-bilinear RGB→NCHW 1/255로 변환해 input tensor digest부터 비교한 뒤,
class/query, confidence, original-pixel bbox, 네 typed drop count를 비교한다.

이 RGB 변환 자체는 TensorRT 없이도 C++ worker helper로 빌드된다. 2×2 RGB→3×3 NCHW
golden fixture의 float32 digest를 C++ contract test와 Python oracle test가 각각 고정하므로,
TensorRT/CUDA가 없는 개발 환경에서도 resize·채널 순서·1/255 drift는 모델 출력 비교 전에
잡힌다. 이것은 CPU inference가 아니며 실제 TensorRT↔ONNX corpus PASS나 HIL 증거를
대체하지 않는다.

corpus는 raw image를 git에 넣는 것으로 lineage를 대신하지 않고, 다음 canonical JSON
manifest와 각 file digest로 준비한다. `rgbFile`은 corpus JSON 기준 safe relative path이고 각 raw file은
정확히 `width * height * 3` byte RGB여야 한다.

```json
{
  "schemaVersion": "1.0",
  "corpusId": "dfine-onnx-corpus-v1",
  "samples": [
    {
      "sampleId": "scene-01",
      "width": 1920,
      "height": 1080,
      "rgbFile": "scene-01.rgb",
      "rgbDigest": "sha256:<64-lower-hex>"
    }
  ]
}
```

실제 corpus는 최소 10 sample이다. 먼저 profile의 `tensorRtDifferential.corpusDigest`에
넣을 canonical digest를 계산한다.

```bash
uv run python tools/edge/verify_tensorrt_differential.py corpus-digest \
  --corpus /secure/dfine-corpus/corpus.json
```

그 digest, registered ONNX digest, preprocessor config digest, corpus ID/count와 기존
허용오차(`confidenceAtol <= 0.001`, `bboxAtolPx <= 0.5`)를 **unsigned candidate**
`EdgeRuntimeProfile`에 채운다. candidate는 Core 서명 전에는 activation authority가
아니다. Manifold에서 TensorRT runner를 빌드하고 evidence를 만든다.

```bash
cmake -S edge/manifold-runtime -B build-edge-trt \
  -DKSI_ENABLE_TENSORRT=ON -DKSI_BUILD_TESTS=ON \
  -DKSI_TENSORRT_ROOT=/opt/tensorrt
cmake --build build-edge-trt --target tensorrt_differential_runner -j

uv run python tools/edge/verify_tensorrt_differential.py verify \
  --runner build-edge-trt/tensorrt_differential_runner \
  --runtime-profile /secure/candidate-runtime-profile.json \
  --onnx /secure/models/dfine.onnx \
  --preprocessing-config /secure/models/preprocessor_config.json \
  --corpus /secure/dfine-corpus/corpus.json \
  --engine-vault-dir /secure/tensorrt-engines \
  --evidence-out /secure/dfine-tensorrt-differential.v1.json
```

출력된 canonical evidence digest를 candidate의 `evidenceDigest`에 넣고 Core가 profile을
서명한다. 이후 같은 bytes를 audit할 때만 `--require-profile-evidence-digest`를 추가한다.
runner/backend/model/corpus/ONNX output/tolerance 중 하나라도 실패하면 evidence를 쓰지
않으며, 이 도구의 `PASS`도 HIL timing, 5 Hz, hardware, production gate를 대체하지 않는다.
