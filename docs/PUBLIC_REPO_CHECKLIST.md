# 공개 저장소 점검표 (PUBLIC_REPO_CHECKLIST)

Status: 2026-10-13 작성. 이 문서는 공개 전환 후 표면 점검 기록이며 제품 정본·수용 상태를 바꾸지 않는다.
정본 우선순위는 [`DOCUMENT_STATUS.md`](DOCUMENT_STATUS.md)를 따른다.

## 확인 완료

- [x] README 이미지·링크 점검 (2026-10-13): 본문의 상대 경로 참조 30여 건 존재 확인, 이미지 전부 로드 확인.
- [x] 합성 표기: README 첫 화면·시연·캡처는 합성 데모 데이터임을 명시. 수치(`-0 / 0 / 0 m³`)는 측정 기록 예시이며 정확도·정산·측량 수용 근거가 아님을 명시.
- [x] 테스트 배지 정직 표기: 초록색 통과 배지 제거, `로컬 검증 2026-10-13` 중립 배지 + GitHub Actions 비활성(계정 결제 문제) 명시.
- [x] 제한적 비밀 스캔 (2026-10-13, 추적 파일 대상): 개인키 헤더·`ghp_/gho_`·`AKIA` 패턴 0건.
  `aws_secret_access_key`·`Bearer …-test-token` 형식은 테스트 픽스처의 플레이스홀더 값만 검출됨
  (`tests/contract/*`, `archive/acquisition-2026/*/tests/*`, 키 형식 검사 가드 1건 제외).
  전체 이력·미추적 파일은 미점검(아래 참조).
- [x] 저장소 공개 상태: `PUBLIC`, 설명·토픽 8건 설정. 커스텀 소셜 프리뷰는 미적용(아래 참조).

## 사용자 결정·조치가 필요한 항목

- [x] **라이선스 결정 (2026-10-13 사용자 결정: 권리 보유)**: `LICENSE` 파일을 두지 않고,
  README 문의 절에 별도 서면 허가 없는 복제·배포·상용 사용 불허를 명시했다.
  Public 공개와 사용 허가는 별개임을 유지한다.
- [ ] **브랜치 정리**: 원격 포함 20여 개 브랜치·877 커밋이 공개 노출 중. 유지/삭제 대상을 지정하면 별도 승인 후 정리한다.
  무단 삭제·히스토리 개작 금지.
- [ ] **`data/geoid/KNGeoid24.tif` 재배포 조건 확인**: 취득 경로는
  [`docs/geo/GEOID_ACQUISITION.md`](geo/GEOID_ACQUISITION.md)에 문서화돼 있으나,
  국토지리정보원 신청·동의 조건상 공개 재배포 권한은 미확인. 외부에 널리 공유하기 전 확인 필요.
  확인 전까지는 현행 추적 상태를 유지하고 재배포를 권장하지 않는다.
- [ ] **소셜 프리뷰 업로드(수동)**: `docs/portfolio/social-preview-1280x640.png`(브랜드 카드) 완성.
  GitHub REST API로 등록할 수 없으므로 저장소 Settings → General → Social preview에서 직접 업로드한다.
- [ ] **전체 이력 비밀 점검**: 위 스캔은 현행 추적 파일의 패턴 검사에 한정한다.
  과거 커밋·삭제 브랜치·미추적 파일 포함 정밀 점검(전용 도구)과 결과 기록이 별도로 필요하다.
- [ ] **라이브 공개 데모**: 개발 워크스테이션(loopback OIDC·시크릿 상주)을 공개 노출하지 않는다.
  공개 URL·TLS·시드·유지 주체가 정해지면 격리 호스트에서 `deploy/compose.synthetic-staging.yaml` 경로로 별도 승인 후 기동한다.

## 롤백

이 점검표·README·포트폴리오 자산만 되돌리려면:

```bash
git checkout -- README.md docs/portfolio docs/PUBLIC_REPO_CHECKLIST.md
```
