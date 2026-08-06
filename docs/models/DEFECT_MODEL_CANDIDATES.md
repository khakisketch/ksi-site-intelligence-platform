# Phase 4 표면 결함 탐지 — 모델·데이터셋 후보 (대표자 결정 대기)

Phase 4(Asset Inspection & Temporal Intelligence, PRD §25) "표면 점검·균열·박락
후보" 항목의 모델 선정 리서치다. `docs/models/MODEL_DECISIONS.yaml`의
`MODEL-B1-001`(Track B 사람 탐지 D-FINE-S)과 같은 형식의 **대표자 결정**이
필요하지만, 이 문서 자체는 결정이 아니라 후보 제시다 — `MODEL_DECISIONS.yaml`은
"각 결정은 대표자 승인 없이 변경하지 않는다"고 명시하므로 이 저장소가 임의로
거기 항목을 추가하지 않는다.

리서치 시점: 2026-08-06.

## 요약 — 권장

1. **1차 후보(즉시 채택 가능)**: `yakhyo/crack-segmentation`(MIT, UNet, 사전학습
   가중치 포함) 또는 `CHDyshli/HrSegNet4CrackSegmentation`(Apache-2.0, CrackSeg9k
   +Asphalt3k+Concrete3k 학습 가중치 공개) — **코드·가중치 둘 다 permissive**라
   D-FINE-S 도입 때와 달리 자체 파인튜닝 없이 엔지니어링 착수가 가능하다. 단
   **균열(crack)만** 커버한다 — 박락·부식·철근노출은 없다.
2. **확장 후보(자체 파인튜닝 필요)**: "Cracks in the Foundation"(CiF, CC BY 4.0,
   148,642 패치, 6클래스 — crack/spalling/rust/exposed-rebar 등)로 위 1차 후보의
   백본을 추가 학습하면 결함 클래스를 넓힐 수 있다. 논문에 실제 다운로드 URL이
   기재돼 있지 않아 저자 컨택이 선행돼야 한다(archive: arxiv.org/abs/2605.18413).
3. **배제**: Ultralytics YOLO 계열(YOLO11/12/26)은 여전히 AGPL-3.0 기본 라이선스
   (Enterprise 구매 시만 예외) — ADR-KSI-012 D2의 AGPL 회피 정책과 정면 충돌해
   배제한다.

## 후보 상세

### 1차 — 코드+가중치 둘 다 permissive (즉시 엔지니어링 착수 가능)

| 후보 | 라이선스 | 학습 데이터 | 커버리지 | 비고 |
|---|---|---|---|---|
| `yakhyo/crack-segmentation` | MIT | 비공개(가중치만 배포) | 균열만 | UNet, 가중치 즉시 사용 가능 |
| `CHDyshli/HrSegNet4CrackSegmentation` | Apache-2.0 | CrackSeg9k+Asphalt3k+Concrete3k | 균열만 | 코드+가중치 둘 다 공개 |

D-FINE-S 도입 때(`MODEL_REGISTRY.yaml` 패턴 — repository_commit·weights revision·
sha256 고정)와 동일한 방식으로 이 두 후보 중 하나를 채택하려면: (a) 정확한
commit/revision·가중치 sha256을 실측해 `MODEL_REGISTRY.yaml`에 등재 (b) 이
프로젝트의 D-FINE 파이프라인(`packages/perception`)과 별도 아키텍처라 어댑터를
새로 짜야 한다(세그멘테이션 출력 형식이 detection과 다름) (c) 균열만 커버하므로
"표면 점검·균열·박락 후보" 요구사항 중 박락은 미충족 — 결정 시 이 갭을 명시해야
한다.

### 확장 — 자체 파인튜닝 데이터셋 후보

