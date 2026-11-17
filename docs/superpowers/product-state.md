# Product state

This page owns the current product goal, slice, next-slice direction, and open product backlog. It is not a task ledger or evidence report. Resume an active Human-assigned checkout task through `.opencode/working-state.md` when present; otherwise use [`../ledger/CURRENT.md`](../ledger/CURRENT.md) for operational routing. Revalidate source and evidence before treating implementation statements as current.

## Goal

물리적 현장 관측을 근거형 Site State/Change로 연결하는 Site Intelligence 기반이다. 공간데이터 제공·외부 재사용과 고정 분석의 API·MCP 제공은 두 제품 경로다 (ADR-KSI-038/039). 고객 원본과 재구성 실행은 고객 장비에 남고, KSI는 파생 산출물의 등록·검사·조건을 충족한 분석과 근거를 소유한다 (ADR-KSI-036). 비행·자율 취득·전술 인지/제어·고객 production 재구성은 out-of-product다 (ADR-KSI-039).

## Current slice
- Name: 외부 재구성 산출물 파일 검사와 용도별 사용 적합성 판정
- Acceptance (user-visible end-to-end): EXT-VAL-01 actual sealed derived bytes format and spatial metadata inspection; EXT-VAL-02 customer declarations separated from measured facts; EXT-VAL-03 versioned Core per-use display comparison height volume decisions with evidence-bound positive and negative paths; EXT-VAL-04 explicit remediation without blanket raw-upload or DSM absence denial; EXT-VAL-05 bounded resources transient retry fencing tenant isolation and restart replay; EXT-VAL-06 mounted Core and processing-controller workflow without managed identity impersonation; EXT-VAL-07 reviewed detailed plan contracts tests independent and integrated verification; EXT-VAL-08 durable docs goal evidence and local versus release acceptance boundaries
- Plan ledger: docs/superpowers/plans/2026-09-07-external-artifact-validation.md
## Next slice

- Open, user-approved work belongs in its named acceptance owner. Obsolete PRD acquisition phases do not create executable or active product scope (ADR-KSI-039).
- The pilot first-release gate remains open: customer-owned reconstruction plus KSI-derived-result registration, inspection, suitability, and customer/operations acceptance. Capture and customer production reconstruction are excluded from KSI responsibility.

### 에이전트 목표 방향 (2026-11-11 사용자 결정)

- 목표는 업무 완수형 AI다. 첫 검증 시나리오는 2시점 DSM 변화 전수 조사 → 이상 구역 탐색·지도 표시 → 근거 포함 보고서 초안 생성이며, 성공 기준은 절차 미지정 상태에서의 자율 수행·지도와 결과물 반영·미검증 수치 미생성이다. 권한 경계와 상세 목표는 [제품 헌법](../product/PRODUCT_CONSTITUTION.md)의 에이전트 목표와 실행 경계를 따른다. 이 방향은 EXT-VAL-01..08이나 별도 host/customer 수락을 변경하지 않는다.

### 개발 우선 방향 (2026-11-11 사용자 결정)

- 기존 사진측량 산출물의 자료등록 자동화, DSM 분석의 정확성·정합 안정성·근거 검증, 대용량 영상 표시, 작업구역 편집 UX에 집중한다. 정상 구현을 보존하고 실제 사용자 불편과 수락 기준에 연결되는 부분만 개선한다. 이 방향은 EXT-VAL-01..08이나 별도 host/customer 수락을 변경하지 않는다.
- 우선 검토 대상은 Pix4D·Terra 결과 폴더 인식으로 기존 등록 화면과 검사 경로의 반복 입력을 줄이는 것이다. 실제 구현 범위는 기존 등록 경로·실행 위치·고객 자료를 확인해 확정하며, 범용 수집 프레임워크나 재구성 실행을 만들지 않는다.
- GDAL 신규 통계·비교 기능과 xDEM은 기존 워커를 대체할 기본 엔진이 아니라 필요한 기능의 비교 실험 후보로 둔다. GRASS/QGIS는 필요할 때 독립 검증 환경에서 사용한다. 동일 데이터·구역·유효 픽셀·허용오차에 대한 수치 차이, 시간·메모리·실패 처리와 대상 OS의 GDAL/PROJ/GEOS 패키징 비용을 확인한 뒤 부분 채택한다. 속도·정확도 개선은 아직 입증되지 않았다.
- rio-tiler·COG·Terra Draw 등은 기존 부분 읽기·표시·편집 기능의 부족이 확인될 때 검토한다. 새 타일 서버·지도 엔진 교체·STAC·공간 DB·3D 플랫폼은 선행 과제가 아니다. 설계면 비교와 벤더 API 확장은 기존 계약과 별도 고객 수락 범위에서 판단한다.

### 전문 측정·분석 기본기 (2026-11-16 사용자 결정)

- 에이전트 연동은 전문 도구를 대신하지 않고 같은 도구를 쓴다. 열람·날짜 비교·선/구역 측정·물량·저장·결과 전달은 포기하지 않을 기본기이며, UI·API·CLI·MCP가 같은 Core 계약과 결과를 사용한다.
- 첫 신규 전문 기능은 저장한 **선의 표면 단면**(단일 표면 → 같은 선의 두 시점 비교)이다. 선에서 체적을 만들지 않는다. 구역 물량은 기존 마스크·체적 계산을 지도의 저장 구역과 연결하는 별도 단계이고, 적치량·설계 대비는 각각 입력·기준면·수락을 확인한 뒤 좁은 프로필부터 진행한다.
- 이 결정은 EXT-VAL-01..08, P-AC-01..06, 고객·호스트·현장 수락을 바꾸지 않으며 기능 존재를 지원·출시로 말하지 않는다. 단계별 기준과 현재 증거는 [표면 측정 v1 수락 목표](../acceptance/SURFACE_MEASUREMENT_V1_ACCEPTANCE.md)가 소유한다.

## Backlog

- 공간데이터 제공과 반복분석의 고객·권리·운영 수락은 EXT-VAL과 별도로 남아 있다. 새 scope나 우선순위는 사람의 현재 지시와 검증 가능한 현행 acceptance owner로 확정한다.
- [현재 작업과 출시 제한](../ledger/CURRENT.md)
