# services/dji-gateway

DJI integration gateway: verified Cloud/PSDK-facing adapters; no product intelligence ownership.

## Source boundaries

```text
src/ksi_dji_gateway/
├─ domain/        capability·transport·요청·영수증. SDK import 금지.
├─ ports/         MissionDelivery / EdgeDispatch / EdgeUplink / MediaTransfer SPI.
├─ routing/       기능별 VERIFIED evidence + feature flag 기반 경로 선택.
├─ persistence/   idempotency journal. v1.2/v1.3 reader, 명시적 receipt-version writer.
├─ adapters/      다섯 path candidate port + pinned HTTPS/Unix bridge transport.
├─ coordinator.py capability route를 v1.3 receipt로 실행하는 idempotent coordinator.
└─ gateway.py     기존 ZeroTouchGateway 공개 API를 보존하는 compatibility facade.
```

RC Plus 2, Manifold direct, MSDK Bridge, Dock 3 차이는 향후 adapter에서만 구현한다.
구현 파일이나 SDK 헤더가 있다는 이유로 capability를 `VERIFIED`로 만들지 않는다.
새 adapter는 필요한 port만 구현하며 비행 제어 권한을 이 서비스에 추가하지 않는다.
기존 facade는 v1.2 receipt를 유지하고, 새 capability 경로의 v1.3 receipt는
capability와 transport가 모두 있어야만 기록된다.

2026-08-26 대표자 개정에 따라 다섯 `IntegrationPath`의 candidate adapter를 미리
구현한다. 각 adapter는 정본 capability catalog에 있는 좁은 port만 광고한다. 실제 호출은
runtime configuration, exact hardware/firmware HIL evidence, capability feature flag가
모두 있어야 가능하다. candidate code와 SDK build는 production 지원 증거가 아니다.
