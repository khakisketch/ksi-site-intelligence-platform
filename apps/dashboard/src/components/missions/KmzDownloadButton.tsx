"use client";

import { useState } from "react";

type DownloadStatus = "idle" | "pending" | "error";

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string; detail?: string };
    // detail 을 먼저 본다 — Core 는 "계약 단독 발급이라 KMZ 가 없다"와 "그런 임무가
    // 없다"를 구분해 주는데, 공통 번역기가 둘 다 404 로 뭉개 "대상을 찾을 수
    // 없습니다."로 만든다. 이 화면에서는 그 구분이 곧 사용자가 할 일을 바꾼다.
    return body.detail ?? body.message ?? "요청을 처리하지 못했습니다.";
  } catch {
    return "요청을 처리하지 못했습니다.";
  }
}

/**
 * 발급된 임무의 KMZ 를 대시보드에서 직접 내려받는다. `hasKmz=false`(계약 단독
 * 발급)면 애초에 파일이 없다는 사실을 눌러보게 하지 않고 바로 보여준다 — "—"로
 * 조용히 넘어가지 않는다(임무 상세 화면의 kmzSha256 필드와 같은 원칙).
 *
 * 클릭 시 재생성이 실패하거나(정책이 바뀌어 더 이상 재현 불가) 저장된 sha256 과
 * 달라 서버가 200 을 거부하면(하류 결정성 위반) 그 사유를 그대로 보여준다 —
 * 성공했다고 속여 빈 파일을 내려주지 않는다.
 */
export function KmzDownloadButton({
  missionId,
  hasKmz,
}: {
  missionId: string;
  hasKmz: boolean;
}) {
  const [status, setStatus] = useState<DownloadStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!hasKmz) {
    return (
      <div className="flex flex-col items-start gap-1">
        <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
          KMZ 다운로드
        </span>
        <span className="text-[12px] break-keep text-ink-muted">
          이 임무는 계약만 발급되어 내려받을 KMZ 파일이 없습니다.
        </span>
      </div>
    );
  }

  async function handleDownload() {
    setStatus("pending");
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/missions/${encodeURIComponent(missionId)}/kmz`);
      if (!response.ok) {
        setErrorMessage(await parseErrorMessage(response));
        setStatus("error");
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      // 서버도 같은 규칙(missionId 기반)으로 Content-Disposition 파일명을 정한다 —
      // 여기서 다시 정해도 어긋나지 않는다(둘 다 결정론적).
      link.download = `${missionId}.kmz`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // click 직후 동기 해제는 Firefox·Safari 에서 다운로드를 취소시키는 사례가
      // 알려져 있다 — 브라우저가 blob 을 읽기 시작할 여유를 주고 해제한다.
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
      setStatus("idle");
    } catch {
      setErrorMessage("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
      setStatus("error");
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={() => void handleDownload()}
        disabled={status === "pending"}
        className="btn"
      >
        {status === "pending" ? "내려받는 중…" : "KMZ 다운로드"}
      </button>
      {status === "error" && errorMessage && (
        <p className="text-[11.5px] font-semibold break-keep text-crit-ink">{errorMessage}</p>
      )}
    </div>
  );
}
