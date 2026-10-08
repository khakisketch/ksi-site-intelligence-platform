# MSDK Field Bridge candidate

이 디렉터리는 `MSDK_FIELD`의 preflight/postflight 후보 native 경계다. 현재 저장소에는
DJI MSDK artifact와 Android build environment가 없으므로 `SDK_BUILT`나 HIL support를
주장하지 않는다. 서버측 candidate adapter는 `SIGNED_CONTRACT_TRANSFER`와
`MEDIA_READ_ONE`만 이 bridge에 보낼 수 있다.

금지 경계:

- Virtual Stick, 이륙, 착륙, RTH, waypoint 실행
- 짐벌 제어, 촬영 시작, 파일 삭제, storage format
- 실행 가능한 좌표를 포함한 명령 envelope
- Pilot 2를 대체하는 비행 UI

SDK artifact와 EULA가 준비되면 이 계약을 Android app의 TLS-pinned transport와 MSDK
media read API에 연결한다. 그 빌드는 `tools/edge/check_msdk_bridge_boundary.py`를 먼저
통과하고 실제 M4D + RC Plus 2 HIL evidence 전에는 `NOT_VERIFIED`로 유지한다.