| 데이터셋 | 라이선스 | 규모 | 클래스 | 리스크 |
|---|---|---|---|---|
| Cracks in the Foundation(CiF) | CC BY 4.0 | 12,896장/148,642패치 | crack·spalling·rust·exposed-rebar·algae 등 6종 | 다운로드 URL 미공개(저자 컨택 필요) |
| dacl10k | **CC BY-NC 4.0**(비상업) | 9,920장 | crack·spalling·rust 등 19종 | 상용 제품에 부적합 — 참고용에서 제외 권고 |
| CrackSeg9k | 표시상 CC BY 4.0(집계본), 원 소스 10개 일부 연구목적 제한 라이선스 혼재 의심 | 9,255장 | 균열만 | 재배포 전 원 소스 10개 라이선스 개별 확인 필요 |

기존 D-FINE(Apache-2.0, 이미 이 코드베이스에 통합됨) 아키텍처를 재사용해 CiF로
직접 파인튜닝하는 경로도 가능하다 — 이 경우 상류 가중치 라이선스 문제 자체가
없어진다(KSI 가 직접 학습한 가중치, D-FINE-S 의 "COCO 이미지 권리 이질성" 같은
잔여 리스크가 없음). 다만 이건 **실제 학습 실행**(GPU 컴퓨팅·평가 corpus 구성)이
필요한 별도 작업이라 이 문서(후보 리서치)의 범위 밖이다.

## 배제 — Ultralytics YOLO 계열

YOLO11·YOLO12·YOLO26 전부 기본 AGPL-3.0(Enterprise 라이선스 구매 시만 예외) —
이 프로젝트가 ODM/NodeODM에 적용한 AGPL 프로세스 경계 정책(ADR-KSI-012 D2)과 같은
이유로 배제한다. 균열탐지 논문·저장소 다수가 YOLO 계열을 베이스로 쓰지만, 그
전부가 이 정책과 충돌한다.

## 3D(포인트클라우드) 기반 결함탐지 — 참고용, 현 단계 채택 불필요

균열 폭·깊이를 3D로 정량화하는 연구가 2025년 이후 활발하지만(폭 오차 <0.1mm
보고 사례 있음), 라이선스가 확인된 프로덕션급 오픈소스 구현은 없다 — 전부 학술
코드 수준. 2D 이미지 기반 탐지가 여전히 산업 표준이다. `ksi_change_detection`
(point cloud C2C)이 이미 이 저장소에 있으므로, "변화 후보 영역"과 "결함 후보"를
결합하려면(예: 변화가 감지된 영역만 결함 탐지 대상으로 좁히기) 그건 이 두
파이프라인의 통합 설계 문제이고 후속 결정 사안이다.

## BIM 연계 — 결함 위치를 IFC 에 기록하는 표준

결함 탐지가 실제로 구현되면 그 결과를 BIM에 되먹임하는 표준 경로가 이미 있다:

- **BCF**(BIM Collaboration Format, buildingSMART 오픈표준) — IFC GUID + 뷰포인트로
  이슈/결함을 소통하는 교환 포맷. `ksi_bim_integration`이 이미 IFC 파일을 읽는
  구조이므로 같은 패키지에서 확장 가능하다.
- **IfcSurfaceFeature**(IFC 4.3, `PredefinedType=DEFECT`) + `IfcRelAdheresToElement`
  — 결함 지오메트리를 BIM 모델에 직접 요소로 인스턴스화하는 전용 엔티티.
  `IfcAnnotation`은 범용 주석용이라 결함 전용이 아니다 — 이 엔티티를 쓰는 것이
  표준에 맞다.

## 다음 결정이 필요한 지점

1. 1차 후보(균열만) 중 하나를 지금 채택하고 박락·부식은 후속 확장으로 미룰지,
   확장 후보(CiF)로 처음부터 다결함 파인튜닝을 할지 — 범위·일정 트레이드오프는
   대표자 결정 사안이다.
2. CiF 데이터셋 실제 다운로드 경로 확보(저자 컨택) — 착수 전 선행 필요.
3. 세그멘테이션 출력(균열 마스크)을 이 코드베이스의 Detection/Observation 계약
   (bbox 기반)에 어떻게 편입할지 — 마스크→bbox 변환인지 별도 계약 신설인지는
   아키텍처 결정이 필요하다.
