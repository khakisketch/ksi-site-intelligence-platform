# Core 권위와 운영 경계

Core는 조직·현장·구역 권한을 확인하고 등록·검사·목적별 판정·작업·결과 및 근거 기록의 정본을 제공한다. 별도 워커와 API/MCP/Console은 새로운 권위를 만들지 않는다.

- 제출된 바이트의 출처·digest와 사용 목적을 확인한다. 고객의 전체 촬영 원본이나 managed reconstruction 자격을 외부 산출물 경로에 요구하지 않는다.
- 신원은 승인된 issuer/subject·조직/리소스 매핑에 묶인다. 초기 현장 등록은 [ADR-KSI-040](../../docs/architecture/ADR-KSI-040-site-bootstrap-and-grant-ownership.md)을 따른다.
- 철회·만료가 있으면 새로운 사용을 차단하고 감사·재현을 위한 불변 근거를 보존한다. 응답이 불명확한 접수는 조용히 다시 쓰지 않고 기존 요청의 상태를 확인한다.
- [계약](../../contracts/)과 [운영 시작 조건](../../deploy/README.md), [검사기 호스트 수락](../../docs/ops/PARSER_SANDBOX_HOST_REQUIREMENTS.md)을 함께 확인한다.

## Restart-only registration recovery stop

For the normal platform production factory, `KSI_CORE_REGISTRATION_STOPPED` is
an optional startup setting: absent or the exact string `false` leaves normal
behavior unchanged; the exact string `true`
refuses new Site and WorkArea registrations (including replacements) at Core's
stores. Other values refuse startup. Reads and authorized replays of already
committed bootstrap requests remain available. Site AOI changes, WorkArea
archive, and unrelated writes are not stopped. This is not an HTTP control and
does not erase or reconcile an uncertain browser request.

For an authorized recovery, stop admitting writes to the old writer, drain all
in-flight work, and verify its journal handles are closed before starting the
guarded writer on the **same authoritative journals**. Explicitly set the stop
again on every restart. Use source-bound, isolated synthetic instances and
generated data to test registration refusals; never send a valid registration
request to authoritative data as a canary. If the wrong writer or setting is
active, that request could create a real Site or WorkArea.

For a live cutover, use approved non-mutating deployment/instance and
configuration evidence to identify the running binary, configured stop, the
authoritative journal set and every possible writer; authorized reads may be
checked without changing data. Such evidence is not a harmless functional proof
that every live route and instance enforces the stop. No such live proof is
established here; if writer coverage or effective enforcement cannot be
established, keep registration unavailable and escalate. Reconcile pending
originals before resuming writes. This setting is not persistent or fleet-wide:
all independently writable instances and data stores
must be accounted for. Older Core binaries ignore it; rolling back Core to one
of them is unsafe. The development runner does not read this setting; local
assemblies must explicitly pass `registration_stopped=True` instead. This
documentation neither activates the setting nor grants deployment authorization.
