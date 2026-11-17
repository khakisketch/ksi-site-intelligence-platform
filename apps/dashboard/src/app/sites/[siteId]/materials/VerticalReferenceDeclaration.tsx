"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { formatKoreanDateTime } from "@/lib/datetime";
import type { VerticalDatum } from "@/lib/core-api/measurement-types";
import { MAX_DECLARATION_BASIS, type VerticalDeclarationState } from "@/lib/core-api/vertical-reference-types";
import { datumLabel } from "@/lib/measurement-vertical";
import { DATUM_CHOICES, declarationErrorText } from "@/lib/vertical-declaration-copy";

/**
 * 파일에 수직 기준이 없는 DSM의 수직 기준 선언.
 *
 * 선언은 사용자의 주장이다. 파일에서 확인한 값처럼 보이지 않게 "사용자 선언"과 "검증하지 않음"을 항상 같이 쓴다.
 * 선언은 이 자료의 높이·단면 읽기에만 쓰이고 체적·두 시점 비교에는 쓰이지 않는다. 높이 단위는 미터로 고정이다.
 */
export function VerticalReferenceDeclaration({
  siteId,
  workAreaId,
  assetRef,
  state,
  canWrite,
}: {
  siteId: string;
  workAreaId: string;
  assetRef: string;
  /** 읽지 못했으면 null. 선언이 없다는 뜻이 아니다. */
  state: VerticalDeclarationState | null;
  canWrite: boolean;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [confirmingWithdraw, setConfirmingWithdraw] = useState(false);
  const [datum, setDatum] = useState<VerticalDatum | "">("");
  const [basis, setBasis] = useState("");
  const [unitConfirmed, setUnitConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 응답을 모르는 실패는 같은 키로 다시 보내 중복 기록을 막는다. 응답을 받으면 새 키를 쓴다.
  const key = useRef<{ id: string; fingerprint: string } | null>(null);
  const lock = useRef(false);

  if (state === null) {
    return <section aria-label="수직 기준 선언" className="rounded-lg border border-line bg-surface p-3 text-caption leading-5 text-ink-2">
      <h4 className="font-semibold text-ink-1">수직 기준 선언</h4>
      <p className="mt-1">선언 상태를 불러오지 못했습니다. 선언이 없다는 뜻이 아닙니다. 잠시 후 다시 열어 확인하세요.</p>
    </section>;
  }

  const current = state.current;
  const sequence = state.history.length;

  async function send(path: "declarations" | "withdrawals", body: Record<string, unknown>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    const fingerprint = `${path}:${JSON.stringify(body)}`;
    if (key.current === null || key.current.fingerprint !== fingerprint) {
      key.current = { id: `console-${crypto.randomUUID()}`, fingerprint };
    }
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-assets/${encodeURIComponent(assetRef)}/vertical-reference/${path}`,
        { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": key.current.id }, body: JSON.stringify(body) },
      );
      const value: unknown = await response.json().catch(() => null);
      if (response.ok) {
        key.current = null;
        setEditing(false);
        setConfirmingWithdraw(false);
        setDatum("");
        setBasis("");
        setUnitConfirmed(false);
        router.refresh();
        return;
      }
      // 서버가 답했으니 이 시도는 끝났다. 같은 키로 다시 보내지 않는다.
      key.current = null;
      const code = typeof value === "object" && value !== null && typeof (value as { code?: unknown }).code === "string" ? (value as { code: string }).code : undefined;
      setError(declarationErrorText(response.status, code));
    } catch {
      // 응답을 모른다. 키를 두어 같은 요청으로 다시 시도하게 한다.
      setError("응답을 확인하지 못했습니다. 같은 요청으로 다시 시도하세요.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  const trimmed = basis.trim();
  const canSubmit = !busy && datum !== "" && trimmed.length > 0 && trimmed.length <= MAX_DECLARATION_BASIS && unitConfirmed;
  const showForm = canWrite && (editing || current === null);

  return (
    <section aria-label="수직 기준 선언" className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-3 text-caption leading-5 text-ink-2">
      <h4 className="font-semibold text-ink-1">수직 기준 선언</h4>

      {current ? (
        <div>
          <p>
            <span className="font-semibold text-ink-1">사용자 선언 · {datumLabel(current.datum!)}</span>
            {" "}· 높이 단위 미터
          </p>
          <p className="mt-0.5 break-words">근거: {current.basis}</p>
          <p className="mt-0.5 text-micro text-ink-muted">
            {current.declaredBy}가 {formatKoreanDateTime(current.declaredAt, { dateStyle: "medium", timeStyle: "short" })}에 선언했습니다.
            파일에서 확인되지 않은 값이며 KSI는 검증하지 않습니다.
          </p>
        </div>
      ) : (
        <p>
          이 파일에는 수직 기준(높이 기준)이 없어 높이·단면을 읽을 수 없습니다. 내보낼 때 쓴 기준을 알면 선언하세요.
          선언은 이 자료의 높이·단면 읽기에만 쓰이며, 체적과 두 시점 비교에는 쓰이지 않습니다.
          {state.history.length > 0 && " 이전 선언은 철회되었습니다."}
        </p>
      )}

      {!canWrite && <p className="text-micro text-ink-muted">선언은 작업 등록 권한이 있는 계정이 할 수 있습니다.</p>}

      {canWrite && (
        <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" title="화면 폭 1024px 이상에서 선언" reason="노트북에서 같은 계정으로 열어 선언하세요. 모바일에서는 선언 내용을 읽기만 할 수 있습니다.">
          {current && !editing && !confirmingWithdraw && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn" onClick={() => { setEditing(true); setDatum(current.datum ?? ""); setBasis(current.basis ?? ""); setUnitConfirmed(false); setError(null); }}>정정하기</button>
              <button type="button" className="btn" onClick={() => { setConfirmingWithdraw(true); setError(null); }}>철회하기</button>
            </div>
          )}

          {current && confirmingWithdraw && (
            <div role="alertdialog" aria-label="선언 철회 확인" className="rounded-lg bg-sunk p-3">
              <p>철회하면 이 선언 위에서 읽은 단면 결과도 더 이상 열리지 않고, 새로 읽을 수도 없습니다. 철회 기록은 남습니다.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void send("withdrawals", { expectedSequence: sequence })}>{busy ? "철회하는 중" : "철회합니다"}</button>
                <button type="button" className="btn" disabled={busy} onClick={() => setConfirmingWithdraw(false)}>취소</button>
              </div>
            </div>
          )}

          {showForm && (
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (!canSubmit) return;
                void send("declarations", { datum, unit: "metre", basis: trimmed, expectedSequence: sequence });
              }}
            >
              <fieldset className="flex flex-col gap-1.5" disabled={busy}>
                <legend className="font-semibold text-ink-1">높이 기준</legend>
                {DATUM_CHOICES.map((choice) => (
                  <label key={choice.datum} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line px-3 py-2 hover:bg-sunk">
                    <input type="radio" name="vertical-datum" value={choice.datum} checked={datum === choice.datum} onChange={() => setDatum(choice.datum)} className="mt-1" />
                    <span><span className="block font-semibold text-ink-1">{choice.label}</span><span className="block text-micro text-ink-muted">{choice.hint}</span></span>
                  </label>
                ))}
              </fieldset>
              <label className="flex flex-col gap-1 font-semibold text-ink-1">근거 (필수)
                <input className="input font-normal" value={basis} maxLength={MAX_DECLARATION_BASIS} disabled={busy} placeholder="예: Terra 내보내기 설정에서 정표고(KNGeoid2018)를 선택함" onChange={(event) => setBasis(event.target.value)} />
                <span className="text-micro font-normal text-ink-muted">어떻게 알았는지 적어 두세요(내보내기 설정, 보고서 등). 나중에 확인하는 사람이 볼 수 있습니다.</span>
              </label>
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={unitConfirmed} disabled={busy} onChange={(event) => setUnitConfirmed(event.target.checked)} className="mt-1" />
                <span>이 파일의 높이 단위가 미터임을 확인했습니다. 단위가 다르면 모든 높이가 어긋납니다.</span>
              </label>
              <p className="text-micro text-ink-muted">선언한 기준이 맞는지는 KSI가 확인하지 않습니다. 틀린 선언은 틀린 높이를 만듭니다.</p>
              <div className="flex flex-wrap gap-2">
                <button type="submit" className="btn btn-primary" disabled={!canSubmit}>{busy ? "저장하는 중" : current ? "정정을 저장" : "선언하기"}</button>
                {current && <button type="button" className="btn" disabled={busy} onClick={() => { setEditing(false); setError(null); }}>취소</button>}
              </div>
            </form>
          )}
        </ResponsiveActionBoundary>
      )}

      {error && <p role="alert" className="text-high-ink">{error}</p>}
    </section>
  );
}
