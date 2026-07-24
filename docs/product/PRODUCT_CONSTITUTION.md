# KSI Site Intelligence Product Constitution

## 제품 정체성

KSI Site Intelligence Platform은 Matrice 4D와 Manifold 3를 중심으로 다양한 물리적 운영현장을 자율 조사·이해·관리하는 산업 중립형 Site Intelligence 플랫폼이다. 건설은 첫 번째 Vertical이다.

핵심 가치는 다음 순서다.

1. 자율 안전순찰
2. 지속적인 공간지도 최신화
3. 공정·변화·물량 분석
4. 구조물·시설물 점검

## 제어 철학

- DJI Flight Controller는 비행 안정화, 저수준 기체 제어, 반응형 충돌회피와 RTH를 담당한다.
- Manifold KSI Edge는 센서 동기화, 인지, 추적, 4D World Model, 위험판단, 재관찰, 로컬 경로·관측점 결정을 담당한다.
- KSI Core는 Mission Contract, 정책, 지도·모델 버전, 이벤트·증거·검토와 운영을 담당한다.
- 서버가 프레임별 조종 명령을 보내지 않는다.
- LLM은 비행 좌표와 안전 제어 명령을 직접 생성하지 않는다.

## 지도 철학

- 사전 지도는 Prior이며 현재 현실의 절대 진실이 아니다.
- 비행은 `map-informed, sensor-guarded` 방식이다.
- 고해상도 Mesh를 직접 충돌회피에 사용하지 않고 Terrain, Occupancy, ESDF, Surface, Semantic Layer로 컴파일한다.
- 지도는 좌표계, 수직기준, 버전, 시각, 불확실성, Provenance를 가진다.

## 참고 저장소 철학

- `KSI Platform`, `KSI-Terra`, `KSI-Scout`는 참고 구현이다.
- Domain, Algorithm, Test, Operational Knowledge는 채택할 수 있다.
- 과거의 중앙추론·수동비행·Dock 중심·평지지도 한계는 목표 아키텍처를 제약하지 않는다.
- 참고 저장소에서 직접 Import하지 않는다. 필요한 코드는 검토·추출·이식 후 KSI 소유 모듈로 만든다.


## Locked Product Defaults

- Coverage: 위험구역 100%, 필수자산 100%, 일반 접근영역 95%
- Battery Reserve: 현장별 설정, 기본 30%
- Offline: 서버단절 중 조건부 계속, RC Link Lost는 DJI 정책
- Evidence: Candidate/High/Critical 전후 3/5/10초
- Retention: 고객별 설정 + 승인된 기본값
