"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import type { TemporalCoherencePolicy } from "@/lib/core-api/types";

type WorkAreaOption = { workAreaId: string; name: string };

type CreateAttempt = {
  key: string;
  body: {
    name: string;
    workAreaIds: string[];
    scheduleId: null;
    executionMode: "EXTERNAL_RECONSTRUCTION";
    temporalPolicy?: TemporalCoherencePolicy;
  };
};

function idempotencyKey(): string {
  return `external-${crypto.randomUUID()}`;
}

export function ExternalObservationCreateForm({
  siteId,
  siteName,
  workAreas,
  initialWorkAreaIds = [],
  temporalPolicy = null,
  templateNotice = null,
}: {
  siteId: string;
  siteName: string;
  workAreas: readonly WorkAreaOption[];
  initialWorkAreaIds?: readonly string[];
  temporalPolicy?: TemporalCoherencePolicy | null;
  templateNotice?: string | null;
}) {
  const router = useRouter();
  const [intent, setIntent] = useState<"external" | "flight">("external");
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>(() => [...initialWorkAreaIds]);
  const [attempt, setAttempt] = useState<CreateAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const submitLock = useRef(false);
  const active = useRef(true);
  const submitAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      submitAbort.current?.abort();
    };
  }, []);

  const toggle = (workAreaId: string) => {
    if (attempt || busy) return;
    setSelected((current) => current.includes(workAreaId)
      ? current.filter((item) => item !== workAreaId)
      : [...current, workAreaId]);
  };

  const submit = async () => {
    if (busy || submitLock.current) return;
    const nextAttempt = attempt ?? (() => {
      const body: CreateAttempt["body"] = {
        name: name.trim(),
        workAreaIds: selected,
        scheduleId: null,
        executionMode: "EXTERNAL_RECONSTRUCTION",
        ...(temporalPolicy ? { temporalPolicy } : {}),
      };
      const next = { key: key.current ?? idempotencyKey(), body };
      key.current = next.key;
      setAttempt(next);
      return next;
    })();
    if (!nextAttempt.body.name || nextAttempt.body.workAreaIds.length === 0) return;

    submitLock.current = true;
    const controller = new AbortController();
    submitAbort.current = controller;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/observation-work-orders`, {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": nextAttempt.key },
        body: JSON.stringify(nextAttempt.body),
        signal: controller.signal,
      });
      const value: unknown = await response.json().catch(() => null);
      if (response.status === 422) {
        if (active.current && submitAbort.current === controller) {
          key.current = null;
          setAttempt(null);
          setError("입력을 확인해 수정한 뒤 다시 요청하세요.");
        }
        return;
      }
      if (!response.ok || !value || typeof value !== "object" || typeof (value as { workOrderId?: unknown }).workOrderId !== "string") {
        throw new Error("create failed");
      }
      if (!active.current || submitAbort.current !== controller) return;
      router.push(`/field/work-orders/${encodeURIComponent((value as { workOrderId: string }).workOrderId)}`);
    } catch (caught) {
      if (active.current && submitAbort.current === controller && !(caught instanceof DOMException && caught.name === "AbortError")) {
        setError("응답을 확인하지 못했습니다. 같은 요청을 다시 시도하거나 작업 목록에서 이미 만들어졌는지 확인하세요.");
      }
    } finally {
      if (submitAbort.current === controller) submitAbort.current = null;
      submitLock.current = false;
      if (active.current) setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5">
      <div>
        <p className="text-[12.5px] text-ink-2">현장에 필요한 관측 방식을 고르고, 다음 작업으로 바로 이어갑니다.</p>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-[22px] font-bold tracking-tight">{siteName} · 새 관측 시작</h1>
          <Link href={`/sites/${encodeURIComponent(siteId)}`} className="text-[13px] font-semibold text-accent-text hover:underline">현장으로 돌아가기</Link>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          className={`relative rounded-xl border p-4 text-left ${intent === "external" ? "border-2 border-ink-1 bg-sunk" : "border-line bg-surface"}`}
          aria-pressed={intent === "external"}
          onClick={() => setIntent("external")}
        >
          {intent === "external" && (
            <span className="absolute top-3 right-3 text-[11px] font-bold text-ink-1">✓ 선택됨</span>
          )}
          <span className="block text-[15px] font-bold">외부 산출물 등록</span>
          <span className="mt-1 block text-[12.5px] leading-5 text-ink-2">이미 만든 정사영상과 DSM을 등록해 비교 결과를 확인합니다.</span>
        </button>
        <Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="rounded-xl border border-line bg-surface p-4 hover:bg-sunk">
          <span className="block text-[15px] font-bold">관측 이력 보기</span>
          <span className="mt-1 block text-[12.5px] leading-5 text-ink-2">등록된 외부 관측 결과와 검토 상태를 확인합니다.</span>
        </Link>
      </div>

      {intent === "external" && (workAreas.length === 0 ? (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-[15px] font-bold">먼저 작업구역을 등록하세요</h2>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">비교할 범위가 있어야 결과의 위치와 의미를 확인할 수 있습니다.</p>
          <Link href={`/sites/${encodeURIComponent(siteId)}/work-areas`} className="btn mt-3 inline-flex">작업구역 만들기</Link>
        </section>
      ) : (
        <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="새 관측 작업 등록은 노트북 이상의 화면에서 진행합니다.">
          <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
            <div>
              <h2 className="text-[16px] font-bold">외부 산출물 작업</h2>
              <p className="mt-1 text-[13px] leading-5 text-ink-2">이 작업은 파일 등록과 비교 확인을 위한 것입니다. 비행 또는 장비 제어는 시작하지 않습니다.</p>
              {templateNotice ? <p className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{templateNotice}</p> : initialWorkAreaIds.length > 0 && <p className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">이전 비교에 사용한 활성 작업구역과 촬영 간격 기준을 미리 골랐습니다. 새 관측을 만들기 전에 범위를 확인하세요.</p>}
            </div>
            <label className="flex flex-col gap-1 text-[13px] font-semibold">작업 이름
              <input aria-label="작업 이름" className="input" maxLength={200} value={name} disabled={busy || attempt !== null} onChange={(event) => setName(event.target.value)} placeholder="예: 9월 6일 현황 비교" />
            </label>
            <fieldset disabled={busy || attempt !== null}>
              <legend className="text-[13px] font-semibold">비교할 작업구역</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {workAreas.map((area) => <label key={area.workAreaId} className="flex cursor-pointer items-center gap-2 rounded-lg border border-line px-3 py-2 text-[13px] hover:bg-sunk">
                  <input type="checkbox" aria-label={area.name} checked={selected.includes(area.workAreaId)} onChange={() => toggle(area.workAreaId)} />
                  <span>{area.name}</span>
                </label>)}
              </div>
            </fieldset>
            {attempt && <p className="rounded-lg bg-sunk px-3 py-2 text-[12.5px] text-ink-2">이 요청은 같은 내용으로 재시도합니다. 내용을 바꾸려면 새 요청으로 시작하세요.</p>}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" disabled={busy || !name.trim() || selected.length === 0} onClick={() => void submit()}>{busy ? "작업 만드는 중" : attempt ? "같은 요청 다시 시도" : "산출물 등록 시작"}</button>
            </div>
            {error && <p role="alert" className="text-[13px] text-high-ink">{error}{attempt && <> <Link href="/field" className="font-semibold underline">작업 목록 확인</Link></>}</p>}
          </section>
        </ResponsiveActionBoundary>
      ))}
    </div>
  );
}
