# Pilot 2 인텔리전스 기능과 KSI 개방형 플랫폼 경계

> 날짜: 2026-08-27
> Requirements: REQ-ACQ-101/103, REQ-INT-101, REQ-SEC-101
> Invariants: INV-001/002/040/041/042/050/060

## 결론

Pilot 2의 인텔리전스 기능 관리는 DJI가 제공하는 별도 AI 배포·호출 체계다. 메뉴에
`로컬 알고리즘`, `클라우드 알고리즘`, `기체의 알고리즘`이 보인다고 해서 현재
Manifold 3의 KSI Edge Runtime이나 KSI Model Pack이 자동으로 등록된 것은 아니다.

KSI는 다음 순서를 채택한다.

1. Open Platform H5/JSBridge 접속점만 read-only로 확인한다.
2. 별도 DJI Cloud API license를 준비해 bootstrap 인증만 확인한다.
3. wayline/media의 read-only 목록 연동을 exact hardware에서 확인한다.
4. KSI 모델을 DJI AI Inside 형식으로 이중 배포할 필요가 있는지 별도 결정한다.

1단계 결과만으로 2~4단계나 어떤 production capability도 활성화하지 않는다.

## 세 메뉴의 의미와 KSI 사용 가능성

| Pilot 2 메뉴 | DJI 쪽 의미 | KSI에서의 현재 판정 |
|---|---|---|
| 로컬 알고리즘 | Pilot 2/RC에 내려받거나 외부 저장매체에서 가져온 DJI 호환 알고리즘 패키지 | KSI DPK/Model Pack과 다른 형식. 자동 호환으로 보지 않음 |
| 클라우드 알고리즘 | 영상 stream을 제3자 cloud inference endpoint로 보내고 처리 화면을 받는 방식 | 현장별 데이터 반출 동의와 지연·보안 검토 후 선택 가능. 비행 안전 판단에는 사용 금지 |
| 기체의 알고리즘 | DJI가 승인·변환·배포한 모델을 기체 내장 연산 또는 지원되는 Manifold 3 경로에서 실행 | 장기 후보. KSI 기존 Edge Runtime을 대체하거나 자동 등록하지 않음 |

DJI FlightHub 2 공식 설명은 제3자 알고리즘을 기체 내장 연산 모듈과 Manifold 3에
통합할 수 있다고 밝힌다. DJI Intelligent Computing Platform은 모델을 로컬에서
학습한 뒤 Developer Platform에 업로드하고, 양자화 후 지정 장비에 배포하는 별도
workflow를 설명한다. 이것은 KSI의 서명된 Model Pack·Edge loader·Mission Contract
계보와 별개의 배포 체계다.

따라서 같은 모델을 두 체계에 배포하려면 최소한 다음이 추가로 필요하다.

- 원본 dataset/model revision과 DJI 변환 산출물 digest의 양방향 lineage
- DJI 양자화 전후 정확도·성능 비교
- exact M4D/Manifold 3 firmware HIL
- DJI algorithm result를 KSI Observation/Event 후보로 변환하는 typed adapter
- uninstall/rollback과 KSI native runtime 간 resource conflict 시험

이 증거가 없으면 DJI 알고리즘 결과는 KSI의 Confirmed Event, CoverageReport,
CaptureQualityReport 또는 비행 의사결정의 권위가 될 수 없다.

## 경고 목록 활용

`경고 목록`은 DJI 인텔리전스 기능이 만든 경고를 보여주는 운영 표면으로 취급한다.
향후 읽기 API가 exact 조합에서 확인되면 KSI는 이를 `vendor observation candidate`로
수신할 수 있다. 다만 다음을 지킨다.

- DJI 경고를 KSI Event 원장에 그대로 Confirmed로 쓰지 않는다.
- organization/site/mission scope를 서버의 인증 context로 다시 결속한다.
- 모델·firmware·threshold·capture time·source frame lineage가 없으면 fail-closed한다.
- Manifold의 로컬 위험 판단이나 DJI Flight Controller 안전 기능을 cloud 경고로 대체하지 않는다.

## Open Platform 1단계

현재 구현은 `services/dji-gateway`의 read-only probe다.

```bash
uv run --locked python -m ksi_dji_gateway.open_platform_probe \
  --bind 0.0.0.0 --port 8080
```

Pilot 2 → Cloud Services → Open Platforms에서
`http://<workstation-ip>:8080/pilot-connect`를 연다. 페이지는 다음 이름의 존재만
확인하고 호출하지 않는다.

- `platformGetVersion`
- `platformIsVerified`
- `platformVerifyLicense`
- `platformLoadComponent`
- `platformIsComponentLoaded`
- `apiGetToken`

페이지는 token·RC/기체 SN을 읽지 않고, 결과를 서버로 보내지 않으며, DJI component를
로드하지 않는다. 브라우저의 network 송신도 CSP `connect-src 'none'`으로 차단한다.

## 공식 근거

- DJI Cloud API JSBridge: https://developer.dji.com/doc/cloud-api-tutorial/en/api-reference/pilot-to-cloud/jsbridge.html
- Pilot access to third-party cloud: https://developer.dji.com/doc/cloud-api-tutorial/en/feature-set/pilot-feature-set/pilot-access-to-cloud.html
- Pilot Wayline Management: https://developer.dji.com/doc/cloud-api-tutorial/en/feature-set/pilot-feature-set/pilot-wayline-management.html
- Cloud API Product Supported: https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html
- DJI Intelligent Computing Platform: https://developer.dji.com/cn/ai-developer/
- FlightHub 2 algorithm overview: https://enterprise.dji.com/flighthub-2

## Rollback

Probe 프로세스를 종료하면 외부 상태는 남지 않는다. 구현 rollback은 probe 모듈과
문서·테스트 커밋만 revert한다. 기존 Mission Contract, FlightArtifact, capability
registry와 모든 feature flag는 변경하지 않는다.
