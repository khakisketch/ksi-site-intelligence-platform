# ADR-KSI-038 — Spatial data and analysis platform for external applications

- Status: ACCEPTED — product direction and staged planning only
- Date: 2026-09-30
- Human decision: 현장 공간데이터를 외부 에이전트·산업용 소프트웨어가 재사용하는 데이터·분석 기반으로 제품을 정의하고, 문서·방향·장기 계획에 반영한다. 이번 지시는 개발 진행을 제외한다.
- Follow-up authority (2026-09-30): 사용자가 이후 개발 전반을 재개하도록 지시했다. 위 Human decision은 최초 문서화 지시의 역사이며 현재 개발 보류를 뜻하지 않는다. 첫 구현 과제는 [SDP-CATALOG-20260930](../superpowers/plans/2026-09-30-spatial-asset-catalog-v1.md)에서 추적한다.
- Requirements: Master PRD §1.1.2 `SDP-REQ-01..08` (product targets; no wire schema assigned).
- Planning ledger: [SDP-20260930](../superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md).
- Supersession: ADR-KSI-037 D1/D2의 제품 전체 범위·고객·첫 MVP 해석을 아래와 같이 확장한다. D3 이후의 분석 의미·권위·정확도·반복 수용 계약은 유지한다. ADR-KSI-036의 고객 소유 재구성·원본 보관·용도별 적합성 경계를 유지한다.
- No implementation claim: 본 결정은 endpoint, schema, STAC conformance, export format, remote MCP transport, client support, 배포 또는 현장 수용 증거가 아니다.

## Context

기존 API-first 방향은 출처·시점·좌표·계산 조건을 가진 분석 기록을 외부에서 재사용하게 한다.
그러나 첫 완성선을 주간 토공 분석에만 두면 외부 프로젝트가 현장 데이터 자체를 활용하는
경로와 책임이 빠진다. 데이터 제공과 서버 분석을 두 가지 제품 기능으로 명시하고,
토공 파일럿의 기존 증거를 재사용하면서 공통 기반을 검증할 별도 데이터 활용 사례가 필요하다.

## D1 — Product identity and customer value

KSI Site Intelligence Platform은 **외부 재구성 엔진이 생성한 현장 공간데이터를
등록·검사·구조화하고, 필요한 공간데이터와 재현 가능한 분석 결과를 API·MCP로 제공하여
고객의 에이전트와 산업용 소프트웨어가 재사용하게 하는 데이터·분석 기반**이다.

데이터 제공과 고정 분석은 **같은 공통 Core 계약을 소비하는 두 가지 활용 방식**이며 별개
제품이 아니다. 이때 보유하는 것은 **관측 범위·관측 시각·유효 조건·미확인 영역·최신성·
변경 이력을 가진 버전화된 현장 관측 기록**이다 — 실시간 디지털트윈이나 현장 전체 상태의
완전 추론이 아니다. 새 최상위 개념이나 별도 ID 체계는 만들지 않고 기존 Site·WorkArea·
Observation Epoch·submission revision·digest 매핑을 재사용한다.

고객 가치는 자료 탐색·공간 전처리·반복 연산·권한·계보·근거 관리를 프로젝트마다 다시
구축하는 부담을 줄이는 것이다. 시간·비용 절감은 실제 외부 개발자의 사용으로 검증한다.
우선 고객 가설은 이미 산출물을 보유하고 타 시스템에 반복 연결하는 건설사 디지털팀,
현장 솔루션 개발사와 SI·AI 개발팀이다. 현장 담당자는 결과 검토자이며 기존 토공
파일럿의 고객 역할도 보존한다. 구매자·지불 의사·지원 비용은 아직 검증되지 않았다.

판정은 **자료 자체의 유효성**, **목적별 사용 적합성**, **분석 결과의 재현 가능성**의 세
층으로 구분한다. 정량 조건이 충족되지 않은 자료가 허용된 열람·추출까지 함께 막히지는 않으며,
열람 가능하다고 정량 사용 가능을 뜻하지도 않는다. 핵심 제품 동작은 **반복 관측**
(`t0→t1` 다음 `t1→t2`)이다: 각 쌍은 새 admission·계산 authority·결과로 결속되고 재사용되는
것은 WorkArea 정의·비교 규칙·연동 흐름이며, 새 관측의 **변경 영향 확인**을 포함한다.

## D2 — Responsibility and two product paths

