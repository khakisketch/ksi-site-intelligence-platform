# Phase 4 표면 결함 탐지 — 모델·데이터셋 후보

**2026-08-07 결정 완료** — 대표자가 아래 "2026-08-07 갱신" 절의 추천(MixerCSeg)을
확정했다. 정식 결정 레코드는 `docs/models/MODEL_DECISIONS.yaml`의
`MODEL-P4-001` 참고(가중치 fetch/pin·`MODEL_REGISTRY.yaml` 등재는 아직 별도
착수 전 — 엔지니어링 착수만 승인된 상태). 이 문서는 그 결정에 이른 리서치
기록으로 계속 보존한다(수정하지 않는다) — 후보 비교 근거가 필요할 때 참고.

Phase 4(Asset Inspection & Temporal Intelligence, PRD §25) "표면 점검·균열·박락
후보" 항목의 모델 선정 리서치다. `docs/models/MODEL_DECISIONS.yaml`의
`MODEL-B1-001`(Track B 사람 탐지 D-FINE-S)과 같은 형식의 **대표자 결정**이
필요하지만, 이 문서 자체는 결정이 아니라 후보 제시다 — `MODEL_DECISIONS.yaml`은
"각 결정은 대표자 승인 없이 변경하지 않는다"고 명시하므로 이 저장소가 임의로
거기 항목을 추가하지 않는다.

리서치 시점: 2026-08-06.

## 2026-08-07 갱신 — 최고 정확도 우선 재조사

**배경**: 이번 라운드 대표자 지시 — "파인튜닝은 나중이고 아직 monetize 전 초기
리서치 MVP다, 사전학습 가중치 라이선스로 과잉제약하지 말고 정확도가 가장 높은
후보를 골라라." 단 이 지시는 **가중치 라이선스**에 한정된 완화이지 **코드
라이선스 정책**(ADR-KSI-012 D2, AGPL 배제)을 푼 게 아니다 — 아래에서 둘을
분리해서 다룬다.

이 절은 기존 "1차 후보"(`yakhyo/crack-segmentation`, `HrSegNet4CrackSegmentation`,
아래 "후보 상세" 절 그대로 유지)를 대체하지 않는다. 정확도를 최우선으로 둘 때
뭐가 더 나은 선택인지 재조사한 결과이고, 최종 채택은 여전히 대표자 서면 결정
(`MODEL_DECISIONS.yaml`) 몫이다.

### 정확도 교차검증 — DeepCrack mIoU를 공통 축으로

여러 논문이 공유하는 사실상 유일한 벤치마크가 DeepCrack이라 이걸 축으로 놓되,
자기보고 숫자만 그대로 순위표로 쓰지 않고 (a) 독립 재현 여부 (b) 코드 라이선스
(c) 가중치 실제 배포 여부 (d) peer review·연식을 같이 봤다.

| 후보 | DeepCrack mIoU | 근거 신뢰도 | 코드 라이선스 | 가중치 공개 | 발표 |
|---|---|---|---|---|---|
| `zhxhzy/SCRWKV` | **0.9289**(전체 최고) | 자기보고만 — 독립 재현 전무, 발표 수 주 | Apache-2.0 | **미확인** | ICML 2026(peer-reviewed지만 신생) |
| `spiderforest/MixerCSeg` | 0.9151 | 자체 논문 내 3개 베이스라인 재현 테이블 포함(준독립 교차검증) | **MIT** | 확인됨(2026-02-28 Google Drive 배포) | CVPR 2026 |
| `Karl1109/CrackSCF` | 0.9079 | **가장 강한 독립 corroboration** — SCSegamba·SCRWKV 양쪽 논문의 재현 베이스라인으로 채택, TUT 데이터셋이 후속 논문 공유 벤치마크로 정착 | **LICENSE 파일 없음**(GitHub API 404 — 기본 all-rights-reserved) | 미확인 | arXiv 2024-08 |
| `Karl1109/SCSegamba` | 0.9022(MixerCSeg의 독립 재현치) | 제3자 재현 숫자 — 자기보고가 아니라는 점에서 신뢰도는 오히려 CrackSCF의 자기보고 0.9079보다 높지만 절대치는 더 낮게 나옴 | **Apache-2.0** | 확인됨(`checkpoint_TUT` 등) | CVPR 2025 |

