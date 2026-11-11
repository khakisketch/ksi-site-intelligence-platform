# Worker lease ownership contract

Applies to REQ-OPS-102 and REQ-SEC-101. Authentication, current lease ownership and artifact authority are separate.

### 4.1 정본 불변식

1. **Lease ownership** — Job `J`의 현재 active lease generation `G`를 소유한 worker
   instance만 `J`를 renew, read input, transition, request upload authority, register
   artifact, complete 또는 fail할 수 있다.
2. **Authentication is not ownership** — 인증 credential은 permission과 organization을
   증명하고 lease ownership을 대신하지 않는다.
3. **Monotonic fencing** — 새로운 acquisition identity가 만료됐거나 다른 acquisition을
   대체해 새 소유권을 취득할 때만 `G+1`이다. 같은 active acquisition의 exact CLAIM retry와
   current-owner RENEW는 `G`를 유지한다. generation은 감소·재사용·client 지정되지 않는다.
4. **Expired means fenced** — expiry에 도달한 generation의 모든 mutation과 heartbeat는
   새 owner의 유무와 무관하게 거부된다.
5. **Side-effect fencing** — artifact upload authority와 storage object location은
   generation에 결속된다. stale generation의 늦은 PUT은 current artifact bytes를
   덮어쓸 수 없다.
6. **Replay-verifiable fencing** — generation 단조성, acquisition identity의 immutable
   binding, owner 일치, renewal high-water 규칙은 replay가 재검증한다. 발급 당시 wall-clock
   만료 판정은 replay가 재현하지 않으며 저장된 `expiresAt`으로 현재 유효성만 계산한다.
7. **One credential, many contenders** — 같은 principal의 서로 다른 instance는 서로 다른
   lease contender다.
8. **Authoritative artifact manifest** — 신규 성공 작업의 유일한 artifact authority는 그
   성공 record가 digest로 결속한 `AuthoritativeArtifactManifestV1`이다. **MUST:** durable
   reference가 있는 artifact를 읽는 어떤 authoritative reader도 site/job/artifact ID에서
   현재 object location을 독립적으로 재유도해서는 안 된다.
9. **Attempt-local files** — 서로 동시에 유효할 수 있는 두 processing attempt는 어떤 writable
   temporary path도 공유해서는 안 된다.

CLAIM response loss is recovered by retrying the exact acquisition identity. A replacement generation gets separate attempt storage and cannot inherit a predecessor's writable paths or artifact authority. Mixed legacy or current journals must replay with their original meaning. Upgrade readers before emitting new records.
