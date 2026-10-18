"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import type { TemporalCoherencePolicy } from "@/lib/core-api/types";

type WorkAreaOption = { workAreaId: string; name: string };

function workAreaLabel(area: WorkAreaOption, index: number): string {
  const name = area.name.trim();
  return name && name !== area.workAreaId ? name : `이름을 확인할 수 없는 작업구역 ${index + 1}`;
}

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
  suggestedName = null,
  templateNotice = null,
  scopeNotice = null,
}: {
  siteId: string;
  siteName: string;
  workAreas: readonly WorkAreaOption[];
  initialWorkAreaIds?: readonly string[];
  temporalPolicy?: TemporalCoherencePolicy | null;
  suggestedName?: string | null;
  templateNotice?: string | null;
  scopeNotice?: string | null;
}) {
  const router = useRouter();
  const [name, setName] = useState(suggestedName ?? "");
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
  // 돌아가기 링크는 현재 정확히 하나 고른 승인 범위만 싣는다. 없거나 여러 개면
  // 맨 현장으로 간다 — 추측으로 범위를 붙이지 않는다.
  const returnHref = selected.length === 1 && selected[0]
    ? `/sites/${encodeURIComponent(siteId)}?workAreaId=${encodeURIComponent(selected[0])}`
    : `/sites/${encodeURIComponent(siteId)}`;

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
      router.push(`/field/work-orders/${encodeURIComponent((value as { workOrderId: string }).workOrderId)}#external-submissions`);
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
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[22px] font-bold tracking-tight">{siteName} · 관측 자료 등록</h2>
          <Link href={returnHref} className="text-[13px] font-semibold text-accent-text hover:underline">현장으로 돌아가기</Link>
        </div>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">
          등록된 외부 비교 기록과 검토 상태는{" "}
          <Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="font-semibold text-accent-text hover:underline">
            외부 비교 기록
          </Link>
          에서 확인하세요.
        </p>
      </div>

      {workAreas.length === 0 ? (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-[15px] font-bold">먼저 작업구역을 등록하세요</h2>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">비교할 범위가 있어야 결과의 위치와 의미를 확인할 수 있습니다.</p>
          <Link href={`/sites/${encodeURIComponent(siteId)}/work-areas`} className="btn mt-3 inline-flex">작업구역 만들기</Link>
        </section>
      ) : (
        <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" reason="노트북에서 같은 계정으로 이 현장의 '관측 자료 등록' 화면을 열어 이어가세요.">
          <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
            <div>
              <p className="text-[13px] leading-5 text-ink-2">비행 또는 장비 제어는 시작하지 않습니다.</p>
              {/* 반복 템플릿 공지는 실제 검증된 반복 진입에서만 page가 넘긴다. 범위 선택만으로 추론하지 않는다. */}
              {templateNotice ? <p className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{templateNotice}</p> : null}
              {scopeNotice && <p role="status" className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{scopeNotice}</p>}
            </div>
            <label className="flex flex-col gap-1 text-[13px] font-semibold">작업 이름
              <input aria-label="작업 이름" className="input" maxLength={200} value={name} disabled={busy || attempt !== null} onChange={(event) => setName(event.target.value)} placeholder={suggestedName ?? "예: 9월 6일 현황 비교"} />
            </label>
            <fieldset disabled={busy || attempt !== null}>
              <legend className="text-[13px] font-semibold">비교할 작업구역</legend>
              <div className="mt-2 grid gap-2">
                {workAreas.map((area, index) => <label key={area.workAreaId} className="flex cursor-pointer items-center gap-2 rounded-lg border border-line px-3 py-2 text-[13px] hover:bg-sunk">
                  <input type="checkbox" aria-label={workAreaLabel(area, index)} checked={selected.includes(area.workAreaId)} onChange={() => toggle(area.workAreaId)} />
                  <span>{workAreaLabel(area, index)}</span>
                </label>)}
              </div>
            </fieldset>
            {selected.length > 1 && (
              <p role="status" className="rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
                작업구역을 {selected.length}개 선택했습니다. 구역별 자료 목록·비교 선택에서는 한 구역씩 확인해야 바로 보입니다. 구역별 비교용이면 하나만 선택하세요. 여러 구역 저장은 그대로 유지됩니다.
              </p>
            )}
            {attempt && <p className="rounded-lg bg-sunk px-3 py-2 text-[12.5px] text-ink-2">이 요청은 같은 내용으로 재시도합니다. 내용을 바꾸려면 새 요청으로 시작하세요.</p>}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" disabled={busy || !name.trim() || selected.length === 0} onClick={() => void submit()}>{busy ? "작업 만드는 중" : attempt ? "같은 요청 다시 시도" : "관측 자료 등록 계속"}</button>
            </div>
            <p className="text-[12px] leading-5 text-ink-2">작업이 만들어지면 파일 제출·검사 화면으로 이동합니다. 파일 올리기는 그 화면에서 이어갑니다.</p>
            {!busy && !attempt && !name.trim() && selected.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요.</p>}
            {!busy && !attempt && !name.trim() && selected.length > 0 && <p className="text-[12.5px] leading-5 text-ink-2">작업 이름을 입력하세요.</p>}
            {!busy && !attempt && name.trim() && selected.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">비교할 작업구역을 하나 이상 선택하세요.</p>}
            {error && <p role="alert" className="text-[13px] text-high-ink">{error}{attempt && <> <Link href="/field" className="font-semibold underline">작업 목록 확인</Link></>}</p>}
          </section>
        </ResponsiveActionBoundary>
      )}
    </div>
  );
}
