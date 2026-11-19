"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { explainExternalUseDecision } from "@/lib/external-use-blockers";
import { failureText, requestErrorText } from "@/lib/measurement-copy";
import type { RequestRow } from "@/lib/measurement-requests";

/** 진행 중인 요청이 있는 동안 서버 화면을 새로 읽는 간격과 횟수 상한. 상한이 지나면 손으로 새로 고치게 한다. */
const POLL_MS = 3000;
const POLL_LIMIT = 40;

export interface RequestFeature {
  featureId: string;
  revision: number;
  lineDigest: string;
}

export interface RequestableAsset extends RequestRow {
  /** 자료 상세로 가는 주소. 수직 기준 선언처럼 자료에서 풀 일이 있을 때 쓴다. */
  assetHref: string;
  requestNotice?: string | null;
}

type Blocked = { reasons: string[]; remediations: string[] };

/**
 * 선택한 측정 선의 날짜(자료)별 단면 요청.
 *
 * 높이를 읽어도 되는지는 Core가 판정한다. 막히면 작업을 만들지 않고 사유와 다음 조치를 보여 준다.
 * 요청은 쓰기라서 화면 폭 1024px 이상에서만 연다. 상태는 읽기라서 어디서나 보인다.
 */
export function ProfileRequests({
  siteId,
  workAreaId,
  feature,
  rows,
  canRequest,
}: {
  siteId: string;
  workAreaId: string;
  feature: RequestFeature;
  rows: RequestableAsset[];
  canRequest: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [blocked, setBlocked] = useState<Record<string, Blocked>>({});
  // 응답을 모르는 실패는 같은 키로 다시 보낸다. 서버가 답하면 새 키를 쓴다.
  const keys = useRef<Map<string, string>>(new Map());
  const lock = useRef(false);
  const active = rows.some((row) => row.state === "active");
  const polls = useRef(0);

  useEffect(() => {
    if (!active) {
      polls.current = 0;
      return;
    }
    const timer = setInterval(() => {
      polls.current += 1;
      if (polls.current > POLL_LIMIT) {
        clearInterval(timer);
        return;
      }
      router.refresh();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active, router]);

  function setError(assetRef: string, text: string | null) {
    setErrors((current) => {
      const next = { ...current };
      if (text === null) delete next[assetRef]; else next[assetRef] = text;
      return next;
    });
  }

  async function request(assetRef: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(assetRef);
    setError(assetRef, null);
    setBlocked((current) => { const next = { ...current }; delete next[assetRef]; return next; });
    const fingerprint = `${assetRef}:${feature.featureId}:${feature.revision}:${feature.lineDigest}`;
    const id = keys.current.get(fingerprint) ?? `console-${crypto.randomUUID()}`;
    keys.current.set(fingerprint, id);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/surface-profile-requests`,
        { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": id }, body: JSON.stringify({ assetRef, feature }) },
      );
      const value: unknown = await response.json().catch(() => null);
      const body = typeof value === "object" && value !== null ? (value as { code?: unknown; decision?: unknown }) : {};
      if (response.ok) {
        keys.current.delete(fingerprint);
        router.refresh();
        return;
      }
      // 5xx는 Core가 이미 처리했는지 모르는 응답이다(예: 판정·작업은 만들었는데 응답 검사에서 502).
      // 키를 두어 다음 시도가 같은 요청으로 가게 한다. 4xx는 서버가 답한 것이므로 새 키를 쓴다.
      if (response.status < 500) keys.current.delete(fingerprint);
      const code = typeof body.code === "string" ? body.code : undefined;
      const decision = body.decision as { reasons?: unknown; remediations?: unknown } | undefined;
      if (code === "HEIGHT_NOT_ELIGIBLE" && decision && Array.isArray(decision.reasons) && Array.isArray(decision.remediations)) {
        setBlocked((current) => ({ ...current, [assetRef]: { reasons: decision.reasons as string[], remediations: decision.remediations as string[] } }));
      } else if (code === "ASSET_VERTICAL_REFERENCE_UNKNOWN") {
        // 같은 제출의 다른 DSM 때문에 판정은 열렸지만 이 자료에는 수직 기준이 없다 — 선언으로 푸는 일이다.
        setBlocked((current) => ({ ...current, [assetRef]: { reasons: ["VERTICAL_REFERENCE_UNKNOWN"], remediations: ["OBSERVE_VERTICAL_REFERENCE"] } }));
      } else {
        setError(assetRef, requestErrorText(response.status, code));
      }
    } catch {
      setError(assetRef, "응답을 확인하지 못했습니다. 같은 요청으로 다시 시도하세요.");
    } finally {
      lock.current = false;
      setBusy(null);
    }
  }

  async function cancel(assetRef: string, jobId: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(assetRef);
    setError(assetRef, null);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/surface-profile-jobs/${encodeURIComponent(jobId)}/cancel`,
        { method: "POST" },
      );
      if (!response.ok) {
        const value: unknown = await response.json().catch(() => null);
        const code = typeof value === "object" && value !== null && typeof (value as { code?: unknown }).code === "string" ? (value as { code: string }).code : undefined;
        setError(assetRef, requestErrorText(response.status, code));
      }
      router.refresh();
    } catch {
      setError(assetRef, "응답을 확인하지 못했습니다. 화면을 새로 고쳐 상태를 확인하세요.");
    } finally {
      lock.current = false;
      setBusy(null);
    }
  }

  return (
    <section aria-label="날짜별 단면 요청" className="min-w-0 rounded-lg border border-line bg-surface p-4">
      <h3 className="text-body font-semibold text-ink-1">날짜별 단면</h3>
      <p className="mt-0.5 text-caption leading-5 text-ink-muted">
        고른 선으로 등록된 높이 자료(DSM)를 읽어 단면을 만듭니다. 선을 고치면 고친 선으로 다시 요청해야 합니다.
      </p>
      <ul className="mt-3 flex flex-col divide-y divide-line">
        {rows.map((row) => {
          const guide = blocked[row.assetRef] ? explainExternalUseDecision(blocked[row.assetRef]!.reasons, blocked[row.assetRef]!.remediations) : null;
          const working = busy === row.assetRef;
          return (
            <li key={row.assetRef} className="flex min-w-0 flex-col gap-2 py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="tabular text-body font-semibold text-ink-1">{row.label}</p>
                  <p className="text-caption text-ink-2" data-request-state={row.state} aria-live="polite">
                    {row.state === "none" && !row.requestNotice && "아직 요청하지 않았습니다."}
                    {row.state === "active" && "단면을 읽는 중입니다. 끝나면 이 화면에 나타납니다."}
                    {row.state === "done" && "단면을 읽었습니다."}
                    {row.state === "unavailable" && "읽은 결과가 있지만 지금은 표시할 수 없습니다."}
                    {row.state === "failed" && `읽지 못했습니다. ${failureText(row.reason)}`}
                    {row.state === "canceled" && "요청을 취소했습니다."}
                  </p>
                  {row.requestNotice && <p className="text-caption leading-5 text-ink-2">{row.requestNotice} <Link className="underline" href={row.assetHref}>자료 상세 열기</Link></p>}
                </div>
                {canRequest && !row.requestNotice && (row.state === "none" || row.state === "failed" || row.state === "canceled") && (
                  <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" inlineNotice={false}>
                    <button type="button" className="btn" disabled={busy !== null} onClick={() => void request(row.assetRef)}>
                      {working ? "요청하는 중" : row.state === "none" ? "단면 요청" : "다시 요청"}
                    </button>
                  </ResponsiveActionBoundary>
                )}
                {canRequest && row.state === "active" && row.jobId && (
                  <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" inlineNotice={false}>
                    <button type="button" className="btn" disabled={busy !== null} onClick={() => void cancel(row.assetRef, row.jobId!)}>
                      {working ? "취소하는 중" : "요청 취소"}
                    </button>
                  </ResponsiveActionBoundary>
                )}
              </div>
              {guide && (
                <div role="alert" className="rounded-lg bg-sunk px-3 py-2 text-caption leading-5 text-ink-2">
                  <p className="font-semibold text-ink-1">{guide.title}</p>
                  <p className="mt-0.5">{guide.explanation}</p>
                  <p className="mt-1">{guide.step}</p>
                  <Link href={row.assetHref} className="mt-1 inline-block underline">자료 상세 열기</Link>
                </div>
              )}
              {errors[row.assetRef] && <p role="alert" className="text-caption text-high-ink">{errors[row.assetRef]}</p>}
            </li>
          );
        })}
      </ul>
      {!canRequest && <p className="mt-3 text-micro text-ink-muted">단면 요청은 작업 등록 권한이 있는 계정이 할 수 있습니다.</p>}
    </section>
  );
}
