"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import type { TemporalCoherencePolicy } from "@/lib/core-api/types";

type WorkAreaOption = { workAreaId: string; name: string };

// hydration 완료 여부를 읽는 공식 게이트다. SSR에서는 getServerSnapshot(false)이
// 잠금 HTML과 일치하고, hydration 확정 뒤 getSnapshot(true)으로 열리며,
// 클라이언트 내비게이션에서는 처음부터 열려 있다. effect 속 setState가 없어
// cascading render도 lint 예외도 필요 없다.
function subscribeHydrated(): () => void {
  return () => {};
}
function getHydratedClientSnapshot(): boolean {
  return true;
}
function getHydratedServerSnapshot(): boolean {
  return false;
}
function useHydratedGate(): boolean {
  return useSyncExternalStore(subscribeHydrated, getHydratedClientSnapshot, getHydratedServerSnapshot);
}

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
  continuity: string;
};

function idempotencyKey(): string {
  return `external-${crypto.randomUUID()}`;
}

const FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;

export function ExternalObservationCreateForm({
  siteId,
  siteName,
  workAreas,
  initialWorkAreaIds = [],
  temporalPolicy = null,
  suggestedName = null,
  templateNotice = null,
  scopeNotice = null,
  accountIdentity = null,
}: {
  siteId: string;
  siteName: string;
  workAreas: readonly WorkAreaOption[];
  initialWorkAreaIds?: readonly string[];
  temporalPolicy?: TemporalCoherencePolicy | null;
  suggestedName?: string | null;
  templateNotice?: string | null;
  scopeNotice?: string | null;
  accountIdentity?: { fingerprint: string } | null;
}) {
  const router = useRouter();
  const [name, setName] = useState(suggestedName ?? "");
  const [selected, setSelected] = useState<string[]>(() => [...initialWorkAreaIds]);
  const [attempt, setAttempt] = useState<CreateAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fingerprint = accountIdentity?.fingerprint;
  const canStart = typeof fingerprint === "string" && FINGERPRINT_PATTERN.test(fingerprint);
  const key = useRef<string | null>(null);
  const submitLock = useRef(false);
  const active = useRef(true);
  const submitAbort = useRef<AbortController | null>(null);
  const hydrated = useHydratedGate();
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      submitAbort.current?.abort();
    };
  }, []);
  // SSR~hydration 사이 이름·구역·제출은 같은 명시적 준비 게이트로 잠근다. 이 값은
  // 외부 스토어 스냅샷이므로 effect 속 setState가 없고, SSR 잠금 HTML과도
  // 일치한다. 잠긴 입력칸에는 실제 사용자 입력이 남을 수 없으므로 보이는 값과
  // state가 갈라질 수 없고, wipe·고착 분기 자체가 생기지 않는다. hydration
  // 완료 후에는 입력칸을 key로 새로 만들어 DOM·리스너 추적을 state와 일치시키고
  // 잠금을 푼다. 준비 안내는 hydration이 끝나기 전 필수 입력 안내 3건을 대신한다.

  const toggle = (workAreaId: string) => {
    if (attempt || busy) return;
    setSelected((current) => current.includes(workAreaId)
      ? current.filter((item) => item !== workAreaId)
      : [...current, workAreaId]);
  };
  // 응답 미확인(모호한 제출) 뒤에는 같은 키 재시도가 기본이다. 내용을 바꾸고
  // 싶으면 명시적인 새 시작만이 새 키를 만든다 — 목록에서 이미 만들어졌는지
  // 먼저 확인해야 중복 등록을 피할 수 있다. 같은 키 재시도는 원래 계정에서만
  // 서버로 나간다. 새로고침·재로그인으로 초안이 사라지면 같은 키 보호도
  // 사라지니, 목록 확인을 먼저 하라는 안내는 그대로 둔다.
  const startOver = () => {
    if (busy) return;
    key.current = null;
    setAttempt(null);
    setError(null);
  };
  // 돌아가기 링크는 현재 정확히 하나 고른 승인 범위만 싣는다. 없거나 여러 개면
  // 맨 현장으로 간다 — 추측으로 범위를 붙이지 않는다.
  const returnHref = selected.length === 1 && selected[0]
    ? `/sites/${encodeURIComponent(siteId)}?workAreaId=${encodeURIComponent(selected[0])}`
    : `/sites/${encodeURIComponent(siteId)}`;
  // 동결된 시도의 작업명 그대로 작업 큐를 검색한다 — 모호한 제출 뒤 이미
  // 만들어진 작업이 있는지 확인할 때 목록 전체를 뒤지지 않게 둔다. 큐 검색은
  // 작업명·현장명 포함 매칭이라 같은 이름 시도가 있으면 바로 보인다.
  // 같은 탭으로 이동하면 이 화면의 동결 키·본문이 사라져 같은 키 복구가
  // 불가능해지므로 새 탭으로 연다. 현장 범위를 함께 실어 동명이 타 현장
  // 결과와 섞이지 않게 두되, 이름 일치만으로 성공을 확정하지 않는다.
  const workQueueHref = attempt
    ? `/field?q=${encodeURIComponent(attempt.body.name)}&site=${encodeURIComponent(siteId)}`
    : "/field";

  const submit = async () => {
    if (busy || submitLock.current) return;
    if (!attempt && !canStart) return;
    const nextAttempt = attempt ?? (() => {
      const body: CreateAttempt["body"] = {
        name: name.trim(),
        workAreaIds: selected,
        scheduleId: null,
        executionMode: "EXTERNAL_RECONSTRUCTION",
        ...(temporalPolicy ? { temporalPolicy } : {}),
      };
      // 첫 시도의 서버 파생 신원을 원래 신원으로 고정한다. 호출자 입력이 아니라
      // page가 서버에서 읽은 값이며, 재시도는 이 값을 그대로 보내 BFF가 현재
      // 세션과 비교한다. 새로고침하면 이 기억은 사라진다.
      const continuity = fingerprint!;
      const next = { key: key.current ?? idempotencyKey(), body, continuity };
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
      const headers: Record<string, string> = {
        "content-type": "application/json",
        "Idempotency-Key": nextAttempt.key,
      };
      headers["x-ksi-continuity-fingerprint"] = nextAttempt.continuity;
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/observation-work-orders`, {
        method: "POST",
        headers,
        body: JSON.stringify(nextAttempt.body),
        signal: controller.signal,
      });
      const value: unknown = await response.json().catch(() => null);
      const responseCode = value && typeof value === "object" && "code" in value
        ? String((value as { code?: unknown }).code ?? "")
        : "";
      // 계정이 바뀐 같은 키 재시도는 서버로 나가지 않고 여기서 끊긴다. 원래
      // 키·내용을 버리면 중복 등록으로 이어지므로 동결을 유지하고, 원래 계정으로
      // 돌아가 같은 요청으로 다시 시도하라는 안내를 준다. 이는 중복 방지 가드이며
      // Core 권한·범위 판단을 대신하지 않는다.
      if (response.status === 409 && responseCode === "ACCOUNT_CONTINUITY_MISMATCH") {
        if (active.current && submitAbort.current === controller) {
          setError("계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 먼저 작업 목록에서 원래 요청의 작업이 이미 만들어졌는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.");
        }
        return;
      }
      // 422도 첫 시도와 재시도를 구분한다. Core는 요청 검증·권한을 멱등성 조회보다
      // 먼저 수행하므로, 재시도가 422로 거부됐다고 해서 이전 모호한 요청이 접수되지
      // 않았다고 단정할 수 없다 — 검증·정책·버전이 바뀌면 이미 접수된 요청의 같은 키
      // 재시도도 재생 전에 거부될 수 있다. 재시도 422는 원래 동결을 유지한다.
      if (response.status === 422) {
        if (active.current && submitAbort.current === controller) {
          if (attempt !== null) {
            setError("다시 보낸 요청이 등록 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 등록 기준이나 정책이 바뀌면 이미 접수된 요청이라도 재시도가 거부될 수 있습니다. 입력과 요청은 이 화면에 그대로 있습니다. 작업 목록에서 이미 만들어졌는지 먼저 확인하세요. 내용이 잘못된 경우 새로 시작해 수정하세요.");
          } else {
            key.current = null;
            setAttempt(null);
            setError("입력을 확인해 수정한 뒤 다시 요청하세요.");
          }
        }
        return;
      }
      // 401/403/404 처리는 첫 시도와 재시도를 구분한다. 첫 시도에서 받은 거부는
      // 확정적이다 — Dashboard 401(세션 게이트)과 출처 가드 403은 Core 호출 전에
      // 끊고, Core 403은 require_permission 의존성이 핸들러 본문
      // (store.create_work_order)보다 먼저 거부하며, Core 404는 범위 검사가 생성보다
      // 먼저 거부하므로, 첫 시도에서는 어느 경우에도 작업이 만들어지지 않았다.
      // 반면 동결된 시도(attempt !== null)의 재시도가 401/403/404를 받으면, 그 거부는
      // 이번 재시도만 확정할 뿐이다. 이전 모호한 요청이 이미 작업을 만들었을 수
      // 있으므로, 원래 키·내용을 버리면 중복 등록으로 이어진다. 재시도 거부는 원래
      // 동결을 유지하고 같은 키 재시도·목록 확인 경로를 살린다. 어느 경우에도
      // 되돌림이나 부재를 단정하지 않는다.
      if (response.status === 401 || response.status === 403 || response.status === 404) {
        if (active.current && submitAbort.current === controller) {
          if (attempt !== null) {
            setError(response.status === 401
              ? "다시 보낸 요청이 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 화면을 벗어나면 입력이 사라지니, 다른 탭에서 같은 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하세요. 계정을 바꾸기 전에 작업 목록에서 원래 요청의 작업이 이미 만들어졌는지 먼저 확인하세요. 다른 계정에서 같은 요청을 다시 시도하면 이 화면에서 새 작업을 만들지 않습니다."
              : response.status === 403
                ? "다시 보낸 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 권한을 확인한 뒤 같은 요청으로 다시 시도하거나, 작업 목록에서 이미 만들어졌는지 먼저 확인하세요."
                : "다시 보낸 요청에서 작업 범위를 확인하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 작업 목록에서 이미 만들어졌는지 먼저 확인하세요. 작업구역이 바뀐 경우 새로 시작해 범위를 다시 선택하세요.");
          } else {
            key.current = null;
            setAttempt(null);
            setError(response.status === 401
              ? "세션이 만료되어 작업을 만들지 못했습니다. 입력은 이 화면에 그대로 있습니다. 화면을 벗어나면 입력이 사라지니, 다른 탭에서 같은 계정으로 다시 로그인한 뒤 이 화면에서 새로 요청하세요. 계정을 바꾸기 전에 작업 목록에서 해당 작업이 이미 있는지 먼저 확인하세요."
              : response.status === 403
                ? "작업 등록 권한이 없어 작업을 만들지 못했습니다. 입력은 이 화면에 그대로 있습니다. 현장 담당자에게 작업 등록 권한을 요청한 뒤(필요하면 다른 탭에서 다시 로그인) 이 화면에서 새로 요청하세요."
                : "작업 범위를 확인하지 못해 작업을 만들지 못했습니다. 입력은 이 화면에 그대로 있습니다. 작업구역 선택을 확인한 뒤 새로 요청하세요.");
          }
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
    <div className="console-page !max-w-[800px]">
      <div>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h2 className="console-page-title">관측 자료 등록</h2>
          <Link href={returnHref} className="text-[13px] font-semibold text-accent-text hover:underline">현장으로 돌아가기</Link>
        </div>
        <p className="console-page-description">{siteName}</p>
        <ol aria-label="자료 등록 흐름" className="mt-5 grid grid-cols-3 gap-3 text-[12px]"><li aria-current="step" className="border-b-2 border-accent pb-3 font-semibold">1. 작업구역</li><li className="border-b-2 border-line pb-3 text-ink-muted">2. 파일 제출</li><li className="border-b-2 border-line pb-3 text-ink-muted">3. 검사 확인</li></ol>
      </div>

      {/* 1024px 미만에서는 쓰기 경계가 폼을 숨기므로, 변경 없는 범위 정보만
          읽기로 보여준다. 여기에는 입력·단추·링크를 두지 않는다. 요약은
          읽기 전용이며, 다른 기기·창으로 입력이 옮겨간다고 약속하지 않는다. */}
      {workAreas.length > 0 && (
        <div data-testid="compact-registration-summary" className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 text-[12.5px] leading-5 text-ink-2 lg:hidden">
          <p className="font-semibold text-ink-1">이 화면의 등록 범위</p>
          {templateNotice ? <p>{templateNotice}</p> : null}
          {scopeNotice ? <p>{scopeNotice}</p> : null}
          <p>비교 후보 작업구역 {workAreas.length}곳: {workAreas.map((area, index) => workAreaLabel(area, index)).join(", ")}</p>
          {initialWorkAreaIds.length > 0 && (
            <p>선택 제안: {initialWorkAreaIds.map((workAreaId) => {
              const index = workAreas.findIndex((area) => area.workAreaId === workAreaId);
              return index >= 0 ? workAreaLabel(workAreas[index]!, index) : null;
            }).filter((label) => label !== null).join(", ")}</p>
          )}
          <p>이 요약은 읽기 전용이며 입력·제출을 대신하지 않습니다. 등록·파일 제출은 화면 폭 1024px 이상에서 같은 계정으로 새로 입력해 진행하세요. 이 화면의 입력은 다른 기기·창으로 옮겨가지 않습니다. 아래 외부 비교 기록에서 목록을 확인하세요. 파일은 다음 화면에서 제출합니다.</p>
        </div>
      )}
      {workAreas.length === 0 ? (
        <section className="rounded-xl border border-line bg-surface p-4">
          <h2 className="text-[15px] font-bold">먼저 작업구역을 등록하세요</h2>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">비교할 범위가 있어야 결과의 위치와 의미를 확인할 수 있습니다.</p>
          <Link href={`/sites/${encodeURIComponent(siteId)}/work-areas`} className="btn mt-3 lg:hidden">작업구역 목록 보기</Link>
          <Link href={`/sites/${encodeURIComponent(siteId)}/work-areas`} className="btn mt-3 hidden lg:inline-flex">작업구역 만들기</Link>
          <p className="mt-2 text-[13px] leading-5 text-ink-2 lg:hidden">모바일에서는 목록을 확인할 수 있습니다. 작업구역 등록은 노트북에서 같은 계정으로 로그인한 뒤 화면 폭 1024px 이상에서 진행하세요.</p>
        </section>
      ) : (
        <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" title="화면 폭 1024px 이상에서 등록" reason="노트북에서 같은 계정으로 로그인하세요. 화면 폭 1024px 이상에서 같은 계정으로 새로 입력해 관측 자료 등록을 진행합니다. 이 화면의 입력은 다른 기기·창으로 옮겨가지 않으며, 권한은 등록 시점에 다시 확인합니다.">
          <section className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5 sm:p-6">
            <div>
              <p className="text-[13px] leading-5 text-ink-2">등록할 자료의 작업 이름과 범위를 선택하세요.</p>
              {/* 반복 템플릿 공지는 실제 검증된 반복 진입에서만 page가 넘긴다. 범위 선택만으로 추론하지 않는다. */}
              {templateNotice ? <p className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{templateNotice}</p> : null}
              {scopeNotice && <p role="status" className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{scopeNotice}</p>}
              {!hydrated && <p role="status" className="mt-2 rounded-lg bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">화면을 준비하고 있습니다. 입력란이 활성화되면 작업 이름과 작업구역을 확인하고 등록하세요. 이 안내가 계속 보이면 자바스크립트 실행과 연결 상태를 확인하세요.</p>}
            </div>
            <label className="flex flex-col gap-1 text-[13px] font-semibold">작업 이름
              <input key={hydrated ? "name-live" : "name-ssr"} aria-label="작업 이름" className="input" maxLength={200} value={name} disabled={!hydrated || busy || attempt !== null} onChange={(event) => setName(event.target.value)} placeholder={suggestedName ?? "예: 9월 6일 현황 비교"} />
            </label>
            <fieldset disabled={!hydrated || busy || attempt !== null}>
              <legend className="text-[13px] font-semibold">비교할 작업구역</legend>
              <div className="mt-2 grid gap-2">
                {workAreas.map((area, index) => <label key={area.workAreaId} className="flex cursor-pointer items-center gap-2 rounded-lg border border-line px-3 py-2 text-[13px] hover:bg-sunk">
                  <input key={hydrated ? `box-live-${area.workAreaId}` : `box-ssr-${area.workAreaId}`} type="checkbox" aria-label={workAreaLabel(area, index)} checked={selected.includes(area.workAreaId)} onChange={() => toggle(area.workAreaId)} disabled={!hydrated || busy || attempt !== null} />
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
              <button className="btn btn-primary" disabled={!hydrated || busy || !name.trim() || selected.length === 0 || (!attempt && !canStart)} onClick={() => void submit()}>{busy ? "작업 만드는 중" : attempt ? "같은 요청 다시 시도" : "관측 자료 등록 계속"}</button>
              {attempt && !busy && error && <button className="btn" onClick={startOver}>새 요청으로 시작</button>}
            </div>
            {!attempt && !canStart && <p role="alert" className="text-[13px] text-high-ink">계정을 확인하지 못해 요청을 보낼 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 화면을 떠나면 입력은 사라집니다.</p>}
            {!attempt && <p className="text-[12px] leading-5 text-ink-2">연속으로 눌러도 같은 요청 한 번으로 처리됩니다.</p>}
            {attempt && !busy && error && <p className="text-[12px] leading-5 text-ink-2">작업 목록에서 이미 만들어졌는지 먼저 확인하세요. 같은 이름이 있다고 해서 원래 요청이 성공했다고 단정하지 마세요. 목록에서 확인할 수 없으면 이 화면에서 같은 요청으로 다시 시도해도 중복 등록되지 않습니다. 새로 시작하면 다른 요청으로 등록됩니다.</p>}
            <p className="text-[12px] leading-5 text-ink-2">계속하면 작업이 만들어집니다. 파일은 다음 화면에서 제출합니다.</p>
            {/* 준비 게이트가 열리기 전에는 필수 입력 안내를 내지 않는다. 잠긴 입력칸에
                입력하라는 안내는 모순이므로, 준비 안내가 그 자리를 대신한다. */}
            {hydrated && !busy && !attempt && !name.trim() && selected.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요.</p>}
            {hydrated && !busy && !attempt && !name.trim() && selected.length > 0 && <p className="text-[12.5px] leading-5 text-ink-2">작업 이름을 입력하세요.</p>}
            {hydrated && !busy && !attempt && name.trim() && selected.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">비교할 작업구역을 하나 이상 선택하세요.</p>}
            {error && <p role="alert" className="text-[13px] text-high-ink">{error}{attempt && <> <Link href={workQueueHref} target="_blank" rel="noopener noreferrer" className="font-semibold underline">작업 목록 확인(새 탭)</Link></>}</p>}
          </section>
        </ResponsiveActionBoundary>
      )}
      <Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="tap-target inline-flex w-fit items-center text-[12px] text-ink-2 underline">외부 비교 기록 확인</Link>
    </div>
  );
}