**교차검증에서 드러난 것**: CrackSCF의 자기보고 DeepCrack mIoU(0.9079)가, 1년 뒤
peer-review를 거친 SCSegamba를 MixerCSeg 논문이 독립 재현한 수치(0.9022)보다
오히려 높다 — 더 최신·더 검증된 모델이 재현 시 더 낮게 나온 것이다. 이는
논문마다 DeepCrack train/test split·전처리가 완전히 동일하지 않다는 신호이고,
crack-sota 서베이가 인용한 재현성 서베이(arXiv 2508.10256)도 이 cross-split
불일치를 이 분야의 알려진 함정으로 명시한다. 그래서 "자기보고 최고치"
(SCRWKV 0.9289)를 그대로 1위로 받지 않고, 재현·라이선스·가중치 공개까지 같이
봤다.

### AGPL 경계 재검토 — 이번 조사엔 새 YOLO 후보 없음, 기존 배제 근거는 명시적으로 보강

survey:repo-policy가 지적한 갭 — 기존 "배제" 절(아래)이 YOLO를 ADR-KSI-012 D2와
"같은 이유로" 배제하면서도 D2의 boundary test(REST 경계 밖 unmodified 컨테이너면
예외 인정)를 실제로 통과시켜본 적이 없었다는 것 — 을 여기서 명시적으로 닫는다.

D2 테스트를 YOLO에 적용하면: ODM/NodeODM은 애초에 서버로 설계돼 REST로 부르는
게 정상 사용 패턴이라 "별도 저작물" 경계가 자연스럽게 성립한다. 반면 Ultralytics
YOLO의 정상 사용 패턴은 `ultralytics` pip 패키지를 프로세스 내부에서 import하는
것 — 이게 정확히 D2가 금지하는 "같은 프로세스/빌드 아티팩트에 링크"다. REST
마이크로서비스로 감싸는 것 자체는 가능하지만 이건 기본 사용법이 아니라 별도
아키텍처 결정을 하나 더 얹는 것이다.

그렇게 감싼다 해도 survey:agpl-boundary-analysis의 결론대로 — AGPL §13은
"배포"가 아니라 "네트워크 상호작용"이 트리거라 REST 경계 자체가 YOLO 코드의
disclosure 의무를 없애지 못한다. REST 경계가 지키는 건 KSI 자체 코드가 결합저작물로
끌려들어가지 않게 하는 것뿐인데, 이마저 "법원이 확정판결 낸 적 없는 불확실한
논거"이고, Ultralytics 본인이 공식 문서에서 "REST로 연결되는 코드도 전부
오픈소스화해야 한다"는 공격적 해석을 이미 걸어놨다. 즉 **REST 경계는 탈출구가
아니라 법적으로 불확실한 리스크 완화 조치**일 뿐이다 — disclosure 리스크 자체를
없애주지 않는다.

**결론**: YOLO11/12/26은 이번 재조사에서도 배제 유지 — 이번엔 boundary test를
실제로 통과시켜서 나온 결론이지 패턴매칭이 아니다. 이번 라운드에서 발굴한 크랙
세그멘테이션 SOTA 후보(SCRWKV/MixerCSeg/CrackSCF/SCSegamba) 중 AGPL은 하나도
없다(Apache-2.0 · MIT · 라이선스 파일 없음 셋 중 하나) — 이 배제가 이번 추천에
실제 영향을 주지는 않지만, "AGPL이면 REST로 감싸서 우회하자"는 다음 라운드의
유혹을 미리 닫아둔다.

### 최종 추천

**1순위 — `spiderforest/MixerCSeg`(MIT)**
- DeepCrack mIoU 0.9151 — 이번 조사에서 재현·라이선스·가중치 공개 셋 다 확인된
  후보 중 최고치.
