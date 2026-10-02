# Civil field data intake — private package

> **적용 범위:** 이 문서는 과거 KSI-managed Civil Processing v1의 원본 사진→재구성·설계면 비교 수용 절차다. ADR-KSI-036/037의 첫 API-first 제품(고객 장비에서 재구성한 DSM 접수→WorkArea 두 시점 변화 분석)의 자료 요청서가 아니다. 첫 제품 입력은 [첫 요청 계약](../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md)과 [현장 자료 준비 패킷](EXTERNAL_EARTHWORK_FIELD_DATA_INTAKE.md)을 따른다.

이 문서는 Civil Processing v1의 **현장 수용 입력**을 가장 단순하게 준비하는 절차다.
입력 감사가 통과해도 실제 처리·정량 비교·현장 수용이 통과한 것은 아니다. 감사기는
`INPUT_READY` 또는 typed `BLOCKED`만 반환하고 항상
`fieldAcceptance=NOT_EVALUATED`를 유지한다.

## 한 번만 준비할 패키지

다음 자료를 같은 익명 현장에 대해 받는다.

1. KSI의 상업적 처리와 파생 DSM/DTM/GeoTIFF·보고서 생성을 허용하는 서면 동의 또는
   라이선스. 하나의 문서가 두 권리 범위를 모두 허용해도 된다.
2. `baseline`과 `current` 두 회차의 카메라 원본 JPEG. 같은 현장·구역이어야 하며 촬영
   시작/종료 UTC를 기록한다. 감사기의 최소 파일 수는 회차당 5장이지만, 실제 처리에는
   분석 가능한 중복도와 구역 coverage가 별도로 필요하다.
3. 각 회차에 대응하는 서로 다른 GCP/georeferencing 파일. 좌표계, 수직기준, 측량 방법을
   함께 기록한다.
4. LandXML 1.0–1.2 meter TIN 설계면과 사용할 Surface 이름·설계 revision.
5. GCP와 독립된 checkpoint 또는 기준 물량. checkpoint는 개수와 수평/수직 정확도를,
   기준 물량은 값과 불확실성 근거를 포함한다.
6. 모든 입력에 공통인 지원 좌표계(`EPSG:5179`, `5185`, `5186`, `5187`, `5188`)와
   수직 datum/basis.

DWG/DXF만 있다면 설계 담당자에게 LandXML TIN 또는 검증된 GeoTIFF 내보내기를 요청한다.
현장명·주소·좌표·원본 사진은 Git에 넣지 않는다.

## 보관 규칙

정본 경로는 다음 하나다.

```text
~/.local/share/ksi-civil-acceptance/<sessionId>/
```

- root/session/nested directory: owner-only `0700`
- manifest와 모든 증거 파일: owner-only `0600`
- symlink, 상위 경로 참조, 다른 사용자 소유 파일: 금지
- manifest: session 바로 아래 `civil-field-acceptance.json`

Manifest 계약은
[`civil-field-acceptance-manifest.v1.json`](../../contracts/schemas/civil-field-acceptance-manifest.v1.json)이다.
`processingProfileDigest`는 현재 Core registry가 발급한 `ksi-odm-civil-v1` digest와 정확히
같아야 한다. `groundControlFiles`에는 `baseline`/`current`가 각각 한 번만 있어야 하고,
각 epoch의 `georeferencing.evidence`는 같은 epoch의 GCP path와 SHA-256에 정확히 결속된다.

## 읽기 전용 입력 감사

Repository root에서 실행한다.

```bash
uv run python tools/audit_civil_field_acceptance.py \
  --manifest "$HOME/.local/share/ksi-civil-acceptance/<sessionId>/civil-field-acceptance.json"
```

감사기는 파일을 변경하지 않는다. 유효한 결과 예시는 다음과 같다.

```json
{"blockers":[],"fieldAcceptance":"NOT_EVALUATED","schemaVersion":"1.0","sessionId":"...","status":"INPUT_READY"}
```

`INPUT_READY` 이후에만 KSI의 정상 흐름으로 원본 봉인 → 같은 profile로 두 회차 처리 →
comparison preflight → 설계/시점 비교 → 독립 기준 대조를 수행한다. 이 전체 결과와 제한을
검토한 뒤 별도의 현장 수용 판정을 기록한다. 입력 감사만으로 `PASS`, survey-grade,
정산용 또는 절대정확도 표현을 사용하지 않는다.

## 협력 현장에 보낼 짧은 요청문

```text
KSI 토목 시계열·물량 기능의 비공개 검증을 위해 익명 현장 1곳의 자료를 요청드립니다.
필요 자료는 (1) meter 단위 LandXML TIN 설계면과 Surface/revision, (2) 같은 구역의
baseline/current 카메라 원본 JPEG, (3) 각 회차 GCP와 CRS·수직기준·측량 방법,
(4) GCP와 독립된 checkpoint 또는 기준 절·성토 물량과 정확도/불확실성 근거입니다.
KSI의 상업적 처리와 파생 DSM/DTM/GeoTIFF·비식별 결과 생성을 허용한다는 서면 근거도
함께 부탁드립니다. 주소·현장명은 익명화할 수 있고 원본은 비공개 owner-only 저장소에
보관하며 Git에는 넣지 않습니다. 결과는 운영관리용 상대 물량 검증이며 계약 정산이나
측량 성과로 사용하지 않습니다.
```

## 범위 경계

이 절차는 `SD/저장매체 → 현장 PC → KSI 웹 업로드` 후처리 경로만 다룬다. 비행, motor,
waypoint 실행, camera/gimbal 제어, DPK, Pilot 2/Manifold 자동 반출 또는 DJI capability
승격을 수행하거나 허가하지 않는다.
