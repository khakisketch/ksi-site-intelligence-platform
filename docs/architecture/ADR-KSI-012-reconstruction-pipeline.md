# ADR-KSI-012 — 3D 재구성 파이프라인: 엔진·실행 위치·라이선스 경계

- 상태: ACCEPTED (2026-08-05, 대표자 확정)
- 관련: ADR-KSI-003(공간 데이터 계보 — Point Cloud 원본/Mesh 파생),
  ADR-KSI-010(온프렘 S3 호환 스토리지, 클라우드 직결 기각),
  ADR-KSI-013(매핑 원본 미디어 반출 경로), MASTER_PRD §15.4(비행 후 Processing —
  Provider Adapter로 Terra/ODM/Pix4D 교체 가능 예정)·§22.2(배포 형태: Cloud/On-Prem/
  Hybrid)·§23.5(상용 패키지 — Processing 크레딧/On-Prem 라이선스), INV-003(참고
  저장소 직접 import 금지), `docs/product/DOMAIN_INVARIANTS.md`(INV-050·051 신설),
  `services/processing-controller`, `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
  (`ODMRunner: ADOPT`)

## 맥락

`services/processing-controller`는 빈 골격으로 이미 예약돼 있고(ADR-KSI-004와 같은
패턴), MASTER_PRD §15.4는 "KSI Processing은 Provider Adapter를 통해 Terra,
ODM/Pix4D 또는 자체 파이프라인을 교체 가능하게 설계한다"고 이미 적어뒀다. 그러나
**기본 엔진이 무엇인지, 무인·온프렘 자동화가 어느 엔진에서 실제로 라이선스상
가능한지는 저장소 어디에도 확정돼 있지 않았다.** 사진측량 재구성 엔진은 대부분
"사람이 데스크톱에서 조작"을 전제로 라이선스를 설계했고, KSI처럼 서버가 트리거하는
무인 자동 처리는 그 전제를 벗어난다 — 엔진 선택이 기능 비교가 아니라 라이선스
문언 대조로 결정되는 이유다.

## 결정

### D1 — 기본 엔진은 자체 호스팅 오픈소스 재구성 엔진(ODM/NodeODM)

`services/processing-controller`는 어댑터다. 특정 엔진에 고정하지 않고 provider를
갈아끼울 수 있게 두되(`ODMRunner: ADOPT`, `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`),
**기본값은 ODM**이다.

- NodeODM을 **무수정 컨테이너**로 띄우고 REST/PyODM(BSD-3 라이선스)으로만
  호출한다. 처리량이 커지면 ClusterODM으로 수평 확장한다 — 컨테이너·REST 경계는
  그대로 유지된다.
- 실행 위치는 현장 서버(온프렘)와 KSI 서버 둘 다 지원한다. 어느 쪽에서 돌든
  같은 어댑터·같은 REST 계약을 쓴다 — 위치는 배포 대상이지 코드 분기가 아니다
  (MASTER_PRD §22.2 Hybrid 배포와 같은 축).
- 하드웨어는 GPU가 아니라 RAM·코어로 산다. 조사 실측(2026-08-05 기준):
  1,039장 / 8코어 / 64GB 환경에서 CPU 처리 3시간 27분 → GPU 처리 2시간 47분
  (개선 15~45%, 워크로드에 따라 변동). 500~3,000장 실무 기준 사양은 **64GB RAM +
  8코어 + VRAM 6GB**로 잡는다 — GPU는 "필수"가 아니라 "있으면 시간이 준다"는
  개선 항목이다.

### D2 — AGPL 경계 (이 ADR의 핵심 안전선)

ODM/NodeODM은 AGPL-3.0이다(`docs/reference/ksi-terra/KSI_TERRA_IMPLEMENTATION_AND_ADOPTION_AUDIT_2026-07-24.md`
§7.2, `docs/reference/ksi-terra/KSI_TERRA_LICENSE_COMPLIANCE_PLAN.md` §3과 같은
전제). 이 ADR이 그리는 금지선은 "AGPL을 SaaS에 쓰지 마라"가 아니다 — 그건 AGPL의
설계 의도와 반대다. 금지선은 **"엔진 코드를 한 줄도 고치지 말고, 우리 코드와
한 저작물로 묶지 마라"**다.

**금지**:

- ODM/WebODM 코드를 수정한 뒤 그 수정본으로 서비스를 제공하는 것
- WebODM UI를 브랜딩 개조해 고객에게 그대로 서빙하는 것
- 우리 오케스트레이터(`ksi_processing_controller`)를 ODM 소스 트리 안에 배치하거나
  같은 프로세스·같은 빌드 산출물로 링크하는 것

**허용**: 무수정 컨테이너 + REST 프로세스 경계 + PyODM import(별도 저작물, BSD-3).
이는 `KSI_TERRA_LICENSE_COMPLIANCE_PLAN.md` §3이 이미 요구한 "별도 프로세스·별도
이미지·KSI proprietary code를 AGPL repository에 포함하지 않음"과 동일 원칙이다.

**온프렘 배포(고객 서버로 이미지를 넘기는 경우)는 AGPL §13(network use)이 아니라
일반 conveying이 적용된다** — 이미지를 상대방에게 넘기는 순간 conveying이 성립하고,
그 이미지가 담은 AGPL 컴포넌트(ODM/NodeODM 무수정 컨테이너)에 대해 소스 제공
offer를 이미지에 동봉해야 한다. KSI 자체 코드(`ksi_processing_controller` 등)는
별도 프로세스·REST 경계로 결합돼 있으므로 이 의무의 대상이 아니다.

### D3 — 기각한 대안: 상용 재구성 엔진

기본 엔진을 ODM으로 확정하기 전에 검토한 네 대안과 기각 근거를 남긴다(모든 가격은
2026-08-05 기준, 통화는 USD로 명기).

**DJI 클라우드(FlightHub 2 Mapping API)** — 기술적으로는 REST 기반 무인 자동화가
된다. 그러나:

1. 현장 원본 사진을 DJI 클라우드로 업로드해야만 동작한다. 이는 ADR-KSI-010이
   "건설 현장 영상의 국외 반출은 고객 계약에서 걸릴 수 있는 사안"으로 이미
   기각한 클라우드 직결과 같은 행위다 — 같은 근거로 기본 경로로 채택하지 않는다.
2. 상업 서비스 제공을 계약서에 이름으로 명시 허가받았던 TerraAPI는 2026년 6월
   단종됐다(**1차 출처 배너 직접 대조 실패** — 단종 사실은 2차 정보로만 확인했고
   DJI 공식 페이지 배너 원문을 직접 대조하지 못했다. 재확인 전까지 이 사실을
   확정으로 인용하지 않는다). 남은 경로는 FlightHub 2 Mapping API License
   Agreement의 "any other API provided on this website" 포괄조항으로 상업
   서비스 제공이 커버되는지 **추정뿐이다 — 서면 확인 필요**. 명시적 상업 허가
   문구를 계약서에서 확인하기 전에는 상업 서비스의 라이선스 기반으로 쓸 수 없다.
3. revocable(사전통지 없이 회수 가능)이고, 배상 상한이 사고당 $50(USD)이며,
   동시 job 수가 2~10개로 제한된다. 상용 서비스의 SLA 기반으로 쓰기엔 약관 자체가
   그 용도를 상정하지 않는다.
4. DJI Terra 데스크톱 앱 자체에는 CLI·headless 실행 경로가 없다(v4.3 매뉴얼
   전수 검색 결과 0건) — "그럼 Terra 데스크톱을 무인 배치로 돌리면 된다"는 우회도
   막혀 있다.

**Pix4D(PIX4Dengine SDK)** — 우리 서버에서 온프렘 무인 실행이 되는 **진짜 경로**다.
다만 Enterprise 계약 전용이고 가격은 비공개 견적이다. SaaS로 제공하려면 사용량
과금 계약과 "Powered by Pix4D" 공개 표기 의무가 붙는다. General Terms §13.1이
라이선스 사용 목적을 "personal or internal business purposes"로 한정하므로,
계약·표기 없는 무인 백엔드 사용은 그 조항 위반이다. **완전 기각이 아니라 보류다**
— 다음 중 하나가 트리거되면 재검토한다: ① 고객이 GCP 기반 측량 정확도 리포트를
계약 요건으로 요구, ② 파일럿 데이터에서 ODM 재구성 실패율이 운영 불가 수준,
③ 법무가 AGPL 프로세스-경계 해석(D2)을 리스크로 판정.

**RealityCapture/RealityScan** — 절대 불가. EULA §1.2(c)(d)가 SaaS·hosted·
time-sharing·service bureau 형태의 제공을 원문으로 금지한다. Epic의 연매출
100만 달러 미만 무료 정책은 이 금지 조항과 무관하게 그대로 적용된다 — 무료
정책은 가격 조건이지 사용 형태 제한을 푸는 게 아니다.

**Agisoft Metashape** — 일반(Node-locked/Floating) 라이선스는 EULA가 "operator
개입 없는 automated processing service"를 금지한다. **함정**: 고객 머신에
고객이 정당하게 구매한 라이선스를 설치해도, 우리 플랫폼이 그 처리를 무인으로
트리거하면 동일하게 이 금지에 걸린다 — "고객 소유 라이선스니까 안전하다"는
가정이 성립하지 않는다. 허용 경로는 Service Provider License뿐이며 가격은 연
약 $6,736(USD)/라이선스, 또는 종량 최소 월 $155.90(USD)이다.

### D4 — 과금 뼈대

1차 과금 단위는 시트가 아니라 **현장(사이트)**이다. 현장소장 결재 단위가
사이트이고, 협력업체·안전관리자 같은 캐주얼 사용자 수를 시트제가 감당하지
못한다 — 시트당 과금은 "누가 로그인했나"를 세지만 이 제품의 가치는 "어느
현장이 커버되고 있나"에서 나온다.

- **현장당 정액 구독 + 처리량 크레딧**(MASTER_PRD §23.5 "Processing 크레딧 또는
  On-Prem 라이선스"의 구체화). 조사한 드론 데이터 플랫폼(DroneDeploy·Propeller·
  Skydio·Esri Site Scan·Pix4Dcloud) 자기서비스 플랜 중 "처리 무제한 포함형"은
  한 곳도 없었다 — 크레딧 소모형이 업계 표준 형태다.
- 크레딧 소모율은 **처리 실행 위치로 갈린다**: 고객 장비(온프렘)에서 돌리면
  소모 0, 우리 서버에서 돌리면 `해상도(MP) × 장수`에 비례한다. 대표자가 원한
  "고객 컴퓨터 등록" 옵션이 자연히 더 싼 tier로 표현된다 — 별도 할인 규칙을
  만들 필요가 없다.
- **위임 경로의 안전한 기본값은 반자동이다**: 고객이 자기 도구(D3의 Pix4D
  Desktop·Metashape 일반 라이선스 등)로 처리하고, 산출물을 우리 포맷으로
  등록만 한다. **무인 자동 실행은 ODM 컨테이너를 고객 서버에 배포하는 경우로
  한정**한다 — 그 외 제품(Pix4D SDK 무계약, Metashape 일반 라이선스)을 무인
  트리거로 쓰면 D3의 함정에 그대로 걸린다.

### D5 — 3D 모델의 첫 용도는 위치 앵커

트리아지에서 3D는 "이 위험이 현장 어디서 나왔나"를 보여주는 위치 앵커부터
만든다. 치수 측정·시계열 비교(ADR-KSI-003의 원본 계열 분석)는 후순위다 —
위치 앵커는 기존 2D 지도 컴포넌트(`apps/dashboard/src/components/map/AoiPolygonMap.tsx`)를
재사용할 수 있어 비용이 가장 낮다. 정밀 측정용 파생물 파이프라인(Mesh·3D
Tiles 서빙 계층)은 그다음 단계다.

### D6 — 탐지 경로는 온보드 하나, 서버 second-pass 재추론은 채택하지 않는다

이 파이프라인으로 현장 원본 사진 전량이 서버(또는 온프렘 처리 노드)에 모이게
되므로, "그럼 서버가 그 원본을 다시 배치로 재추론해서 온보드가 놓친 위험을
잡으면 되지 않나"라는 확장이 자연스럽게 떠오른다. **대표자 확정: 채택하지
않는다.** 위험 탐지 경로는 Manifold 온보드 하나이며, 재구성 파이프라인이
서버에 모으는 원본은 3D 재구성 입력일 뿐 재탐지 입력이 아니다 — 비용(전체
현장 사진 재추론) 대비 실익이 부족하다는 판단이다.

이는 새 제어 경계가 아니라 기존 경계(CLAUDE.md `Control boundaries` —
"Manifold owns tactical perception", INV-001)의 연장 확인이다: 실시간 판단만이
아니라 **사후 배치 재탐지도** Manifold 경로 밖으로 나가지 않는다는 뜻으로
명시한다. 온보드 탐지 정확도 개선은 Model Registry(INV-043)·Capability
Registry(INV-041) 경로로 다루고, 이 second-pass는 그 대체재로 두지 않는다.

## 결과 — 알려진 대가

- **ODM에는 구조화된 측량 정확도(GCP/RMSE) 리포트가 없다.** 토공량·치수 측정이
  상품의 핵심이 되는 순간 이게 Pix4D(D3)로 갈아타는 전환 트리거다.
- 처리 시간이 상용 엔진 대비 길 수 있고, 재구성 실패율은 아직 파일럿 데이터로만
  확인할 수 있다(실측 전).
- D6로 인해 온보드가 놓친 위험은 서버 재추론으로 사후 구제되지 않는다 — 탐지
  정확도의 유일한 개선 경로는 온보드 모델 자체의 개선이다.
