"""Read-only DJI Pilot 2 Open Platform WebView probe.

This module deliberately serves static, same-origin assets only.  The browser
code observes whether a narrow allowlist of JSBridge method *names* exists; it
never invokes a bridge method, reads device identifiers, loads a DJI module, or
sends a result back to the server.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from urllib.parse import urlsplit

_HTML: Final = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>KSI Pilot 2 연결 진단</title>
  <link rel="stylesheet" href="/pilot-connect/probe.css">
</head>
<body>
  <main>
    <p class="eyebrow">KSI SITE INTELLIGENCE</p>
    <h1>Pilot 2 개방형 플랫폼 연결 진단</h1>
    <p class="summary">
      이 페이지는 연결 표면만 읽습니다. 라이선스 인증, 토큰·시리얼 조회,
      DJI 모듈 로드, 파일 전송, 임무·카메라·기체 제어를 수행하지 않습니다.
    </p>
    <section class="verdict" aria-live="polite">
      <span id="badge" class="badge pending">확인 중</span>
      <h2 id="headline">Pilot 2 환경을 확인하고 있습니다.</h2>
      <p id="detail">잠시만 기다려 주세요.</p>
    </section>
    <section>
      <h2>읽기 전용 확인 결과</h2>
      <dl id="checks"></dl>
    </section>
    <section class="boundary">
      <h2>이번 단계의 경계</h2>
      <ul>
        <li>함수는 호출하지 않고 이름의 존재 여부만 확인합니다.</li>
        <li>결과는 이 화면에만 표시하고 서버로 전송하지 않습니다.</li>
        <li>성공해도 DJI capability는 계속 NOT_VERIFIED입니다.</li>
      </ul>
    </section>
  </main>
  <script src="/pilot-connect/probe.js" defer></script>
</body>
</html>
"""

_CSS: Final = """:root {
  color-scheme: light;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f4f5f2;
  color: #17201b;
}
body { margin: 0; }
main { max-width: 760px; margin: 0 auto; padding: 36px 24px 56px; }
.eyebrow { color: #52685a; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
h1 { font-size: clamp(28px, 5vw, 44px); line-height: 1.12; margin: 8px 0 16px; }
h2 { font-size: 19px; line-height: 1.35; }
.summary { color: #425248; font-size: 17px; line-height: 1.65; }
section {
  background: white; border: 1px solid #d9dfda; border-radius: 14px;
  margin-top: 20px; padding: 20px;
}
.verdict { border-left: 6px solid #8a968d; }
.verdict.present { border-left-color: #177245; }
.verdict.absent { border-left-color: #a86216; }
.badge {
  border-radius: 999px; display: inline-block; font-size: 12px;
  font-weight: 800; padding: 6px 10px;
}
.badge.pending { background: #e7eae7; color: #455048; }
.badge.present { background: #daf0e3; color: #0b5b35; }
.badge.absent { background: #f6e5d4; color: #7a4108; }
dl { display: grid; grid-template-columns: minmax(180px, 1fr) auto; gap: 0; margin: 0; }
dt, dd { border-top: 1px solid #edf0ed; margin: 0; padding: 11px 0; }
dt:first-of-type, dd:first-of-type { border-top: 0; }
dd { font-weight: 750; text-align: right; }
.yes { color: #0b6a3b; }
.no { color: #8a4c0c; }
.boundary { background: #f9faf8; }
li { line-height: 1.6; margin: 5px 0; }
@media (max-width: 520px) {
  main { padding: 24px 16px 40px; }
  section { padding: 17px; }
  dl { grid-template-columns: 1fr; }
  dd { border-top: 0; padding-top: 0; text-align: left; }
}
"""