- MIT는 이번 조사에서 발견된 라이선스 중 가장 깨끗하다 — 가중치 라이선스를
  과잉제약하지 말라는 이번 지시와 별개로, 코드 라이선스는 오히려 여유 있게 통과.
- CVPR 2026 peer-reviewed, 가중치 2026-02-28 공개 확인, 자체 논문에 3개
  베이스라인 재현 테이블 포함(스스로 검증 가능하게 설계).
- **트레이드오프**: 전체 자기보고 1위(SCRWKV, 0.9289)보다 1.4 mIoU 포인트 낮다.
  "정확도 절대 최우선"을 문자 그대로 적용하면 SCRWKV가 이겨야 하지만, SCRWKV는
  가중치 배포 자체가 미확인이라 — "파인튜닝은 나중"이라는 이번 라운드 전제
  자체를 지금 실행할 수 없을 위험이 있다. 이건 라이선스 트레이드오프가 아니라
  순수 실행가능성 리스크다.

**런너업 1 — `Karl1109/SCSegamba`(Apache-2.0)** — 더 안전한 선택
- MixerCSeg의 독립 재현치 기준 DeepCrack mIoU 0.9022(MixerCSeg 대비 -1.3pt),
  대신 CVPR 2025로 한 세대 더 battle-tested, 가중치 공개 확정(`checkpoint_TUT`),
  Apache-2.0.
- 정확도를 살짝 양보하고 커뮤니티 검증 기간을 사는 선택. MixerCSeg가 실제
  파인튜닝 단계에서 예상 못 한 문제(가중치 로딩 이슈·재현 실패 등)를 보이면
  이쪽으로 즉시 대체 가능한 게 실질적 가치.

**런너업 2(관찰/오버라이드용) — `zhxhzy/SCRWKV`(Apache-2.0)** — 문자 그대로
"최고 정확도"를 원하면 이것
- DeepCrack mIoU 0.9289로 전체 최고, 라이선스도 Apache-2.0이라 정책상 배제
  사유는 없다 — "정확도 최우선"을 사람이 문자 그대로 밀어붙이고 싶다면 정책이
  막을 이유는 없는 후보다.
- 다만 (a) 발표 수 주밖에 안 돼 독립 재현 전무 (b) 사전학습 가중치의 실제 공개
  여부·조건이 리포에서 확인 안 됨 — 지금 채택하면 "가중치가 없어 처음부터 직접
  학습해야 하는" 상황을 만날 수 있다. 몇 달 뒤 재평가 대상으로 워치리스트에
  올려둔다.

### 다중 결함 클래스(박락·철근노출·부식·백화·조류) 관점 — 백본 교체 시사점

