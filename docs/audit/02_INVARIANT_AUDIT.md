# 불변식 감사 (읽기 전용)

> 작성 2026-09-01 · 기준 커밋 `41d9f55` + uncommitted civil-readiness WIP
> 선행 문서: `docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT.md`,
> `docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT_CODEX_REVIEW.md`
> (`ARCHITECTURE_AUDIT_REVIEW = VERIFIED_WITH_CORRECTIONS`)
>
> **번호 규약**: 이 문서는 `INV-A01…`을 쓴다. 제품 도메인 불변식
> (`docs/product/DOMAIN_INVARIANTS.md`의 `INV-001…INV-06x`)의 번호 공간을 침범하지
> 않기 위해서다. 각 항목은 대응하는 제품 INV를 본문에 명시한다.
>
> **원칙**: 실행 코드가 정본이다. 문서·주석·테스트는 증거이되 의도를 정의하지 않는다.
> 관례와 다르다는 이유만으로 결함으로 분류하지 않았다. 저장소만으로 확인 불가한 것은
> `NEEDS_EXTERNAL_EVIDENCE`로 남겼다.
>
> **작업 트리**: 시작 시점에 이미 dirty였다(`.ai/*`, `.ksi/*`, Phase Registry,
> civil acceptance, Core 조립/계약/Dashboard의 civil-readiness WIP). 어느 것도
> 되돌리거나 stage·정리하지 않았다. 제품 코드는 수정하지 않았다.

---

## 목차