_JS: Final = """(() => {
  'use strict';

  const safeMethodNames = Object.freeze([
    'platformGetVersion',
    'platformIsVerified',
    'platformVerifyLicense',
    'platformLoadComponent',
    'platformIsComponentLoaded',
    'apiGetToken'
  ]);
  const bridge = window.djiBridge;
  const bridgePresent = bridge !== undefined && bridge !== null;
  const methodPresence = Object.fromEntries(
    safeMethodNames.map((name) => [name, bridgePresent && typeof bridge[name] === 'function'])
  );
  const report = Object.freeze({
    schemaVersion: '1.0',
    bridgePresent,
    methodPresence: Object.freeze(methodPresence),
    callsPerformed: 0,
    identifiersRead: 0,
    resultsTransmitted: 0
  });

  const badge = document.getElementById('badge');
  const headline = document.getElementById('headline');
  const detail = document.getElementById('detail');
  const verdict = document.querySelector('.verdict');
  const checks = document.getElementById('checks');

  badge.textContent = bridgePresent ? 'BRIDGE PRESENT' : 'BRIDGE ABSENT';
  badge.className = `badge ${bridgePresent ? 'present' : 'absent'}`;
  verdict.classList.add(bridgePresent ? 'present' : 'absent');
  headline.textContent = bridgePresent
    ? 'DJI Pilot 2 JSBridge 접속점이 보입니다.'
    : 'DJI Pilot 2 JSBridge 접속점이 보이지 않습니다.';
  detail.textContent = bridgePresent
    ? '다음 단계에서 별도 DJI Cloud API 라이선스를 준비해 인증만 검증할 수 있습니다.'
    : '일반 브라우저이거나 이 조합에서 개방형 플랫폼 브리지가 보이지 않습니다.';

  const rows = [
    ['window.djiBridge', bridgePresent],
    ...safeMethodNames.map((name) => [name, methodPresence[name]]),
    ['DJI 함수 호출', report.callsPerformed === 0],
    ['식별정보 조회', report.identifiersRead === 0],
    ['결과 외부 전송', report.resultsTransmitted === 0]
  ];
  for (const [label, value] of rows) {
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value ? '예' : '아니오';
    description.className = value ? 'yes' : 'no';
    checks.append(term, description);
  }

  Object.defineProperty(window, 'KSI_PILOT_OPEN_PLATFORM_PROBE', {
    configurable: false,
    enumerable: false,
    value: report,
    writable: false
  });
})();
"""


@dataclass(frozen=True, slots=True)
class ProbeAsset:
    content_type: str
    body: bytes


_ASSETS: Final = {
    "/pilot-connect": ProbeAsset("text/html; charset=utf-8", _HTML.encode()),
    "/pilot-connect/": ProbeAsset("text/html; charset=utf-8", _HTML.encode()),
    "/pilot-connect/probe.css": ProbeAsset("text/css; charset=utf-8", _CSS.encode()),
    "/pilot-connect/probe.js": ProbeAsset("text/javascript; charset=utf-8", _JS.encode()),
}


class PilotOpenPlatformProbeHandler(BaseHTTPRequestHandler):
    """Serve the static probe without request logging or mutable methods."""

    server_version = "KSI-Pilot-Probe/1.0"
    sys_version = ""

    def _send_asset(self, *, include_body: bool) -> None:
        path = urlsplit(self.path).path
        asset = _ASSETS.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", asset.content_type)
        self.send_header("Content-Length", str(len(asset.body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Security-Policy", _content_security_policy())
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        if include_body:
            self.wfile.write(asset.body)

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._send_asset(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._send_asset(include_body=False)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        """Avoid retaining RC address, path, or headers in a raw access log."""


def _content_security_policy() -> str:
    return "; ".join(
        (
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "connect-src 'none'",
            "img-src 'none'",
            "media-src 'none'",
            "object-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )


def build_probe_server(*, bind: str, port: int) -> ThreadingHTTPServer:
    if not bind.strip():
        raise ValueError("bind address는 비어 있을 수 없다")
    if not 0 <= port <= 65535:
        raise ValueError("port는 0..65535 범위여야 한다")
    server = ThreadingHTTPServer((bind, port), PilotOpenPlatformProbeHandler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pilot 2 Open Platform용 읽기 전용 KSI JSBridge probe를 제공한다."
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = build_probe_server(bind=args.bind, port=args.port)
    bound_host = server.server_address[0]
    host = bound_host.decode() if isinstance(bound_host, bytes) else bound_host
    port = int(server.server_address[1])
    print(f"KSI Pilot 2 read-only probe: http://{host}:{port}/pilot-connect", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PilotOpenPlatformProbeHandler", "ProbeAsset", "build_probe_server", "main"]
