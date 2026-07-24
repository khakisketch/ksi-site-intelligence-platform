# ADR-KSI-002 — Mission Contract 서명 정책

- 상태: ACCEPTED (2026-07-25, 대표자 반영사항 6)
- 관련: INV-011, REQ-MSN-101, MASTER_PRD §8.3·§21.4

## 맥락

`mission-contract.v1.1.json`의 `signature`는 `{algorithm, digest}`뿐이라 "서명 필드 존재"만
검증 가능하고 암호학적 검증이 불가능하다. 대표자 지시: 실제 암호학적 서명을 검증하라.

## 결정

1. **알고리즘**: Ed25519 (RFC 8032). 결정적 서명·작은 키·광범위 검증 구현(`cryptography` 라이브러리).
2. **정규화(canonicalization)**: 서명 대상 payload는 계약 JSON에서 `signature` 블록을 제거한 뒤
   **UTF-8 · key 정렬 · 최소 구분자(`,`/`:`) · ensure_ascii=False**로 직렬화한 바이트열
   (RFC 8785 JCS의 실용 부분집합 — 계약 스키마는 부동소수 정밀도 함정이 없는 필드 구성).
3. **digest**: `sha256:<hex>` — 정규화 바이트열의 SHA-256. 감사·중복제거용이며 서명은 digest가
   아니라 **정규화 바이트열 자체**에 대해 수행한다.
4. **스키마 진화**: `mission-contract.v1.2.json`을 **additive**로 신설한다
   (v1.1은 동결 보존). signature 블록:

```json
{
  "algorithm": "Ed25519",
  "keyId": "string (key registry 참조)",
  "digest": "sha256:<hex>",
  "signature": "base64 (정규화 payload에 대한 Ed25519 서명)"
}
```

5. **Key Registry**: `keyId → {public_key, status(ACTIVE|REVOKED), not_after}`.
   검증기는 registry 주입을 받으며, unknown keyId·REVOKED·만료 키는 **검증 실패**다.
6. **검증 실패는 typed 결과**로 반환한다 (`SignatureVerdict`: VALID / INVALID_SIGNATURE /
   UNKNOWN_KEY / REVOKED_KEY / DIGEST_MISMATCH / SCHEMA_VERSION_MISMATCH / EXPIRED_CONTRACT).
   실패 시 계약은 실행 불가 (fail-closed, INV-011).

## 필수 네거티브 테스트 (P0-1 수용기준)

- payload 1필드 변조 → INVALID_SIGNATURE (또는 DIGEST_MISMATCH)
- unknown keyId → UNKNOWN_KEY
- schemaVersion 불일치 → SCHEMA_VERSION_MISMATCH
- REVOKED 키의 유효 서명 → REVOKED_KEY
- signature 블록만 다른 계약 간 digest 동일성 (정규화 안정성)

## 비범위

- 키 배포·회전 운영(KMS/HSM)은 배포 설계 시 별도 ADR.
- Edge Map Package·Model Pack 서명은 동일 정책을 재사용하되 별도 스키마.
