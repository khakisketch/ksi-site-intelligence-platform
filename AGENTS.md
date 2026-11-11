# KSI Site Intelligence 작업 지침

- 제품·계약의 권위와 작업 진입점은 [제품 및 개발 기준](docs/00_READ_FIRST.md)을 따른다. 해당 소유자 코드·계약·테스트를 함께 확인한다.
- [도메인 불변식](docs/product/DOMAIN_INVARIANTS.md)을 지킨다. 기계 검증이나 RTK FIX만으로 정량·정산·현장·고객 수락을 주장하지 않는다.
- 참조 저장소를 런타임에서 직접 가져오거나 명시적 요청 없이 핀을 바꾸지 않는다. [이관 검증 입력](docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json)을 보존한다.
- 계획·진행·검토 기록은 대화에서 다룬다. 계속 유지해야 할 계약은 기존 정본에 반영한다.

## 구현과 외부 기술 채택

- KSI는 외부 사진측량 소프트웨어의 산출물을 활용하는 전문 분석 플랫폼이다. 원본 사진 처리·매핑·재구성 엔진 개발과 실행은 제품 범위에서 제외한다. 상세 경계는 [제품 요구사항](docs/product/MASTER_PRD_v3.0.md)을 따른다.
- 먼저 해당 기능의 기존 구현·의존성·계약·테스트를 확인한다. 직접 구현하기 전에 검증된 오픈소스·라이브러리·SDK·CLI의 재사용 가능성을 검토하되, 기존 의존성으로 해결되면 새 의존성을 추가하지 않는다.
- 자체 구현은 필요성이 입증될 때만 개발한다. 외부 검증 기술·기존 의존성으로 해결되는 문제는 직접 만들지 않으며, 직접 구현을 택하려면 동일 입력·구역·허용오차 기준의 비교로 유지보수·성능·안정성·라이선스·보안·패키징·배포 비용의 실질적 이점이 입증되어야 한다.
- 정상 작동하는 기능은 불필요하게 교체하지 않는다. 외부 기술은 자체 구현 대비 유지보수·성능·안정성·라이선스·보안·패키징·배포 비용의 실질적 이점이 확인되는 부분만 채택한다. 새 버전이나 기능 목록만으로 성능·정확도 향상을 주장하지 않는다.
- 기존 워커에서 라이브러리를 직접 호출하는 것으로 충분하면 별도 추상화 계층·커넥터 프레임워크·서비스를 만들지 않는다. 에이전트 활용만을 이유로 새 데이터베이스·메타데이터 표준을 선행 도입하지 않는다.
- 분석 엔진·버전·전처리 변경은 동일 입력과 구역에 대한 수치 허용오차·NoData·경계 픽셀·실패 처리·자원 사용을 비교한다. 채택 시 기존 결과와 계보를 덮어쓰지 않고 해당 버전·프로필·주요 설정을 결속하며, 품질 판정과 권한·수락 경계는 KSI가 유지한다.

## 은퇴 상태와 에이전트 파일 처리

- KSI-managed 재구성 발급·실행은 은퇴했다. 새 managed ProcessingJob을 발행·전이·lease·등록하지 않으며, NodeODM 워커 체인도 없다. 역사 재구성 기록은 읽기 전용 replay·조회로만 다룬다. 봉인된 역사 profile binding 1건(`ksi-odm-civil-v1`)은 `services/core/src/ksi_core/domains/processing/historical_processing_profiles.py`가 소유하고, 미등록·변조 binding은 replay가 fail-closed로 거부한다.
- 에이전트 파일 처리 규칙: 공간 파일은 `services/spatial-data-mcp`의 `fileReference`(인가된 receipt에서만 파생된 `spatial-data-file-reference.v1` 기술자)로 참조한다. 창 읽기는 `services/processing-controller/src/ksi_processing_controller/spatial_data_worker.py`의 native-window 요청(`plan_external_native_window`)과 `packages/geo-spatial/src/ksi_geo_spatial/external_native_window.py`의 픽셀 상한·창 읽기(`max_output_pixels`·`max_output_bytes`·envelope 한도)를 통해서만 수행한다. 모델에는 권한 있는 자산 참조·작업 ID·한도 있는 메타데이터/통계·근거만 반환한다. 전체 GeoTIFF·전체 픽셀 배열·base64 본문을 도구 응답이나 프롬프트에 넣지 않는다. 실제 파일 접근은 현장/조직 권한·허용 용도·자원 한도·감사를 유지하는 워커가 수행한다.