survey:defect-classes 결론은 그대로 유효하다 — 5개 클래스를 전부 커버하는
permissive 코드+공개 가중치 기성 모델은 없고, 박락·부식·백화까지 확장하려면
여전히 CiF(CC BY 4.0) 파인튜닝이 필요하다(아래 "확장 — 자체 파인튜닝 데이터셋
후보" 절 그대로). 바뀌는 건 파인튜닝 **베이스가 되는 백본**이다: 기존 절은
UNet(`yakhyo`)/HrSegNet을 베이스로 상정했는데, 이번 조사에서 나온
MixerCSeg/SCSegamba류 아키텍처가 균열 단일클래스에서 이미 더 높은 정확도를
보이는 만큼 CiF 다중클래스 파인튜닝에서도 더 나은 시작점일 가능성이 높다 —
다만 이건 **추론이지 실측이 아니다**: 이번 서베이 어디에도 이 아키텍처들을
다중클래스로 파인튜닝한 결과는 없다. 대표자 결정 시 "1차 후보를 MixerCSeg로
교체"와 "1차 후보는 유지하고 CiF 파인튜닝 베이스만 재검토"를 구분해서 결정해야
한다.

dacl10k(CC BY-NC)·GYU-DET(YOLOv11 + CC BY-NC-ND) 배제는 기존 판단 그대로
유지한다 — 재도출하지 않음.

### 갱신된 다음 결정 지점 (대표자 확인 필요)

1. **1차 후보 교체 여부**: 균열 단일클래스라도 지금 바로 정확도를 올리려면
   `yakhyo`/`HrSegNet` 대신 `MixerCSeg`(1순위) 또는 `SCSegamba`(런너업)로 전환 —
   MIT/Apache-2.0 둘 다 코드 라이선스는 문제 없음. 단 세그멘테이션 어댑터를 새로
   짜야 하는 기존 (b)번 갭은 아키텍처가 바뀌어도 동일하게 남는다.
2. **SCRWKV 워치리스트 등재**: 몇 달 뒤(가중치 공개·독립 재현 여부 확인 후)
   재평가. 대표자가 "지금 당장 문자 그대로 최고 숫자"를 원하면 이 리스크를
   감수하고 지금 채택하는 것도 정책적으로는 막히지 않는다 — 다만 그건 엔지니어링
   실행 리스크를 대표자가 명시적으로 받아들이는 결정이어야 한다.
3. **CrackSCF/CrackMamba(shengyu27)의 "LICENSE 파일 없음" 상태**: 둘 다 AGPL보다
   오히려 더 막힌 상태(저자 허가 없이는 기본적으로 사용 불가) — 저자 컨택 없이는
   채택 후보에서 제외.
4. 기존 문서의 미결 사항(CiF 다운로드 경로 확보, 세그멘테이션→Detection/Observation
   계약 편입)은 그대로 유효 — 재도출하지 않음.

### 출처

- SCRWKV — [arXiv 2605.14926](https://arxiv.org/abs/2605.14926) / [ICML 2026 poster](https://icml.cc/virtual/2026/poster/62616) / [GitHub](https://github.com/zhxhzy/SCRWKV)
- MixerCSeg — [arXiv 2603.01361](https://arxiv.org/html/2603.01361v1) / [CVPR 2026 Open Access](https://openaccess.thecvf.com/content/CVPR2026/html/Zhao_MixerCSeg_An_Efficient_Mixer_Architecture_for_Crack_Segmentation_via_Decoupled_CVPR_2026_paper.html) / [GitHub](https://github.com/spiderforest/MixerCSeg)
- CrackSCF — [arXiv 2408.12815](https://arxiv.org/html/2408.12815v1) / [GitHub](https://github.com/Karl1109/CrackSCF)
- SCSegamba — [arXiv 2503.01113](https://arxiv.org/abs/2503.01113) / [CVPR 2025 Open Access](https://openaccess.thecvf.com/content/CVPR2025/html/Liu_SCSegamba_Lightweight_Structure-Aware_Vision_Mamba_for_Crack_Segmentation_in_Structures_CVPR_2025_paper.html) / [GitHub](https://github.com/Karl1109/SCSegamba)
- CrackMamba(Topology-aware) — [arXiv 2410.19894](https://arxiv.org/abs/2410.19894) / [Automation in Construction](https://www.sciencedirect.com/science/article/abs/pii/S0926580524005818) / [GitHub](https://github.com/shengyu27/CrackMamba)
- 재현성 함정 서베이 — [arXiv 2508.10256](https://arxiv.org/html/2508.10256v1)
- AGPL §13 원문 — [gnu.org/licenses/agpl-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html), Ultralytics의 공격적 해석 — [docs.ultralytics.com/models/yolo11](https://docs.ultralytics.com/models/yolo11), 마이크로서비스 경계 미확정 논의 — [OSPOCO](https://ospo.co/blog/questions-and-answers-about-the-agpl/)
- ADR-KSI-012 D2 — `docs/architecture/ADR-KSI-012-reconstruction-pipeline.md`(AGPL 경계 정책 원본, 44-67행)
- dacl10k/CiF/GYU-DET 관련 출처는 아래 "후보 상세"·"확장" 절 인용 그대로

---

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
