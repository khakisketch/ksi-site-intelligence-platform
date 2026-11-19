"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { FEATURE_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { saveLineErrorText } from "@/lib/measurement-copy";
import {
  MAX_LINE_NAME,
  MAX_LINE_VERTICES,
  approxLengthM,
  createLineBody,
  insertVertex,
  lineIssues,
  lineNameIssue,
  moveVertex,
  outsideAreaCount,
  removeVertex,
  reviseLineBody,
  rowsToVertices,
  verticesToRows,
  type LineVertex,
  type VertexRow,
} from "@/lib/measurement-line";

import { LineEditorMap } from "./LineEditorMap";

export interface LineEditorProps {
  siteId: string;
  workAreaId: string;
  areaName: string;
  /** 작업구역 경계. 모르면 null이며 안내만 한다. */
  ring: LineVertex[] | null;
  initialVertices: LineVertex[];
  initialName: string;
  /** 있으면 새 개정으로 고치는 중이다. */
  editing: { featureId: string; revision: number } | null;
  /** 저장돼 있던 좌표계. 경위도가 아니어서 변환해 보여 주는 경우에만 있다. */
  convertedFromCrs: string | null;
  source: {
    assetRef: string;
    fileName: string;
    captureDate: string | null;
    footprint: LineVertex[] | null;
  } | null;
  /** 처음 지도를 열 때 자료 범위에 맞춘다. 편집 중이면 저장된 선이 우선한다. */
  focusRing: LineVertex[] | null;
  /** 측정 목록 복귀 주소에 작업구역과 자료 선택을 보존한다. */
  returnHref: string;
}

const MAX_HISTORY = 50;
const UNCONFIRMED_SAVE = "저장 응답을 확인하지 못했습니다. 같은 내용으로 다시 저장하면 처리 결과를 확인할 수 있습니다.";

function savedLineHref(returnHref: string, featureId: string): string {
  const [pathname, search = ""] = returnHref.split("?", 2);
  const params = new URLSearchParams(search);
  params.delete("ref");
  params.delete("cur");
  params.delete("comparison");
  params.set("feature", featureId);
  return `${pathname}?${params}`;
}

function without<T>(record: Record<number, T>, index: number): Record<number, T> {
  const next = { ...record };
  delete next[index];
  return next;
}

