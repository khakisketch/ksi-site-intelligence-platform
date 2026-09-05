# 설계 적대적 검토 (읽기 전용)

> 작성 2026-09-01 · 기준 커밋 `41d9f55` + 기존 uncommitted civil-readiness WIP
>
> 검토 대상
> - `docs/design/WORKER_LEASE_IDENTITY_CONTRACT.md`
> - `docs/design/MISSION_ISSUANCE_ATOMICITY_CONTRACT.md`
> - `docs/design/CAPABILITY_SEMANTIC_CONTRACT.md`
>
> 근거 감사
> - `docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT.md` (+ Codex review)
> - `docs/audit/02_INVARIANT_AUDIT.md` (+ Codex review, `VERIFIED_WITH_CORRECTIONS`)
>
> **역할**: 적대적 검토다. 설계가 약속한 불변식을 깨는 **구체적 실행 순서**를 만드는 것이
> 목적이고, 다른 아키텍처가 더 낫다는 이유로 재설계를 제안하지 않는다. 모든 반론은
> ①현재 저장소 동작 ②구체적 interleaving ③계약 내부 모순 중 하나로 뒷받침한다.
> 표면적·미관상 지적은 넣지 않았다.
>
> **작업 트리**: 시작 시점에 이미 dirty였다. 어떤 파일도 되돌리거나 stage·commit·정리하지
> 않았다. 제품 코드는 수정하지 않았다. 생성한 파일은 이 문서 하나다.
>
> **검증 방법**: 세 계약이 인용한 코드 위치를 전부 다시 열어 확인했고, 계약이 인용하지
> 않은 인접 경로(artifact key 소비처, store lock 그래프, listener 발화 위치, worker
> work_dir, firmware 출처)를 추가로 추적했다. 테스트는 실행했고 결과를 §E에 적었다.

---

## 요약 판정

```text
DESIGN_ADVERSARIAL_REVIEW      = PASS_WITH_REQUIRED_CORRECTIONS

WORKER_LEASE_DESIGN_REVIEW     = PASS_WITH_REQUIRED_CORRECTIONS
MISSION_ISSUANCE_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
CAPABILITY_SEMANTIC_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
```

세 설계 모두 **방향은 옳고 구현 가능**하다. Mission issuance 설계의 원자성 경계는 실제
primitive로 구현 가능함을 확인했다(§B-0). Worker lease의 generation fencing은 핵심
공격(만료 후 stale writer의 늦은 PUT)을 실제로 막는다(§A-0).

그러나 **네 건의 blocking correction**이 있다. 셋은 worker lease 계약, 하나는 capability
계약이며, 전부 "구현 세부"가 아니라 **계약 문장이 결정하지 않았거나 스스로 모순되는
지점**이다. 특히 A-1과 A-3은 각각 "stale bytes가 authoritative가 될 수 있는" 경로를
남긴다 — 프롬프트가 허용 불가라고 지정한 바로 그 부류다.

---

# A. WORKER LEASE DESIGN ATTACK

## A-0. 먼저: 핵심 공격은 실제로 막힌다 (설계 성공 확인)

프롬프트가 지정한 5단계 실행을 계약대로 따라가면 다음과 같다.

```text
1. A가 generation 1을 CLAIM              → lease(J, instance=A, gen=1)
2. A가 정지(GC pause / 네트워크 분리)
3. lease 만료
4. B가 CLAIM                              → lease(J, instance=B, gen=2)   [monotonic +1]
5. A가 재개하여 각각 전송:
   - heartbeat  RENEW(instance=A, gen=1)  → STALE_LEASE_GENERATION  ✅
   - artifact upload-url(gen=1)           → STALE_LEASE_GENERATION  ✅
   - artifact 등록(gen=1)                 → STALE_LEASE_GENERATION  ✅
   - completion SUCCEEDED(gen=1)          → STALE_LEASE_GENERATION  ✅
   - failure FAILED(gen=1)                → STALE_LEASE_GENERATION  ✅
   - retry CLAIM                          → LEASE_HELD_BY_ANOTHER (B가 active) ✅
```

Core mutation 5종은 이미 단일 관문 `_check_lease_locked`를 통과하므로
(`processing_jobs.py:1743-1766`, 호출처 `:1228`, `:1533`, `:1622`, `:1798`) generation
비교를 그 함수 하나에 넣으면 전수 적용된다. 설계 §4.6의 verdict 표는 이 다섯을 모두
덮는다.

**늦은 PUT도 막힌다.** A가 4단계 이전에 발급받은 presigned PUT URL은 TTL 안에서 여전히
유효하지만, 그 URL이 가리키는 자리는 `.../g1/dsm-1`이고 B가 등록하는 자리는
`.../g2/dsm-1`이다. A의 바이트는 물리적으로 존재하되 어떤 원장 레코드도 그것을 가리키지
않는다 — 프롬프트가 요구한 구분("stale bytes still physically exist"는 허용,
"stale bytes can become authoritative"는 불가)을 generation-scoped key가 정확히 만족한다.

**클라이언트 측 조기 중단도 성립한다.** stale RENEW가 예외를 던지면
`run_to_completion`의 `poll()` 콜백은 예외를 삼키지 않으므로
(`services/processing-controller/src/ksi_processing_controller/odm.py`,
`for _ in range(max_polls): ... poll()`) 즉시 ODM 루프를 빠져나가고
`run_job`의 광범위 `except Exception`이 받아 FAILED 전이를 시도(역시 stale 거부)한 뒤
원 예외를 다시 던진다. stale worker가 계산을 계속 돌면서 자원을 점유하는 상태가 아니다.

아래 blocking 항목은 이 성공을 **무효화하는 우회로**들이다.

---

## A-1 [BLOCKING] artifact object key는 저장되지 않고 **5곳에서 재유도**된다 — reader를 함께 바꾸지 않으면 stale bytes가 authoritative가 된다

### 현재 저장소 동작

`processing_jobs.py:1205`가 이 저장소의 현행 규약을 명시한다.

> **키는 저장하지 않고 유도한다** — `build_processing_artifact_object_key`

즉 artifact 레코드에 object key가 없다. key를 소비하는 모든 지점이 `(site_id, job_id,
artifact_id[, filename])`에서 **매번 다시 계산**한다. 실제 소비처는 upload 경로 하나가
아니라 **5곳 / 4개 모듈**이다.

| # | 위치 | 용도 |
|---|---|---|
| 1 | `processing_jobs.py:1234` | upload target (쓰기) |
| 2 | `processing_jobs.py:2700` | `GET .../artifacts/{id}/download` 주 파일 |
| 3 | `processing_jobs.py:2708` | 같은 route의 `auxiliary_files` 전부 |
| 4 | `checkpoint_validations.py:872-875` | 독립 checkpoint 검증이 읽는 immutable DSM |
| 5 | `comparison_requests.py:1219` / `design_conformance_requests.py:1986` | 비교·설계 대비 워커의 입력 |

### 계약 내부의 공백

