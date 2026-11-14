# Mission issuance and activation gates

Historical acquisition contract. Current scope is governed by [ADR-KSI-039](../architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md).

## 2. 요구 correctness invariant

정본 invariant는 다음이다.

> **Mission M은 M의 route/contract를 생성하고 발급을 인가하는 데 사용한 Site 및 기타
> mutable prerequisite witness가 M의 Mission journal durable append 경계에서도 현재일
> 때만 durably issued가 될 수 있다.**

이는 질문에 제시된 “A mission may be durably issued only if the site/mission prerequisite
state used to authorize issuance is still current at the durability boundary”와 동등하다.
단순히 append 직전에 값을 한 번 더 읽는 것은 비교와 append 사이에 다시 전이가 가능하므로
충분하지 않다. **비교와 Mission append가 prerequisite mutation과 같은 lock 경계로
직렬화되어야 한다.**

이미 발급된 Mission은 이후 Site 상태가 바뀌어도 과거 발급 사실을 잃지 않는다.
`INV-052`는 신규 issuance boundary를 제어하며, 과거 record replay를 현재 Site 상태로
재심사하지 않는다. 현재 precheck도 기존 mission ID는 현재 Site gate보다 먼저 처리한다는
원칙을 명시한다(`mission_records.py:556-562`, `:596-603`).

### 3.4 Production pre-activation runtime latency gate

위 commit-time snapshot validity 요구는 유지하며 완화하지 않는다. Acquisition issue gate를
production에서 enable하기 전에 representative 실제 issuance workload로 다음 end-to-end 구간을
측정해야 한다.

```text
authorization witness capture
→ route generation
→ KMZ/contract materialization과 기타 issuance pre-commit work
→ Ed25519 signing
→ conditional commit 진입 직전
```

측정에는 최소 route generation duration, signing duration, 그 밖의 queueing·KMZ build·canonical
serialization을 포함한 모든 pre-commit latency와 합계가 있어야 한다. 소형 happy-path 평균이
아니라 실제 운영에서 대표적인 worst-case AOI/waypoint/work-order 조합과 반복 분포를 사용한다.

```text
observed issuance pre-commit latency
  = route generation duration
  + signing duration
  + every other issuance pre-commit latency
```

판정 threshold를 새로 만들지 않는다. 유일한 기준은 기존 communication snapshot의 실제
validity window와 commit 시 `snapshot`이 unexpired여야 한다는 §3.3 규칙이다. 현재 계약의
snapshot TTL 상한은 5분(300초)이지만, 300초를 별도의 성공 budget이나 새 threshold로
간주하지 않고 각 witness가 기록한 실제 `expiresAt`까지 남은 시간으로 판정한다.

> **PRE-ACTIVATION RUNTIME GATE:** representative worst-case issuance가 기존 snapshot-validity
> 요구를 지키면서 신뢰성 있게 commit까지 완료할 수 있음을 **실제 route generation duration +
> signing duration + 그 밖의 issuance pre-commit latency** 실측으로 입증하지 못하면 production
> activation은 반드시 `BLOCKED`다. snapshot TTL을 우회하거나 commit expiry 검사를 제거하지
> 말고, operational/design issue를 먼저 해결한 뒤 다시 측정한다.

이 runtime gate는 feature flag가 OFF인 동안 OCC revision/witness/atomic commit 메커니즘 자체를
구현하거나 contract test하는 선행조건은 아니다. 단, representative worst-case latency가 기존
snapshot-validity 요구 안에서 신뢰성 있게 완료됨을 입증하지 못하면 feature activation은
operational/design issue가 해결될 때까지 반드시 `BLOCKED`다. 구현 완료와 production activation
evidence를 별도 상태로 기록한다.

runtime validation evidence는 각 대표 workload의 witness `capturedAt`/`expiresAt`, route generation,
KMZ/contract materialization, signing, queueing/serialization, conditional commit 진입 시각과 성공·
`ACQUISITION_WITNESS_STALE` 결과를 보존해야 한다. 별도의 숫자 threshold를 만들지 않으며, 각
실행이 기존 snapshot-validity predicate를 만족했는지만 판정한다. 이 evidence가 없거나
representative worst-case에서 반복적으로 predicate를 만족하지 못하면 feature가 disabled인
상태를 유지한다. OCC mechanism 구현·replay·contract test는 feature가 disabled인 동안 이 실측을
기다리지 않는다.