| Owner | Responsibility |
| --- | --- |
| 고객·재구성 도구 | 촬영·재구성·내보내기, 원본 사진 보관, 자료 제공·처리·반출 권리 |
| KSI Core | 자산·버전·현장·시점 매핑, 용도별 적합성·권한·정책, 작업·결과·근거·계보의 지속 기록 |
| KSI 처리 워커 | Core가 허용한 고정 프로필의 검사·공간 가공·계산과 측정 사실 보고 |
| KSI API·MCP·향후 SDK/CLI | 같은 Core 기록과 허용된 데이터 접근 제공; 클라이언트별 계산·권위 복제 없음 |
| 외부 에이전트·소프트웨어 | 고객 전용 분석·보고·비전 모델·시뮬레이션·업무 통합 |
| 사람 | 결과 사용 목적·업무 검토·공식 승인 및 실제 장비 운용 판단 |

**분석 경로:** 고정된 분석을 요청하고 입력·프로필·조건·근거가 결속된 결과를 조회한다.
주간 두 시점 상대 지형 변화가 첫 사례다.

**데이터 경로:** 권한이 있는 현장·시점·구역의 자산을 찾고, 지원하는 작업과 제한을 확인한 뒤
해당 구역의 데이터와 공간 메타데이터를 외부 코드에서 사용한다. 다운로드 허용,
AI 반출 허용, 처리 적합성과 분석 적합성은 각각의 조건으로 판정한다.

최소 Console은 등록·상태·오류와 보완·근거·접근 관리·사용량 확인을 지원한다.
외부 도구에서 완료되는 업무를 자체 채팅·보고서 편집기·범용 3D/BIM 편집기로 모두
재현하는 것은 이 플랫폼 검증의 필수조건이 아니다. 기존 Console·장기 Acquisition 기능의
삭제나 재설계는 이번 결정에 포함하지 않는다.

두 경로가 공통 기반 위에서 완결되는 흐름이 이 플랫폼의 차별성이다. `t0→t1`은 자료 등록 →
목적별 적합성 판정 → 분석 → 결과·근거 반환 → 사람 검토/재관측 제안 연결로 끝나고, `t1→t2`는
새 자료 등록 → 기존 정의·비교 규칙 재사용 + **변경 영향 확인** → 새 쌍의 admission·재분석 →
결과 갱신으로 이어진다. 재사용되는 것은 정의·규칙·연동 흐름이며, 이전 쌍의 계산 authority나
결과는 재사용하지 않는다. 이 반복에서 고객별로 별도 개발해야 하는 코드와 사람이 개입해야
하는 작업이 얼마나 줄어드는지를 입증한다(ADR-KSI-037 D3의 분석 의미는 유지).

## D3 — Staged scope and acceptance

| Stage | Scope | Acceptance boundary |
| --- | --- | --- |
| 기존 첫 분석 파일럿 | ADR-KSI-037의 실제 `t0→t1`, `t1→t2` 상대 지형 변화 및 선택한 인증 Codex MCP 흐름 | 기존 계산·음성·권한·운영·고객 수용 기준을 그대로 충족해야 함 |
| 첫 플랫폼 검증 | DSM·정사영상의 공통 자산 체계와 구역 데이터 접근; 같은 현장 자료의 분석 경로 + 외부 코드 활용 경로 | 독립 외부 개발자가 문서·예제로 실제 데이터를 받아 사용하고, 다음 관측에서도 두 경로를 재사용함 |
| 후속 확장 | Point cloud 범위/속성/밀도 선택; Mesh 원본·텍스처·공간 기준 전달; 외부 분석 레이어 등록 | 형식·연산·대상 소비자별 별도 계약과 실제 데이터 수용 |
| 활용 패키지 | 검증된 API 위의 MCP 연결·SDK/CLI 예제·스킬, 고객이 요구한 변환/시뮬레이터 어댑터 | 선택한 버전·클라이언트·환경에서 검증한 작업만 지원 표시 |

기존 토공 파일럿 완료는 첫 플랫폼 전체 완료와 다르다. 현재 `EXT-VAL` slice의 이름,
acceptance 또는 미완 상태는 바꾸지 않는다. 데이터 경로는 새 작업으로 계획하며 기존
분석 결과나 과거 테스트를 공간 추출·서빙의 증거로 재분류하지 않는다.

## D4 — Data and capability contracts to specify before implementation

- 자산 식별은 기존 Site·WorkArea·Observation Epoch·제출 revision·digest를 재사용하는
  매핑부터 설계한다. 새 독립 ID 체계를 중복 생성하지 않는다. 촬영 시점과 처리 시점을 구분한다.
- 파일 종류를 유지하고 메타데이터·접근 규칙을 통일한다. 원본 참조, 산출물 종류, 범위,
  CRS·수직기준·단위·축·격자/해상도·NoData, 가공 조건·버전·digest를 제공한다.