export function LineEditor({ siteId, workAreaId, areaName, ring, initialVertices, initialName, editing, convertedFromCrs, source, focusRing, returnHref }: LineEditorProps) {
  const router = useRouter();
  const [vertices, setVertices] = useState<LineVertex[]>(initialVertices);
  const [history, setHistory] = useState<LineVertex[][]>([]);
  const [name, setName] = useState(initialName);
  const [drafts, setDrafts] = useState<Record<number, VertexRow>>({});
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  const [addRow, setAddRow] = useState<VertexRow>({ lat: "", lon: "" });
  const [addError, setAddError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ id: string; fingerprint: string } | null>(null);
  const lock = useRef(false);

  const change = (next: LineVertex[]) => {
    setHistory((current) => [...current.slice(-(MAX_HISTORY - 1)), vertices]);
    setVertices(next);
    setError(null);
  };
  const undo = () => {
    const previous = history[history.length - 1];
    if (!previous) return;
    setHistory(history.slice(0, -1));
    setVertices(previous);
    setDrafts({});
    setRowErrors({});
    setError(null);
  };

  const rows = verticesToRows(vertices);
  const issues = lineIssues(vertices);
  const nameIssue = lineNameIssue(name);
  const pendingRows = Object.keys(drafts).length > 0;
  const outside = outsideAreaCount(vertices, ring);
  const lengthM = approxLengthM(vertices);
  const canSave = !busy && issues.length === 0 && nameIssue === null && !pendingRows;

  const editRow = (index: number, field: keyof VertexRow, value: string) => {
    const draft = { ...(drafts[index] ?? rows[index]!), [field]: value };
    const parsed = rowsToVertices([draft]);
    if (parsed.ok) {
      setDrafts(without(drafts, index));
      setRowErrors(without(rowErrors, index));
      change(moveVertex(vertices, index, parsed.vertices[0]!));
    } else {
      setDrafts({ ...drafts, [index]: draft });
      setRowErrors({ ...rowErrors, [index]: parsed.reason.replace(/^1번째 줄: /, "") });
    }
  };

  const addByCoordinates = () => {
    const parsed = rowsToVertices([addRow]);
    if (!parsed.ok) {
      setAddError(parsed.reason.replace(/^1번째 줄: /, ""));
      return;
    }
    if (vertices.length >= MAX_LINE_VERTICES) {
      setAddError(`점은 ${MAX_LINE_VERTICES}개까지 둘 수 있습니다.`);
      return;
    }
    setAddError(null);
    setAddRow({ lat: "", lon: "" });
    change(insertVertex(vertices, vertices.length, parsed.vertices[0]!));
  };

  async function save() {
    if (lock.current || !canSave) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    const body = editing ? reviseLineBody(editing.revision, name, vertices) : createLineBody(workAreaId, name, vertices);
    const path = editing
      ? `measurement-features/${encodeURIComponent(editing.featureId)}/revisions`
      : "measurement-features";
    const fingerprint = `${path}:${JSON.stringify(body)}`;
    if (key.current === null || key.current.fingerprint !== fingerprint) {
      key.current = { id: `console-${crypto.randomUUID()}`, fingerprint };
    }
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/${path}`, {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": key.current.id },
        body: JSON.stringify(body),
      });
      const value: unknown = await response.json().catch(() => null);
      if (response.ok) {
        const featureId = typeof value === "object" && value !== null
          ? (value as { revision?: { featureId?: unknown } }).revision?.featureId
          : undefined;
        if (typeof featureId !== "string" || !FEATURE_ID_PATTERN.test(featureId) || (editing && featureId !== editing.featureId)) {
          setError(UNCONFIRMED_SAVE);
          return;
        }
        key.current = null;
        router.push(savedLineHref(returnHref, featureId));
        return;
      }
      if (response.status >= 500 || response.status === 408) {
        setError(UNCONFIRMED_SAVE);
        return;
      }
      key.current = null;
      const code = typeof value === "object" && value !== null && typeof (value as { code?: unknown }).code === "string" ? (value as { code: string }).code : undefined;
      setError(saveLineErrorText(response.status, code));
    } catch {
      setError(UNCONFIRMED_SAVE);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  return <>
    {source && <aside aria-label="선택한 DSM" className="min-w-0 rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-caption text-ink-muted">선택한 DSM · {source.captureDate ?? "촬영 시기 미상"}</p>
      <p className="break-all text-body font-semibold text-ink-1">{source.fileName}</p>
      {source.footprint
        ? <p className="mt-1 text-caption text-ink-2">지도에 표시한 자료 경계는 DSM 전체 격자의 외곽입니다. 경계 안에도 높이가 없는 지점이 있을 수 있습니다.</p>
        : <p className="mt-1 text-caption text-high-ink">파일의 좌표계와 격자 경계로는 이 자료의 범위를 지도에 표시할 수 없습니다.</p>}
    </aside>}
    <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" title="화면 폭 1024px 이상에서 그리기" reason="측정 선은 지도에서 점을 눌러 그립니다. 노트북에서 같은 계정으로 여세요. 모바일에서는 저장한 선을 볼 수만 있습니다.">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
        <div className="min-h-[420px] overflow-hidden rounded-xl border border-line bg-sunk lg:h-[600px]" aria-label="측정 선 그리기 지도">
          <LineEditorMap
            vertices={vertices}
            ring={ring}
            sourceRing={source?.footprint ?? null}
            focusRing={focusRing}
            disabled={busy}
            onAdd={(vertex) => vertices.length < MAX_LINE_VERTICES && change(insertVertex(vertices, vertices.length, vertex))}
            onMove={(index, vertex) => change(moveVertex(vertices, index, vertex))}
          />
        </div>

        <form
          aria-label="측정 선"
          className="flex min-w-0 flex-col gap-4 rounded-xl border border-line bg-surface p-4 sm:p-5"
          onSubmit={(event) => { event.preventDefault(); void save(); }}
        >
          <div>
            <p className="text-micro text-ink-muted">{areaName}</p>
            <h3 className="text-lead font-bold">{editing ? "측정 선 고치기" : "새 측정 선"}</h3>
            <p className="mt-1 text-caption leading-5 text-ink-2">
              지도에서 점을 차례로 눌러 선을 그립니다. 점은 끌어서 옮길 수 있고, 아래 표에서 좌표로 고칠 수도 있습니다. 저장은 선의 위치만 기억하며 어떤 자료도 읽지 않습니다.
            </p>
          </div>

          {editing && (
            <p role="note" className="rounded-lg bg-sunk px-3 py-2 text-caption leading-5 text-ink-2">
              고치면 새 개정으로 저장됩니다. 이미 읽은 단면은 이전 개정의 결과로 남고, 새 개정의 단면은 다시 요청해야 합니다.
              {convertedFromCrs && ` 이 선은 ${convertedFromCrs}로 저장되어 있어 지도 좌표로 바꿔 보여 줍니다. 저장하면 새 개정은 경위도 선이 됩니다.`}
            </p>
          )}

          <label className="flex flex-col gap-1 text-body font-semibold">이름
            <input className="input font-normal" value={name} maxLength={MAX_LINE_NAME} disabled={busy} placeholder="예: 북쪽 경사면" onChange={(event) => { setName(event.target.value); setError(null); }} />
          </label>

          <div aria-live="polite" className="tabular rounded-lg bg-sunk px-3 py-2 text-caption leading-5 text-ink-2">
            <p>점 <strong className="text-ink-1">{vertices.length}</strong>개 · 지도 위 길이 약 <strong className="text-ink-1">{lengthM.toFixed(1)} m</strong></p>
            {outside !== null && outside > 0 && <p className="text-high-ink">작업구역 밖에 있는 점이 {outside}개 있습니다. 구역 안에서 그렸는지 확인하세요.</p>}
            {ring === null && <p>이 구역의 모양을 지도에 표시하지 못했습니다. 구역 안인지는 확인하지 않습니다.</p>}
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" disabled={busy || history.length === 0} onClick={undo}>되돌리기</button>
            <button type="button" className="btn" disabled={busy || vertices.length === 0} onClick={() => change([])}>모두 지우기</button>
          </div>

          {vertices.length > 0 && (
            <fieldset className="flex flex-col gap-1.5" disabled={busy}>
              <legend className="text-body font-semibold">점 좌표 (위도, 경도)</legend>
              <ol className="flex flex-col gap-1.5">
                {rows.map((row, index) => {
                  const shown = drafts[index] ?? row;
                  return (
                    <li key={index} className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="tabular w-5 shrink-0 text-right text-caption text-ink-muted">{index + 1}</span>
                        <input aria-label={`${index + 1}번 점 위도`} inputMode="decimal" className="input min-w-0 flex-1 text-caption" value={shown.lat} onChange={(event) => editRow(index, "lat", event.target.value)} />
                        <input aria-label={`${index + 1}번 점 경도`} inputMode="decimal" className="input min-w-0 flex-1 text-caption" value={shown.lon} onChange={(event) => editRow(index, "lon", event.target.value)} />
                        <button type="button" className="btn px-2" aria-label={`${index + 1}번 점 지우기`} onClick={() => { setDrafts({}); setRowErrors({}); change(removeVertex(vertices, index)); }}>×</button>
                      </div>
                      {rowErrors[index] && <p role="alert" className="pl-6 text-micro text-high-ink">{rowErrors[index]}</p>}
                    </li>
                  );
                })}
              </ol>
            </fieldset>
          )}

          <fieldset className="flex flex-col gap-1.5" disabled={busy}>
            <legend className="text-body font-semibold">좌표로 점 추가</legend>
            <div className="flex items-center gap-1.5">
              <input aria-label="추가할 점 위도" inputMode="decimal" placeholder="위도" className="input min-w-0 flex-1 text-caption" value={addRow.lat} onChange={(event) => setAddRow({ ...addRow, lat: event.target.value })} />
              <input aria-label="추가할 점 경도" inputMode="decimal" placeholder="경도" className="input min-w-0 flex-1 text-caption" value={addRow.lon} onChange={(event) => setAddRow({ ...addRow, lon: event.target.value })} />
              <button type="button" className="btn" onClick={addByCoordinates}>추가</button>
            </div>
            {addError && <p role="alert" className="text-micro text-high-ink">{addError}</p>}
          </fieldset>

          {(issues.length > 0 || nameIssue !== null || pendingRows) && (
            <ul className="list-disc pl-5 text-caption leading-5 text-ink-2" aria-label="저장하려면">
              {issues.map((issue) => <li key={issue}>{issue}</li>)}
              {nameIssue !== null && <li>{nameIssue}</li>}
              {pendingRows && <li>좌표가 올바르지 않은 점을 고치세요.</li>}
            </ul>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="submit" className="btn btn-primary" disabled={!canSave}>{busy ? "저장하는 중" : editing ? "새 개정으로 저장" : "선 저장"}</button>
            <Link href={returnHref} className="btn">돌아가기</Link>
          </div>
          {error && <p role="alert" className="text-body text-high-ink">{error}</p>}
        </form>
      </div>
    </ResponsiveActionBoundary>
  </>;
}
