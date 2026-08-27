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
├─ open_platform_probe.py Pilot 2 WebView의 JSBridge 이름만 확인하는 무상태 HIL probe.
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
모두 있어야 가능하다. Runtime configuration과 trusted routing context의 organization,
Site, Gateway device, Edge device binding도 정확히 일치해야 하며 request body의 scope는
이 context를 바꿀 수 없다(INV-060). candidate code와 SDK build는 production 지원 증거가 아니다.

## Pilot 2 Open Platform read-only probe

개방형 플랫폼의 최초 실기 확인은 전체 Cloud API를 구성하지 않고 아래 probe만 띄운다.

```bash
uv run --locked python -m ksi_dji_gateway.open_platform_probe --bind 0.0.0.0 --port 8080
```

Pilot 2에는 같은 LAN에서 접근 가능한 `http://<workstation-ip>:8080/pilot-connect`를
입력한다. 이 페이지는 `window.djiBridge`와 공식 bootstrap 함수 이름의 존재 여부만
읽으며 어떤 DJI 함수도 호출하지 않는다. 토큰·RC/기체 SN을 읽지 않고, 결과를 서버에
전송하지 않으며, Mission/Media/MQTT/WS/MOP 모듈도 로드하지 않는다. 이 probe 성공은
Cloud API license 인증이나 exact M4D + RC Plus 2 capability의 `VERIFIED` 근거가 아니다.
