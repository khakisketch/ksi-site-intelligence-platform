# ADR-KSI-032 — Civil Operations runtime provenance와 처리 자원정책 v1

- Status: Accepted
- Date: 2026-08-30
- Requirements: REQ-OPS-101/102, REQ-WRK-101, REQ-INT-104, REQ-SEC-101, REQ-UX-101
- Invariants: INV-040/050/053/054/055/060
- Related: ADR-KSI-008, ADR-KSI-010, ADR-KSI-012, ADR-KSI-030, ADR-KSI-031
- Supersedes: 없음. 기존 원본·ProcessingJob·산출물·보고서와 비교 판정을 수정하거나
  재작성하지 않는다.

## Context

토목 처리의 엔진 recipe와 NodeODM 이미지는 이미 불변 profile로 고정됐지만, 외부 VM을
조립하는 Python·Node·MinIO·Caddy·보조 이미지에는 tag-only 또는 `latest` 참조가 남아
있었다. 같은 Git commit을 다시 배포해도 다른 bytes가 내려올 수 있으므로, 애플리케이션
lockfile만으로는 실행물을 재현할 수 없다.

처리 작업도 임무당 활성 작업 1건, worker lease·heartbeat·재회수는 구현돼 있으나 한 조직이
무제한 크기의 봉인 번들과 무제한 대기 작업을 발급하는 것을 막는 서버 소유 admission
정책은 없었다. Dashboard의 batch 크기나 브라우저 validation은 보안 경계가 아니다. 반대로
임의의 숫자를 환경변수 하나로 바꾸고 과거 job에 소급 적용하면, 같은 job이 어느 보호
envelope 아래 발급됐는지 재생할 수 없다.

## Decision

### D1 — 제품 소유 runtime 이미지는 tag와 multi-architecture digest를 함께 고정한다

프로덕션 Dockerfile의 모든 외부 `FROM`/`COPY --from`과 배포 Compose의 모든 외부
`image`는 사람이 읽을 수 있는 정확한 버전 tag와 OCI manifest-list digest를 함께 쓴다.
`latest`, floating minor tag, digest 없는 외부 runtime은 정적 release gate가 거부한다.

로컬에서 빌드한 `ksi-*:*local` 이미지는 외부 공급망이 아니라 그 배포의 build output이므로
예외다. 다만 실제 release에서는 소스 SHA와 산출 이미지 digest를 별도 release manifest와
SBOM에 결속해야 한다. `references/`는 읽기 전용 참고 저장소라 이 게이트의 제품 소유
대상이 아니다.

### D2 — Core가 versioned Processing Resource Policy를 소유한다

Civil pilot의 첫 정책은 `ksi-civil-pilot-r1`이다. 파일 수, 개별 원본 신고 byte, 번들
신고 byte 합계, 총 megapixel, 조직별 활성 ProcessingJob 수의 상한을 불변 snapshot으로
정하고 canonical SHA-256 digest를 계산한다. 이 값은 정확도나 요금제가 아니라 single-
customer pilot에서 runaway storage/queue/compute를 막는 보호 envelope다. 실제 부하시험
결과로 값을 바꾸려면 같은 ID를 수정하지 않고 새 policy ID를 발급한다.

클라이언트는 policy ID, 상한, override를 ProcessingJob 발급 요청에 제출하지 않는다.
Core가 봉인 SourceMedia와 Mission/Site 조직 원장에서 직접 측정해 admission을 판정한다.
한도를 넘으면 숫자를 잘라 실행하거나 다른 profile로 fallback하지 않고 typed reason을
반환한다.

### D3 — 발급 당시 policy snapshot과 digest를 journal에 결속한다

새 ProcessingJob 발급 레코드는 full resource-policy snapshot과 digest를 함께 보존한다.
재생은 digest를 다시 계산하고, 반쪽 binding·위조 snapshot·당시 snapshot 자체를 위반한
발급 레코드를 거부한다. policy 도입 이전 기록은 값을 추정하지 않고
`LEGACY_UNMANAGED`로 읽는다.

동일한 활성 job의 멱등 재요청은 현재 policy를 다시 적용해 과거에 성공한 요청을 실패로
바꾸지 않고 기존 record를 반환한다. 다른 새 작업에는 현재 policy를 적용한다. 정책 목록은
인증 사용자에게 read-only로 제공해 Dashboard와 로컬 업로더가 상수를 복제하지 않게 한다.

### D4 — admission과 물리 byte enforcement를 구분한다

v1의 byte 수는 SourceMedia 등록 claim을 서버가 합산한 admission 값이며, 실제 byte는 worker가
전량 다운로드해 SHA-256·길이·해상도를 다시 재는 기존 검증이 최종 권위다. 일반 presigned
PUT이 object-store 용량 자체를 보장한다는 주장은 하지 않는다. 버킷 quota와 upload-time
content-length enforcement는 실제 선택한 S3 사업자·브라우저 호환 검증 뒤 별도 adapter
capability로 연다. claim보다 큰 bytes는 기존 worker 검증에서 실패하며 성공 job 근거가 될
수 없다.

### D5 — 기존 Operations Console 안에서만 상태를 표현한다

Console은 기존 업로드·처리 카드에서 현재 policy 이름과 사용량/상한, typed 거부 이유와
다음 행동을 보여준다. 새 전역 메뉴나 별도 관리자 제품을 만들지 않는다. 시스템 운영자는
기존 metrics·구조화 로그와 조직 범위의 job projection을 사용하며, raw filename·좌표·사진
내용은 metric label이나 일반 로그에 넣지 않는다.

## Security, operations and claims

- image digest pin은 취약점이 없다는 뜻이 아니다. SBOM·scanner 결과·승인자는 release별로
  별도 기록한다.
- resource policy 통과는 처리 성공, 비용 확정, 현장 정확도 또는 고객 데이터 배포 승인이
  아니다.
- 조직별 활성 작업 수는 Mission/Site 원장에서 유도하며 요청 body의 organization ID를
  신뢰하지 않는다(INV-060).
- GitHub Actions billing, 실제 외부 IdP/Cloud, 국내 현장 데이터, FIELD-0a와 DJI capability는
  이 ADR로 승인되거나 승격되지 않는다.

## Rollback

신규 policy 발급 경로를 read-only로 내리고 기존 job·원본·산출물·보고서는 그대로 조회한다.
과거 journal에서 policy snapshot을 지우거나 `LEGACY_UNMANAGED`에 현재 값을 소급하지 않는다.
런타임 image pin은 availability를 위해 `latest`로 되돌리지 않고, 검증된 이전 digest로
rollback한다. 정량 비교의 fail-closed compatibility gate는 완화하지 않는다.
