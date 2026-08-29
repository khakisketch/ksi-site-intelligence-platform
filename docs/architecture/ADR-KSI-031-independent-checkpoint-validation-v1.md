# ADR-KSI-031 — 독립 검사점 DSM 검증 v1

- Status: Accepted
- Date: 2026-08-29
- Requirements: REQ-INT-101/104, REQ-SEC-101, REQ-UX-101
- Invariants: INV-020/023/024/040/050/053/060
- Related: ADR-KSI-012, ADR-KSI-016, ADR-KSI-030
- Supersedes: 없음. 기존 `ProcessingArtifact.accuracy`, 처리 결과, 비교 요청과 리포트를
  수정하거나 재작성하지 않는다.

## Context

체적 비교에는 이미 양쪽 epoch의 독립 검사점 RMSE가 있을 때만
`uncertaintyM3`를 계산하는 계약과 배선이 있다. 그러나 KSI-managed NodeODM 경로에는
검사점 리포트 생산자가 없어서 값이 항상 `null`이었다. 산출물 등록자가
`checkpointRmseM` 숫자만 신고하는 경로는 외부 adapter 호환에는 필요하지만, KSI가
관리하는 처리 경로에서 실제 어떤 검사점과 어떤 DSM을 대조했는지 증명하지 못한다.

사용자가 RMSE를 입력하게 하면 계산값과 주장이 같은 신뢰 경로에 놓인다. 반대로 Core가
대용량 래스터 바이트를 직접 중계·해석하면 control plane에 GDAL 처리 책임이 섞인다.
설계면 검증과 마찬가지로 바이트 관측은 Processing Controller가, 불변 원장·권한·최종
판정은 Core가 소유해야 한다.

## Decision

### D1 — 입력은 DSM별 봉인된 독립 검사점 CSV다

v1은 UTF-8 CSV 한 형식만 받는다.

```text
checkpoint_id,easting_m,northing_m,elevation_m
```

파일은 5 MiB 이하, 3~10,000점, 고유한 비공백 ID와 finite meter 좌표·표고를 가져야
한다. 등록 시 사용자는 파일 SHA-256·크기·CRS·수직기준과 “재구성 조정/GCP와 독립된
검사점”이라는 명시적 attestation 및 근거를 제출한다. 사용자가 제출할 수 있는 정확도
숫자 필드는 없다.

등록은 완료된 DSM artifact에만 결속한다. Core가 mission/site/organization,
DSM artifact ref·digest·CRS·수직기준과 고정 검증 profile
`ksi-dsm-checkpoint-nearest-v1`의 digest를 snapshot으로 굳힌다. 객체 키는 서버가 만들고,
`REGISTERED → SEALED → VALIDATED|REJECTED`는 append-only다. 거부 후 복구는 과거 판정을
고치는 것이 아니라 새 validation을 등록하는 것이다.

### D2 — 워커가 두 원본 바이트를 직접 읽고 전점을 대조한다

Processing Controller는 presigned GET으로 봉인된 CSV와 대상 DSM을 받아 각각 SHA-256을
다시 계산한다. DSM은 단일 band·지원 CRS여야 하고, CSV CRS 및 수직기준은 artifact와
직접 비교 가능해야 한다. 고정 profile은 각 검사점 좌표에서 nearest pixel center를
샘플링하며, 점 하나라도 래스터 밖이거나 nodata면 부분 통계를 만들지 않고 전체 검증을
typed rejection으로 끝낸다.

잔차는 `DSM elevation - checkpoint elevation`이고, 전점의 count, mean, MAE, vertical
RMSE, maximum absolute error를 결정적으로 계산한다. 네트워크·스토리지 5xx/만료 URL 같은
일시 실패는 영구 거부로 기록하지 않고 다음 polling에서 재시도한다. 반면 새 presigned
GET에서도 원본 객체가 404인 상태는 `CHECKPOINT_OBJECT_MISSING`/`DSM_OBJECT_MISSING`으로
종료해 새 검증을 등록할 수 있게 한다. 워커가 보낸 관측에서 Core는 실제
digest·size·CRS와 통계의 산술 일관성을 다시 대조한 뒤에만 `VALIDATED`를 각인한다.

### D3 — 비교는 KSI 검증값을 우선하고 과거 adapter 의미를 보존한다

비교 입력은 동일 artifact에 결속된 최신 terminal `VALIDATED` 기록의 RMSE를 우선한다.
없으면 기존 외부 adapter 호환 경계인
`ProcessingArtifact.accuracy.checkpointRmseM`을 읽되, GCP fitting `accuracy.rmse`는 절대
사용하지 않는다. 양쪽 DSM 모두 근거가 있을 때만 기존 제곱합근×구역면적 방식으로
`uncertaintyM3`를 계산하고, 보고서 note는 서버 직접 대조 근거를 밝힌다. 한쪽이라도
없으면 기존대로 `null + reason`이다.

검사점 검증은 정량 비교의 필수 조건으로 추가하지 않는다. 같은 profile·lineage·CRS·
수직기준을 가진 두 epoch의 상대 물량은 계속 계산할 수 있지만, 검증 없이는 오차한계·
절대 정확도·측량급 또는 계약 정산 주장을 할 수 없다.

### D4 — 기존 Console에 선택형 카드만 추가한다

Mission 상세의 기존 원본 업로드와 비교 카드 사이에 “독립 검사점 검증(선택)” 카드를
추가한다. 사용자는 완료 DSM, CSV, CRS·수직기준·독립 근거를 고르고 attestation을
명시적으로 체크한다. UI는 SHA-256과 업로드를 수행하고 상태·typed rejection·서버 계산
RMSE/MAE를 표시하지만 RMSE 입력란은 제공하지 않는다. Home·현장·작업·확인 항목,
전역 메뉴, 디자인 시스템과 기존 비교 UX는 바꾸지 않는다.

## Security, data and claims

- 사람 등록·봉인은 site write 권한과 organization 범위를, 워커 관측은
  `PROCESSING_WORK` 전용 자격을 사용한다. 다른 조직의 job·artifact·validation은
  존재하지 않는 것처럼 404로 접는다(INV-060).
- 원본 CSV와 좌표는 object storage에만 두고 Git·일반 로그·리포트 문자열에 싣지 않는다.
  원장은 정제된 파일명, 운영자 선언·독립 근거, digest·계보와 집계 통계만 보존한다.
- “독립”은 운영자 attestation이며 서버가 측량 작업의 실제 독립성을 물리적으로 증명한
  것은 아니다. 따라서 software `VALIDATED`는 측량급·정산 수용이 아니다.
- 국내 현장 수용은 실제 두 epoch와 독립 측량 성과로 별도 평가하며, 기존 FIELD-0a와
  DJI capability 상태를 바꾸지 않는다.

## Rollback

`KSI_CORE_CHECKPOINT_VALIDATION_ENABLED=false`와
`NEXT_PUBLIC_KSI_CHECKPOINT_VALIDATION_ENABLED=0`으로 신규 등록/Console mutation을 닫는다.
기존 기록과 조회는 read-only로 유지하고 이미 봉인된 항목은 안전하게 terminal 판정할 수
있다. 기존 `ProcessingArtifact`, DSM, 원본, 비교 결과를 삭제하거나 accuracy gate를
느슨하게 하지 않는다.
