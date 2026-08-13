# Mission Contract 서명키 수명주기 (운영 절차)

- 근거: ADR-KSI-010 §2(파일 공급 유지·회전 절차 명문화), ADR-KSI-002(Ed25519 서명),
  INV-011
- 구현: `services/core/src/ksi_core/signing_keys.py`,
  `packages/mission-contracts/src/ksi_mission_contracts/signing.py`

## 전제

키는 **현장 서버의 로컬 파일**에서 공급한다. KMS 를 쓰지 않는 이유는 서명마다
네트워크 왕복이 생겨 오프라인 현장에서 임무를 발급할 수 없게 되기 때문이다
(ADR-KSI-005). 파일 공급을 택한 이상 **파일 권한과 디스크 암호화가 유일한
보호막**이므로, 아래 배포 전제가 지켜지지 않으면 이 설계는 성립하지 않는다.

**배포 전제 (미충족 시 재검토 대상)**

- 개인키 파일은 `0600`, 소유자는 Core 프로세스 사용자. 느슨하면 기동이 거부된다.
- 서버 디스크는 암호화(LUKS 등). 도난 시 키가 그대로 나간다.
- 현장 서버는 물리적으로 통제되는 공간에 둔다.

## 배치

```
<data-dir>/signing/
  keys.json
  <keyId>.private.pem     # 활성 키만 필요
  <keyId>.public.pem      # 전부(과거 키 포함)
```

```json
{
  "active": "core-2026-08",
  "keys": [
    { "keyId": "core-2026-08", "status": "ACTIVE" },
    { "keyId": "core-2026-02", "status": "ACTIVE", "notAfter": "2026-09-01T00:00:00Z" },
    { "keyId": "core-2025-11", "status": "REVOKED" }
  ]
}
```

`keyId` 는 서명에 실려 나가므로 검증자가 어느 키인지 알 수 있다. 발급은 항상
`active` 하나로만 한다 — 여러 키로 동시에 발급하면 어느 것이 정본인지 잃는다.

## 회전 (정기)

> **compose 배포에서는 이 절차를 소유권 전환으로 감싼다.** 아래 명령은 배포 방식과
> 무관한 형태로 적혀 있는데, `deploy/compose.yaml` 로 띄운 경우 키 디렉터리
> (`deploy/signing-keys/`)의 소유자가 컨테이너 uid(10001)로 넘어가 있어 일반 계정으로는
> 새 파일을 만들 수 없다. 실제로 실행할 명령은 `docs/ops/DEPLOYMENT.md` §2-1 에 있다.

권장 주기는 **6개월**이다. 유출 정황이 없어도 도는 이유는, 회전 절차가 실제로
작동하는지를 사고가 난 뒤에 처음 확인하지 않기 위해서다.

1. 새 키쌍 생성. `keyId` 는 발급 시점을 담는다(`core-YYYY-MM`).
   ```bash
   openssl genpkey -algorithm ed25519 -out <keyId>.private.pem
   chmod 600 <keyId>.private.pem
   openssl pkey -in <keyId>.private.pem -pubout -out <keyId>.public.pem
   ```
2. `keys.json` 에 새 항목을 추가하고 `active` 를 새 `keyId` 로 바꾼다.
3. **이전 키는 지우지 않는다.** `status: ACTIVE` 로 남기고 `notAfter` 를 준다 —
   그때까지 이전 키로 서명된 계약이 검증된다. 값은 **가장 긴 `validForHours`
   보다 넉넉히** 잡는다(그 안에 기체가 들고 있는 계약이 모두 만료된다).
4. Core 재기동. 기동 시 매니페스트가 검증된다 — 활성 키가 REVOKED 이거나,
   개인키와 공개키가 어긋나거나, 권한이 느슨하면 **기동을 거부한다**.
5. `notAfter` 가 지난 뒤 이전 키의 개인키 파일을 파기한다(공개키 항목은 남긴다 —
   "그 시기에 이 키가 있었다"는 사실 자체가 감사 정보다).

## 폐기 (유출 의심)

**폐기는 발급 중단이 아니라 검증 거부다.** 서버가 사라져도 로컬에서 유효한 계약이
살아있는 게 이 제품의 설계이므로(server loss must not invalidate a locally valid
Mission Contract), 폐기는 그 예외를 만드는 **유일한 장치**다.

1. 즉시 회전(위 1~4)으로 새 활성 키를 올린다.
2. 유출 키 항목을 `status: "REVOKED"` 로 바꾼다. Core 재기동 후 그 키로 서명된
   계약은 **전부 검증 실패**한다 — 이미 기체에 내려간 것도 포함이다.
3. 그 키로 발급된 임무가 현장에서 도는 중이면 회수·재발급이 필요하다. 폐기는
   진행 중인 비행을 자동으로 멈추지 않는다(Manifold 는 이미 받은 계약을 로컬
   기준으로 실행한다) — **운영자가 직접 중단시켜야 한다.**
4. 원장에 폐기 사유와 시각을 남긴다.

`KeyRegistry` 에는 REVOKED → ACTIVE 복귀 API 가 **의도적으로 없다**. 상태 변경은
단조 방향뿐이고, 되살리려면 새 `keyId` 로 회전해야 한다 — 설정 재적재로 유출 키가
조용히 부활하는 경로를 막는다.

## 확인되지 않은 것

- **HSM/TPM 도입 시점** — 오프라인을 유지하면서 키를 보호하는 유일한 대안이지만
  현장 서버 사양 확정이 선행돼야 한다(ADR-KSI-010 미해결 항목).
- **회전 주기 6개월의 근거** — 업계 관행에 따른 초기값이다. 파일럿 운영 데이터로
  재검토한다.