- [A. 영속 상태 불변식](#a-영속-상태-불변식) — INV-A01…A08
- [B. 멱등·순서 불변식](#b-멱등순서-불변식) — INV-A09…A10
- [C. 생애주기·상태기계 불변식](#c-생애주기상태기계-불변식) — INV-A11…A13
- [D. 권한·소유권 불변식](#d-권한소유권-불변식) — INV-A14…A19
- [E. 산출물·파일 불변식](#e-산출물파일-불변식) — INV-A20…A21
- [F. Capability 불변식 (전용 분석)](#f-capability-불변식-전용-분석) — INV-A22…A24
- [G. 설정 복원 불변식](#g-설정-복원-불변식) — INV-A25
- [H. 컴포넌트 간 불변식](#h-컴포넌트-간-불변식) — INV-A26…A27
- [Capability 증거·승격 전용 질의 6문](#capability-증거승격-전용-질의-6문)
- [최종 요약](#최종-요약)

---

# A. 영속 상태 불변식

## INV-A01 — 쓰기 성공은 fsync 이후에만 반환된다

### Invariant

`append`가 정상 반환했다면 그 레코드는 디스크에 완결된 줄로 존재한다. 반환 전에
파일 fsync가, 파일이 새로 생성된 경우 부모 디렉터리 fsync까지 끝나 있다.

### Why this invariant exists

Edge는 ACK를 받은 항목을 로컬에서 지운다(`packages/event-contracts/src/ksi_event_contracts/offline_sync.py:20-23`).
ACK 후 서버가 잃으면 그 관측은 세상에서 사라진다.

### Evidence

- `services/core/src/ksi_core/durable_journal.py:340-378` `_append_durable` —
  POSIX short-write 루프(`:360-370`), `os.fsync(fd)`(`:371`), 신규 생성 시
  `_fsync_dir(self._path.parent)`(`:377`).
- `services/core/src/ksi_core/durable_journal.py:82-89` `_fsync_dir`.
- `services/core/src/ksi_core/edge_sync.py:592-628` — `EdgeSyncStore._append_durable`가
  동형으로 구현(별도 클래스, 같은 규약).
- 직렬화 규약: `ensure_ascii=True`(U+2028 등 유니코드 개행이 줄 분리를 깨는 경로 차단),
  `allow_nan=False`(`durable_journal.py:344-349`).

### Enforcement paths

`DurableJournal.append` 하나가 유일한 쓰기 경로다. 30개 도메인 store 전부 이 메서드를
통해서만 기록한다(`services/core/src/ksi_core/app_assembly.py`의 `journal(...)` 팩토리).
`EdgeSyncStore`만 자기 구현을 갖는다.

### Potential bypass paths

없음. `_WRITE = os.write` 모듈 상수(`durable_journal.py:67`)는 fault injection 테스트
전용 대체 지점이며 프로덕션 경로를 우회하지 않는다.

### Restart/recovery behavior

미완결(개행 없는) 꼬리는 "기록된 적 없음"으로 취급되어 잘린다 → INV-A04.

### Existing tests

`tests/contract/test_durable_journal.py:65` (durable-before-return),
`:201` (short write not silently accepted), `:285` (parent dir fsync),
`:311` (U+2028 payload survives restart), `:259` (NaN rejected+seals).

### Missing tests

없음 — 이 불변식은 fault injection까지 포함해 충분히 고정돼 있다.

### Classification

VERIFIED

### Failure consequence

P0 — 현장 관측의 비가역 유실.

### Recommended next investigation

없음.

---

## INV-A02 — 하나의 journal 파일에는 writer가 하나뿐이다

### Invariant

같은 journal 파일에 대해 프로세스 간에는 `flock` 배타 잠금이, 프로세스 내부에서는
인스턴스 `threading.Lock`이 단일 writer를 보장한다.

### Why this invariant exists

두 writer가 같은 append-only 파일에 쓰면 재생 순서가 곧 원장의 의미인 이 설계
(`durable_journal.py:203-208`)에서 상태가 조용히 갈라진다.

### Evidence

- `services/core/src/ksi_core/durable_journal.py:91-116` `_acquire_writer_lock` —
  `fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)`, 실패 시 `JournalRecoveryError`로 기동 거부.
- `durable_journal.py:169-177` — 생성자가 lock → recover 순서로 진행하고, recover가
  실패하면 `_release_writer_lock()` 후 재던진다(잔존 flock 방지).
- 프로세스 내부: `append`/`replay`/`close` 전부 `with self._lock:`(`:300`, `:311`, `:441`).
- 배포 수준: `Dockerfile:57` CMD에 `--workers` 없음, `deploy/compose.yaml`에 Core
  replica 선언 없음.

### Enforcement paths

모든 store 생성자가 `DurableJournal`을 통해 잠금을 잡는다.
`tools/enforce_retention.py:77-81`은 이 규약을 알고 있다 — `--execute`는 writer 잠금을
잡고(따라서 Core 정지 필요), dry-run만 `open_read_only`를 쓴다.

### Potential bypass paths

**두 개를 확인했다.**

1. **`DurableJournal.open_read_only`(`:132-156`)는 flock을 잡지 않는다.** 이는 의도된
   설계이고(dry-run이 서버 정지를 요구하면 아무도 안 본다), 쓰기는 영구 봉인
   (`_sealed_reason = "read-only"`, `:151`)으로 막혀 있다. 단일 writer 자체는 깨지지
   않는다. 다만 **읽기 일관성**에는 별도 구멍이 있다 → INV-A06.
2. **`EventStore`는 예외 시 `self._journal.close()`로 봉인한다**
   (`services/core/src/ksi_core/events.py:1145`, `:1369`). `DurableJournal.close()`는
   봉인과 **동시에 flock을 해제한다**(`durable_journal.py:439-453` →
   `_release_writer_lock`). 즉 events.jsonl에 대해서만, 프로세스가 살아 있는 동안
   프로세스 간 잠금이 사라진다. 다른 30개 store는 `journal.close()`를 **생성자 실패
   경로에서만** 호출하므로(예: `sites.py:249`, `processing_jobs.py:896`) 이 형상이
   없다 — events.py가 유일한 런타임 봉인 사용처다.

### Restart/recovery behavior

`__init__` 재생 실패 시 잠금을 반드시 해제해(`durable_journal.py:171-176`) 재시도가
"다른 프로세스가 소유 중"으로 오도되지 않는다. `__del__`(`:455`)은 최후 방어.

봉인 후 `/ready`는 503을 반환한다 — `app_assembly.py:631-645`가 `opened` 목록의
`sealed_reason`을 보고, events journal은 `production.py:556-559`의 팩토리를 거쳐
`opened`에 들어간다. 따라서 오케스트레이터가 재시작을 유도한다(구멍 2의 실질 완화).

### Existing tests

`tests/contract/test_durable_journal.py:234` (두 번째 인스턴스 거부),
`:112` (재생 실패가 잠금을 푼다), `:502` (read-only가 writer와 공존),
`:557` (read-only close가 남의 잠금을 풀지 않는다),
`tests/contract/test_edge_sync_ingest.py` (두 번째 프로세스 writer 거부),
`tests/contract/test_production_assembly.py` (두 앱 조립에 서로 다른 data dir 필요).

### Missing tests

`EventStore`가 예외로 봉인한 뒤에도 events.jsonl의 writer 잠금이 유지되는지(또는
"해제됨이 의도"라는 것이 고정돼 있는지)를 확인하는 테스트가 없다.

### Classification

PARTIALLY_VERIFIED
(프로세스 간·스레드 간 잠금 자체는 VERIFIED. 배포 수준 단일 노드 가정은
`INTENTIONAL_SINGLE_NODE_ASSUMPTION` — ADR-KSI-008 §138-140이 다중 인스턴스를 DB 전환
trigger로 명시. events 봉인의 잠금 해제만 미검증 표면.)

### Failure consequence

P2 — 봉인된 Core가 메모리 projection으로 읽기를 계속 서비스하는 동안 제2 writer
(예: `enforce_retention.py --execute`)가 events.jsonl에 append할 수 있다. 그 상태에서
Core의 읽기 뷰는 journal과 갈라진다. `/ready` 503이 재시작을 유도하므로 창은 좁고,
쓰기는 이미 전부 실패하므로 원장 손상은 아니다.

### Recommended next investigation

`DurableJournal`에 "잠금은 유지한 채 봉인"하는 명시적 API(`seal(reason)`)가 필요한지
검토. `close()`의 두 책임(봉인+자원 해제)이 분리되면 events.py는 의도한 쪽만 부를 수 있다.

---

## INV-A03 — 재생은 실시간 경로와 같은 게이트를 다시 태운다

### Invariant

기동 시 journal 재생은 live 경로와 **동일한 판정 함수**를 사용하고, 하나라도
거부되면 기동 자체를 거부한다. journal을 손으로 고쳐 게이트를 우회할 수 없다.

### Why this invariant exists

재생 로직과 실시간 로직이 갈라지면, 원장 조작이 곧 게이트 우회 경로가 된다.

### Evidence

- `services/core/src/ksi_core/edge_sync.py:315-320` — 재생이 `self._ledger.ingest(entry)`를
  그대로 다시 부르고 `ACCEPTED`가 아니면 `StoreRecoveryError`.
- `services/core/src/ksi_core/processing_jobs.py:50-55` — "재생도 live와 같은 전이표를
  다시 태운다"; `:1078-1101` 산출물 계보 앵커를 재생에서 재확인.
- `services/core/src/ksi_core/sites.py:252-270` `_replay` — 미지 `kind`·참조 무결성
  위반·기록된 `before`와 현재 projection 불일치·불법 전이 전부 `SiteStoreRecoveryError`.
- `services/core/src/ksi_core/source_media.py:28-36` — `compare_measurements`가 live와
  재생의 공유 SSOT.
- `services/core/src/ksi_core/design_conformance_reports.py:39-46` — 재생은 바이트를 다시
  읽지 않는 대신 journal에 남긴 `coreRecomputedDigest`를 대조한다(기동이 오브젝트
  스토리지 가용성에 묶이지 않게).
- `services/core/src/ksi_core/edge_dispatch.py:282-353` `_replay` — 중복 dispatchId,
  존재하지 않는 activation, 미래 receipt, TTL 이탈, flight-start의 activation 선행조건을
  전부 재검증.

### Enforcement paths

각 store의 `_replay`. 전부 생성자에서 호출되고, 실패는 조립 실패 → 프로세스 기동 거부.

### Potential bypass paths

없음. 단, **재생이 현행 게이트로 과거 레코드를 판정한다**는 성질에 알려진 대가가 있다
→ INV-A08.

### Restart/recovery behavior

이 불변식 자체가 재시작 동작의 정의다.

### Existing tests

`tests/contract/test_durable_journal.py:106,134,144` (오염 거부),
`tests/replay/test_replay_determinism.py` (동일 입력 → 동일 fingerprint/hash/transitions),
`tests/contract/test_edge_sync_ingest.py`, `tests/contract/test_sites_api.py`,
`tests/contract/test_processing_jobs.py`.

### Missing tests

없음(각 store별로 재생 거부 테스트가 존재).

### Classification

VERIFIED

### Failure consequence

P1 — 원장 조작이 게이트 우회 경로가 된다.

### Recommended next investigation

없음.

---

## INV-A04 — torn tail은 "기록된 적 없음"과 동치다

### Invariant

개행 없이 끝난 마지막 부분 줄은 ACK된 적이 없으므로 잘라내고 정상 기동한다.
단, **봉인된 세그먼트**의 부분 줄은 설명 불가능한 상태이므로 기동을 거부한다.

### Evidence

- `services/core/src/ksi_core/durable_journal.py:257-286` — 활성 파일은 truncate+fsync,
  봉인 세그먼트(`tolerate_torn_tail=False`)는 `JournalRecoveryError`(`:263-268`).
- `durable_journal.py:210-214` — 봉인 세그먼트에 부분 줄이 있을 수 없는 근거(회전은
  fsync 완결 후에만, rename은 원자적).
- `edge_sync.py:322-336` — 같은 규약 + 오프셋 기반 truncate
  (`resume_at + len(raw) - len(tail)`, 스냅샷 재생과 정합).
- truncate 실패도 `JournalRecoveryError`로 감싼다(`durable_journal.py:283-289`) —
  raw `OSError` 누출 없음.

### Enforcement paths

`_read_records`(활성/세그먼트 분기) · `EdgeSyncStore._recover`.

### Potential bypass paths

`open_read_only`는 truncate하지 않고 완결 줄까지만 본다(`:151`, `:271-276`) — 읽기
전용 소비자에게 정확한 뷰이며 우회가 아니다.

### Restart/recovery behavior

ENOSPC 부분 쓰기 후에도 서버가 뜬다. 해당 항목은 Edge 재전송으로 복구된다
(`edge_sync.py:324-327`).

### Existing tests

`tests/contract/test_durable_journal.py:85`, `:151`, `:449`,
`tests/contract/test_durable_journal.py:527` (read-only는 truncate하지 않는다).

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P2 — 이 처리가 없으면 부분 쓰기 한 번이 서버를 영구 기동 불가로 만든다.

### Recommended next investigation

없음.

---

## INV-A05 — append 중 임의 예외는 원장을 봉인한다

### Invariant

`append` 도중 발생한 **어떤** 예외(`BaseException` 포함)도 journal을 봉인하고
이후 모든 append를 거부한다. "디스크에 없는데 성공처럼 보이는" 상태를 만들지 않는다.

### Evidence

- `services/core/src/ksi_core/durable_journal.py:311-336` — `except BaseException`으로
  `_sealed_reason` 설정 후 `JournalSealedError` 재던짐.
- `durable_journal.py:317-327` — `deepcopy`가 `try` **안**에 있는 이유가 주석에 명시:
  durable 성공 후 메모리 반영 실패(RecursionError)도 봉인으로 승격해 "디스크에는 있는데
  메모리에 없는" 불일치를 fail-closed로 드러낸다.
- `edge_sync.py:560-578` — `OSError`와 그 밖의 `BaseException`을 모두 봉인.
- 봉인 표면화: `app_assembly.py:631-645` `/ready` 503.

### Enforcement paths

`DurableJournal.append`, `EdgeSyncStore.ingest_event_bundle`.
각 store는 `JournalSealedError`를 잡아 typed `STORE_UNAVAILABLE`(503 + `Retry-After`)로
변환한다(예: `processing_jobs.py:1730-1734`).

### Potential bypass paths

`EventStore`는 append **밖**의 예외를 `close()`로 봉인한다 → INV-A02 구멍 2.
봉인 자체는 성립하며 잠금 해제만 부수효과다.

### Restart/recovery behavior

봉인은 프로세스 수명 내내 유지된다. 재시작만이 해제 경로다(의도).

### Existing tests

`tests/contract/test_durable_journal.py:177`, `:259`, `:246`.

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P0 — 봉인이 없으면 재전송이 `DUPLICATE_IGNORED`(=ACK)로 둔갑해 유실이 확정된다
(`edge_sync.py:560-563`이 이 시나리오를 명시).

### Recommended next investigation

없음.

---

## INV-A06 — 세그먼트 회전은 순서를 보존하고 아무 것도 잃지 않는다

### Invariant

회전 후에도 재생 결과는 회전 전과 동일한 순서·동일한 집합이다. 회전 실패는 데이터를
손상시키지 않으며 봉인 사유가 아니다.

### Evidence

- `services/core/src/ksi_core/durable_journal.py:379-412` `_rotate_if_needed` —
  `os.rename`(같은 디렉터리 원자적) + `_fsync_dir`, 실패는 warning 후 다음 append에서 재시도.
- `durable_journal.py:203-215` `_recover` — 세그먼트 번호 오름차순 → 활성 파일 순.
- `durable_journal.py:187-201` `_existing_segments` — `.lock` 파일과 사람이 만든 동명
  파일을 정규식으로 배제.
- 임계 초과 **후** 검사(`:384-388`) — 한 레코드가 임계보다 커도 한 세그먼트에 온전히 담긴다.

### Enforcement paths

`append` 성공 직후에만 호출(`durable_journal.py:336-338`).

### Potential bypass paths

**읽기 전용 재생과 회전의 경합(실제 구멍).** `_recover`는 (1) 세그먼트를 glob해 읽고
(2) 활성 파일을 읽는다. (1)과 (2) 사이에 writer가 회전하면, 옛 활성 파일은 glob되지
않은 새 세그먼트가 되고 reader는 거의 빈 새 활성 파일만 읽는다 → **최대 한 세그먼트
분량(기본 64 MiB)의 레코드가 조용히 누락**된다.
영향 범위: `open_read_only`를 쓰는 두 소비자뿐이다 —
`tools/enforce_retention.py:81`(dry-run)과 `tools/retention_scheduler.py:75`.
누락 방향은 "덜 만료로 판정"이라 **삭제가 과다해지지 않는다**(안전한 방향).
`--execute`는 writer 잠금을 잡으므로(Core 정지 전제) 이 경합이 없다.

### Restart/recovery behavior

`test_segment_numbering_continues_after_restart`가 재시작 후 번호 연속을 고정한다.

### Existing tests

`tests/contract/test_durable_journal.py:364` (회전 후 재생 순서 보존),
`:383` (기본 OFF), `:393`, `:417`, `:432`, `:470` (회전 실패가 봉인하지 않는다),
`:544` `test_read_only_sees_rotated_segments` — **단, writer를 닫은 뒤에 reader를 연다**
(순차 시나리오). 동시 회전 창은 테스트되지 않는다.

### Missing tests

writer가 회전하는 동안 `open_read_only` 재생이 레코드를 잃지 않는지(또는 잃는 것이
수용된 동작인지) 고정하는 테스트.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P2 — 보관 정책 dry-run/스케줄러 보고가 조용히 과소 보고된다. 삭제는 안전한 방향으로
치우치므로 데이터 손실은 아니다.

### Recommended next investigation

`_recover`가 활성 파일을 먼저 열어 fd를 잡은 뒤 세그먼트를 glob하도록 순서를 바꾸면
누락이 중복(양성)으로 바뀌는지, 아니면 회전 세대 번호를 확인하는 재시도 루프가
필요한지 설계 검토.

---

## INV-A07 — 스냅샷은 journal이 부정하는 것을 주장할 수 없다

### Invariant

edge-sync 스냅샷이 손상·규칙 위반이면 버리고 전량 재생한다(결과 동일, 느릴 뿐).
반대로 journal 쪽이 스냅샷 경계와 어긋나면(짧아졌다·앞부분이 바뀌었다·건수가 다르다)
기동을 거부한다.

### Why this invariant exists

append-only 파일이 줄어드는 것은 설명되지 않는 상태다. 그대로 재생하면 두 정본이
조용히 갈라진 원장으로 서비스가 뜬다.

### Evidence

- `services/core/src/ksi_core/edge_sync.py:341-360` (신뢰 방향 규약),
  `:354-448` `_load_snapshot`, `:449-498` `_write_snapshot`.
- `edge_sync.py:181-217` — `_snapshot_digest`, `_hash_prefix(path, through)`
  (스냅샷 경계까지의 바이트 해시 대조).
- 스냅샷 쓰기는 ACK 이후의 관심사이며 실패해도 `ACCEPTED`를 취소하지 않는다
  (`edge_sync.py:585-598`).
- `snapshot_every=None`(기본)이어도 **이미 있는 스냅샷 파일은 읽는다** — 안전한 쪽.

### Enforcement paths

`EdgeSyncStore._recover` → `_load_snapshot` → 오프셋 재생.

### Potential bypass paths

스냅샷을 무시하고 전량 재생으로 검증하려면 파일을 치워야 한다(문서화된 운영 절차,
`edge_sync.py:44-47`).

### Restart/recovery behavior

이 불변식이 곧 재기동 비용 관리 장치다. edge-sync는 회전이 아니라 스냅샷을 쓴다
(재기동 비용이 파일 크기가 아니라 항목당 정규화+sha256이므로).

### Existing tests

`tests/contract/test_edge_sync_ingest.py` (스냅샷 경계 불일치 기동 거부 포함).

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P1 — 두 정본이 갈라진 원장으로 기동.

### Recommended next investigation

31개 원장 중 스냅샷을 가진 것은 edge-sync 하나뿐이다. 나머지의 cold-start 비용은
측정된 적이 없다 → Codex 검토의 "journal 규모·복구 benchmark" 과제와 동일.

---

## INV-A08 — 재생은 **현행** 게이트로 **과거** 레코드를 판정한다

### Invariant

게이트를 조이면, 그 조임 이전에 기록된 레코드가 재생에서 거부되어 기동 불가가 될 수
있다. 이는 INV-A03의 필연적 대가이며 "느슨하게 재생"은 해답이 아니다.

### Why this invariant exists

재생을 느슨하게 하는 순간 원장 조작이 게이트 우회 경로가 된다(INV-A03).

### Evidence

- `services/core/src/ksi_core/equipment_support.py:35-45` — 이 대가가 코드 주석으로
  명시돼 있고 첫 사례("동일 단계 재선언에도 증거 필수")까지 기록돼 있다.
  실운영 원장이 생긴 뒤 조일 때는 레코드에 게이트 버전을 남기거나 재생 실패 메시지에
  마이그레이션 절차를 넣어야 한다고 적혀 있다.
- `services/core/src/ksi_core/edge_dispatch.py:289-300` — 반대 사례: 봉투는 **저널 원문
  그대로** 보관하고 모델은 검증에만 쓴다. 재덤프하면 서명 대상 바이트가 바뀌어 과거
  발행분 전부가 장비에서 `INVALID_DISPATCH_SIGNATURE`가 된다.
- `edge_dispatch.py:282-353` — 재생은 **현재 risk policy pack / runtime profile
  registry를 대조하지 않는다.** 따라서 설정 변경이 기동을 깨뜨리지 않는다(의도적 설계).

### Enforcement paths

각 store의 `_replay`.

### Potential bypass paths

해당 없음(이것은 결함이 아니라 성질이다).

### Restart/recovery behavior

게이트 조임 커밋 이후 첫 재시작이 위험 지점이다. 현재 원장이 비어 있는 개발 단계에서는
드러나지 않는다.

### Existing tests

`tests/contract/test_equipment_support_api.py`, 각 store의 재생 거부 테스트.
**게이트 버전/마이그레이션을 다루는 테스트는 없다.**

### Missing tests

"게이트를 조인 뒤 기존 원장이 재생 가능한가"를 확인하는 회귀 픽스처(원장 골든 파일).

### Classification

VERIFIED (성질로서) / 운영 위험은 NEEDS_EXTERNAL_EVIDENCE

### Failure consequence

P2 — 배포 후 첫 재시작에서 Core가 뜨지 않는다. 데이터는 온전하다.

### Recommended next investigation

원장 골든 픽스처를 커밋해 게이트 변경 PR이 "과거 원장 재생 가능"을 CI에서 증명하게
한다. equipment_support.py가 요구한 "게이트 버전 기록"의 실제 필요 여부를 이 픽스처로
판단할 수 있다.

---

# B. 멱등·순서 불변식

## INV-A09 — Edge→Core 수신은 4중 신원으로 멱등이고 장비별 순서를 보존한다

### Invariant

같은 항목의 재전송은 상태를 바꾸지 않는다. 재전송의 정의는
`(idempotency_key, edge_device_id, device_sequence, payload_digest)` **네 값이 전부
동일**할 때뿐이며, 하나라도 다르면 재전송이 아니라 충돌이다. 같은 장비의 순번은
역행하지 않고 중복되지 않는다.

### Evidence

- `packages/event-contracts/src/ksi_event_contracts/offline_sync.py:140-152`
  `EntryIdentity` (키만으로 판정하면 다른 장비의 별개 항목이 조용히 사라진다는 근거 명시).
- `offline_sync.py:173-234` `SyncLedger.ingest` — 판정 순서: 정규화 → digest 정합 →
  멱등 신원 → 순번 중복 → 순번 역행. 순서 근거가 docstring에 있다(재전송은 당연히
  순번이 역행하므로 멱등 판정이 먼저여야 한다).
- 7가지 typed verdict(`offline_sync.py:116-127`) — 예외를 던지지 않는다.
- Core 배선: `services/core/src/ksi_core/edge_sync.py:541` — 규칙을 재구현하지 않고
  `SyncLedger`에 위임.

### Enforcement paths

`EdgeSyncStore.ingest_event_bundle`(live) + `EdgeSyncStore._recover`(재생) — 같은 함수.

### Potential bypass paths

원장 반영 **전에** 3개 사전 게이트가 있다: 중첩 깊이 상한(`edge_sync.py:526-530`),
`EventBundle` 스키마 검증(`:533-540`), 정책 게이트
(`classify_edge_bundle`, `edge_sync.py:757-765`). 셋 다 "영구 422로 그 장비 큐 전체가
막히는" 것을 막기 위해 원장 선점 이전에 판정한다.

`_seen` / `_sequence_keys`(`offline_sync.py:167-176`)는 장비별로 **무한 성장**한다.
`_accepted`만 요약으로 축소됐다(감사 #13). 장기 가동 시 메모리 선형 증가.

### Restart/recovery behavior

재생이 같은 `ingest`를 다시 태우고 `ACCEPTED`가 아니면 기동 거부(INV-A03).

### Existing tests

`tests/contract/test_offline_sync.py`, `tests/contract/test_edge_sync_ingest.py`,
`contracts/conformance/payload-canonicalization.v1.json`(언어 간 벡터).

### Missing tests

`_seen`/`_sequence_keys`의 메모리 성장 상한에 대한 테스트·문서가 없다.

### Classification

VERIFIED

### Failure consequence

P1 — 중복 수신이 이벤트 수를 부풀려 안전 판단을 왜곡한다. 순서 붕괴는 사후 조사를
불가능하게 한다.

### Recommended next investigation

장비 1대가 1년간 보낼 항목 수 × 항목당 상주 바이트로 `SyncLedger` 상주 메모리 상한을
추정. 스냅샷은 재기동 비용만 줄이고 상주 메모리는 줄이지 않는다.

---

## INV-A10 — ACK는 durable 수신 **과 ** event projection이 모두 성공했을 때만 나간다

### Invariant

Edge가 201/200(ACK)을 받았다면 그 bundle은 edge-sync 원장에 durable하고 event
projection에도 반영돼 있다. "수신은 ACK했는데 트리아지에 안 보이는" 상태는 ACK되지 않는다.

### Evidence

- `services/core/src/ksi_core/edge_sync.py:768-786` — `ACCEPTED`/`DUPLICATE_IGNORED`
  둘 다 projection을 수행하고, `STORE_UNAVAILABLE`이면 503으로 **뒤집는다**.
- `services/core/src/ksi_core/app.py:127-131` — `edge_sync_store`에 `event_store`가
  필수라는 조립 규칙이 이 불변식의 구조적 전제.
- `events.py:1117-1146` `project_bundle` — 내부 예외를 무차별 봉인 후 `STORE_UNAVAILABLE`.
- `UPDATE_DIVERGED`는 ACK를 막지 않는다(원문은 이미 durable — 장비 sync를 독살하지 않는다).

### Enforcement paths

`build_edge_sync_router.ingest_event_bundle`(`edge_sync.py:721-800`) 하나.

### Potential bypass paths

**두 단계가 원자적이지 않다.** `store.ingest_event_bundle`이 durable 성공한 뒤
projection이 실패하면 503이 나가고 Edge는 지우지 않는다. 그러나 그 항목은 이미
edge-sync 원장에 있다. **재시작만으로는 projection이 복구되지 않는다** —
`EdgeSyncStore._recover`는 `SyncLedger`만 복원하고 `EventStore`로 재투영하지 않는다
(`edge_sync.py:280-336`). 복구는 **전적으로 Edge의 재전송에 의존**하며, 재전송은
`DUPLICATE_IGNORED` → projection 재시도로 정확히 이어진다(`edge_sync.py:768`).
즉 불변식은 성립하지만 그 성립 조건에 **Edge 측 계약**(ACK 없으면 지우지 않는다)이
포함된다. Edge 쪽 근거:
`edge/manifold-runtime/include/ksi/edge/store_forward.hpp:3-9` — ACK 하나로는 evidence
미완료 candidate를 지우지 않는 비대칭 상태 전이.

### Restart/recovery behavior

위 참조. Core 단독 복구 경로는 없다(설계상 Edge가 정본 사본을 들고 있으므로).

### Existing tests

`tests/contract/test_edge_sync_ingest.py`, `tests/contract/test_events_triage.py`,
`edge/manifold-runtime/tests/edge_runtime_tests.cpp` `TestArtifactVaultAndStoreForward`
(`:1444`), `TestCoreRestSyncWire`(`:1692`).

### Missing tests

"edge-sync 원장에는 있으나 events 원장에는 없는 항목"이 재시작 후 재전송으로만
복구된다는 것을 Core 쪽에서 고정하는 통합 테스트.

### Classification

PARTIALLY_VERIFIED (Core 단독으로는 자기 복구 불가 — Edge 계약에 의존)

### Failure consequence

P1 — Edge가 계약을 어기고(ACK 없이 삭제) 사라지면 그 관측은 트리아지에 영원히 없다.
edge-sync 원장에는 남아 있으므로 감사 추적은 가능하다.

### Recommended next investigation

Core 기동 시 "edge-sync 원장에 있으나 events projection에 없는 항목"을 세는 진단
카운터(재투영이 아니라 계측)를 두면 이 불일치가 관측 가능해진다.

---

# C. 생애주기·상태기계 불변식

## INV-A11 — 현장 상태 전이는 표를 따르고 SUSPENDED 복귀는 기억된 직전 상태로만 간다

### Invariant

`SiteStatus` 전이는 정적 전이표를 따른다. `SUSPENDED`는 어느 상태에서나 진입 가능하지만
이탈은 저장소가 기억한 직전 상태로만 가능하다. 품질 검증 단계를 건너뛰는 간선은 없다.

### Evidence

- `packages/domain/src/ksi_domain/enums.py:158-169` `_ALLOWED_SITE_TRANSITIONS` —
  `PATROL_READY`로 들어오는 간선은 `PROVISIONAL_AUTONOMY`·`PATROL_ACTIVE` 둘뿐,
  `MODEL_STALE → PATROL_READY` 직행 없음.
- `enums.py:172-215` `assert_site_transition` — `cur is SUSPENDED`면 정적 표를 쓰지 않고
  `nxt is resume_target`일 때만 허용, `resume_target is None`이면 거부,
  `SUSPENDED → SUSPENDED` 재진입은 항상 거부.
- 자동 전진도 같은 게이트를 지난다:
  `services/core/src/ksi_core/spatial_model.py:_advance` → `self._site_store.transition(...)`,
  그리고 그 앞에 `source_statuses` 명시 필터가 하나 더 있다.
- AOI 교체는 `UNMAPPED`에서만(`sites.py:30-41`) — 다만 그 잠금의 실효를 sites.py 자신이
  정정해 두었다(`:44-53`: 임무 AOI와 현장 AOI는 현재 대조되지 않는다).

### Enforcement paths

`SiteStore.transition`(HTTP) · `SpatialModelLifecycle._advance`(자동) · `_replay`(재생).
셋 다 `assert_site_transition`을 통과한다.

### Potential bypass paths

`SpatialModelLifecycle._advance`는 `SiteStore.get(site_id)`를 쓰는데 이는 요청 조직
문맥으로 필터링된다(`sites.py:get`). 워커 principal의 조직과 현장 조직이 다르면
`UNKNOWN_SITE`로 조용히 넘어간다(metric만 증가). 다만 처리 작업 가시성 자체가 이미
Mission 경유 조직 스코프이므로(`processing_jobs.py:_record_is_visible_locked`)
**워커 1개 = 조직 1개**가 일관된 전제다. 결함이 아니라 미문서화된 배포 제약이다.

### Restart/recovery behavior

`sites.py:22-28` — 재생이 불법 전이를 다시 판정해 기동 거부.

### Existing tests

`tests/contract/test_site_transitions.py`, `tests/contract/test_sites_api.py`,
`tests/contract/test_spatial_model.py`.

### Missing tests

없음(전이표 자가검증까지 존재: `enums.py:415`).

### Classification

VERIFIED

### Failure consequence

P1 — 품질 검증 우회는 미검증 모델 위에서 자율 운항을 여는 경로다.

### Recommended next investigation

"워커 principal 1개 = 조직 1개" 제약을 `docs/ops/DEPLOYMENT.md`에 명시할지 결정.

---

## INV-A12 — 종단 상태에서 나가는 전이는 없다

### Invariant

`ProcessingJobStatus.{SUCCEEDED, FAILED, CANCELLED}`와
`EventStatus.{CONFIRMED_EVENT, DISMISSED}`는 종단이다. 끝난 것의 결론을 나중에 고쳐
쓸 수 없다.

### Evidence

- `services/core/src/ksi_core/processing_jobs.py:48-50` — 전이표 서술,
  `:373-392` `assert_job_transition`.
- `processing_jobs.py:1614-1621` — 산출물 등록은 `RUNNING`에서만("끝난 작업에 근거를
  소급하지 않는다").
- `services/core/src/ksi_core/events.py:1230-1232` — `_FINALIZED_STATUSES`인 event는
  Edge update가 뒤집지 못한다.
- `events.py:34-42` — Edge는 종단 상태를 애초에 주장할 수 없다(`STATUS_NOT_EDGE_ASSERTABLE`).
- `packages/domain/src/ksi_domain/enums.py:46-62` `EventStatus` + 전이표.

### Enforcement paths

`assert_job_transition` / `can_event_transition` — live·재생 공용.

### Potential bypass paths

없음. `CANCELLED` 전이만 lease를 요구하지 않는다(`processing_jobs.py:2453-2456`) —
"워커가 죽어 lease가 살아 있는 동안 취소가 막히면 정확히 취소가 필요한 상황에서
막힌다"는 명시적 근거가 있고, 이는 종단성이 아니라 lease 규칙의 예외다.

### Restart/recovery behavior

재생이 같은 전이표를 태운다.

### Existing tests

`tests/contract/test_processing_jobs.py`, `tests/contract/test_events_triage.py`.

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P1 — 감사 추적이 감사 대상이 된다.

### Recommended next investigation

없음.

---

## INV-A13 — 임무 타입 × 현장 상태 게이트(INV-052)는 발급 시점에 강제된다

### Invariant

현장의 현재 상태에서 허용되지 않는 임무 타입은 서명·발급되지 않는다
("먼저 매핑, 그 다음 사전지도 기반 자율").

### Evidence

- `packages/domain/src/ksi_domain/mission_gating.py` — 표의 SSOT이고, 근거가 불명확한
  항목(SURVEY_GRADE_MAPPING·ASSET_INSPECTION·INCIDENT_SURVEY)은 "문서에 별도 근거 없음,
  보수적 유추"로 자체 표시돼 있다.
- `services/core/src/ksi_core/mission_records.py:566-608` `precheck_issuance` —
  `is_mission_type_allowed_at_site_status` 호출, `MISSION_TYPE_SITE_STATUS_MISMATCH`(409).
- 두 발급 경로 모두 호출: `mission_issuance.py:229`(계약 단독),
  `mission_plans.py:787`(계약+KMZ 짝).

### Enforcement paths

`precheck_issuance` 하나. **오직 여기 하나다.**

### Potential bypass paths

**TOCTOU 창이 실재한다.** `precheck_issuance`는 스스로 "낙관적 사전 체크이며 최종
권위는 `MissionStore.record_issuance`"라고 적는다(`mission_records.py:614-615`).
그런데 `record_issuance`(`mission_records.py:522-540`)는 **mission_id 중복만** 확인하고
현장 상태·siteFrame을 다시 보지 않는다.

발급 경로의 실제 순서(`mission_issuance.py:229-291`):
`precheck` → acquisition readiness(`:245`) → v1.3 sequence reserve(`:257`) →
`sign_contract`(`:263`) → `record_issuance`(`:291`).
짝 발급(`mission_plans.py:787…917`)은 여기에 경로 생성(coverage planning)까지 끼어
창이 더 길다.

이 창 안에서 현장 상태가 바뀌는 경로는 **운영자 조작만이 아니다** —
`SpatialModelLifecycle.advance_for_job_status`가 워커의 SUCCEEDED 보고를 계기로 현장을
자동 전진시킨다(`processing_jobs.py:2460-2468`). 즉 두 사람의 동시 조작 없이도 재현
가능하다. 모든 Core 라우트가 sync `def`(총 61개)여서 Starlette 스레드풀에서 진짜로
병렬 실행된다는 점이 이 창을 실재하게 만든다.

### Restart/recovery behavior

이미 기록된 발급은 재심사되지 않는다(의도 — `mission_records.py:596-601`: 인가는 발급
시점에 끝났다).

### Existing tests

`tests/contract/test_mission_site_status_gate.py`, `tests/contract/test_mission_records.py`,
`tests/contract/test_mission_plans.py` — **전부 순차 시나리오다.**
Core 계약 스위트 전체에서 스레드를 쓰는 테스트는
`tests/contract/test_live_view_frame_detector_typed.py:106` 하나뿐이고 이 영역과 무관하다.

### Missing tests

발급 진행 중 현장 상태를 전이시키는 동시성 테스트. 특히
`SUSPENDED` 전이와 `AUTONOMOUS_PATROL` 발급의 경합.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P1 — 현장이 `SUSPENDED`(운영 중단)로 넘어간 직후에도 그 현장의 서명된 임무 계약이
발급·기록될 수 있다. 계약은 durable하고 되돌릴 수 없다.
**P0로 올리지 않는 이유**: 그 계약이 실제 비행이 되려면 dispatch → 장비 activation →
사람의 이륙 승인이 더 필요하고(INV-001, `deploy` 구성상 자동 이륙 경로 없음),
INV-052는 즉시적 안전 게이트가 아니라 도메인 독트린 게이트다. 온보드 자동 실행이
열리면 같은 결함이 P0가 된다.

### Recommended next investigation

`record_issuance`에 현장 상태·siteFrame 재확인을 넣는 것이 옳은지, 아니면 발급 전체를
단일 잠금 구간으로 묶는 것이 옳은지 설계 판단. 후자는 경로 생성(수백 ms~초)을 잠금
안에 넣게 되므로 단순하지 않다 — 전자(재확인 후 거부)가 유력하나 서명·sequence를 이미
소비한 뒤라 "예약 후 폐기" 의미론을 정해야 한다(INV-A18의 gap 허용 규약과 정합).

---

# D. 권한·소유권 불변식

## INV-A14 — 하나의 처리 작업은 한 번에 한 워커만 실행한다

### Invariant

`lease`를 쥔 워커만 `/input` 조회·상태 전이·산출물 등록을 할 수 있고, 같은 시점에
그 lease를 쥘 수 있는 워커는 하나다.

### Evidence

- `services/core/src/ksi_core/leasing.py:80-96` `check_lease` — `lease.worker_id != worker_id`이면
  `HELD_BY_ANOTHER`.
- `services/core/src/ksi_core/processing_jobs.py:1743-1766` `_check_lease_locked` —
  워커 행위의 공통 관문. 호출처 4곳: `:1228`(input), `:1533`(transition),
  `:1622`(artifact register), `:1798`(upload target).
- `processing_jobs.py:254` `DEFAULT_LEASE_TTL = 15분`; 갱신도 journal에 적는다(`:1723-1729`).
- 회수 경로: `leasing.py:98-108` `is_claimable` — `RUNNING`이면서 lease가 없거나 만료된
  작업만 후보. `processing_jobs.py:1865` `list_pending`가 이를 사용.
- 동일 모델이 `comparison_requests.py`·`design_conformance_requests.py`·
  `region_extraction_requests.py`에도 적용된다.

### Enforcement paths

Core의 store 잠금 안에서 판정하므로 **단일 Core 프로세스 안에서는 원자적**이다.

### Potential bypass paths

**`worker_id`는 워커 인스턴스가 아니라 토큰의 principalId다.**
`processing_jobs.py:2489-2491` — `worker_id=principal.principal_id`.
워커는 자기 식별자를 보내지 않는다(`services/processing-controller/.../core_client.py`,
`runner.py:482-540`의 `main()`은 `KSI_WORKER_CORE_TOKEN` 하나만 읽는다).

그런데 동시성 모델은 "프로세스를 여러 개 띄운다"이다
(`services/processing-controller/src/ksi_processing_controller/worker.py:56-58`,
`runner.py:27-31`: "동시성은 프로세스를 여러 개 띄우는 것으로 얻는다 — lease가 이미 그
경합을 막는다"). 그리고 배포 레퍼런스는 워커 토큰을 **하나만** 정의한다
(`deploy/.env.example` `KSI_WORKER_CORE_TOKEN=`, `deploy/compose.yaml`의 단일 `worker`
서비스가 `env_file`을 공유).

따라서 `docker compose up --scale worker=N`으로 문서화된 방식대로 확장하면 N개 프로세스가
**같은 principalId**를 쓴다 → `check_lease`가 전부 "갱신"으로 통과 → 같은 작업을 동시에
실행한다. lease는 이 경우 아무 것도 막지 못한다.

귀결(코드로 확인한 범위):
- 두 워커가 같은 `artifact_id`로 `POST .../artifacts/upload-url`을 받으면 **같은
  object key**가 나온다(`processing_jobs.py:717` `build_processing_artifact_object_key`는
  결정적). 두 ODM 실행 결과는 비트 동일하지 않으므로 나중 PUT이 앞의 바이트를 덮는다.
- 산출물 등록은 워커가 신고한 `digest`를 그대로 원장에 적는다(INV-A21) → 원장의
  digest와 스토리지 바이트가 갈라질 수 있다.
- 먼저 끝난 쪽이 `SUCCEEDED`로 전이하면 뒤의 등록은 `JOB_NOT_RUNNING`/
  `DUPLICATE_ARTIFACT`로 거부된다 — 즉 **원장은 일관되지만 스토리지 바이트는 아닐 수 있다.**

### Restart/recovery behavior

죽은 워커의 작업은 lease 만료 후 다른 워커(또는 재시작된 같은 워커)가 회수해 처음부터
다시 돈다(`runner.py:57-76`). 부분 등록분이 있으면 `DUPLICATE_ARTIFACT`로 `FAILED`가
될 수 있음이 명시돼 있다 — "영원히 멈춤보다 낫다"는 수용된 절충.

### Existing tests

`tests/contract/test_processing_jobs.py:2966-3032` (활성 lease는 후보에서 빠진다,
만료 후 `worker-2`가 회수), `:1774`, `:2489`.
**전부 store 레벨에서 `worker_id`를 다른 값으로 넣는 테스트다.** HTTP 경로에서 같은
토큰의 두 호출자가 어떻게 되는지를 고정한 테스트는 없다.

### Missing tests

같은 principalId를 쓰는 두 호출자가 같은 job을 동시에 `acquire_lease` → 둘 다 통과함을
**명시적으로 고정**하는 테스트(현재 동작을 인정하든, 거부로 바꾸든 먼저 못 박아야 한다).

### Classification

PARTIALLY_VERIFIED
(단일 워커 프로세스 전제에서는 VERIFIED. 문서화된 확장 방식에서는 강제되지 않는다.)

### Failure consequence

P1 — 중복 계산(비용)에 더해, 원장에 기록된 산출물 digest와 스토리지 실제 바이트가
불일치할 수 있다. 그 산출물은 이후 비교·설계 대비 계산의 입력이 되고, 처리 산출물에는
바이트 재검증이 없다(INV-A21).

### Recommended next investigation

두 방향 중 택일:
(a) 워커가 인스턴스 식별자(`KSI_WORKER_ID` 또는 랜덤 UUID)를 헤더로 보내고 Core가
`worker_id = f"{principal_id}:{instance_id}"`로 lease를 잡는다 — 배포 설정 변경 없이
확장이 안전해진다.
(b) 워커 확장 = 토큰 분리를 배포 문서에 못 박고 계약 테스트로 강제한다.
어느 쪽이든 먼저 "현재 동작 고정 테스트"부터 넣는다.

---

## INV-A15 — 실행 주체는 자기 검증을 주장할 수 없다 (측정과 판정의 분리)

### Invariant

워커·업로더·운영자는 "검증됐다"는 판정을 보낼 수 없다. 측정값만 보내고 판정은 Core가
한다. 사람은 정확도·잔량·체적을 주장할 수 없다.

### Evidence

- `services/core/src/ksi_core/source_media.py:28-45` — 워커는
  `SourceMediaMeasurement`("재보니 sha256이 X, 4000×3000이더라")만 보내고, 판정은
  `compare_measurements`(`:624 부근`)가 한다. **워커 응답에 신고값을 싣지 않아**
  되읊기가 구조적으로 불가능하다(`processing_jobs.py:118-122`).
- `compare_measurements` — 측정 집합이 등록 집합과 정확히 같아야 한다(`missing`·
  `unexpected`·`mismatched` 셋 다 비어야 통과). 같은 mediaId 중복 측정은 `unexpected`.
- `services/core/src/ksi_core/checkpoint_validations.py:1-8` — 운영자는 독립성만
  증언할 수 있고 **정확도 값을 제출할 수 없다**. 워커가 sealed CSV와 immutable DSM을
  실제로 읽어 측정하고, store가 재생 시 종단 verdict를 재계산한다.
- `services/core/src/ksi_core/design_conformance_reports.py:9-27` — 리포트 수신 순간
  차분 래스터 바이트를 직접 재해싱해 워커 신고와 대조하고, 다르면 기록하지 않고
  요청을 `FAILED`로 보낸다.
- `services/core/src/ksi_core/auth.py:29-33` — `PROCESSING_WORK`는 어느 사람 role에도
  매핑되지 않는다. 사람이 처리 상태를 손으로 찍을 수 없다.
- `services/core/src/ksi_core/processing_jobs.py:322-372` `assert_succeeded_is_backed` —
  `SUCCEEDED`는 전이표와 **별개** 게이트를 하나 더 통과한다(source authority 산출물 1건
  이상 + 입력 실측 대조 통과).

### Enforcement paths

각 store의 수신 메서드. live·재생 공용 함수로 구현돼 있어 원장 조작으로도 우회 불가.

### Potential bypass paths

없음. 단 **처리 산출물(point cloud/DSM/orthophoto) 자체의 바이트는 이 규율에서 제외**돼
있다 → INV-A21(명시적으로 범위 밖이라고 선언돼 있음).

### Restart/recovery behavior

`design_conformance_reports.py:39-46` — 재생은 바이트를 다시 읽지 않고 journal에 남긴
`coreRecomputedDigest`를 대조한다. "확인 없이 기록된 리포트"가 손으로 심어져도 기동에서
걸린다.

### Existing tests

`tests/contract/test_source_media.py`, `tests/contract/test_design_conformance_reports.py`,
`tests/contract/test_checkpoint_validations.py`, `tests/contract/test_processing_jobs.py`.

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P0 — 실행 주체의 자기보고가 근거가 되면 "유효한 리포트가 있는데 그 지도는 다른 파일"이
성립한다. 이 값들은 정산·분쟁의 근거로 쓰인다.

### Recommended next investigation

없음. 이 저장소에서 가장 잘 지켜진 불변식군이다.

---

## INV-A16 — 조직 경계는 인증된 요청 문맥으로 중앙 상속된다

### Invariant

HTTP 요청 안에서 store 조회는 인증 Principal의 `organizationId`로 필터링되고, 다른
조직의 레코드는 **존재하지 않는 것과 같은 응답**을 받는다(존재 여부 oracle 금지, INV-060).

### Evidence

- `services/core/src/ksi_core/auth.py:449-465` `_REQUEST_PRINCIPAL` ContextVar +
  `current_request_organization_id()`.
- `auth.py:513-529` `_principal_request_scope` — async generator dependency로 set/reset.
  주석이 근거를 명시: sync endpoint/threadpool에도 문맥이 복사되고 응답 후 반드시 reset된다.
- 소비처: `mission_records.py:get/list`, `sites.py:get/list`,
  `processing_jobs.py:_record_is_visible_locked`(Mission 경유 상속),
  `edge_sync.py:802-826`(다른 조직의 순번을 oracle로 만들지 않기 위해 event 가시성을 관문으로).
- 명시적 변형 `get_scoped(...)`가 요청 문맥 없는 내부 조정 코드용으로 따로 있다.

### Enforcement paths

인증 dependency 3종(`require_permission` 127회, `require_principal` 6회,
`require_permission_any`) 전부 `_principal_request_scope`를 거친다. 저장소 전체에서
`Depends(_resolve_principal)` 직접 사용은 `auth.py:514` 한 곳(= `_principal_request_scope`
자신)뿐이다. 커스텀 dependency 6종도 전부 `require_permission`/`require_principal` 위에
얹혀 있다(`equipment_states.py:327`, `coverage_reports.py:615`,
`capture_quality_reports.py:305`, `edge_sync.py:687` 등).

### Potential bypass paths

없음. 공개 표면 4종(`/health`·`/capabilities`·`/ready`·`/metrics`)은 조직 데이터를
반환하지 않는다.

### Restart/recovery behavior

요청 밖(재생·배치)에는 문맥이 없고, 그 경우 필터가 적용되지 않는다 — 의도된 설계이며
`auth.py:461-464`가 "호출자가 이 값이 없다는 이유로 인가를 생략해서는 안 된다"고 못 박는다.

### Existing tests

`tests/contract/test_observation_work_orders.py::test_api_is_organization_scoped_and_approval_is_optimistic`
(foreign detail/list/create가 404),
`tests/contract/test_events_triage.py::test_list_can_apply_explicit_organization_scope_without_request_context`
(요청 밖 명시 scope 분리),
`tests/contract/test_mission_records.py::test_mission_reads_hide_other_organization_and_keep_legacy_journal_compatible`.

### Missing tests

모든 `require_permission`/`require_principal` 소비처와 각 custom dependency가 요청 문맥을
통해 조직 필터를 실제로 상속하는지 전수 검증하는 회귀는 없다. 위 테스트는 대표 HTTP/store
소비처만 증명하며, dependency 전수 연결은 현재 정적 코드 조사 근거다.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P0 — 조직 간 데이터 유출.

### Recommended next investigation

없음.

---

## INV-A17 — 장비 신원은 요청 본문이 아니라 인증 토큰이 정한다

### Invariant

장비가 보낸 본문의 `edgeDeviceId`/`gatewayDeviceId`가 인증된 `device_id`와 다르면
원장 반영 **전에** 거부한다.

### Evidence

- `services/core/src/ksi_core/edge_sync.py:748-754` — `principal.device_id != entry.edge_device_id`
  이면 403 `DEVICE_MISMATCH`(원장 반영 전).
- `services/core/src/ksi_core/edge_dispatch.py:528-531` — dispatch의 `edgeDeviceId`와
  요청 장비가 다르면 `NOT_FOUND`(존재 힌트 금지).
- `edge_dispatch.py:532-536` — receipt의 `edge_device_id` 불일치 + dispatch binding
  불일치는 `RECEIPT_MISMATCH`.
- `services/core/src/ksi_core/acquisition/api.py:82-85` — `principal.kind`가
  `GATEWAY_DEVICE`인지, `principal.device_id == request.gateway_device_id`인지 확인.
- `services/core/src/ksi_core/acquisition/store.py:86-92` `_assert_binding` —
  snapshot의 `gateway_device_id`가 그 현장 profile에 등록된 장비와 같은지.
- `services/core/src/ksi_core/auth.py:391-400` — `EDGE_DEVICE`는 role 표와 무관하게 고정
  권한 5종만 갖는다.
- `services/core/src/ksi_core/device_attestation.py:1-8` — bearer 신원과 별개로,
  증거 산출물 1건의 불변 신원에 대한 Ed25519 서명을 검증하는 두 번째 축.
  HTTP 등록 표면이 없고 운영이 out-of-band로 공개키를 넣는다.

### Enforcement paths

각 라우터 진입부(원장 접근 전).

### Potential bypass paths

없음.

### Restart/recovery behavior

`device_attestation` 공개키는 파일에서 기동 시에만 읽는다(`production.py:505-509`,
파일 부재는 기동 거부) → INV-A25와 같은 설정 복원 의존성.

### Existing tests

`tests/contract/test_edge_sync_ingest.py`, `tests/contract/test_edge_dispatch_api.py`,
`tests/contract/test_acquisition_connectivity.py`, `tests/contract/test_device_attestation.py`.

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P0 — 장비 하나의 토큰으로 다른 장비의 순번축을 오염시키거나 남의 임무를 활성화할 수 있다.

### Recommended next investigation

없음.

---

## INV-A18 — mission_id는 재사용되지 않고, v1.3 sequence는 gap을 허용하되 재사용하지 않는다

### Invariant

같은 `mission_id`로 두 번째 발급 레코드가 기록되지 않는다. `(issuerId, siteId)`별
sequence는 양의 단조 증가이며, 예약 후 발급이 실패해 생긴 **gap은 허용하지만 예약된
숫자는 절대 재사용하지 않는다**.

### Evidence

- `services/core/src/ksi_core/mission_records.py:522-540` `record_issuance` —
  중복 확인과 append를 **한 잠금 구간**에 묶는다("여기가 최종 권위").
- `mission_records.py:MissionIssuanceSequenceStore` — 클래스 docstring이 gap 허용/재사용
  금지를 명시. `reserve()`는 잠금 안에서 `high_water+1` → append → 반영 순서.
- 재생(`_replay`)이 `sequence <= previous`를 오염으로 보고 기동 거부.
- 조립 게이트: `app.py:625-631` — writer v1.3은 서명키·issuerId·durable sequence store가
  모두 있어야 조립된다.

### Enforcement paths

`record_issuance`(잠금 안 check-then-append), `reserve`(잠금 안).

### Potential bypass paths

gap은 설계상 허용이므로 우회가 아니다. 발급 실패 시(예: `MISSION_ID_CONFLICT`) 예약된
sequence가 소비되는 것은 **의도된 동작**이다.

### Restart/recovery behavior

`high_water`는 append 성공 후에만 전진한다. append가 봉인 실패하면 전진하지 않지만 그
원장은 이미 봉인돼 후속 예약이 불가능하다.

### Existing tests

`tests/contract/test_mission_records.py::test_mission_store_duplicate_mission_id_does_not_overwrite_and_survives_restart`,
`tests/contract/test_mission_records.py::test_v13_site_sequence_reservations_are_durable_and_allow_gaps`,
`tests/contract/test_mission_records.py::test_v13_site_sequence_replay_rejects_duplicate_or_lower_values`
(현재 fixture는 `2 -> 2` 중복만 기록·거부한다).

### Missing tests

같은 `(issuerId, siteId)` journal에 높은 sequence 뒤의 더 낮은 sequence(예: `2 -> 1`)를
기록하고 재생이 거부하는지 확인하는 회귀가 없다. 현재 재생 테스트는 이름과 달리 중복
`2 -> 2`만 증명한다; lower-value 거부는 코드의 `sequence <= previous` 경계 조사 근거다.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P1 — 발급 이력이 덮이면 "무슨 근거로 날았나"에 답할 수 없다.

### Recommended next investigation

없음.

---

## INV-A19 — 서명된 산출물의 바이트는 원문 그대로 보관·재전달된다

### Invariant

Mission Contract와 MissionDispatchEnvelope는 저장·재생·재전달 과정에서 재직렬화되지
않는다. 서명 대상 바이트열이 변하면 장비 검증이 실패하기 때문이다.

### Evidence

- `packages/mission-contracts/src/ksi_mission_contracts/signing.py:30-48`
  `canonical_payload_bytes` — `signature` 블록 제외 + `ksi_domain.canonical_json_bytes`
  (event-contracts의 `payload_digest`와 **같은 정규화 규약 공유**).
- `signing.py:50-53` — 서명은 digest가 아니라 **정규화 바이트열 자체**에 대해 수행.
- `signing.py:160-178` `SignatureVerdict` — 검증 실패는 예외가 아니라 typed verdict(fail-closed).
- `services/core/src/ksi_core/edge_dispatch.py:289-300` — 재생 시 모델은 **검증에만** 쓰고
  보관은 저널 원문 그대로. 재덤프하면 그 시점 스키마의 optional 필드가 생겨 봉투가
  장비에서 `INVALID_DISPATCH_SIGNATURE`가 된다(근거가 코드 주석에 있음).
- `edge_dispatch.py:487-492` — 발급 원장의 `kmz_sha256`을 그대로 싣는다. 여기서 KMZ를 다시
  만들거나 해싱하지 않는다("발급된 그 파일"이 아니라 "지금 만들면 나오는 파일"을 보증하게 되므로).
- KMZ 바이트 보관: `app.py:892` `kmz_storage=evidence_storage` — 서버 안전상수 변경이
  이전 발급분 전량을 영구 409로 만들던 경로를 닫는다.

### Enforcement paths

`EdgeDispatchStore._replay`/`next_for_device`, `mission_plans._regenerate_pair_artifact`
(`:545`), `mission_plans.py:975-1020`(재생성 digest가 원장과 다르면 typed 실패).

### Potential bypass paths

없음.

### Restart/recovery behavior

재생이 원문을 보존하므로 재기동 후에도 같은 봉투가 나간다.

### Existing tests

`tests/contract/test_edge_dispatch_contracts.py`(2,298 LOC),
`tests/contract/test_mission_plans.py`, `packages/mission-contracts` 자체 테스트,
`edge/manifold-runtime/tests/edge_runtime_tests.cpp` `TestNativeMissionKmzHandoff`(`:385`),
`TestFlightExecutionKmzEnvelopeRederivation`(`:3494`).

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P0 — 이미 현장에 발급된 계약이 서버 변경 한 번으로 전부 무효가 된다(제품 근본 전제
"server loss must not invalidate a locally valid Mission Contract" 위반).

### Recommended next investigation

없음.

---

# E. 산출물·파일 불변식

## INV-A20 — 오브젝트 키는 서버가 만든다

### Invariant

클라이언트가 준 문자열이 스토리지 객체 키로 그대로 쓰이지 않는다. 경로 탈출(`../`)과
타 현장 덮어쓰기가 구조적으로 불가능하다.

### Evidence

- `services/core/src/ksi_core/evidence.py:7-11`(설계 근거), `:239-262` `build_object_key`.
- `services/core/src/ksi_core/identifiers.py:26-40` — `^[A-Za-z0-9][A-Za-z0-9_.-]*$`
  `fullmatch`(트레일링 개행 허용 갭까지 닫음). 첫 글자 영숫자 강제로 `..`·`-` 배제.
- `source_media.py:408` `build_source_media_object_key(site_id, mission_id, media_id)`.
- `processing_jobs.py:717` `build_processing_artifact_object_key`.
- Edge 쪽 대칭: `edge/manifold-runtime/include/ksi/edge/store_forward.hpp:45-49` —
  로컬 경로만 보내고 remote key는 Core가 장비 소유권 인증 후 유도한다("client-selected
  remote key를 받으면 cross-event/path traversal 위험이 다시 열린다").
- 허용 content-type 화이트리스트(`evidence.py:40-50`) — `text/html`·`image/svg+xml`·
  JavaScript 계열 거부.

### Enforcement paths

키를 만드는 함수 3종 + `is_path_safe_identifier`가 그 입력 성분을 모두 검증한다.

### Potential bypass paths

없음.

### Restart/recovery behavior

무관.

### Existing tests

`tests/contract/test_evidence.py::test_path_escaping_artifact_id_is_refused`,
`tests/contract/test_source_media.py::test_path_escaping_media_id_is_refused_by_object_key_builder`,
`tests/contract/test_design_conformance_requests.py::test_raster_object_key_refuses_path_escaping_identifiers`,
`edge/manifold-runtime/tests/edge_runtime_tests.cpp` `TestMediaIdConvention` and
`TestSpoolArtifactIdUnambiguous`.

### Missing tests

evidence/source-media/raster key builder의 경로 탈출 거부는 회귀로 확인되지만, 모든 객체 키
생성 경로와 Edge의 remote-key 비수용을 하나의 cross-site overwrite 회귀로 묶어 증명하는
테스트는 없다. 그 전체 결론은 현재 코드 경계 조사에 의존한다.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P0 — 타 현장 증거 덮어쓰기.

### Recommended next investigation

없음.

---

## INV-A21 — 원장의 digest와 스토리지 바이트의 일치 — **강제 강도가 3단계로 다르다**

### Invariant (실제로 성립하는 것)

산출물 종류에 따라 세 가지 서로 다른 불변식이 성립한다. 하나로 뭉뚱그릴 수 없다.

| 대상 | 강제 방식 | 성립하는 문장 |
|---|---|---|
| Edge evidence | **스토리지 레이어 강제** — digest-bound presigned PUT | 다른 바이트는 스토리지가 거부한다 |
| 설계 대비 차분 래스터 | **Core 재해싱** — 리포트 기록 순간 바이트를 직접 읽어 해싱 | 원장의 모든 리포트에 대해 재해싱 결과가 항상 같다 |
| 원본 사진 번들 | **워커 독립 측정 + Core 대조** | 봉인 후 `VERIFIED` 번들의 신고값은 실측과 같았다 |
| 처리 산출물(DSM·point cloud·orthophoto) | **없음** | `digest`는 워커의 보고값이다 |

### Why this invariant exists

지도가 내려받는 바이트와 표의 숫자가 갈라지면 어느 화면에서도 보이지 않는다
(`design_conformance_reports.py:9-16`).

### Evidence

- **digest-bound**: `services/core/src/ksi_core/evidence.py:95-113`
  `DigestBoundEvidenceStorage`, `evidence_s3.py:129` `presigned_put_bound_digest`
  (S3 checksum 강제). **유일한 소비처는 `edge_dispatch.py:955, 1059`** — 즉 Edge 증거
  등록 경로 하나뿐이다.
- **Core 재해싱**: `design_conformance_reports.py:9-27` + 요청 쪽의 두 번째 확인
  (`:29-37`, 두 시점 사이 객체가 덮이는 창을 닫기 위해 의도적 중복).
- **워커 측정 대조**: `source_media.py:28-45`, `compare_measurements`.
- **없음**: `processing_jobs.py:128-131` — "산출물 바이트 자체. `digest`·`format`은
  워커의 보고값이고 Core가 객체를 읽어 대조하지 않는다. 이 모듈이 강제하는 것은
  **계보의 무결성**이지 산출물 내용의 진위가 아니다." 등록 코드도 그대로다
  (`processing_jobs.py:1638` `digest=spec.digest`). 업로드 URL도 평문 presigned PUT
  (`processing_jobs.py:2643-2647`).

### Enforcement paths

위 표 참조. 계보 무결성은 별도로 강제된다 — `lineage.source_digest`는 요청이 아니라
봉인된 번들에서 오고(`processing_jobs.py:1633-1636`), 재생이 이를 재확인한다(`:1096-1101`).

### Potential bypass paths

- 처리 산출물: 워커가 임의 digest를 신고할 수 있다(명시적 범위 밖).
- 원본 사진: presigned PUT TTL 15분(`evidence.py:32`) 안에 같은 URL로 덮어쓰면 검증
  시점과 처리 시점의 바이트가 다를 수 있다. 봉인 후 신규 등록은 거부되지만
  (`source_media.py:77`), 이미 발급된 URL의 남은 수명은 닫히지 않는다. 실행하려면
  업로드 권한을 이미 가진 주체여야 한다.
- INV-A14(공유 토큰 워커)와 결합하면 처리 산출물의 불일치가 **사고로도** 발생할 수 있다.

### Restart/recovery behavior

`design_conformance_reports.py:39-46` — 재생은 스토리지를 읽지 않고 journal의
`coreRecomputedDigest`를 대조한다(기동이 스토리지 가용성에 묶이지 않게).

### Existing tests

`tests/contract/test_evidence.py`, `tests/contract/test_design_conformance_reports.py`,
`tests/contract/test_source_media.py`, `tests/contract/test_upload_source_bundle.py`.

### Missing tests

처리 산출물의 "원장 digest ≠ 스토리지 바이트"가 **탐지되지 않는다**는 현재 동작을
고정하는 테스트(문서화된 경계를 테스트로도 박아두면 나중에 조용히 달라지지 않는다).

### Classification

PARTIALLY_VERIFIED (종류별로 다르며, 그 차이가 문서화돼 있다)

### Failure consequence

P1 — 처리 산출물은 비교·설계 대비·체적 계산의 입력이고 그 결과는 정산·분쟁 근거다.
다만 그 하류 계산의 **결과물**(차분 래스터)은 Core 재해싱으로 보호되므로 사슬 전체가
검증되지 않는 것은 아니다.

### Recommended next investigation

처리 산출물에도 digest-bound PUT을 쓸 수 있는지(현재 어댑터가 이미 지원한다 —
`evidence_s3.py:129`) 검토. 비용은 워커가 업로드 전에 digest를 알아야 한다는 것뿐이고,
워커는 이미 파일을 만들었으므로 알 수 있다. 이는 INV-A14의 사고 결과도 함께 막는다.

---

# F. Capability 불변식 (전용 분석)

## INV-A22 — 미검증 capability는 운영 표면에 노출되지 않는다

### Invariant

`GET /capabilities`는 `VERIFIED` 상태의 항목만 반환한다. `SPIKE_REQUIRED`/`BLOCKED`는
절대 포함되지 않는다.

### Evidence

- `services/core/src/ksi_core/capability/registry.py:185-193` `list_operational`.
- `services/core/src/ksi_core/app.py:587-607` — 공개 응답은 식별·상태만
  (firmware/PSDK 버전은 배치 기체 표적화 정보라 제외).
- `registry.py:80-110` — 초기 등록으로 `VERIFIED`를 부여할 수 없다.
- `registry.py:141-147` — `VERIFIED` 승격에는 11필드 `SpikeEvidence` 필수.
- `packages/domain/src/ksi_domain/capability.py:68-73` — 전이표
  (`SPIKE_REQUIRED→{VERIFIED,BLOCKED}`, `BLOCKED→{SPIKE_REQUIRED}`, `VERIFIED→{BLOCKED}`).
  모든 전이에 evidence 필수.
- `capability.py:75-95` `assert_capability_transition`.
- `packages/domain/src/ksi_domain/spike_evidence.py:15-20` — `failure_result` 필수
  ("실패를 안 봤다"와 "실패를 찾지 않았다"를 구분하기 위해).

### Enforcement paths

`/capabilities` 라우트 하나가 `list_operational()`만 호출한다.

### Potential bypass paths

없음 — 오히려 **너무 좁다** → INV-A23.

### Restart/recovery behavior

매 기동마다 9개 `SPIKE_REQUIRED`를 새로 시드한다(`registry.py:202-223`, `app.py:576-578`).
`assemble_app`은 `create_app(registry=...)`을 넘기지 않는다.

### Existing tests

`tests/contract/test_capability_gate.py` (Codex 독립 실행 결과 35 passed).

### Missing tests

없음.

### Classification

VERIFIED (단, 현재는 공집합에 대해 자명하게 참)

### Failure consequence

P0 — 미검증 기능이 운영 UI·Mission Contract 정책 선택지에 노출된다.

### Recommended next investigation

없음.

---

## INV-A23 — capability 검증 상태는 재시작을 넘어 살아남아야 한다

### Invariant (성립해야 하지만 **표현할 수단이 없는** 것)

한 번 실기 증거로 `VERIFIED`가 된 capability는 프로세스 재시작 후에도 `VERIFIED`여야
하고, 그 증거는 감사 가능해야 한다.

### Evidence

- `services/core/src/ksi_core/capability/registry.py:57-65` — `self._records`는 순수
  `dict`다. journal도, repository adapter도, 영속 인자도 없다.
- `registry.py`에 `transition()`을 호출하는 **HTTP 라우트가 없다.**
  저장소 전체에서 비테스트 호출부 0건(`grep`으로 확인).
- `app_assembly.py`의 `create_app(...)` 호출부에 `registry=` 인자가 없다 →
  `app.py:576-578`이 새 레지스트리를 시드한다.
- `production.py`에 capability evidence loader가 없다(환경변수 목록 24종 중 관련 항목 없음).
- 결과: production 조립의 `GET /capabilities`는 항상 `{"capabilities": [], "count": 0}`.

### Enforcement paths

없음. 이 불변식을 표현하는 코드 자체가 없다.

### Potential bypass paths

해당 없음(승격 경로가 없으므로 우회할 것도 없다). 위험은 반대 방향이다 — 실기 검증이
끝났을 때 **코드/설정 주입 외에 반영 수단이 없어**, 급하게 만든 우회가 증거 승인·감사
계보·회귀 차단·재시작 결정성을 배포마다 다르게 만들 수 있다.

### Restart/recovery behavior

정의상 유실. 테스트처럼 custom registry를 주입한 프로세스 안에서만 `VERIFIED`가 보인다.

### Existing tests

`tests/contract/test_capability_gate.py` — 무증거 승격 거부와 미노출 게이트를 고정한다.
**durable promotion 경로가 있다는 증거는 아니다**(Codex 검토 Finding E와 동일 결론).

### Missing tests

"승격된 capability가 재시작 후에도 `VERIFIED`다"를 요구하는 테스트. 지금 쓰면 실패한다 —
그것이 이 gap의 정확한 크기다.

### Classification

UNVERIFIED (불변식이 코드로 표현돼 있지 않다)

### Failure consequence

P2 — 현재 상태는 안전하다(fail-closed). 위험은 첫 HIL 통과 시점에 발생하는 **우회
압력**이며, 그 우회가 INV-A22/A08을 함께 손상시킬 수 있다.

### Recommended next investigation

아래 [Capability 증거·승격 전용 질의 6문](#capability-증거승격-전용-질의-6문) 참조.

---

## INV-A24 — 하나의 capability에는 하나의 권위 있는 검증 상태가 있어야 한다

### Invariant (성립하지 않는 것)

"이 기능이 실기에서 검증됐는가"에 대해 시스템 전체가 하나의 답을 가져야 한다.

### Evidence — **세 개의 독립된 capability 어휘가 공존한다**

| # | 어휘 | 상태값 | 영속 | 런타임 도달 | 증거 기준 |
|---|---|---|---|---|---|
| 1 | `ksi_domain.capability.CapabilityVerificationState`<br>(`SPIKE-DJI-01…09`) | `VERIFIED`/`SPIKE_REQUIRED`/`BLOCKED` | **없음**(메모리) | `GET /capabilities` (항상 빈 값) | 11필드 `SpikeEvidence` |
| 2 | `ksi_core.acquisition.models.CapabilityStatus`<br>(`AcquisitionCapability`) | `VERIFIED`/… | **있음**(`acquisition-connectivity.jsonl`) | `POST /v1/gateway-sync/heartbeats` → `GET /v1/sites/{id}/acquisition-readiness` | **장비 자기신고 + 비어있지 않은 `evidenceRef` 문자열** |
| 3 | `ksi_dji_gateway.domain.capabilities.CapabilityStatus` | `NOT_VERIFIED`/`VERIFIED`/`BLOCKED` | 있음(`GatewayJournal`) | **없음**(런타임 host 부재) | `CapabilityEvidence` + 별도 `VendorDocumentationStatus` 축 |

세부 근거:
- 축 1: `packages/domain/src/ksi_domain/capability.py:28-37`,
  `services/core/src/ksi_core/capability/registry.py:202-212`.
- 축 2: `services/core/src/ksi_core/acquisition/models.py:75-90`(enum),
  `:266-280` `CapabilityReceiptV1.verified_requires_evidence`
  (`VERIFIED`면 `evidenceRef` 필수 — **문자열이 비어 있지 않기만 하면 된다**),
  `:468` `RC_REQUIRED_CAPABILITIES = frozenset(AcquisitionCapability)`,
  `services/core/src/ksi_core/acquisition/store.py:232-244` —
  `status is VERIFIED and item.evidence_ref`인 capability 집합으로
  `ReadinessStatus.READY`를 판정.
- 축 3: `services/dji-gateway/src/ksi_dji_gateway/domain/capabilities.py:31-63`.
  `CapabilityStatus` docstring이 "runtime route를 활성화할 수 있는 **유일한** evidence
  축"이라고 선언하지만, 그 registry를 소비하는 런타임 host가 없다(아키텍처 감사 §Runtime).
- 축 1과 축 2 사이에 어떤 대조 코드도 없다(`grep`으로 확인 — 상호 import 0건).

### Enforcement paths

각 축이 자기 안에서만 일관된다. 교차 검증 지점 없음.

### Potential bypass paths

축 2가 유일하게 **런타임에서 도달 가능하고 durable한** "VERIFIED"이며, 그 근거는
장비의 자기신고다. 축 1이 요구하는 11필드 실기 증거와 신뢰 모델이 전혀 다르다.

**다만 현재 권한 방향은 안전하다** — 이 점이 중요하다:
- 게이트는 기본 OFF다(`deploy/.env.example`
  `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false`).
- OFF일 때 `app.py:875-883` `_acquisition_readiness`는 무조건 `(True, "…disabled")`를
  반환한다 — **발급을 막지 않는다**.
- 따라서 플래그를 켜면 **더 엄격해질 뿐**이고, 장비가 자기 자신을 `VERIFIED`로 신고한
  최악의 경우가 정확히 현재(OFF) 동작과 같다.
- 즉 이것은 권한 상승 경로가 **아니다**. "VERIFIED"라는 단어의 의미가 두 축에서 다르다는
  **어휘 충돌**이다.

### Restart/recovery behavior

축 2는 만료(`expiresAt`) 기반이라 stale snapshot으로 새 임무를 Ready 처리하지 않는다
(`store.py:195-201`, `contracts/schemas/connectivity-snapshot.v1.json:5`).
축 1은 재시작마다 초기화. 축 3은 재생되지만 아무도 읽지 않는다.

### Existing tests

`tests/contract/test_capability_gate.py`(축 1),
`tests/contract/test_acquisition_connectivity.py`(축 2),
`services/dji-gateway/tests/`(축 3).
**세 축의 정합을 확인하는 테스트는 없다.**

### Missing tests

"축 2에서 `VERIFIED`로 신고된 capability가 축 1에서 `SPIKE_REQUIRED`일 때 시스템이
무엇을 주장하는가"를 고정하는 테스트.

### Classification

VIOLATED (단일 권위 불변식이 성립하지 않는다) / 현재 위험은 낮음

### Failure consequence

P2 — 오늘은 어떤 잘못된 허용도 만들지 않는다(위 권한 방향 분석 참조). 위험은
운영자·감사자가 "이 capability는 검증됐는가"를 물었을 때 세 개의 다른 답이 존재하고,
그중 가장 엄격한 축이 유일하게 작동하지 않는 축이라는 점이다.

### Recommended next investigation

축 2의 `CapabilityStatus.VERIFIED`를 다른 이름(예: `DEVICE_REPORTED_OK`)으로 바꾸는
것만으로도 어휘 충돌이 해소되는지 검토. 계약 스키마 변경이므로 비용이 있지만,
축 1의 durable promotion을 설계하기 **전에** 정리해야 이름 충돌이 설계로 굳지 않는다.

---

# G. 설정 복원 불변식

## INV-A25 — 원장 복원만으로는 Core의 동작이 복원되지 않는다

### Invariant (실제로 성립하는 것)

Core의 일부 필수 동작은 **journal에 없고 환경변수·파일에만 있는** 설정에 의존한다.
데이터 볼륨만 복원하면 그 동작은 조용히 사라진다.

### Evidence

journal에 없는 운영 필수 상태:

| 설정 | 출처 | 없을 때의 동작 |
|---|---|---|
| risk policy pack | `KSI_CORE_RISK_POLICY_PACKS_JSON`(`production.py:424`) | 해당 pack을 참조하는 mission이 **dispatch 대상에서 조용히 제외**된다(warning 로그만) — `edge_dispatch.py:449-452` |
| edge runtime profile | `KSI_CORE_EDGE_RUNTIME_PROFILES_JSON`(`production.py:453`) | 같음 — `edge_dispatch.py:453-461` ("장비는 이 endpoint에서 아무 mission도 관측하지 않는다") |
| 장비 attestation 공개키 | `KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE`(`production.py:505`) | 파일 부재는 기동 거부(fail-closed) |
| 서명키 | `KSI_CORE_SIGNING_KEYS_DIR` 호스트 바인드(`deploy/compose.yaml:60-73`) | 재생성 시 기존 발급 계약 전량 검증 실패 |
| 인증 토큰 digest | `KSI_CORE_PRINCIPAL_TOKENS_JSON` | 기동 거부 |
| 기능 플래그 6종 | 환경변수 | 기본값으로 되돌아감 |

`edge_dispatch.py:282-353` `_replay`가 **현재 registry를 대조하지 않는 것은 의도**다
(설정 변경이 기동을 깨지 않게). 그 결과 "봉투는 남아 있고 기동도 되는데 새 dispatch만
안 나가는" 상태가 성립한다.

`deploy/compose.yaml:22-26`은 백업 대상을 `ksi-data` 볼륨 + `deploy/signing-keys/`
디렉터리 둘로 명시한다. **`.env`는 그 목록에 없다.**

### Enforcement paths

기동 시 필수 항목은 fail-closed로 거부된다(`production.py:497-534`). 선택 항목
(policy pack·runtime profile)은 부재가 런타임 warning으로만 나타난다.

### Potential bypass paths

해당 없음(설계 성질).

### Restart/recovery behavior

`deploy/bin/backup-vm.sh`, `restore-check-vm.sh`, `smoke-backup-restore.sh`가 존재한다 —
이들이 `.env`/policy pack을 포함하는지는 **저장소 밖 운영 절차에 달렸다**(스크립트
내용은 이 감사에서 확인하지 않았다).

### Existing tests

`tests/contract/test_production_assembly.py`(환경변수 검증),
`tests/contract/test_edge_dispatch_contracts.py`(pack/profile 부재 시 dispatch 제외).

### Missing tests

"data 볼륨만 복원하고 policy pack 설정을 잃은 Core가 dispatch를 못 하는 상태"를 재현해
그것이 로그 warning만 남기는 조용한 실패임을 고정하는 테스트.

### Classification

PARTIALLY_VERIFIED / NEEDS_EXTERNAL_EVIDENCE(백업 절차가 `.env`를 포함하는지)

### Failure consequence

P2 — 복원된 Core가 정상 기동하고 `/ready` 200을 반환하면서 임무를 하나도 배포하지
않는다. 관측 가능한 신호는 warning 로그와 장비의 `NO_MISSION` 응답뿐이다.

### Recommended next investigation

`/ready`에 "risk policy pack 0건 · runtime profile 0건"을 degraded 신호로 넣을지 검토.
또는 `deploy/README.md`의 백업 대상에 설정 파일을 명시.

---

# H. 컴포넌트 간 불변식

## INV-A26 — URL 경로 세그먼트가 되는 모든 식별자는 경로-안전하다

### Invariant

`siteId`·`missionId`·`edgeDeviceId`·`eventId`·`organizationId`·`issuerId`는 durable
기록 **전에** 경로-안전성이 검증된다. 기록은 성공했는데 조회 라우트에 영원히 도달할 수
없는 레코드가 만들어지지 않는다.

### Evidence

- `services/core/src/ksi_core/identifiers.py:1-16` — 근거 서술(FastAPI str convertor는
  `/`를 포함할 수 없고 uvicorn이 라우팅 전에 `%2F`를 언쿼트하므로 인코딩 우회 불가).
- `identifiers.py:26-40` — `fullmatch` 사용 이유가 명시(`match`+`$`는 트레일링 개행 1개를
  허용해 "같은 값의 두 레코드 공존" 갭을 연다).
- 파생 식별자도 안전을 물려받는다: `processing_jobs.py:769-776` `build_job_id`
  (`{missionId}-pj{n}`), `events.py:21-30` `event_key = "{edgeDeviceId}::{eventId}"`
  (`:`는 패턴에 없으므로 `::` 분해가 모호해지지 않는다).
- 소비처: `mission_records.validate_mission_identifiers`,
  `events._project_bundle_locked`(`:1158-1162`), `sites.py`, `auth.py`,
  `mission_records.MissionIssuanceSequenceStore._replay`, `civil_readiness.py`(URL quote).

### Enforcement paths

각 store의 수신 경로 + 재생 경로.

### Potential bypass paths

없음. 길이 상한은 없다(근거: 운영 규모에서 URL 길이 한도에 닿을 사례가 없어 임의 상한을
대표자 결정 없이 고정하지 않음 — `identifiers.py:22-25`).

### Restart/recovery behavior

재생이 같은 검증을 다시 태운다.

### Existing tests

`tests/contract/test_mission_records.py::test_mission_id_with_slash_rejected_422_not_trapped_404`,
`tests/contract/test_mission_records.py::test_site_id_with_invalid_characters_rejected_422`,
`tests/contract/test_events_triage.py::test_slash_in_event_id_is_rejected_not_trapped`,
`tests/contract/test_events_triage.py::test_slash_in_edge_device_id_is_rejected`,
`tests/contract/test_events_triage.py::test_trailing_newline_in_event_id_is_rejected`,
`tests/contract/test_capability_runtime_api.py::test_runtime_preflight_rejects_path_unsafe_identifiers_with_422`.

### Missing tests

위 회귀는 mission/site/event/edge-device 및 runtime preflight의 identifier 입력을 다룬다.
`organizationId`·`issuerId`의 모든 durable 기록 경로와 모든 store replay 경계를 전수로
검증하는 회귀는 없으므로, "모든 식별자" 결론의 그 부분은 정적 코드 조사만으로 남는다.

### Classification

PARTIALLY_VERIFIED

### Failure consequence

P1 — 도달 불가능한 레코드(트랩)가 원장에 durable하게 쌓인다.

### Recommended next investigation

없음.

---

## INV-A27 — 모든 시각은 tz-aware이고, Edge가 공급한 시각은 별도로 검증된다

### Invariant

서버가 만드는 시각은 항상 UTC tz-aware다. Edge/클라이언트가 공급한 시각은 수신 시
tz-aware 여부와 미래성이 검증된다.

### Evidence

- `_require_tz_aware` 계열이 각 store에 존재(`processing_jobs.py:778-781`,
  `events.py:1132`, `edge_dispatch.py:419-420`, `mission_records`, `acquisition`).
- `events.py:1164-1171` — naive `occurredAt` 거부(`INVALID_EVENT_TIMESTAMP`). 근거 명시:
  `astimezone(UTC)`가 서버 로컬 타임존으로 조용히 재해석해 감사 시간축을 어긋나게 한다.
- `events.py:1242-1244` — `occurredAt`은 event-update 레코드에 싣지 않는다(보관 정책
  만료 기준이라 Edge 입력으로 움직이면 안 된다).
- `edge_dispatch.py:536-538` — 미래 activation receipt 거부(`RECEIPT_MISMATCH`,
  cross-device/timing oracle을 만들지 않도록 verdict는 일반적으로 유지).
- `edge_dispatch.py:315-320` — 재생에서도 `receipt.activated_at > recorded_at` 거부.
- Edge C++ 대칭: `edge/manifold-runtime/include/ksi/control_plane/supervisor.hpp:48-51` —
  미래 heartbeat 허용창 1초(`kHeartbeatFutureToleranceMs`), 초과 시 기록 거부.
  근거: NTP 점프가 `last_heartbeat`를 오염시키면 이후 모든 정상 heartbeat가
  `kStaleIgnored`로 무시돼 임무 내내 영구 `FAIL_CLOSED`에 갇힌다.
- `supervisor.hpp:56-59` — 상태기는 **내부에서 시계를 읽지 않는다**(호출자가 `now`를
  소유) → replay/HIL 결정성.
- `acquisition/models.py:322` — capability `checkedAt`은 snapshot `observedAt` 이후일 수 없다.

### Enforcement paths

수신 경계 + 재생 경계 양쪽.

### Potential bypass paths

없음.

### Restart/recovery behavior

재생이 같은 시각 검증을 다시 태운다.

### Existing tests

`tests/contract/test_events_triage.py:1249`(occurredAt이 Edge 입력으로 움직이지 않는다),
`tests/contract/test_edge_dispatch_contracts.py`,
`tests/golden/test_telemetry_interp*.py`,
`edge_runtime_tests.cpp` `TestTelemetryAlignment`(`:894`), 제어평면 테스트.

### Missing tests

없음.

### Classification

VERIFIED

### Failure consequence

P1 — 감사 시간축 붕괴, Edge의 영구 FAIL_CLOSED 래치.

### Recommended next investigation

없음.

---

# Capability 증거·승격 전용 질의 6문

## 1. 어떤 불변식이 성립해야 하는가

네 값 사이에 성립해야 할 문장은 다음 다섯 개다(현재 어느 것도 코드로 표현돼 있지 않다):

> **C1 (근거 필수)** 어떤 capability가 `VERIFIED`이면, 그 상태를 만든 11필드
> `SpikeEvidence` 레코드가 durable하게 존재하고 조회 가능하다.
>
> **C2 (재시작 보존)** 재시작 전후로 같은 capability는 같은 상태를 갖는다.
> 상태는 프로세스 수명이 아니라 원장 수명을 갖는다.
>
> **C3 (노출 종속)** `list_operational()`이 노출하는 집합은 C1을 만족하는 집합과 정확히
> 같다. 증거 없이 노출되는 항목도, 증거가 있는데 노출되지 않는 항목도 없다.
>
> **C4 (회귀 가능)** `VERIFIED → BLOCKED` 강등은 증거 요구 없이 즉시 가능하고,
> 재승격은 **새** 증거를 요구한다(옛 증거를 물려받지 않는다).
>
> **C5 (승인 주체)** 증거를 원장에 넣는 주체는 검증 대상 장비 자신이 될 수 없다.

C4는 이미 `registry.py:169-177`에 코드로 있고(강등 시 `spike_evidence=None`),
C5는 `EquipmentSupportStore`가 `EQUIPMENT_SUPPORT_APPROVE` 권한으로 구현한 형태가 있다.
C1~C3만 존재하지 않는다.

## 2. 지금 이 불변식을 표현할 인프라가 있는가

**부분적으로 있다.** 판정 로직은 완성돼 있고 영속 계층만 없다.

이미 있는 것:
- 전이표 + 증거 게이트: `ksi_domain/capability.py:68-95`
- 구조화 증거 계약: `ksi_domain/spike_evidence.py`(11필드, `failure_result` 필수)
- 노출 게이트: `registry.py:185-193`
- 강등 시 증거 소거: `registry.py:169-177`

없는 것: journal, replay, HTTP 표면, 승인 권한, 조립 배선.

## 3. 어떤 기존 저장 원시가 참여할 수 있는가

**`EquipmentSupportStore`가 정확한 선례다.** 같은 문제(증거 기반 단계 승급, 안전 표시,
운영 UI 노출)를 이미 durable하게 푼 구현이 저장소 안에 있다:

- `services/core/src/ksi_core/equipment_support.py:180-262` — `DurableJournal` 위의 store,
  `_replay`(`:199`)가 live와 **같은 판정 함수**를 다시 태운다.
- `:262` `register` — 항상 최하위 단계로만 등록(임의 단계 직행 우회 차단).
- `:296` `transition` — 승급은 한 단계씩 + 증거, 강등은 증거 없이 즉시.
- `:525-600` HTTP 라우터 + `Permission.EQUIPMENT_SUPPORT_APPROVE`(`auth.py:180`).
- `:512-523` — 표시값(`productionSupported`)은 파생 계산으로만 낸다.
- 자체 문서화된 함정: `:35-45` — **재생이 현행 게이트로 과거 레코드를 판정하므로**
  게이트를 조일 때 기존 원장이 기동 불가가 될 수 있다(INV-A08).

그 밖에 참여 가능한 원시:
- `DurableJournal`(회전·봉인·재생 전부 제공)
- `EvidenceStorage`(raw log 아티팩트 보관 — `SpikeEvidence.raw_log_ref`가 이미 그 자리를 비워둠)
- `DeviceAttestationRegistry`(`device_attestation.py:1-8`) — HTTP 등록 표면 없이 운영이
  out-of-band로 공개키를 넣는 패턴. **offline signed attestation import**를 원한다면
  이것이 이미 있는 신뢰 모델이다.
- `auth.Permission` + `_ROLE_PERMISSIONS`(승인 권한 신설 자리)

## 4. 무엇이 없는가

1. `capability-evidence.jsonl` journal과 그 위의 store(= `EquipmentSupportStore` 형태).
2. `create_app(registry=...)` 배선 — 현재 `app_assembly.py`가 넘기지 않는다.
3. 승격 표면(HTTP 또는 기동 시 서명된 파일 import)과 그 권한.
4. `SpikeEvidence`의 wire 계약(`contracts/schemas/`에 대응 스키마가 없다).
5. 증거 digest / 중복·replay 방어 / 하드웨어·펌웨어·경로·transport·build 바인딩.
6. 조직 범위 결정 — capability는 **제품 전역** 사실인가 조직별 사실인가.
   (`EquipmentSupportStore`는 전역으로 결정했다 — `app.py:568-572`가 "현장·임무와 무관한
   제품 전역 사실이라 대조할 상대가 없다"고 명시. 같은 논리가 적용될 가능성이 높다.)
7. 게이트 버전 기록 / 원장 마이그레이션 절차(INV-A08의 알려진 함정).

## 5. `/capabilities`를 비어 있지 않게 만드는 것만으로 다른 불변식이 깨질 수 있는가

**예 — 세 가지를 확인했다.**

**(a) INV-A22가 자명한 참에서 실질 게이트로 바뀐다.** 지금은 공집합이라 노출 게이트가
시험된 적이 없다. `list_operational()`의 소비자는 `/capabilities` 하나뿐이지만
(`grep` 확인), 대시보드가 이 값을 읽기 시작하면 UI가 `state` 문자열을 스스로 해석하는
경로가 생길 수 있다 — `equipment_support.py:31-34`가 정확히 그 실패를 경고한다
("화면이 `state` 문자열을 보고 스스로 판단하면 새 단계가 추가되는 날 조용히 틀린다").

**(b) INV-A24의 어휘 충돌이 실질 충돌로 승격된다.** 축 1이 `SPIKE-DJI-04`를 `VERIFIED`로
노출하는 동시에 축 2가 같은 기능 영역을 장비 자기신고로 판정하고 있으면, 두 답이
운영자에게 동시에 보인다. **승격 구현 전에 어휘를 정리해야 한다.**

**(c) INV-A08의 함정을 그대로 밟는다.** 새 store의 `_replay`가 현행 게이트로 과거
레코드를 판정하므로, `SpikeEvidence` 필드를 하나라도 추가하는 순간 기존 원장이 기동
불가가 된다. `EquipmentSupportStore`가 이 대가를 이미 문서화했고, capability 원장은
**실기 증거라 재작성이 불가능**하므로 더 위험하다.

추가로: 노출은 늘리는 방향이므로 **`/capabilities`는 무인증 공개 표면**임을 유지해야
한다(`app.py:597-599`가 이미 firmware/PSDK 버전을 제외하는 이유). 승격이 구현되면
공개 응답에 무엇이 실리는지 다시 심사해야 한다.

## 6. 구현 착수 전에 무엇이 증명돼야 하는가

1. **어휘 결정** — 축 2의 `VERIFIED`를 개명할 것인가, 두 축을 명시적으로 다른 개념으로
   문서화할 것인가. (질의 5b)
2. **범위 결정** — 전역인가 조직별인가. `EquipmentSupportStore`의 전역 결정이 그대로
   적용되는지 대표자 확인.
3. **승인 경로 결정** — HTTP `ADMIN` 라우트인가, 기동 시 서명된 파일 import인가.
   후자면 `DeviceAttestationRegistry` 패턴을 그대로 쓸 수 있고 "원문 자격을 프로세스가
   모른다"는 기존 규율과 정합한다.
4. **게이트 버전 규약** — 증거 스키마가 나중에 조여질 것을 전제로, 레코드에 게이트
   버전을 남길지 마이그레이션 절차를 문서화할지 **먼저** 정한다(INV-A08).
5. **원장 골든 픽스처** — 첫 레코드를 쓰기 전에, 재생 호환을 CI에서 증명하는 픽스처
   체계를 만든다.
6. **초기 데이터는 여전히 전부 `SPIKE_REQUIRED`** — 승격 인프라를 만드는 작업과 실제로
   무언가를 `VERIFIED`로 올리는 작업은 별개 커밋·별개 승인이어야 한다.

---

# 최종 요약

**INVARIANT_AUDIT = MATERIAL_GAPS_FOUND**

근거: **확정된 P0 결함은 없다.** 영속성·서명·조직 경계·장비 신원·측정과 판정의 분리 등
안전 축의 핵심 불변식은 실제로 강제되고 재생 경로까지 대칭으로 닫혀 있다.
발견된 것은 P1 3건·P2 6건이며, 그중 둘(INV-A13 TOCTOU, INV-A14 lease 소유권)은
**문서화된 정상 운용 방식에서 재현 가능**하므로 `VERIFIED`로 종결할 수 없다.

## 시스템 중요도 상위 10개 불변식

| 순위 | 불변식 | 분류 |
|---|---|---|
| 1 | INV-A01 fsync 이후에만 성공 반환 | VERIFIED |
| 2 | INV-A15 실행 주체는 자기 검증을 주장할 수 없다 | VERIFIED |
| 3 | INV-A19 서명된 산출물의 바이트는 원문 보존 | VERIFIED |
| 4 | INV-A16 조직 경계 중앙 상속 | VERIFIED |
| 5 | INV-A03 재생은 live와 같은 게이트를 다시 태운다 | VERIFIED |
| 6 | INV-A09 4중 신원 멱등 + 순서 보존 | VERIFIED |
| 7 | INV-A17 장비 신원은 토큰이 정한다 | VERIFIED |
| 8 | INV-A05 append 예외는 원장을 봉인한다 | VERIFIED |
| 9 | INV-A14 한 작업 = 한 워커 | PARTIALLY_VERIFIED |
| 10 | INV-A13 임무타입 × 현장상태 게이트 | PARTIALLY_VERIFIED |

## P0 findings

**없음.**

`INV-A01`·`A05`·`A15`·`A16`·`A17`·`A19`·`A20`은 실패 시 P0 결과를 낳지만, 전부
`VERIFIED`로 강제되고 있음을 확인했다. 이 감사에서 위반이 확인된 P0급 불변식은 하나도
없다.

## P1 findings

| ID | 요약 | 분류 |
|---|---|---|
| INV-A13 | `precheck_issuance`가 유일한 INV-052 강제 지점인데 `record_issuance`가 재확인하지 않아, 발급 도중 현장 상태 변경(운영자 조작 또는 워커 성공 보고에 의한 **자동** 전진)이 게이트를 우회할 수 있다 | PARTIALLY_VERIFIED |
| INV-A14 | lease 소유자가 워커 인스턴스가 아니라 토큰 principalId라, 문서화된 확장 방식(단일 토큰 + 프로세스 복제)에서 같은 작업이 동시 실행된다 | PARTIALLY_VERIFIED |
| INV-A21 | 처리 산출물의 digest는 워커 신고값이며 바이트 재검증이 없다(명시적 범위 밖). INV-A14와 결합하면 원장과 스토리지가 사고로 갈라질 수 있다 | PARTIALLY_VERIFIED |

INV-A10(ACK 2단계 비원자성)은 Core 단독 자기복구가 없다는 점에서 P1 결과를 갖지만,
Edge 계약이 성립하는 한 불변식 자체는 유지되므로 위 표에는 넣지 않았다.

## 가장 가치가 높은 미작성 테스트 5개

1. **발급 중 현장 상태 전이 경합** — `AUTONOMOUS_PATROL` 발급이 진행되는 동안 현장을
   `SUSPENDED`로 전이시켰을 때 계약이 기록되는지. (INV-A13. Core 계약 스위트에 이 영역
   동시성 테스트가 **하나도 없다**.)
2. **같은 토큰 두 호출자의 lease 경합** — 동일 principalId로 같은 job을 두 번
   `acquire_lease` 했을 때 둘 다 통과함을 명시적으로 고정. (INV-A14)
3. **처리 산출물 digest 불일치 미탐지** — 원장 digest와 스토리지 바이트가 다를 때 어떤
   경로도 이를 잡지 않음을 고정(문서화된 경계를 테스트로도 박는다). (INV-A21)
4. **회전 중 read-only 재생** — writer가 회전하는 동안 `open_read_only`가 레코드를
   잃는지. 보관 정책 dry-run의 정확성이 여기에 달렸다. (INV-A06)
5. **capability 승격의 재시작 보존** — 지금 쓰면 실패하는 red test. 그 실패 지점이
   INV-A23 gap의 정확한 크기다.

부가(6번째 가치): `EventStore`가 봉인 시 events.jsonl의 writer 잠금을 놓는 동작을
고정하는 테스트(INV-A02).

## 외부 증거가 필요한 findings

| 항목 | 필요한 증거 |
|---|---|
| INV-A02 / A07 (원장 규모) | 실운영 journal별 records/bytes, cold-start 시간, peak RSS — Codex 검토의 동일 과제 |
| INV-A08 (게이트 조임 위험) | 실운영 원장이 존재하는 시점 이후에만 실재하는 위험 |
| INV-A14 (실제 노출) | 워커를 2개 이상으로 확장해 운용한 적이 있는지 |
| INV-A24 (실제 노출) | `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=true`인 배포가 있는지 |
| INV-A25 (백업 범위) | `deploy/bin/backup-vm.sh`가 `.env`/policy pack을 포함하는지 |
| Capability 축 1 전체 | HIL 실기 증거 자체 — 저장소로 대체 불가 |

## 고치면 안 되는 것 (의도된 아키텍처 제약)

1. **단일 노드 writer 가정** — ADR-KSI-008 §138-140이 다중 인스턴스를 DB 전환 trigger로
   명시. 파일 journal은 그 전 단계의 채택된 결정이다.
2. **`/capabilities`의 빈 기본값** — INV-041의 의도 그 자체. 부채는 빈 응답이 아니라
   승격 경로 부재다(INV-A23).
3. **`dji-gateway`의 런타임 host 부재** — HIL adapter 선정 전 host를 만들면 production
   mock fallback이 된다(INV-040/041 위반).
4. **처리 산출물 digest의 producer-claim 성격** — `processing_jobs.py:128-131`이 명시적으로
   범위를 그었다. 강화 자체는 권장하지만(INV-A21 권고), "이 모듈이 계보를 강제하고 내용을
   강제하지 않는다"는 경계 자체는 유지되어야 한다.
5. **보관 정책의 수동 실행** — `retention.py:19-24`. 데이터를 지우는 코드가 아무도
   부르지 않았는데 도는 것보다 낫다.
6. **워커의 원본 2회 다운로드** — `worker.py:50-55`의 명시적 절충.
7. **`open_read_only`가 flock을 잡지 않는 것** — dry-run이 서버 정지를 요구하면 아무도
   보지 않게 된다(`durable_journal.py:134-137`). 고칠 것은 회전 경합이지 잠금 정책이 아니다.
8. **재생이 현행 게이트로 과거를 판정하는 것(INV-A08)** — "느슨하게 재생"은 원장 조작을
   게이트 우회로 만든다. 대가를 없애는 것이 아니라 관리하는 것이 답이다.

## durable capability evidence/promotion은 여전히 정당한 개발 후보인가

**예. 다만 착수 전 선행 결정 4건이 필요하다.**

정당한 이유(이 감사에서 새로 확인한 것):
- 승격 로직·증거 계약·전이표·강등 규칙은 **이미 완성돼 있고 테스트도 있다**(35 passed).
  없는 것은 영속 계층 하나다 — 즉 작업 범위가 좁고 경계가 명확하다.
- 같은 문제를 durable하게 푼 선례가 저장소 안에 있다(`EquipmentSupportStore`).
  설계를 새로 발명할 필요가 없다.
- 부재의 위험이 **시간에 따라 커진다** — 첫 HIL 통과 시점에 우회 압력이 최대가 되고,
  그때 급조한 경로는 증거 승인·감사 계보·재시작 결정성을 배포마다 다르게 만든다.

다만 우선순위를 낮추는 요소:
- 현재 어떤 잘못된 허용도 만들지 않는다(fail-closed). P2다.
- **INV-A24 어휘 충돌을 먼저 정리하지 않으면**, 승격 구현이 두 개의 `VERIFIED`를 코드로
  굳혀 나중에 되돌리기 더 어려워진다.

권장 순서: **어휘 결정(질의 6-1) → 범위·승인 경로 결정(6-2, 6-3) → 게이트 버전 규약과
원장 골든 픽스처(6-4, 6-5) → 그 다음에 store 구현.**
그리고 이 감사가 발견한 P1 2건(INV-A13, INV-A14)은 capability 작업보다 앞선다 — 둘 다
지금 운용 중인 경로에서 재현 가능하고, INV-A14는 수정 비용이 작다.

---

## 부록 — 이 감사의 방법과 한계

- 실행 코드·헤더·계약 스키마·배포 정의·테스트를 직접 읽었다. 파일명 기반 추론은 배제했다.
- 각 불변식마다 ① 강제 지점 전수 검색 ② 우회 경로 검색 ③ 테스트 검색 ④ 문서 대조를
  수행했다. 문서가 코드와 충돌하면 코드를 정본으로 삼았다.
- 라우트 핸들러가 sync `def` 61개 / `async def` 0개임을 확인해, Starlette 스레드풀에서의
  실제 병렬성을 전제로 경합을 평가했다.
- Core 계약 스위트에서 동시성 테스트를 검색한 결과 관련 테스트가 0건임을 확인했다
  (`threading`/`concurrent` 사용 6파일 중 store·API 경합을 다루는 것은 없음).
- **실행하지 않은 것**: 실장비/HIL, production 원장 크기·cold-start·RSS 측정,
  `deploy/bin/*.sh` 내용 검토, 부하·경합 재현 실험. 이들에 의존하는 결론은 전부
  `NEEDS_EXTERNAL_EVIDENCE`로 표시했다.
- 제품 코드를 수정하지 않았다. 생성한 파일은 이 문서 하나다.
- 이미 dirty였던 작업 트리의 어떤 변경도 되돌리거나 stage·정리하지 않았다.
