# KSI-Terra-derived Acceptance Addendum

## Processing

- 실제 이미지가 queued→processing→finalized 상태전이를 통과한다.
- production에서 PlaceholderRunner로 finalized가 될 수 없다.
- Worker kill 후 같은 NodeODM job_ref에서 resume된다.
- 같은 Job을 다중 Worker가 중복 선점하지 않는다.
- transient 오류는 backoff, permanent 오류는 dead-letter된다.

## Spatial Quality

- CRS 미지정/불일치 산출물은 거부된다.
- vertical datum이 기록된다.
- GCP 미검증이면 절대 RMSE가 API/UI에서 노출되지 않는다.
- RTK Fix는 품질 신호로만 표시된다.
- GCP와 CP가 분리된다.
- ODM GCP 적용 여부가 엔진 로그와 품질 리포트에 기록된다.

## Artifacts

- COG range read가 동작한다.
- COPC 부분 스트리밍이 동작한다.
- 3D Tiles가 실제 현장 위치·방향으로 렌더된다.
- 대형 모델은 계층 LOD를 사용한다.
- 모든 Artifact가 입력 manifest와 engine version을 가진다.

## Change/Quantity

- 비교 회차가 둘 다 finalized여야 한다.
- 동일 CRS co-registration 후에만 비교한다.
- cut/fill 규약이 고정된다.
- 유효 셀·threshold·오차근거가 기록된다.

## Security/License

- cross-org 읽기·다운로드가 차단된다.
- production dev-header 인증이 차단된다.
- signed URL 만료 후 접근이 거부된다.
- SBOM과 third-party notices가 생성된다.
- AGPL 구성요소가 정책 경계를 벗어나지 않는다.
