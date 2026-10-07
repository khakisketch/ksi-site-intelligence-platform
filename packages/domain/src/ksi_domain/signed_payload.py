"""중립 payload digest 헬퍼 — 서명대상 정규화와 SHA-256 digest (INV-011).

정규화 규약 자체(key 정렬·최소 구분자·``allow_nan=False`` 등)는
``ksi_domain.canonical_json_bytes`` 가 소유한다. 이 모듈은 그 위에 "최상위
``signature`` 블록은 서명 대상에서 뺀다"는 규칙과 ``sha256:<hex>`` digest
형식을 얹는다 — flight 패키지(``ksi_mission_contracts.signing``)를 거치지
않고 platform reader 가 직렬화를 공유할 수 있게 한다.

이 두 함수는 ``ksi_mission_contracts.signing`` 에서 기계적으로 옮긴 것으로,
바이트·예외·메시지가 원본과 동일하다. 키/서명/검증 구현은 옮기지 않는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes


def canonical_payload_bytes(contract: Mapping[str, Any]) -> bytes:
    """계약 dict의 서명대상 정규화 바이트열 (``signature`` 블록 제외, ADR-KSI-002 §2).

    최상위 ``signature`` 키만 제외한다 — 중첩된 ``signature`` 와 나머지 필드는
    모두 유지된다.

    Raises:
        ValueError: NaN/Infinity 또는 JSON 도메인 밖 타입 포함 — 발행(sign) 시점의
            typed 실패다. verify 경로에서는 외곽 가드가 MALFORMED_CONTRACT 로 강등.
    """
    payload = {key: value for key, value in contract.items() if key != "signature"}
    try:
        return canonical_json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"계약을 정규 JSON 으로 표현할 수 없다: {exc}") from exc


def sha256_digest(payload: bytes) -> str:
    """정규화 바이트열의 SHA-256 digest, ``sha256:<hex>`` 형식 (ADR-KSI-002 §3)."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
