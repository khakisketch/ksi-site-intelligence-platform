# Bearer 토큰 만료·회전 (운영 절차)

- 근거: ADR-KSI-008 §2(파일 공급 토큰 인증), [[SIGNING_KEY_LIFECYCLE]] 와 같은 모양
- 구현: `services/core/src/ksi_core/auth.py`(`TokenStatus`·`PrincipalTokenRecord`·
  `AuthRegistry`), `services/core/src/ksi_core/production.py`(`_parse_principal_tokens`)

## 전제

토큰도 서명키처럼 **digest 를 환경변수(`KSI_CORE_PRINCIPAL_TOKENS_JSON`)로
공급**한다 — 원문 토큰은 배포자만 알고, Core 프로세스는 sha256 digest 만
받는다(`auth.py` 모듈 docstring). 회전이 성립하려면 새로 배포한 토큰과, 아직
기기·운영자 손에 남아 있는 이전 토큰이 **겹치는 구간** 동안 함께 유효해야
한다 — 서명키의 활성 키 + 유예기간 이전 키와 정확히 같은 이유다.

## 형식

```json
[
  {
    "tokenSha256": "<새 토큰의 sha256 digest>",
    "principalId": "op-1",
    "kind": "OPERATOR",
    "role": "ADMIN",
    "deviceId": null
  },
  {
    "tokenSha256": "<이전 토큰의 sha256 digest>",
    "principalId": "op-1",
    "kind": "OPERATOR",
    "role": "ADMIN",
    "deviceId": null,
    "status": "ACTIVE",
    "notAfter": "2026-09-01T00:00:00Z"
  }
]
```

`status`(기본 `"ACTIVE"`, 또는 `"REVOKED"`)와 `notAfter`(ISO 8601 tz-aware,
기본 없음=만료 없음)는 선택 필드다 — 기존 배포(둘 다 생략)는 지금까지와
똑같이 동작한다. **같은 `principalId` 로 여러 항목을 등록할 수 있다** — 단
가리키는 신원(`kind`/`role`/`deviceId`)이 완전히 같을 때만이다. 신원이 다른데
`principalId` 만 같으면 `AuthRegistry` 가 기동을 거부한다(설정 오사고 방지).

## 회전 (정기)

1. 새 토큰 원문을 생성하고(배포자 로컬에서만, 프로세스로 전달하지 않는다)
   sha256 digest 를 계산한다.
2. `KSI_CORE_PRINCIPAL_TOKENS_JSON` 에 새 digest 항목을 추가한다 —
   `status` 생략(=`ACTIVE`), `notAfter` 생략(=만료 없음).
3. **이전 digest 항목은 지우지 않는다.** `status: "ACTIVE"` 로 남기고
   `notAfter` 를 준다 — 그때까지 이전 토큰을 들고 있는 기기·운영자가 계속
   인증된다. 값은 **토큰을 배포·교체할 시간을 넉넉히** 잡는다.
4. Core 재기동. `_parse_principal_tokens` 가 형식을 검증하고(`RuntimeError`
   즉시 거부), `AuthRegistry` 생성자가 불변식(digest 중복·신원 충돌 등)을
   추가로 검증한다 — 어느 한쪽이라도 위반이면 기동을 거부한다.
5. `notAfter` 가 지난 뒤에는 `resolve()` 가 그 digest 를 자동으로 거부한다
   (만료됨 = 401, 미지 토큰과 같은 문구 — 열거 오라클 방지). 다음 정기 배포
   때 항목 자체를 JSON 에서 제거해도 안전하다.

## 폐기 (유출 의심)

**폐기는 발급 중단이 아니라 검증 거부다.**

1. 유출 digest 항목의 `status` 를 `"REVOKED"` 로 바꾼다.
2. 즉시 새 토큰으로 회전(위 1~4)한다 — 폐기된 principal 이 계속 인증을
   필요로 하면 새 토큰 없이는 그 즉시 전부 401 이 된다.
3. Core 재기동 후 그 digest 로는 어떤 요청도 통과하지 못한다 — `notAfter`
   와 무관하게 즉시 적용된다(`resolve()` 가 상태를 만료보다 먼저 본다).
4. `AuthRegistry`/`TokenStatus` 에는 REVOKED → ACTIVE 복귀 API 가 **의도적으로
   없다** — 되살리려면 새 digest 로 다시 발급해야 한다(`KeyRegistry` 와 같은
   단조 방향 원칙).

## 확인되지 않은 것

- **회전 주기의 근거** — 서명키와 마찬가지로 업계 관행 기반 초기값이며, 이
  문서는 절차의 모양만 고정한다. 실제 권장 주기(예: 90일)는 파일럿 운영
  데이터로 재검토한다.
- **자동화 여부** — 지금은 배포자가 수동으로 JSON 을 편집하고 재기동한다.
  토큰 발급·배포를 자동화하는 도구는 이 파일럿 범위 밖이다.