- `등록 가능 / 읽기 가능 / 추출 가능 / 해당 분석 가능 / 정확도 평가 / 사람 검토`를
  구분한다. 필수 정보가 없는 작업만 이유와 보완 방법으로 제한한다. 정사영상 제공에
  토공용 DSM·검사점 조건을 일괄 적용하지 않는다.
- 영역 추출은 요청 영역·실제 출력 영역·경계 셀·NoData·해상도·재표본화·변환 이력을
  명시해야 한다. 좌표나 높이를 추측해 맞추지 않는다. 가공으로 정확도가 검증되지는 않는다.
- 대용량 결과는 작은 구조화 응답과 권한이 적용된 파일/리소스 접근을 분리한다.
  형식별 바이트·픽셀·영역·동시성·시간·보관·전송 한도는 실제 표본 측정 후 고정한다.
  기존 Analysis V2의 512 KiB 응답 및 64 KiB coverage Range를 일반 데이터 전송 한도로
  자동 확장하지 않는다.
- 접근 링크·타일·캐시·Range·다운로드에도 조직/현장/구역 범위와 권한 회수 정책을
  적용한다. 서명 URL 방식, TTL과 이미 내려받은 사본의 책임은 별도 계약에서 정한다.
- 외부 분석 레이어는 생산자·모델/버전·입력 digest·관측/처리 시점·검토 상태를 결속하고
  KSI 계산·검증 결과와 구별한다. 결과 재등록은 후속 계약이며 기존 원장을 덮어쓰지 않는다.

## D5 — Agent and application integration

Core API가 공통 계약이며 MCP는 에이전트용 어댑터다. 목표 도구는 자료 탐색,
사용 가능 작업 확인, 구역 데이터 준비, 고정 분석 요청, 상태·결과·근거 조회다.
임의 GIS 코드 실행·원시 저장소 키·SQL을 도구 계약으로 노출하지 않는다.

긴 작업은 지속적인 작업 ID, 멱등성, 상태 조회와 실패 이유를 갖는다. 취소·기한·재시도·
부분 산출물 정리·사용량 정책은 새 작업 계약에서 명세·검증한다. 현재 Analysis에
이 기능이 모두 구현됐다고 주장하지 않는다. 스킬은 사용 절차를 설명하며 권한은 Core가 강제한다.
현재 내부 Copilot의 INV-061 도구 권한과 외부 인증 MCP principal은 합쳐 해석하지 않는다.
새로운 데이터 반출 경로는 범위·동의·감사 계약과 독립 보안 검토가 필요하다.

Codex 한 경로의 분석 검증을 Claude·ChatGPT·원격 MCP·MCP Apps 지원으로 확대해 표시하지
않는다. 최초 플랫폼 검증도 선택한 MCP 한 클라이언트와 외부 API 소비 코드 한 사례로
지원 범위를 고정한 후 수행한다.

## D6 — Preserved boundaries and unresolved choices

INV-020/024/040/050/051/053/054/055/060/061을 보존한다. 기존 managed/test 원본 권위,
external submission, 파생 산출물과 외부 모델 결과를 혼합하지 않는다. 데이터 접근이
측정·정산·공정·안전·로봇 주행 가능성을 인증하지 않는다. 실제 제어는 MCP의 책임이 아니다.
KSI Safety는 공간 맥락을 소비할 수 있는 별도 제품이며 자동 코드 통합을 뜻하지 않는다.

STAC, COG, 3D Tiles는 채택 후보다. STAC은 공간·시간 자산 기술/탐색을,
COG는 GeoTIFF의 부분 접근을 지원하지만 KSI의 권한·적합성·근거 모델을 대신하지 않는다.
호환 표준·버전·라이브러리·정확한 포맷 선택은 표본과 소비자 요구를 근거로 결정한다.
참고: [STAC](https://stacspec.org/en/about/stac-spec/),
[OGC COG](https://docs.ogc.org/is/21-026/21-026.html).

구매자 검증, 최소 입력 프로필, 공간 추출 의미, 데이터 전달·권한 회수, 외부 결과 재등록,
운영 비용·보관·지원 및 과금은 계획 원장의 보완 항목에서 추적한다. 가격·SLA·모든
벤더/포맷 지원은 이번 결정으로 확정하지 않는다. 장기 Acquisition/Edge 설계와 과거
구현 증거는 보존하되 이 플랫폼 검증의 자동 실행 선행조건으로 만들지 않는다.

> 2026-10-07 routing note (dated evidence above is preserved): the preserved-acquisition
> clause routes to [ADR-KSI-039](ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md) —
> long-term acquisition is out-of-product and preserved only as historical evidence,
> never as an automatic-execution precondition.
