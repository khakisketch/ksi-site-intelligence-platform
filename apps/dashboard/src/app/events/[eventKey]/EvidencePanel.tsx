"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import { API_ERROR_MESSAGE, evidenceDeviceBoundLabel } from "@/lib/core-api/labels";
import type { EvidenceSummary, EvidenceUploadResponse, EvidenceViewResponse } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";

// Core 가 받는 MIME allowlist 와 같은 목록(ADR-KSI-010 §1) — 여기서 미리 걸러
// "고르고 나서 415" 를 막는다. 서버 검사가 정본이고 이건 편의다.
const ACCEPTED = "application/json,image/jpeg,image/png,image/webp,video/mp4,video/webm";

/**
 * 파일명을 경로-안전 artifactId 로 바꾼다.
 *
 * Core 가 이 값을 객체 키 세그먼트로 쓰므로 영숫자 시작 + `[A-Za-z0-9_.-]` 만
 * 허용된다(서버도 다시 검증한다 — 여기 통과가 승인이 아니다). 한글 파일명이
 * 통째로 사라지지 않게 걸러진 자리는 `-` 로 남기고, 같은 이름을 다시 올릴 때
 * 409(DUPLICATE_ARTIFACT)가 나지 않도록 시각을 덧붙인다.
 */
function toArtifactId(fileName: string): string {
  const stamp = new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14);
  const base = fileName.normalize("NFC").replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "");
  return `${stamp}-${base || "evidence"}`.slice(0, 120);
}

function isImage(contentType: string): boolean {
  return contentType.startsWith("image/");
}

async function readMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string; code?: string };
    if (body.code && body.code in API_ERROR_MESSAGE) {
      return API_ERROR_MESSAGE[body.code as keyof typeof API_ERROR_MESSAGE];
    }
    return body.message ?? "요청을 처리하지 못했습니다.";
  } catch {
    return "요청을 처리하지 못했습니다.";
  }
}

export function EvidencePanel({
  eventKey,
  evidence,
  canUpload,
}: {
  eventKey: string;
  evidence: EvidenceSummary[];
  canUpload: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // artifactId → 방금 발급받은 열람 URL. 캐시하지 않는다 — 수명이 분 단위라
  // 오래 들고 있으면 만료된 URL 을 계속 보여주게 된다.
  const [viewing, setViewing] = useState<Record<string, EvidenceViewResponse>>({});

  async function handleUpload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const artifactId = toArtifactId(file.name);
      const registered = await fetch(`/api/events/${encodeURIComponent(eventKey)}/evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifactId, contentType: file.type }),
      });
      if (!registered.ok) {
        setError(await readMessage(registered));
        return;
      }
      const { uploadUrl } = (await registered.json()) as EvidenceUploadResponse;

      // 파일 바이트는 대시보드 서버를 거치지 않는다 — 브라우저가 스토리지로 직접 PUT.
      const uploaded = await fetch(uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
      });
      if (!uploaded.ok) {
        // 등록은 원장에 남았고 업로드만 실패한 상태다 — 그 사실을 그대로 말한다.
        setError(
          `스토리지 업로드에 실패했습니다(${uploaded.status}). 등록은 기록됐으니 같은 파일을 다시 올리면 됩니다.`,
        );
        return;
      }
      router.refresh();
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setBusy(false);
    }
  }

  async function handleView(artifactId: string) {
    setError(null);
    try {
      const response = await fetch(
        `/api/events/${encodeURIComponent(eventKey)}/evidence/${encodeURIComponent(artifactId)}`,
      );
      if (!response.ok) {
        setError(await readMessage(response));
        return;
      }
      const body = (await response.json()) as EvidenceViewResponse;
      setViewing((current) => ({ ...current, [artifactId]: body }));
    } catch {
      setError("열람 링크를 발급받지 못했습니다.");
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium break-keep">증거</h2>
        {canUpload && (
          <label className="tap-target flex cursor-pointer items-center rounded-md border border-line-strong px-3 text-[13px] font-semibold break-keep hover:bg-sunk">
            {busy ? "올리는 중…" : "증거 추가"}
            <input
              type="file"
              accept={ACCEPTED}
              disabled={busy}
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // 같은 파일을 다시 고를 수 있게 값을 비운다(onChange 가 안 도는 것을 막는다).
                event.target.value = "";
                if (file) void handleUpload(file);
              }}
            />
          </label>
        )}
      </div>

      {error && (
        <p className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink">
          {error}
        </p>
      )}

      {evidence.length === 0 ? (
        <p className="text-sm break-keep text-ink-2">
          등록된 증거가 없습니다.
          {canUpload && " 사진·영상을 올리면 확정 근거로 남습니다."}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {evidence.map((artifact) => {
            const view = viewing[artifact.artifactId];
            const deviceBound = evidenceDeviceBoundLabel(artifact.deviceBound);
            return (
              <li
                key={artifact.artifactId}
                className="flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="num break-token text-[12.5px] font-semibold">
                      {artifact.artifactId}
                    </span>
                    <StateBadge label={deviceBound.label} tone={deviceBound.tone} />
                  </span>
                  <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
                    {formatKoreanDateTime(artifact.registeredAt, { dateStyle: "medium", timeStyle: "short" })}
                  </span>
                </div>
                <p className="text-[11.5px] break-keep text-ink-muted">
                  {artifact.contentType} · 등록 {artifact.registeredBy}
                </p>

                {artifact.tombstonedAt ? (
                  // "없음"이 아니라 "폐기됨" — 사고 조사에서 이 둘은 다른 사실이다.
                  <p className="rounded-md bg-sunk px-2.5 py-2 text-[12px] break-keep text-ink-2">
                    보관 정책으로 폐기되었습니다(
                    {formatKoreanDateTime(artifact.tombstonedAt, { dateStyle: "medium", timeStyle: "short" })}
                    ).
                    {artifact.tombstoneReason && ` 사유: ${artifact.tombstoneReason}`}
                  </p>
                ) : view ? (
                  <div className="flex flex-col gap-1.5">
                    {isImage(artifact.contentType) ? (
                      /* presigned URL 은 수명이 분 단위라 next/image 의 최적화·캐시
                         경로와 맞지 않는다(빌드타임 최적화 대상이 아니다). */
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={view.viewUrl}
                        alt={`증거 ${artifact.artifactId}`}
                        className="max-h-80 w-full rounded-md object-contain"
                      />
                    ) : (
                      <video src={view.viewUrl} controls className="max-h-80 w-full rounded-md" />
                    )}
                    <p className="text-[11px] break-keep text-ink-muted">
                      이 링크는 {formatKoreanDateTime(view.expiresAt, { dateStyle: "medium", timeStyle: "short" })}에 만료됩니다.
                    </p>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => void handleView(artifact.artifactId)}
                    className="tap-target self-start rounded-md border border-line-strong px-3 text-[12.5px] font-semibold break-keep hover:bg-sunk"
                  >
                    열어보기
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
