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
- 자료 올리기와 상세 등록에서 DJI Terra와 PIX4Dmapper 결과 폴더를 선택할 수 있다. 브라우저가 정사영상·DSM 후보를 찾고 GeoTIFF 머리말로 종류를 확인한다. 여러 촬영이나 처리 결과가 함께 있으면 운영자가 한 묶음을 고른다. 폴더 경로는 선택 화면에서만 쓰며 촬영일·제작사 신고는 기존 등록 절차를 따른다. 인식하는 배치는 [DJI Terra 출력 안내](https://dl.djicdn.com/downloads/dji-terra/20241008/DJI%20Terra%20Operation%20Guide%20v4.2.pdf)와 [PIX4Dmapper 결과 구조](https://support.pix4d.com/hc/en-us/articles/202558649)를 기준으로 한다.
- GDAL 신규 통계·비교 기능과 xDEM은 기존 워커를 대체할 기본 엔진이 아니라 필요한 기능의 비교 실험 후보로 둔다. GRASS/QGIS는 필요할 때 독립 검증 환경에서 사용한다. 동일 데이터·구역·유효 픽셀·허용오차에 대한 수치 차이, 시간·메모리·실패 처리와 대상 OS의 GDAL/PROJ/GEOS 패키징 비용을 확인한 뒤 부분 채택한다. 속도·정확도 개선은 아직 입증되지 않았다.
- rio-tiler·COG·Terra Draw 등은 기존 부분 읽기·표시·편집 기능의 부족이 확인될 때 검토한다. 새 타일 서버·지도 엔진 교체·STAC·공간 DB·3D 플랫폼은 선행 과제가 아니다. 설계면 비교와 벤더 API 확장은 기존 계약과 별도 고객 수락 범위에서 판단한다.

### 전문 측정·분석 기본기 (2026-11-16 사용자 결정)

- 에이전트 연동은 전문 도구를 대신하지 않고 같은 도구를 쓴다. 열람·날짜 비교·선/구역 측정·물량·저장·결과 전달은 포기하지 않을 기본기이며, UI·API·CLI·MCP가 같은 Core 계약과 결과를 사용한다.
- 첫 신규 전문 기능은 저장한 **선의 표면 단면**(단일 표면 → 같은 선의 두 시점 비교)이다. 선에서 체적을 만들지 않는다. 구역 물량은 기존 마스크·체적 계산을 지도의 저장 구역과 연결하는 별도 단계이고, 적치량·설계 대비는 각각 입력·기준면·수락을 확인한 뒤 좁은 프로필부터 진행한다.
- 단일 DSM·저장 선 단면은 명시적으로 조립한 Core의 요청자·일꾼 HTTP와 불변 결과 저장·현재 권한 재확인까지 연결됐다. Console에서 선 그리기, 날짜별 단면 요청·읽기와 수직 기준 선언을 제공한다. 두 시점의 높이차는 같은 선 개정과 표본 위치, 두 DSM의 독립 근거, 승인된 호환성 기록을 확인해야 읽을 수 있다. 운영자 CLI로 같은 결과와 비교를 다시 읽을 수 있다. 단면 워커는 원본 바이트와 격자를 대조하고 고정된 Linux 실행기에서 계산한다. 운영 호스트의 격리 검증·활성화, 실제 호환성 승인 자료와 MCP 단면 접근이 남아 있다.
- 정식 Core는 기존 공간데이터 구성에 단면용 보호 설정을 추가한 배포에서만 단면 작업을 장착한다. 두 시점 비교는 운영자가 서명한 정확한 자료 쌍과 작업구역의 승인을 사용한다. 승인 철회 후에는 저장된 비교 주소에서도 수치를 다시 읽을 수 없다. 현재 근거는 시험용 서명과 공개 연구 자료를 각각 사용한 로컬 검증이다. 단계별 기준과 고객·호스트·현장 수락 범위는 [표면 측정 v1 수락 목표](../acceptance/SURFACE_MEASUREMENT_V1_ACCEPTANCE.md)가 소유한다. EXT-VAL-01..08과 P-AC-01..06은 별도 기준을 따른다.

### 자료 올리기·사용성 (2026-11-17 사용자 결정)

- UI·UX뿐 아니라 실제 공간 자료를 올리고 쓰는 흐름의 사용성을 제품 개발에 포함한다. 첫 작업은 올리기 전 점검이다. 파일을 고르면 브라우저가 앞부분만 읽어 KSI 검사가 거부할 조건과 다시 내보내는 방법을 알려 주고, 검사 거부 사유를 한국어로 설명한다. 이 안내는 판정이 아니며 등록을 막지 않는다. 최종 판정은 등록 뒤 Core 검사만 만든다.
- 수직 기준이 없는 일반 DSM은 사용자가 수직 기준을 **선언**해 높이·단면을 읽게 하는 방향으로 정했다. 선언값은 파일에서 관측한 값과 화면·결과에서 항상 구분한다. 선언 원장·높이 판정·자료 상세 화면은 구현·검증됐다(위 "전문 측정·분석 기본기"). 선언값은 Core가 검증하지 못하는 사용자 주장이며 관측값과 항상 구분해 표시한다.
- 자료 화면에서 `자료 올리기`를 열면 정사영상과 DSM을 함께 또는 차례로 선택할 수 있다. 브라우저는 파일 머리말로 종류를 확인하고, 위치를 해석할 수 있는 파일의 범위를 작업구역과 함께 지도에 표시한다. 범위를 표시할 수 없는 파일은 화면에서 종류를 알려 준다. 촬영 시작·종료 시각이 있으면 한 화면에서 작업 생성부터 봉인까지 진행한다. 촬영일만 알거나 시점이 미상인 자료는 같은 구역의 `상세 등록`을 이용한다. 각 파일은 전송 직전에 권한을 발급받아 한 번의 PUT으로 올린다. 봉인 응답이 끊기면 같은 제출에서 봉인을 다시 확인한다. 저장소에 파일이 없거나 신고한 내용과 다르다고 Core가 확인하면 같은 제출의 파일을 다시 올릴 수 있다. 등록 작업은 1024px 이상에서 제공한다.
- 작업구역과 파일 범위는 각 자료의 좌표계에서 WGS84로 변환해 표시한다. 변환할 수 없으면 겹침 판정을 생략한다.
- 봉인 뒤에는 검사 상태와 등록 기록을 확인하고 자료 상세로 이동할 수 있다. 검사 상태 조회가 끊기거나 정책을 기다리는 동안에도 같은 제출을 다시 조회할 수 있다. 검사에서 수직 기준이 비어 있는 DSM을 확인하면 기준을 아는 사용자를 자료 상세의 선언으로 안내한다. 운영 저장소와 현장 회선은 별도 검증 대상이다.
- 자료 표는 구역 안에서 촬영일이 최신인 자료부터 페이지를 나누고 촬영일 미상은 뒤에 둔다. 검색·필터는 현재 페이지에 적용한다. 거부된 파일의 상세에서 검사 사유와 내보내기 방법을 확인하고 해당 작업의 등록 버전으로 이동한다. 작업이 열려 있으면 최신 V3 봉인본의 **수정본 등록**에서 기존 촬영일과 출처를 확인하고 새 버전에 포함할 파일을 선택한다. 이전 버전의 파일과 검사 기록은 보존되며, 새 버전의 파일을 다시 검사한다. 작업 기록에서 각 파일의 자료 상세로 돌아갈 수 있다.
- 검사한 DSM의 자료 상세에서 공간 지도를 열면 해당 자료가 선택되고, 측정 선을 열면 파일과 촬영일이 따라간다. 저장한 선을 고르거나 자료 격자 경계를 보며 새 선을 그릴 수 있다. 그리기를 취소하면 보던 선과 날짜 선택으로 돌아간다. 선을 저장한 뒤 사용자가 단면을 요청하면 해당 파일과 선 개정으로 높이를 읽는다. [봉길리 공개 DSM 검증](../acceptance/SURFACE_MEASUREMENT_V1_ACCEPTANCE.md#두-시점-비교의-수치-확인)
- 이어서 검토할 항목은 축소본이 있는 파일의 올리기 전 미리보기와, 올릴 때 같은 구역의 기존 DSM과 좌표계가 다르면 알리는 안내다. 한국 UTM 51N·52N은 분석 좌표계에 포함돼 있고 자동 재투영은 하지 않는다. EXT-VAL-01..08과 고객·현장 수락은 해당 수락 기준을 따른다.

## Backlog

- 공간데이터 제공과 반복분석의 고객·권리·운영 수락은 EXT-VAL과 별도로 남아 있다. 새 scope나 우선순위는 사람의 현재 지시와 검증 가능한 현행 acceptance owner로 확정한다.
- [현재 작업과 출시 제한](../ledger/CURRENT.md)