설계 §4.4는 **쓰기 쪽만** 규정한다: "artifact registration event는 `leaseGeneration`과 실제
`storageObjectKey` 또는 동등한 immutable storage binding을 함께 기록한다."
읽기 쪽에 대해서는 "legacy artifact는 현재 결정적 key를 reader가 사용하되
`LEGACY_UNFENCED`로 취급한다" 한 문장뿐이고, **위 5개 소비처 중 어느 것도 열거되지
않는다.** §"Files to change"와 rollout §4.9(step 4 "generation-scoped digest-bound artifact
upload/binding 적용")에도 reader 전환 단계가 없다.

### 구체적 실행

```text
0. (enforcement ON, generation-scoped 쓰기만 배포된 상태)
1. A가 gen 1 CLAIM → upload-url(dsm-1) → 키 .../g1/dsm-1 → PUT(bytes_A) → 등록(digest_A)
2. A 정지 → lease 만료
3. B가 gen 2 CLAIM → upload-url(dsm-1) → 키 .../g2/dsm-1 → PUT(bytes_B)
4. B가 등록 시도 → (A-3 참조: 현재 identity 규칙이면 DUPLICATE_ARTIFACT)
5. 운영자/워커가 GET /v1/processing-jobs/J/artifacts/dsm-1/download
   → processing_jobs.py:2700이 (site,J,dsm-1)로 **legacy 키**를 재유도
   → generation 없는 그 자리에는 fencing이 적용된 적이 없다
6. comparison/design-conformance/checkpoint 워커도 4·5번 위치에서 같은 legacy 키를 읽는다
```

결과: 원장은 generation-scoped 키를 기록하는데 **모든 읽기 경로는 fencing되지 않은 옛
자리를 본다.** 그 자리는 정확히 늦은 stale PUT이 착지할 수 있는 곳이므로,
"stale bytes가 authoritative가 된다"가 성립한다. 반대로 legacy 자리에 아무도 쓰지 않게 되면
다운로드·비교·설계 대비·checkpoint 검증이 전부 조용히 빈 객체를 읽는다.

### 필요한 정정 (blocking)

1. artifact 레코드에 `storageObjectKey`(및 `auxiliaryFiles` 각각의 키)를 **저장**하고,
   위 5개 소비처를 전부 "저장된 키를 읽는다"로 바꾼다. `auxiliary_files` 키가 계약에서 한
   번도 언급되지 않았다 — 명시해야 한다.
2. `processing_jobs.py:1205`의 "키는 저장하지 않고 유도한다"는 현행 규약을 뒤집는 것이므로
   Adoption decisions에 `REPLACE`로 올린다.
3. rollout에 **reader 전환을 writer 전환보다 먼저** 두는 단계를 넣는다(§4.5 step 1의
   "reader 먼저" 원칙과 같은 이유).
4. legacy(generation 없는) artifact와 신규 artifact가 공존하는 기간의 reader 분기를
   4개 모듈 전부에 대해 규정한다.

---

## A-2 [BLOCKING] CLAIM 재시도가 자기 자신을 fencing한다 — 계약 §4.1(3) ↔ §4.6 모순

### 계약 내부 모순

- §4.1(3): "새 소유권 취득은 `G+1`; **같은 active owner의 renewal만** `G`를 유지한다."
- §4.4: "`renewal=false`이면 generation은 이전 high-water mark+1이어야 한다."
- §4.2: "`RENEW`는 현재 generation을 반드시 보내며 expiry 뒤 자동 `CLAIM`으로 해석하지
  않는다." — `CLAIM`에는 client generation을 **금지**한다(§4.3).

그러면 **이미 active lease를 쥔 instance가 다시 `CLAIM`을 보내면** 어떻게 되는가?
`CLAIM`이므로 `renewal=false`이고, §4.4에 따라 generation은 high-water+1이 된다.
그러나 §4.1(3)에 따르면 소유자가 바뀌지 않았으므로 새 소유권 취득이 아니다.
**계약이 이 경우를 두 가지로 동시에 규정한다.**

### 구체적 실행 (프롬프트의 "CLAIM response lost")

```text
1. A(instance=X)가 CLAIM 전송
2. Core: lease(J, X, gen=5) durable append + fsync 완료
3. 응답이 네트워크에서 유실 (또는 A의 read timeout)
4. A는 lease를 못 얻었다고 판단하고 CLAIM 재전송  ← runner의 정상 재시도 경로
5. §4.4 해석: renewal=false → gen=6 발급
6. A는 gen 6으로 계속 진행 — 그러나 3단계 이전에
   이미 gen 5로 발급받은 presigned URL과 gen 5로 등록한 artifact는 전부 stale이 된다
```

즉 **응답 한 번이 유실되면 워커가 자기 자신을 fencing한다.** 5단계 이후 A가
`.../g5/...`로 진행 중이던 업로드는 A-1의 orphan이 되고, gen 5로 이미 등록한 artifact가
있으면 A-3의 교착까지 겹친다. 이는 이 설계가 도입하는 **신규** 실패 모드다(현재는
`acquire_lease` 재호출이 항상 무해한 renewal이다 — `processing_jobs.py:1704`
`renewing = current is not None and denial is None`).

`worker.py:419`의 heartbeat가 초기 취득과 **완전히 같은 호출**(`core.acquire_lease(job_id)`)
이라는 현행 코드도 이 모호성을 실제 경로로 만든다 — 클라이언트가 두 의미를 구분해 보내도록
바꾸는 과정에서 "잘 모르겠으면 CLAIM" 같은 구현이 나오기 쉽다.

### 필요한 정정 (blocking)

`CLAIM`을 **소유자 기준으로 멱등**하게 정의한다.

> `CLAIM`이 도착했을 때 그 job의 active lease가 **이미 요청 instance의 것**이면,
> generation을 증가시키지 않고 현재 `(generation, expiresAt)`을 그대로 반환한다
> (`LEASE_ALREADY_HELD` 또는 `LEASED` 재반환). generation 증가는 **소유 instance가 실제로
> 바뀌거나, 직전 generation이 만료된 뒤 재취득할 때만** 일어난다.

§4.6 표에 이 행을 추가하고, §4.4의 "renewal=false ⇒ high-water+1"을
"**소유 instance가 바뀌었거나 직전 lease가 만료됐을 때** ⇒ high-water+1"로 좁힌다.

---

## A-3 [BLOCKING] artifact identity가 job-scoped인데 계약이 generation-scoped 여부를 정하지 않았다 — 두 선택지 모두 불변식을 깬다

### 현재 저장소 동작

`processing_jobs.py:1246-1273` `_check_artifact_identity_locked`:

```python
known = {a.artifact_id for a in job.artifacts}
if artifact.artifact_id in known:
    return (ProcessingJobVerdict.DUPLICATE_ARTIFACT, ...)
missing = [p for p in artifact.lineage.derived_from if p not in known]
```

- 중복 판정 범위는 **job 전체**다(generation 무관).
- `derivedFrom` 부모도 **같은 job**에 있어야 한다.
- `assert_succeeded_is_backed`(`processing_jobs.py:322-355`)도 인자가
  `artifacts: Sequence[ProcessingArtifact]` — **job의 전체 artifact 집합**이며 generation을
  받지 않는다.

설계 §4.4는 registration event에 `leaseGeneration`을 **기록**한다고만 하고, identity와
`assert_succeeded_is_backed`의 범위가 job-scoped로 남는지 generation-scoped가 되는지
결정하지 않는다. 두 선택 모두 문제가 있다.

### 선택 (a): identity를 job-scoped로 유지 → 회수 경로가 결정론적으로 죽는다

```text
1. A(gen 1): ODM 완주 → pc-1(point cloud, authority=source) 등록 성공
2. A가 dsm-1 등록 직전에 정지 (SUCCEEDED 전이 전)
3. lease 만료 → B(gen 2)가 CLAIM (job은 RUNNING이고 lease 만료 → is_claimable=True)
4. B는 처음부터 재실행한다 (worker.py에 부분 재개 없음 — runner.py:70-76이 명시)
5. B가 pc-1 등록 → DUPLICATE_ARTIFACT  ← generation과 무관하게 job-scoped 중복
6. B는 FAILED로 끝난다
7. 다음 회수도 같은 지점에서 같은 이유로 실패 → 이 job은 영구히 완료 불가
```

현재도 같은 형상이 존재하지만 `runner.py:70-76`은 이를 "드문 창"이라고 적는다. fencing이
들어오면 이 경합은 **드물지 않고 결정론적**이 된다 — 만료 회수는 정상 경로이기 때문이다.

### 선택 (b): identity를 generation-scoped로 변경 → stale artifact가 SUCCEEDED를 뒷받침한다

`assert_succeeded_is_backed`가 job의 artifact 전체를 보므로, gen 1이 남긴
`authority=source` artifact가 **gen 2의 SUCCEEDED 게이트를 통과시킨다.**

```text
1. A(gen 1): pc-1(g1) 등록 — bytes_A, digest_A
2. A 정지 → 만료 → B(gen 2)
3. B: ODM 재실행 실패 또는 point cloud 미생성, dsm-1(g2)만 등록
4. B가 SUCCEEDED 전이 → assert_succeeded_is_backed가 job artifacts 전체를 보고
   pc-1(g1)의 authority=source를 발견 → 통과
5. 결과: gen 2가 만든 적 없는 gen 1의 산출물이 gen 2의 완료 근거가 된다
```

이것이 정확히 "stale bytes can become authoritative"다. INV-051의 의미("이 작업이 원본을
만들었다")도 함께 무너진다.

### 필요한 정정 (blocking)

계약이 다음 셋을 **모두** 명시해야 한다.

1. artifact identity의 범위: `(job_id, artifact_id)`인가 `(job_id, generation, artifact_id)`인가.
2. `assert_succeeded_is_backed`의 입력 범위: **완료를 주장하는 generation의 artifact 집합만**
   보아야 한다(권장). 그러지 않으면 (b)가 성립한다.
3. `derivedFrom` 부모 해석 범위: 같은 generation 안으로 좁힌다(권장). job 전체로 두면
   gen 2의 파생물이 gen 1의 부모를 가리킬 수 있고, 그 부모의 바이트는 아무도 재검증하지 않았다.
4. (1)에서 generation-scoped를 택하면 **부분 등록 후 회수** 시나리오가 정상 동작하는지
   테스트로 고정한다. job-scoped를 유지하면 (a)의 영구 실패를 수용 가능한 결과로 계약에
   적어야 한다 — 조용히 남겨두면 안 된다.

---

## A-4 [BLOCKING] 복수 replica가 **같은 로컬 work_dir**을 공유한다 — Core fencing이 닿지 않는 교차 job 오염

### 현재 저장소 동작

`worker.py`의 작업 파일 경로는 **평면(flat)이고 job별로 분리되지 않는다**.

- `worker.py:313` `work_dir.mkdir(parents=True, exist_ok=True)` — job별 하위 디렉터리 없음
- `worker.py:344` `local_path = work_dir / media.media_id`
- `worker.py:432` `archive_path = work_dir / "all.zip"` ← **상수 파일명**
- `worker.py:226-240` `_cleanup_work_files`가 `finally`에서 경로를 `unlink`

`work_dir`는 `KSI_WORKER_WORK_DIR` 환경변수 하나이고(`runner.py:498-500`), compose는 worker
서비스에 `ksi-worker-work:/var/lib/ksi/worker` 명명 볼륨을 마운트한다
(`deploy/compose.yaml`). `--scale worker=N`은 **같은 서비스 정의를 복제**하므로 모든
replica가 같은 볼륨·같은 `work_dir`를 갖는다.

### 구체적 실행 — lease fencing이 원리적으로 개입할 수 없다

```text
1. replica A가 job J1을 CLAIM (gen 1)  ← 정상, 경합 없음
2. replica B가 job J2를 CLAIM (gen 1)  ← 다른 job이므로 lease 충돌 자체가 없다
3. A: NodeODM 완주 → work_dir/all.zip 에 J1 아카이브 기록
4. B: NodeODM 완주 → work_dir/all.zip 에 J2 아카이브 기록 (A의 파일을 덮어씀)
5. A: work_dir/all.zip 에서 산출물 추출 → **J2의 바이트를 J1의 artifact로 업로드·등록**
6. 또는 B의 finally가 A의 진행 중 all.zip 을 unlink → A가 알 수 없는 실패
```

5번의 결과는 `jobId=J1`의 원장이 J2의 바이트를 가리키는 **계보 위조**다. digest는 A가 실제로
읽은 바이트(=J2의 것)와 일치하므로 digest 검증으로도 걸리지 않는다. 이것은 같은 job의
stale writer 문제가 **아니므로** lease/generation 설계 어디에도 걸리지 않는다.

### 계약과의 충돌

설계 §4.9 step 6은 "stale rejection/orphan metric 관측 후에만 worker replica 수를 2 이상으로
확대"라고 적는다. 즉 **이 계약이 scale-out을 승인하는 문서**인데, scale-out을 안전하게
만드는 전제 중 로컬 파일시스템 격리가 빠져 있다. Codex 검토도 같은 사실을 지적했다
(`02_INVARIANT_AUDIT_CODEX_REVIEW.md` §1.7).

### 필요한 정정 (blocking)

`work_dir` 격리를 replica>1의 **명시적 전제조건**으로 계약에 넣는다. 최소 형태는
`work_dir / worker_instance_id / job_id /` 하위 디렉터리이며, `_cleanup_work_files`가 그
하위 트리만 지우도록 범위를 좁힌다. 볼륨을 replica마다 분리하는 배포 방식도 대안이지만,
그러면 §5 "worker process마다 bearer token을 발급하는 것을 아키텍처 요구로 만들지 않는다"와
같은 이유로 배포 복잡도를 다시 올린다 — 코드 쪽 격리가 계약에 더 맞다.

---

## A-5 [REQUIRED CORRECTION] "Replay equivalence"가 과장돼 있다

### 계약의 주장

§4.1(6): "**Replay equivalence** — live와 replay는 같은 generation 전이표를 적용하며,
누락·역행·잘못된 renewal은 store recovery를 fail-closed 거부한다."

### 현재 저장소 동작이 말하는 것

`processing_jobs.py:1203-1232` `_replay_lease`의 docstring이 명시적으로 부정한다.

> live 게이트(다른 워커가 유효 lease를 쥐고 있으면 발급 거부)를 재생이 다시 태우지
> **못한다** — 그 판정에는 발급 당시의 `now`가 필요한데 재생 시점에는 그 시각이 지나
> 있어 어떤 lease든 만료로 보인다. 시간축 판정은 재생으로 재현되지 않는 부류이고,
> 그 사실을 여기 적어 둔다.

따라서 replay에서 재검증 **가능한 것**과 **불가능한 것**이 갈린다.

| 항목 | replay 재검증 |
|---|---|
| generation 단조 증가 / 역행 / 누락 | 가능 (저장된 정수 비교) |
| `renewal=true`의 instance·generation 일치 | 가능 |
| `renewal=false`의 generation == high-water+1 | 가능 |
| **`renewal=true`가 만료 전에 일어났는가** | **불가능** (발급 당시 `now` 없음) |
| 다른 instance가 active일 때의 CLAIM 거부 | 불가능 (같은 이유) |

즉 journal을 손으로 고쳐 만료된 generation의 `renewal=true` 레코드를 끼워 넣으면
replay가 그것을 통과시킨다. 이것은 fencing 설계의 결함이 아니라 시간 기반 TTL의 내재적
성질이며(기존 코드가 이미 그렇다), 그러므로 **계약이 약속을 그 범위로 좁혀 써야 한다.**

### 필요한 정정

§4.1(6)을 "generation의 단조성·소유 일치·high-water 규칙은 replay가 재검증한다. **lease
만료 시각 판정은 replay가 재현하지 않는다**(`_replay_lease` docstring)"로 정정한다.
§4.8 test 7("lease generation journal 역행·누락 renewal·owner 변경 renewal replay 거부")은
그대로 유효하다 — 이 셋은 모두 시간 비의존이다.

---

## A-6 [NON-BLOCKING] `worker_instance_id`는 클라이언트 주장값이다 — 위협 모델을 명시해야 한다

§2.C는 "두 프로세스는 서로 다른 cryptographically-random `worker_instance_id`를 **생성해야
한다**"고 쓰지만, Core는 이를 검증할 수단이 없다. 같은 credential을 가진 프로세스는 남의
instance ID를 그대로 보낼 수 있고, 그러면 RENEW가 성공해 fencing이 무력화된다.

§4.2가 "lease handle은 bearer secret의 대체물이 아니다"라고 적은 것은 옳지만, §2.C의 문장은
그 한계를 흐린다. 실제 보증은 다음과 같이 좁게 써야 한다.

> `worker_instance_id`는 **우발적 동일시(accidental conflation)를 제거**한다. 같은
> credential을 쥔 프로세스가 고의로 남의 instance ID를 참칭하는 경우는 이 메커니즘이
> 막지 않으며, 그 위협은 credential 분리 또는 신뢰 경계로 다룬다.

이는 이 설계의 목표(같은 토큰을 쓰는 **정상** 프로세스들을 구분)에 비추어 충분하다.
blocking이 아니라 문장 정정이다.

---

## A-7 [NON-BLOCKING] 부수적으로 확인된 사항

- **버려진 NodeODM task**: stale worker가 중단해도 그 워커가 제출한 NodeODM task는 남는다
  (`odm.py` `run_to_completion`은 취소 API를 부르지 않는다). 계산 자원 누수이며 정합성
  문제는 아니다. §4.7 observability에 orphan NodeODM task 계측을 넣을 가치가 있다.
- **generation의 wire 폭**: JSON 정수로 나가므로 JS reader에서 2^53 초과 시 정밀도가 깨진다.
  실사용에서 도달 불가하지만, wire 계약에 int64 안전 범위를 명시해 두면 나중에 dashboard가
  이 값을 읽게 될 때 논쟁이 없다.
- **네 store 동형 적용**: comparison / design-conformance / region-extraction의 lease 사용은
  확인했다(`comparison_requests.py:1392,1430,1500` 등). design-conformance의 diff-raster는
  Core가 두 번 재해싱하므로(`design_conformance_reports.py:9-37`) 같은 generation 안의 byte
  substitution에는 이미 강하지만, **리포트 기록 이후**의 늦은 overwrite는 재검증되지 않는다.
  §4.4의 generation-scoped binding을 diff-raster에도 적용하는지 명시하면 이 구멍도 닫힌다.

## A. 결론

```text
WORKER_LEASE_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
```

핵심 fencing 메커니즘은 지정된 공격을 실제로 막는다(§A-0). 그러나 A-1(reader 미전환),
A-3(artifact identity 미결정)은 각각 stale bytes가 authoritative가 되는 경로를 남기고,
A-2(CLAIM 멱등성)는 계약 내부 모순이며, A-4(공유 work_dir)는 이 계약이 승인하는 scale-out을
안전하지 않게 만든다. **네 건 모두 계약 문장 수정으로 해소 가능**하며 재설계는 필요 없다.

---

# B. MISSION ISSUANCE DESIGN ATTACK

## B-0. 먼저: 원자성 경계가 실제 primitive로 구현 가능함을 확인했다

프롬프트가 요구한 검증("A design that says 'atomically check and append' without identifying
an actual atomicity boundary is not sufficient")에 대해:

**구현 가능하다.** 근거는 세 가지다.

1. **필요한 lock이 전부 프로세스 로컬로 존재한다.** `SiteStore._lock`(`sites.py:241`),
   `ObservationWorkOrderStore._lock`, `AcquisitionConnectivityStore._lock`은 `RLock`
   (`acquisition/store.py:42`), `MissionStore._lock`. Core는 단일 프로세스이고
   (`Dockerfile:57`에 `--workers` 없음) 모든 라우트가 sync `def`라 같은 프로세스 스레드풀에서
   돈다. 따라서 네 lock을 `ExitStack`으로 정해진 순서에 잡으면 실제 직렬화가 성립한다.
2. **`MissionStore`가 leaf lock임을 확인했다.** `mission_records.py` 안에 다른 store 참조가
   0건이다(grep 결과 없음). 반대로 **8개 모듈이 `self._mission_store.*`를 호출**하며
   그중 여럿은 자기 lock을 쥔 채 호출한다(`source_media.py:1448-1449`가 SourceMedia lock →
   Mission lock, `coverage_reports.py:367→373`이 Coverage lock → Mission lock,
   `edge_dispatch.py:429`가 EdgeDispatch lock → Mission lock). **모든 중첩이 Mission을 마지막에
   잡는다.** 설계의 `Site → WorkOrder → Acquisition → Mission` 순서는 이 성질을 보존하므로
   순환이 없다.
3. **역방향 중첩이 없음을 확인했다.** 가장 의심스러운 경로였던 WorkOrder status listener는
   lock **밖**에서 발화한다 — `observation_work_orders.py`의 세 호출지점(`:405`, `:480`,
   `:524`)이 모두 8-space 들여쓰기로 `with self._lock:` 블록을 벗어나 있다. 이 listener는
   `_create_review_ready_briefing` → `SiteBriefingService.refresh` → SiteStore + Copilot
   HTTP로 이어지므로(`app_assembly.py`), 만약 lock 안에서 발화했다면
   **WorkOrder → Site**가 되어 coordinator의 `Site → WorkOrder`와 정확히 교착했을 것이다.
   같은 이유로 `on_approved` 콜백도 라우터 레벨에서 호출된다
   (`observation_work_orders.py:827`, `:905`).
   자동 Site 전진도 전부 store lock 밖이다(`processing_jobs.py:2330`, `:2464`,
   `mission_execution.py:456`).

## B-1. 프롬프트가 지정한 네 실행 — 전부 차단됨

| # | 실행 | 결과 | 근거 |
|---|---|---|---|
| 1 | witness 읽기 → 서명 → Site `SUSPENDED` → commit | **차단** | commit이 Site lock 안에서 `site_issuance_revision` 비교. `SUSPENDED` 진입은 `site-transitioned` event이므로 revision이 증가한다 |
| 2 | witness 읽기 → WorkOrder 변경 → commit | **차단** | `ObservationWorkOrder.version`이 update마다 +1이고 replay가 이를 강제한다(`observation_work_orders.py:118-162`). witness가 version·cycle·status를 담는다 |
| 3 | witness 읽기 → Acquisition 변경 → commit | **차단** | `snapshot_id`가 unique하고 profile 변경 시 기존 snapshot이 폐기된다(`acquisition/store.py:52-83`, `:123-155`) |
| 4 | witness 읽기 → 값이 바뀌었다 되돌아옴(ABA) → commit | **차단** | 아래 |

### ABA에 대한 판정 — 값 비교만으로는 취약하고, revision이 이를 막는다

`SiteStatus`는 열거형이고 `A → B → A` 복귀가 실제로 가능하다. 예:
`PATROL_READY → PATROL_ACTIVE → PATROL_READY`는 전이표에 양방향 간선이 존재한다
(`enums.py:163-165`). 따라서 **status 값만 비교하면 두 전이가 일어난 사실이 사라진다.**

설계 §3.1의 `site_issuance_revision`(registration=1, `site-transitioned`마다 +1)은 두 전이를
+2로 관측하므로 ABA를 정확히 잡는다. 이 판단은 옳다.

`updated_at`을 쓰지 않기로 한 결정도 옳다 — `site-aoi-set`·`site-model-age-policy-set`
(`sites.py:651`, `:704`)도 `updated_at`을 움직이므로 인가와 무관한 변경이 false conflict를
만든다.

### siteFrame 불변성 주장을 독립 확인했다

Site journal의 kind는 정확히 네 개다: `site-registered`(`sites.py:503`),
`site-transitioned`(`:579`), `site-aoi-set`(`:651`), `site-model-age-policy-set`(`:704`).
`siteFrame`은 `site-registered`에서만 기록된다(`:513`). 따라서 §3.1의
"siteFrame은 등록 후 immutable projection"은 **사실이다.** revision을 status 전이만으로
세는 것이 인가 입력 전체를 덮는다.

## B-2. 나머지 지정 시나리오

| 시나리오 | 계약의 답 | 판정 |
|---|---|---|
| 같은 mission 동시 발급 | Mission lock 안 duplicate check→append (`mission_records.py:522-540`) | ✅ 기존 primitive가 이미 원자적 |
| 클라이언트 중복 retry | 같은 digest → 200 stored result (§5.3) | ✅ pair는 이미 구현(`mission_plans.py:774-776`), contract-only로 확장 필요 |
| 같은 mission ID·다른 idempotency identity | 409 `MISSION_ID_CONFLICT` | ✅ |
| 서명 전 crash | Mission append 없음 → issued 아님 | ✅ |
| 서명 후 crash | append 없음 → issued 아님. sequence gap 허용 | ✅ `MissionIssuanceSequenceStore`가 gap 허용·재사용 금지를 이미 계약으로 가짐 |
| commit 내부 crash | 프로세스 종료로 lock 해제, journal은 fsync 단위로 일관 | ✅ |
| durable append 후 HTTP 응답 전 crash | issued. 동일 retry는 200 | ✅ §5.3이 contract-only에 digest를 추가해야 성립 — 계약이 명시함 |
| journal replay | revision을 Site journal 순서로 복원 | ✅ 결정적 |
| KMZ 생성 실패 | Mission append 이전이므로 issued 아님 | ✅ |
| contract 생성됐으나 KMZ 실패 | 동일 | ✅ |
| 서명 성공·commit 실패 | signed bytes는 authority 없는 임시값 | ✅ §6.4 |
| commit 성공·응답 직렬화 실패 | 위 "append 후 crash"와 동일 | ✅ |
| commit 직후 Site 전이 | 허용 — invariant는 durability boundary까지의 currentness | ✅ §6 마지막 문단 |
| 서로 다른 mission type이 같은 prerequisite 경쟁 | 발급은 Site revision을 바꾸지 않으므로 둘 다 통과 | ✅ 정상 — 한 현장에 복수 임무 발급은 합법 |

## B-3 [REQUIRED CORRECTION] §5.1의 lock 인벤토리 서술이 사실과 다르다 (결론은 살아남음)

### 계약의 문장

> 현재 Site transition은 Site lock 하나, WorkOrder update는 WorkOrder lock 하나,
> Acquisition observation은 Acquisition lock 하나, Mission append는 Mission lock 하나를
> 잡으므로 후속 구현 전에 reverse nested path가 없음을 구조 테스트로 고정한다.

### 사실

"각 store가 lock 하나만 잡는다"는 **그 네 store에 대해서만** 참이다. 시스템 전체로는
최소 8개 모듈이 `self._mission_store.*`를 호출하고, 그중 여럿은 자기 lock을 쥔 채다.

| 모듈 | `self._mission_store.*` 호출 수 | 자기 lock 안에서 호출 확인 |
|---|---|---|
| `source_media.py` | 8 | 예 (`:1448-1449`) |
| `checkpoint_validations.py` | 4 | — |
| `comparison_requests.py` | 4 | — |
| `design_conformance_requests.py` | 4 | — |
| `region_extraction_requests.py` | 4 | — |
| `coverage_reports.py` | 3 | 예 (`:367` → `:373`) |
| `mission_execution.py` | 2 | — |
| `edge_dispatch.py` | 1 | 예 (`:426-429`) |

또한 `processing_jobs.py`의 `_record_is_visible_locked`는 **Job lock을 쥔 채**
`self._source_media.mission_is_visible(...)`을 호출하고, 그것이 다시 SourceMedia lock →
Mission lock으로 내려간다. 즉 실제로는 **Job → SourceMedia → Mission**의 3단 중첩이 이미
존재한다.

### 결론에 미치는 영향

**설계의 결론(역방향 중첩 없음)은 유지된다** — 위 모든 중첩이 Mission을 마지막에 잡고
`MissionStore`는 다른 store를 참조하지 않기 때문이다. 그러나 근거 문장이 틀렸으므로
§5.1의 구조 테스트 명세도 함께 틀린다. "각 store가 lock 하나만 잡는지"를 검사하면
`source_media`·`coverage_reports`·`edge_dispatch`·`processing_jobs`에서 즉시 실패한다.

### 필요한 정정

§5.1의 서술을 실제 성질로 바꾼다.

> **`MissionStore`의 lock은 leaf다** — `mission_records.py`는 다른 store를 참조하지 않는다.
> 현재 존재하는 모든 cross-store 중첩(`processing_jobs → source_media → mission`,
> `coverage_reports → mission`, `edge_dispatch → mission`, `checkpoint_validations →
> mission`, comparison/design-conformance/region-extraction → mission)은 Mission을 마지막에
> 잡는다. Commit coordinator의 `Site → WorkOrder → Acquisition → Mission` 순서는 이 성질을
> 보존한다.

구조 테스트는 "각 store가 lock 하나"가 아니라 **"Mission leaf 성질"과 "Site·WorkOrder·
Acquisition을 Mission 이후에 잡는 경로가 없음"**을 검사해야 한다.

## B-4 [REQUIRED CORRECTION] Acquisition witness의 5분 TTL과 서명 시간이 충돌할 수 있다 — livelock 정의가 없다

### 계약의 요구

§3.3: commit 시점에도 "같은 profile/snapshot이며 **만료되지 않았고** readiness가 true여야
한다."

### 현재 저장소 동작

`ConnectivitySnapshotV1`의 TTL 상한은 **5분**이다(`acquisition/models.py:283-323`,
`contracts/schemas/connectivity-snapshot.v1.json`). readiness는 `now >= snapshot.expires_at`
이면 `CONNECTIVITY_STALE`을 반환한다(`acquisition/store.py:195-201`).

한편 짝 발급의 lock 밖 작업은 **경로 생성 + KMZ 빌드 + Ed25519 서명**이다
(`mission_plans.py:762-920`). 넓은 AOI의 lawnmower 경로 생성 시간은 저장소에서 측정된 적이
없다.

### 구체적 실행

```text
1. issue gate ON (KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=true)
2. t=0   witness 캡처 — snapshot S, expires_at = t+280s
3. t=0   경로 생성 시작 (넓은 AOI)
4. t=300 서명 완료, commit 진입
5. commit: snapshot S가 만료됨 → ACQUISITION_WITNESS_STALE (409)
6. 재시도: 새 snapshot S'로 witness 캡처 → 다시 300초 소요 → 다시 만료
   → 이 현장·이 AOI에서는 **영구히 발급 불가**
```

이는 안전 문제가 아니라 **liveness 문제**다. 그러나 결과는 "새 snapshot으로 다시 요청해야
한다"(§6.4)는 계약의 지시를 따라도 성공할 수 없는 상태이므로, 계약이 답을 가져야 한다.

### 필요한 정정

다음 중 하나를 명시한다.

- (a) acquisition witness는 **인가 시점 사실**로 취급하고 commit에서는 profile/snapshot
  **동일성**만 비교한다(만료는 재검사하지 않는다). 근거: readiness는 "발급을 시작해도 되는가"
  이지 "지금 이 순간 통신이 살아있는가"가 아니며, `in_flight_contract_policy`가 이미
  `REMAINS_VALID_UNTIL_CONTRACT_EXPIRY`다(`acquisition/store.py:_view`). — **권장**
- (b) 만료 재검사를 유지하되, 경로 생성 시간 상한을 정하고 초과 시 조기 실패시킨다.
- 어느 쪽이든 **경로 생성 소요 시간의 실측**이 선행돼야 한다(§"외부 증거" 참조).

Site revision과 WorkOrder version은 이 문제가 없다 — 시간이 아니라 사건 수로 판정하므로
느린 서명이 자동으로 conflict를 만들지 않는다.

## B-5 [NON-BLOCKING] `ensure_run`이 commit 이전에 durable하다

`mission_plans.py:711-717`의 `_resolve_work_order`가 서명·commit **이전에**
`acquisition_coordination_store.ensure_run(...)`을 호출해 `AcquisitionRun`을 durable하게
만든다. commit이 witness conflict로 거부되면 이 run은 참조되지 않은 채 남는다.

`ensure_run`은 `(organization_id, work_order_id, cycle_number)` 키로 멱등하므로
(`acquisition/coordination.py:159-167`) 재시도가 같은 run을 재사용한다. 따라서 **실질 피해가
없다.** 다만 §6.4가 "signed bytes나 reserved sequence를 Mission으로 기록하지 않는다"만
말하고 이 durable side effect를 언급하지 않으므로, 한 문장 추가를 권한다.

## B-6 [REQUIRED TEST] witness 완전성이 모듈 간 암묵 결합이다

§3.1은 "AOI와 model-age policy는 **현재** mission precheck의 인가 입력이 아니므로 revision을
올리지 않는다"고 쓴다. 이 주장은 오늘 사실이다 — `precheck_issuance`는 `site.aoi`를 읽지
않고(`mission_records.py:539-603`), 짝 발급은 요청이 실어 보내는 `request.aoi`를 쓴다
(`sites.py:44-53`이 "임무 AOI와 현장 AOI는 현재 대조되지 않는다"고 명시).

그러나 이는 **두 모듈 사이의 강제되지 않은 결합**이다. 나중에 누군가 route authorization에
`site.aoi`를 넣으면서 revision 규칙을 함께 고치지 않으면, witness가 인가 입력을 조용히
덜 덮게 되고 그 실패는 테스트가 아니라 운영에서 드러난다.

§8의 테스트 13개에 lock-order 인벤토리는 있으나 **witness 완전성 테스트는 없다.**
"`precheck_issuance`가 읽는 Site 필드 집합 ⊆ revision이 덮는 필드 집합"을 구조적으로
고정하는 테스트를 필수 목록에 추가해야 한다.

## B. 결론

```text
MISSION_ISSUANCE_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
```

**무단 durable mission을 만드는 실행을 하나도 구성하지 못했다.** 지정된 네 실행과 추가
14개 시나리오가 모두 차단된다. ABA도 revision 방식이 정확히 막는다. 원자성 경계는 실재하는
primitive로 구현 가능하며 lock 순환도 없음을 독립 확인했다.

정정이 필요한 것은 근거 서술(B-3)과 미정의 실패 모드(B-4)이며, 둘 다 계약 문장 수정으로
해소된다. B-3은 구조 테스트의 명세를 바꾸므로 구현 전에 고쳐야 한다.

---

# C. CAPABILITY SEMANTIC DESIGN ATTACK

## C-0. 먼저: 다섯 개념 분리는 지정된 공격 대부분을 막는다

프롬프트가 지정한 시나리오 중 다음은 계약이 정확히 차단한다.

| 시나리오 | 계약의 차단 지점 | 판정 |
|---|---|---|
| 장비는 지원한다는데 field evidence 없음 | §2.2 gateway observation은 promotion 권한 없음; §4.1(3-4) approval + qualification 필수 | ✅ |
| HIL 승인이 revoke됐는데 field evidence는 있음 | §6.7(1) 미해소 `BLOCKED/REVOKED`가 `QUALIFIED/APPROVED`보다 우선 | ✅ |
| HIL 승인됐으나 gateway가 현재 unavailable | §4.2(7) unexpired `REPORTED_AVAILABLE` 필요 | ✅ |
| capability A의 route evidence가 B를 승격 | §6.3(5) 별도 approver가 product approval을 결정 — 자동 승격 없음 | ✅ |
| vendor 문서가 field failure를 이김 | §6.7(3) 명시적 금지 | ✅ |
| 재시작 후 모순 evidence | §6.6(3) — 단, C-4 참조 | ⚠ |

또한 계약이 Codex 검토의 정정을 정확히 반영했다: §1.1 표가 DJI Gateway evidence의 persistence를
"없음"으로 적었고(`GatewayJournal`은 integration receipt만 저장 —
`dji-gateway/persistence/journal.py:17-100`), §6.4가 `BLOCKED`/`REVOKED` append에도 evidence를
요구한다(내 이전 감사의 C4 오류를 반복하지 않았다).

아래 두 건은 계약 **내부 모순**이며, 그 상태로 persistence를 설계하면 모순이 스키마로 굳는다.

---

## C-1 [BLOCKING] §7의 legacy 매핑이 §9와 모순된다 — actor 없는 레코드가 최고 권위 등급으로 승격된다

### 계약 내부 모순

- **§7 Public compatibility mapping 표**:
  `Core /capabilities.state=VERIFIED` → `ProductCapabilityApproval.APPROVED`
- **§9 Persistence 설계의 다음 입력**:
  "legacy memory-only state의 migration: durable evidence가 없으면 승격하지 않고
  `LEGACY_UNATTESTED` audit-only로 보존."

같은 legacy 값에 대해 §7은 `APPROVED`, §9는 `LEGACY_UNATTESTED`를 지시한다.

### 현재 저장소 동작이 §7을 더 나쁘게 만든다

`CapabilityRegistry.transition()`의 시그니처에는 **approver를 받는 인자가 없다**
(`capability/registry.py:115-146`: `capability_id, nxt, *, evidence, firmware, sdk, aircraft,
now, spike_evidence`). `SpikeEvidence`에 `operator` 필드가 있지만
(`spike_evidence.py:35-78`) 그것은 **시험을 수행한 사람**이지 승인한 주체가 아니다.

그런데 계약 §2.4는 `ProductCapabilityApproval`에 대해 다음을 요구한다.

> Approval authority: 인증된 human/release approval role. Gateway/device가 스스로 승격할 수
> 없다.
> Evidence authority: one or more qualified route evidence와 필요한 product/HIL evidence.

그리고 §6.1은 "Field operator: raw evidence 생산과 attestation 권위. **스스로 production
approval 불가**"라고 두 역할을 명시적으로 분리한다.

따라서 §7의 매핑은 **evidence producer만 기록된 actor-less 레코드를, producer와 분리된
approver를 요구하는 권위 등급으로 변환**한다. 이것이 프롬프트가 배제하라고 지정한
"compatibility mapping이 한 종류의 VERIFIED를 다른 authority class로 조용히 바꾸는" 경우다.

### 현재 도달 가능성

낮다 — Core registry는 메모리 전용이고 production 조립에 promotion 경로가 없어
`/capabilities`는 항상 빈 응답이다. 그러나 **이 매핑을 지금 확정하면 persistence 설계가
그것을 스키마로 굳힌다.** 그래서 blocking이다.

### 필요한 정정 (blocking)

§7의 해당 행을 두 갈래로 나눈다.

| Legacy 값 | 조건 | Internal semantic |
|---|---|---|
| Core `VERIFIED` | durable approval 레코드(approver·evidence set digest·support matrix·validity 포함)가 있음 | `ProductCapabilityApproval.APPROVED` |
| Core `VERIFIED` | 위 레코드 없음(현재의 모든 메모리 전용 상태) | `LEGACY_UNATTESTED` — audit-only, `/capabilities` 비노출 |

동시에 §2.4에 "approver identity는 `SpikeEvidence.operator`와 **다른 필드**여야 한다"를
명시한다.

---

## C-2 [BLOCKING] activation이 evidence revocation을 넘어 살아남는다 — §5 내부 모순

### 계약 내부 모순

- §5: "Verification이 새로 생겨도 activation은 **자동 ON되지 않는다**."
- §5: "Evidence revocation 또는 product approval revocation은 모든 관련 activation을 즉시
  **effective INACTIVE로 projection**한다. **config record를 삭제할 필요는 없다.**"
- §6.4: "activation OFF는 즉시 적용되며 evidence state는 그대로다."

revocation이 **projection만** 바꾸고 activation 레코드는 `ACTIVE`로 남는다면, 다음이 성립한다.

### 구체적 실행

```text
1. 운영자가 (org=O, site=S, route=R1) activation을 ACTIVE로 설정   ← 명시적 운영 결정
2. R1의 field evidence가 REVOKED (firmware regression 발견)
3. projection: effective INACTIVE   ← §5대로 즉시 차단, 여기까지는 옳다
4. 시간이 지나 새 evidence로 R1이 다시 QUALIFIED, product approval도 재승인
5. projection 재계산: activation 레코드가 여전히 ACTIVE이므로 → effective ACTIVE
6. 결과: **2번의 revocation 이후 아무도 다시 켜는 결정을 하지 않았는데 route가 열린다**
```

5번은 §5 첫 문장("Verification이 새로 생겨도 activation은 자동 ON되지 않는다")을 정면으로
어긴다. 계약이 activation을 "저장된 의도"로 두면서 revocation을 "일시적 projection 마스크"로
정의했기 때문에 발생하는 모순이다.

프롬프트의 "activation survives evidence revocation" 항목이 정확히 이 경우다.

### 필요한 정정 (blocking)

revocation이 activation **레코드 자체**에 미치는 효과를 명시한다. 권장:

> evidence 또는 product approval의 `REVOKED`는 영향받는 모든 activation 레코드를
> `SUSPENDED`로 **append**한다(삭제가 아니라 상태 전이). `SUSPENDED`에서 `ACTIVE`로의 복귀는
> 새 운영 결정을 요구하며, 재qualification만으로는 일어나지 않는다.

§2.5가 이미 `SUSPENDED` 상태를 정의하고 있으므로 새 개념이 필요 없다 — 그 상태를 이
전이의 목적지로 지정하기만 하면 된다.

---

## C-3 [REQUIRED CORRECTION] 9→5 매핑의 성질이 미정의다 — approval이 매핑 버전을 고정해야 한다

### 프롬프트의 질문에 대한 답

매핑은 다음이어야 한다.

| 성질 | 요구 | 이유 |
|---|---|---|
| injective | **아니오 (요구해서는 안 됨)** | 9개 PRD spike(`SPIKE-DJI-01…09`, `capability/registry.py:202-212`)와 5개 semantic capability(`AcquisitionCapability`, `Capability`)는 축이 다르다. 단사를 강요하면 존재하지 않는 1:1을 지어내게 된다 |
| many-to-one | **방향을 지정해야 함** | "product capability 하나가 **여러** route qualification을 요구한다"만 허용. "route qualification 하나가 여러 product를 **자동 만족**한다"는 금지(§6.3(5)의 별도 approver 요구와 정합) |
| versioned | **필수** | 아래 참조 |
| hardware-specific | **필수** | Gateway registry key가 이미 `(path, capability, hardware, firmware)`다(`dji-gateway/domain/capabilities.py:110-153`) |
| firmware-specific | **필수** | 동일. 단 C-5 참조 |
| evidence-scope-specific | **필수** | §2.3의 `test_build/policy_scope`까지 포함 |

### 미정의 지점 — 매핑 버전과 approval의 관계

§4.1(2)는 매핑이 "explicit, versioned, many-to-many"라고 하고, §2.4는 approval의 scope가
"product capability ID + supported route matrix + firmware/build/policy"라고 한다.
**두 곳에 route 집합이 존재한다** — 매핑 안에도, approval 안에도. 계약은 둘이 어긋날 때
무엇이 이기는지 말하지 않는다.

### 구체적 실행

```text
1. 매핑 v1: product P는 route {R1, R2}를 요구
2. approver가 P를 APPROVED — 그 시점 R1·R2 모두 QUALIFIED
3. 매핑 v2 배포: 운영 편의로 P의 요구 집합을 {R1}로 축소 (R2를 별도 product로 분리)
4. R2가 firmware regression으로 REVOKED
5. §4.1(4)는 "approval이 요구하는 모든 RouteEvidenceQualification"을 검사한다
   → **어느 버전의 요구 집합인가?**
      매핑 v2를 보면 {R1}만 확인 → P는 계속 노출된다
      approval의 matrix를 보면 {R1,R2} → P는 비노출된다
6. 전자를 택하면 매핑 편집 한 번이 기존 approval의 증거 요구를 사후적으로 약화시킨다
```

### 필요한 정정

> 각 `ProductCapabilityApproval`은 승인 시점의 **매핑 버전 ID를 고정(pin)하고 자신의
> required route matrix를 값으로 복사해 보관한다.** 이후 매핑 버전이 바뀌어도 기존 approval의
> 요구 집합은 변하지 않는다. 새 매핑 버전으로 넘어가려면 **새 approval**이 필요하다.

이는 `design_conformance_requests`가 work area 폴리곤을 **값으로 복사**하는 기존 관습과
동형이다(`app_assembly.py`: "설계 대비 요청이 이 저장소에서 폴리곤을 **값으로** 복사해
가므로"). 저장소에 이미 있는 패턴이라 새 개념이 아니다.

---

## C-4 [REQUIRED CORRECTION] firmware scope가 **장비 자기신고 문자열**로 선택된다

### 현재 저장소 동작

route qualification은 exact `(path, capability, hardware_model, firmware_version)`으로
조회된다(`dji-gateway/domain/capabilities.py:110-153`). 그 두 값을 `select()`에 넣는 것은
호출자다.

```python
# routing/capability_router.py:47-83
evidence = self._registry.require_verified_for(
    port.integration_path, capability,
    hardware_model=hardware_model,      # ← 인자
    firmware_version=firmware_version,  # ← 인자
)
```

값의 출처는 `RoutingContext.hardware_model` / `.firmware_version`
(`dji-gateway/coordinator.py:33-34`)이고, Core 쪽에서 같은 값을 실어 나르는 유일한 wire는
`CapabilityReceiptV1.hardware_model` / `.firmware_version`
(`acquisition/models.py:268-269`) — 즉 **gateway device가 자기 heartbeat에 적어 보내는
문자열**이다.

### 계약과의 충돌

- §6.5: "Route qualification: exact firmware/build scope가 바뀌면 **자동 non-applicable**."
- §2.2: gateway observation의 권위는 "**무엇을 보고했는가**"에만 있다.

두 문장을 합치면: **어떤 evidence가 자신에게 적용되는지를 검증 대상 장비가 스스로 고른다.**
프롬프트의 "old evidence survives a firmware change"가 바로 이 경로로 성립한다.

```text
1. R1이 firmware F1에서 QUALIFIED
2. 기체 펌웨어가 F2로 업그레이드됨
3. gateway가 (버그·설정 고정·의도적으로) 계속 F1을 보고
4. select(firmware_version="F1") → R1의 QUALIFIED evidence 적중 → route 사용 허가
5. F2에서 검증된 적 없는 동작이 승인된 것처럼 실행된다
```

§4.2(7)이 요구하는 "unexpired `REPORTED_AVAILABLE`"은 이를 막지 못한다 — 그 관측 자체가
같은 장비가 보낸 같은 snapshot이기 때문이다. 게다가 §4.2(7)은 "route가 current connectivity를
요구하면"이라는 조건부라, connectivity를 요구하지 않는 route는 **현재 firmware 사실을 전혀
확인하지 않는다.**

### 필요한 정정

계약이 firmware/hardware identity를 **별도의 authority 질문**으로 승격해야 한다. 최소한
다음 중 하나를 명시한다.

- (a) firmware/hardware identity는 attested fact로 취급한다 — 서명된 device attestation
  (저장소에 `DeviceAttestationRegistry`라는 out-of-band 공개키 등록 선례가 이미 있다:
  `services/core/src/ksi_core/device_attestation.py`)로 확인된 값만 scope 선택에 쓴다.
- (b) 자기신고 firmware는 scope 선택에 쓰되, 그 사실을 계약에 명시하고 route qualification의
  보증을 "장비가 신고한 firmware에 대한 검증"으로 **약하게** 서술한다.
- (c) firmware-scoped qualification을 사용하는 모든 route는 current observation을 **무조건**
  요구한다(§4.2(7)의 조건부를 제거).

어느 쪽이든, 지금처럼 "exact firmware scope가 안전을 보장한다"고 쓰면서 그 firmware를
피검증 주체가 정하게 두면 안 된다.

---

## C-5 [REQUIRED CORRECTION] §6.6(3)이 두 가지 서로 다른 실패 동작을 대안으로 제시한다

> revocation/supersession graph가 모순이거나 cycle이면 **startup fail-closed 또는** 해당
> capability를 **BLOCKED projection으로 격리**한다.

두 동작은 운영상 완전히 다르다.

- startup fail-closed: Core가 뜨지 않는다 — 이 저장소의 **모든** 다른 store가 replay 모순에
  대해 취하는 동작이다(`sites.py:22-28`, `edge_sync.py:315-320`,
  `equipment_support.py:199` 등).
- BLOCKED 격리: Core는 뜨고 그 capability만 비노출된다 — 이 저장소 최초의
  **replay-tolerant store**가 된다.

"또는"으로 남기면 구현자가 임의로 고르고, 그 선택이 곧 운영 계약이 된다. 하나를 정해야 한다.

**권장: 격리(isolate).** capability는 다른 원장과 달리 **Core 기동의 전제가 아니다**
(현재도 항상 빈 목록으로 정상 동작한다). 하나의 오염된 capability 때문에 현장·임무·이벤트
전체가 멈추는 것은 blast radius가 과하다. 다만 이 선택은 이 저장소의 기존 replay 규율에서
벗어나는 **의도적 예외**이므로, 그렇게 계약에 적고 이유를 남겨야 한다.

---

## C-6 [NON-BLOCKING] `/capabilities`의 의미 재정의가 무인증 표면 정책과 만나는 지점

§4는 `/capabilities`를 "product catalog operational eligibility"로 확정하고 firmware/SDK/raw
evidence를 계속 제외한다(`app.py:594-606` 근거). 이는 옳다.

다만 현재 이 엔드포인트는 **무인증 공개 표면**이고 계약 테스트의 allowlist에 올라 있다
(`tests/contract/test_api_contract_sync.py`의 `_UNAUTHENTICATED_ALLOWLIST`). 지금은 항상 빈
목록이라 공개해도 무해하지만, promotion이 구현되면 "이 제품이 어떤 DJI 기능을 검증했는가"가
무인증으로 열거 가능해진다. persistence 설계 단계에서 이 표면을 계속 무인증으로 둘지
재심사 항목으로 남길 것을 권한다. 지금 결정할 필요는 없다.

## C. 결론

```text
CAPABILITY_SEMANTIC_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
```

다섯 개념 분리와 authority 계층은 지정된 공격 대부분을 정확히 막는다. 그러나 C-1(§7↔§9)과
C-2(§5 내부)는 **계약 자신이 서로 반대되는 지시를 하는 지점**이고, 둘 다 "한 종류의
승인이 다른 권위 등급으로 조용히 바뀌는" 경로다. persistence 설계를 시작하기 전에
반드시 해소해야 한다 — 모순을 스키마로 굳히면 되돌리는 비용이 훨씬 커진다.

C-3(매핑 버전 고정)과 C-4(firmware 출처)는 persistence 입력 데이터의 형태를 결정하므로
역시 선행 결정이다. C-5는 한 문장 선택이다.

---

# D. IMPLEMENTATION ORDER REVIEW

## 제안된 순서

```text
1. Worker lease generation fencing + generation-scoped artifact storage
2. Mission issuance authorization witness + atomic commit
3. Capability canonical ID + explicit 9→5 mapping
4. Capability persistence/API/HIL promotion
```

## 판정: **순서를 바꿀 필요가 없다.** 다만 세 조건을 붙인다.

### D-1. 기술적 의존성은 없다

- Task 1과 Task 2는 서로 다른 store 집합을 건드리고 공유 primitive가 없다. Task 1은
  work store의 lease 레코드와 artifact key를, Task 2는 Site revision과 commit coordinator를
  다룬다.
- Task 1이 새로운 cross-store lock 중첩을 만들지 않으므로 Task 2의 lock-order 인벤토리에
  영향이 없다(§B-3의 인벤토리는 Task 1 전후로 동일).
- Task 3은 Task 4의 입력이며 이 의존은 계약이 이미 명시한다.
- Task 3/4는 Task 1/2와 독립이다.

### D-2. Task 1 내부의 순서는 계약이 정한 대로가 옳다

계약 §"구현 순서" 1번이 "generation-scoped artifact storage binding까지 **같은 안전 변경으로**
닫는다"고 한 것은 중요하다. fencing만 먼저 배포하고 storage binding을 나중에 하면
**A-1의 구멍이 그 기간 내내 열려 있다** — Core mutation은 fence되는데 늦은 PUT은 여전히
legacy 결정적 키에 착지한다. 분리 배포 금지를 계약에 유지해야 한다.

단, §A-1의 정정에 따라 **reader 전환이 writer 전환보다 먼저** 와야 한다(§4.5 step 1의
"reader 먼저" 원칙과 같은 이유).

### D-3. 심각도는 Task 2가 더 높다 — 순서는 유지하되 지연 금지

객관적으로 보면:

| | 결과 | 등급 |
|---|---|---|
| Task 2가 고치는 결함 | Site가 `SUSPENDED`인데 서명된 계약이 durable 원장에 존재 — **권위 위반** | 감사 P1(상단) |
| Task 1이 고치는 결함 | 중복 계산 + 원장 digest와 스토리지 바이트 불일치 가능 | 감사 P1(하단) |

Task 1을 먼저 두는 것은 여전히 합리적이다 — "네 store에 필드를 추가하고 replay를 확장하는"
패턴을 **lock 순서를 건드리지 않는 낮은 위험**에서 먼저 익히고, 그 다음 가장 뜨거운 쓰기
경로(Mission 발급)에 cross-store lock을 넣는 것이 안전하다.

다만 Task 2가 무기한 밀리면 더 심각한 결함이 더 오래 열려 있게 된다. **Task 1 완료와 Task 2
착수 사이에 다른 작업을 끼우지 않는다**는 조건을 붙일 것을 권한다.

### D-4. scale-out 활성화는 Task 1의 완료 조건이 아니다

계약 §4.9 step 6("worker replica 수를 2 이상으로 확대")은 §A-4(공유 `work_dir`)가 해소되기
전에는 실행할 수 없다. `work_dir` 격리를 Task 1 범위에 넣거나, step 6을 별도 후속 작업으로
분리해야 한다. **fencing이 끝났다는 이유로 replica를 늘리면 A-4의 교차 job 오염이 열린다.**

---

# E. TEST AND WARNING REVIEW

## E-1. 경고의 정체

설계가 보고한 "353 passed, 1 warning"의 경고를 재현·확인했다.

```text
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated;
  install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
```

독립 실행 결과(이 검토에서 직접 수행):

| 실행 집합 | 결과 |
|---|---|
| Codex 검토와 동일한 9개 파일 | `308 passed, 1 warning in 10.55s` |
| 위 + 설계가 인용한 6개 파일(worker/runner/core_client/mission_plans/mission_issuance/sites_api) | `524 passed, 1 warning in 14.98s` |

경고 건수가 테스트 수와 무관하게 **항상 정확히 1**이다. `fastapi/testclient.py` **import
시점**에 한 번 발생하는 모듈 수준 경고이기 때문이다. 따라서 353이든 308이든 524든 같은 경고
하나이며, 특정 테스트나 세 설계 중 어느 것과도 무관하다.

`pyproject.toml`에 `filterwarnings` 설정이 없음을 확인했다 — 이 경고가 예고 없이 실패로
승격될 경로는 없다.

## E-2. 분류

```text
WARNING_CLASSIFICATION = TECH_DEBT
```

**BENIGN이 아닌 이유**: 세 작업이 요구하는 신규 테스트가 거의 전부 HTTP barrier 테스트다
(worker lease의 동일 credential 경쟁, mission issuance의 signing barrier). 이들은 모두
`TestClient`를 쓰므로, 상류가 `httpx2` 이전을 강제하는 시점에 마이그레이션 대상이 **이번
작업으로 늘어난다.**

**IMPLEMENTATION_BLOCKER가 아닌 이유**: 현재 실패를 만들지 않고, 세 설계의 정합성이나
구현 가능성에 어떤 영향도 주지 않으며, `filterwarnings=error` 설정이 없어 우발적 CI 실패도
불가능하다.

**권장 처리**: 세 작업과 함께 고치지 않는다. 별도 의존성 정비 작업으로 분리하고, 그때
`TestClient` 사용처를 일괄 이전한다.

## E-3. 각 구현에 **선행 또는 동반**되어야 하는 최소 회귀 테스트

계약들의 테스트 목록(§4.8 10개, §8 13개, §8.2 12개)은 좋은 출발점이지만, 이 검토가 찾은
공격을 덮지 못하는 항목이 있다. 아래는 **추가**되어야 하는 최소 집합이다.

### Task 1 (worker lease) — 선행 5 + 동반 4

**선행(구현 전에 현재 동작을 고정)**

| # | 테스트 | 이유 |
|---|---|---|
| T1-1 | 같은 principal의 두 호출자가 같은 job을 `acquire_lease` → **둘 다 통과**함을 명시적으로 고정 | 현재 동작을 못 박아야 fencing 도입이 무엇을 바꾸는지 diff로 보인다 |
| T1-2 | artifact object key가 **저장되지 않고 5곳에서 재유도**됨을 구조적으로 고정 (§A-1의 5개 위치 인벤토리) | reader 전환 누락을 컴파일 타임 대신 테스트로 잡는다 |
| T1-3 | `_check_artifact_identity_locked`의 중복 판정이 **job 범위**임을 고정 | §A-3의 선택지를 바꿀 때 무엇이 깨지는지 드러난다 |
| T1-4 | `assert_succeeded_is_backed`가 job 전체 artifact를 본다는 것을 고정 | 동일 |
| T1-5 | 두 replica가 같은 `work_dir`에서 `all.zip`을 덮어쓰는 현재 동작 재현 | §A-4를 회귀로 만든다 |

**동반(구현과 같은 커밋)**

| # | 테스트 |
|---|---|
| T1-6 | §A-0의 5단계 stale 거부 전수 (heartbeat/upload/register/complete/fail/retry) — 네 store 전부 |
| T1-7 | **CLAIM 멱등성**: 같은 instance의 CLAIM 재전송이 generation을 올리지 않음 (§A-2) |
| T1-8 | generation-scoped 키에 등록된 artifact를 **다운로드·비교·설계대비·checkpoint 4경로가 모두 저장된 키로 읽음** (§A-1) |
| T1-9 | replay: generation 역행·누락 renewal·owner 변경 renewal 거부. **만료 판정은 검증 범위 밖임을 문서화**(§A-5) |

### Task 2 (mission issuance) — 선행 2 + 동반 5

**선행**

| # | 테스트 | 이유 |
|---|---|---|
| T2-1 | **lock 그래프 인벤토리**: `MissionStore`가 leaf임 + 8개 모듈의 Mission 호출이 전부 마지막임 (§B-3) | 계약의 틀린 서술을 올바른 성질로 대체 |
| T2-2 | `_notify_status_listeners`·`on_approved`·`site_lifecycle` 호출이 **store lock 밖**임을 고정 | coordinator의 `Site → WorkOrder` 순서를 안전하게 만드는 load-bearing 성질인데 현재 무보호 |

**동반**

| # | 테스트 |
|---|---|
| T2-3 | contract-only / pair 두 endpoint에서 signing barrier 중 `SUSPENDED` 전이 → append 0, typed 409 |
| T2-4 | Site `A→B→A`(예: `PATROL_READY→PATROL_ACTIVE→PATROL_READY`) → status는 같아도 revision conflict |
| T2-5 | **witness 완전성**: `precheck_issuance`가 읽는 Site 필드 ⊆ revision이 덮는 필드 (§B-6) |
| T2-6 | acquisition witness: snapshot TTL 만료 시 §B-4에서 택한 동작이 실제로 그것임 |
| T2-7 | 비교 통과 후 append 전 전이 시도가 실제로 commit lock에 직렬화됨 (barrier 테스트) |

### Task 3 (capability semantic) — 동반 4

| # | 테스트 |
|---|---|
| T3-1 | legacy Core `VERIFIED`(durable approval 없음)가 `LEGACY_UNATTESTED`로 매핑되고 `/capabilities`에 노출되지 않음 (§C-1) |
| T3-2 | evidence revocation → activation `SUSPENDED` → 재qualification만으로 `ACTIVE`로 복귀하지 않음 (§C-2) |
| T3-3 | 매핑 버전 v2 배포가 v1로 승인된 approval의 required route 집합을 바꾸지 않음 (§C-3) |
| T3-4 | 9→5 매핑의 누락·중복·unknown ID·cycle이 fail-closed (계약 §8.2 test 12 유지) |

### Task 4 (capability persistence) — 계약 §8.2의 12개를 그대로 유지하되, C-4/C-5 결정을 반영한 항목 2개 추가

| # | 테스트 |
|---|---|
| T4-1 | firmware scope 선택 값의 출처가 §C-4에서 택한 authority를 따름 |
| T4-2 | replay 모순 시 §C-5에서 택한 동작(기동 거부 또는 격리) 하나만 일어남 |

---

# 최종 결과

```text
DESIGN_ADVERSARIAL_REVIEW      = PASS_WITH_REQUIRED_CORRECTIONS

WORKER_LEASE_DESIGN_REVIEW     = PASS_WITH_REQUIRED_CORRECTIONS
MISSION_ISSUANCE_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
CAPABILITY_SEMANTIC_DESIGN_REVIEW = PASS_WITH_REQUIRED_CORRECTIONS
```

## 1. 구현 전 blocking corrections

전부 **계약 문서 수정**이며 재설계나 새 아키텍처가 필요 없다.

| # | 대상 | 내용 |
|---|---|---|
| B1 | Worker §4.4, §4.9, Adoption | **A-1** artifact object key를 저장하고 5개 소비처(`processing_jobs.py:2700`·`:2708`, `checkpoint_validations.py:872-875`, `comparison_requests.py:1219`, `design_conformance_requests.py:1986`)를 전부 전환. `auxiliary_files` 키 포함. reader 전환을 writer보다 먼저. `processing_jobs.py:1205`의 "키는 저장하지 않고 유도한다" 규약을 `REPLACE`로 등재 |
| B2 | Worker §4.1(3), §4.4, §4.6 | **A-2** 같은 instance가 active lease를 쥔 상태의 `CLAIM`은 generation을 올리지 않고 현재 값을 재반환(멱등). generation 증가 조건을 "소유 instance 변경 또는 직전 lease 만료"로 좁힘 |
| B3 | Worker §4.4 | **A-3** artifact identity와 `assert_succeeded_is_backed`의 범위를 generation-scoped로 할지 명시. generation-scoped를 택하면 완료 판정은 **완료를 주장하는 generation의 artifact만** 본다고 못 박음. job-scoped를 유지하면 부분 등록 후 회수가 영구 실패함을 수용 결과로 기술 |
| B4 | Worker §4.9, §5 | **A-4** replica>1의 전제조건으로 `work_dir` 격리(`work_dir/{instance}/{job}/`)를 명시. 격리 전 scale-out 금지 |
| B5 | Capability §7, §2.4 | **C-1** legacy Core `VERIFIED`를 durable approval 유무로 두 갈래로 나누고, approver identity가 `SpikeEvidence.operator`와 다른 필드임을 명시 |
| B6 | Capability §5 | **C-2** revocation이 activation 레코드를 `SUSPENDED`로 전이시키고, 재qualification만으로 `ACTIVE`로 돌아가지 않음을 명시 |

## 2. Non-blocking improvements

| # | 대상 | 내용 |
|---|---|---|
| N1 | Worker §4.1(6) | **A-5** replay equivalence를 "generation 단조성·소유 일치·high-water"로 한정. 만료 판정은 replay 범위 밖임을 명시 |
| N2 | Worker §2.C | **A-6** `worker_instance_id`의 보증을 "우발적 동일시 제거"로 좁혀 서술 |
| N3 | Worker §4.7 | orphan NodeODM task 계측 추가. generation의 int64 wire 범위 명시 |
| N4 | Worker §4.4 | design-conformance diff-raster에도 generation-scoped binding을 적용하는지 명시 |
| N5 | Mission §5.1 | **B-3** lock 인벤토리 서술을 "MissionStore leaf" 성질로 교체 |
| N6 | Mission §6.4 | **B-5** commit 거부 시 선행 `ensure_run`이 durable하게 남고 멱등 재사용됨을 명시 |
| N7 | Capability §4.1(2), §2.4 | **C-3** approval이 매핑 버전을 pin하고 required route matrix를 값으로 복사 |
| N8 | Capability §6.5, §4.2(7) | **C-4** firmware/hardware identity의 authority를 (a)(b)(c) 중 하나로 확정 |
| N9 | Capability §6.6(3) | **C-5** "기동 거부 또는 격리"에서 하나를 택함(격리 권장 + 예외 사유 기록) |
| N10 | Capability §4 | **C-6** promotion 구현 후 `/capabilities` 무인증 유지 여부를 재심사 항목으로 등재 |

## 3. 필수 선행 테스트

§E-3 표 참조. **구현 전에 반드시 먼저 들어가야 하는 것은 7개다.**

- Task 1: T1-1(같은 principal 이중 lease 통과 고정), T1-2(artifact key 5개 소비처 인벤토리),
  T1-3·T1-4(identity/backing 범위 고정), T1-5(공유 `work_dir` 충돌 재현)
- Task 2: T2-1(lock 그래프 leaf 성질), T2-2(listener·lifecycle이 lock 밖임)

나머지는 구현과 같은 커밋에 동반한다.

## 4. 외부 증거가 필요한 가정

| # | 가정 | 필요한 증거 |
|---|---|---|
| X1 | **§B-4**: 경로 생성 + KMZ 빌드 + 서명이 acquisition snapshot의 5분 TTL 안에 끝난다 | 실제 AOI 크기 분포에서의 `build_mission_plan` 소요 시간 실측. 이 값이 TTL에 근접하면 §B-4의 (a)안이 필수가 된다 |
| X2 | **§A-4**: 현재 배포가 worker를 2개 이상 운영한 적이 있는가 | 운영 기록. Codex 검토와 동일하게 저장소만으로는 확인 불가. 결함 성립 조건은 아니고 긴급도에만 영향 |
| X3 | **§B-4, §C-4**: `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=true`인 배포가 있는가 | 배포 설정. false이면 두 항목의 현재 노출은 0이다 |
| X4 | **§A-1**: Mission journal fsync 지연 분포 | commit lock 보유 시간의 상한. Site 전이 지연 허용치 판단에 필요 |
| X5 | Capability 전반 | 실제 HIL/field evidence. 이 검토는 코드가 증거를 **어떤 의미로 받아들이는지**만 판정했다 |

## 5. TASK 1을 즉시 시작해도 되는가

**코딩은 아직 안 된다. 계약 수정 후 즉시 시작할 수 있다.**

- B1·B2·B3·B4는 전부 **Task 1의 계약 문장**이고, 넷 다 "구현 중에 정하면 되는 세부"가
  아니다. 특히 B3(artifact identity 범위)은 어느 쪽을 택하느냐에 따라 journal 레코드 형태와
  `assert_succeeded_is_backed`의 시그니처가 달라지므로, 코드를 쓰기 시작한 뒤 결정하면 되돌리는
  비용이 크다.
- B1은 변경 대상 파일 수를 1개 모듈에서 4개 모듈로 바꾼다 — 작업 크기 산정 자체가 달라진다.
- 이 네 건은 **문서 수정 작업**이며 새로운 조사가 필요 없다(근거 위치가 이 문서에 전부
  적혀 있다). 반나절 수준이다.
- 그 뒤 T1-1 ~ T1-5의 선행 테스트를 먼저 넣고 구현에 들어가면 된다.

Task 2는 B5/B6와 무관하므로 Task 1과 동일한 조건(N5 서술 정정 + T2-1·T2-2 선행 테스트)에서
착수 가능하다. Task 3은 C-1·C-2 모순 해소가 곧 그 작업의 내용이므로 지금 착수해도 된다.
**Task 4(capability persistence)만은 C-1·C-2·C-3·C-4·C-5가 전부 닫히기 전에 시작하면 안 된다.**

---

## 부록 — 이 검토가 수행한 것과 하지 않은 것

**수행**
- 세 계약이 인용한 코드 위치를 전수 재확인. 인용이 틀린 곳은 §B-3 하나였다(결론은 유지).
- 계약이 인용하지 않은 인접 경로 추적: artifact key 소비처 5곳, store lock 그래프 8개 모듈,
  WorkOrder listener 발화 위치 3곳, worker `work_dir` 사용 4곳, firmware 값의 출처 2단계.
- 테스트 2회 실행(308 passed / 524 passed, 각 1 warning) 및 경고 원인 확정.
- 프롬프트가 지정한 A 15개·B 14개·C 9개 시나리오를 각각 계약 조항에 대조.

**하지 않음**
- 제품 코드·계약·테스트·배포 설정 수정. 생성 파일은 이 문서 하나다.
- 기존 dirty 파일의 stage·commit·revert·정리.
- 실장비/HIL, 부하·경합 실측, 경로 생성 시간 측정(§X1), 운영 로그 조회(§X2, §X3).
- 대안 아키텍처 제안 — 세 계약이 택한 방향(generation fencing / witness OCC / 5개념 분리)은
  전부 적절하다고 판단했고, 반론은 그 방향 **안에서의** 결함으로 한정했다.
