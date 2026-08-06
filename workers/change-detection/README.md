# workers/change-detection

Temporal alignment and spatial change processing.

**실구현 위치**: `services/change-detection/`(`ksi_change_detection`,
uv workspace 멤버). `workers/*`는 uv workspace에서 제외돼 있고(`pyproject.toml`
`tool.uv.workspace.exclude`), 이 저장소의 실제 관례는 `services/processing-controller`
(ODM 워커)처럼 워커 코드도 `services/*` 아래 둔다 — 이 디렉터리는 초기 계획
스캐폴딩만 남은 상태다(2026-08-06).
