"""KSI Geo Spatial — 측지 기반(ADR-KSI-016 D3 의 Site reference frame 계층).

## 이 패키지가 존재하는 이유

실태 조사(2026-08-07) 시점에 이 저장소에는 좌표변환이 없었다 — `pyproj` 사용
0건, 수직기준(지오이드) 처리 0건. CRS 는 `ProcessingArtifact.crs` 문자열
태그로만 흘렀고, 실제 변환은 어디서도 수행되지 않았다. 그 상태에서 "두 시점의
표고를 비교한다"거나 "설계 계획고 대비 현재 지반고"를 말하면 숫자가 조용히
틀린다 — 한국에서 타원체고와 정표고(표고)의 차이는 20~30m 대다.

## 두 축을 분리한다

- **수평(:mod:`ksi_geo_spatial.crs`)** — EPSG 투영좌표계 간 재투영. 지오이드
  격자 없이 즉시 동작한다(PROJ 의 EPSG DB 만 필요).
- **수직(:mod:`ksi_geo_spatial.vertical`)** — 타원체고↔정표고. **격자 데이터가
  있어야만 성립하고, 없으면 fail-closed 로 거부한다.** 0 으로 대치하지 않는다.

이 분리가 중요한 이유: 수평은 지금 완전히 쓸 수 있고, 수직은 데이터 확보와
정확도 검증이 끝나기 전까지 상용 경로에서 쓸 수 없다(ADR-KSI-016 §결과,
risk `geoid-grid-provenance-unverified`). 한 모듈에 섞으면 "좌표변환이 된다"는
말이 두 축 모두를 가리키는 것으로 오해된다.

## INV-020 강제 지점

"CRS·수직기준이 다른 산출물을 직접 비교·병합하지 않는다"를 코드로 막는 곳이
:func:`ksi_geo_spatial.crs.assert_same_crs` 다 — 비교 연산의 입구에서 부른다.
"""

from __future__ import annotations

__all__ = ["crs", "vertical"]
