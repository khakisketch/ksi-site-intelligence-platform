"use client";

import Link from "next/link";
import { useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { isSpatialDataExecutionState, type SpatialDataBounds } from "@/lib/core-api/spatial-data-types";
import {
  MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM,
  PIXEL_WINDOW_BLOCKER_COPY,
  canUseWholeGrid,
  initialPixelWindowDims,
  resolveBoundedPixelWindow,
  type InspectedRasterGrid,
} from "@/lib/spatial-data-request";

const STATE_LABEL: Record<string, string> = {
  QUEUED: "대기",
  RUNNING: "처리 중",
  COMPLETED: "완료",
  FAILED: "실패",
  CANCELED: "취소됨",
  EXPIRED: "기한 만료",
};

/** Core가 돌려주는 typed 사유를 그대로 옮긴다 — 판정을 새로 만들지 않는다. */
const REASON_COPY: Record<string, string> = {
  PERMISSION_DENIED: "이 자료를 요청할 권한이 없습니다. 권한 있는 담당자에게 요청하세요.",
  NOT_FOUND: "자료를 찾을 수 없거나 현재 접근할 수 없습니다.",
  GRANT_REQUIRED: "이 자료에 대한 명시적 사용 권리가 아직 없습니다. 관리자에게 권리 설정을 요청하세요.",
  AMBIGUOUS_GRANT: "같은 자료에 적용할 권리가 둘 이상입니다. 관리자에게 확인을 요청하세요.",
  ACCESS_REVOKED: "이 자료의 사용 권리가 회수되었습니다. 관리자에게 확인하세요.",
  ACCESS_EXPIRED: "이 자료의 사용 권리가 만료되었습니다. 관리자에게 확인하세요.",
  ACTIVATION_UNAVAILABLE: "자료 준비 작업이 이 환경에서 활성화되어 있지 않습니다. 관리자에게 확인하세요.",
  POLICY_UNAVAILABLE: "자료 준비 정책을 확인할 수 없습니다. 잠시 후 다시 시도하세요.",
  SOURCE_UNSEALED: "제출이 마무리되지 않은 자료입니다. 검사 기록이 있는 봉인 자료만 요청할 수 있습니다.",
  SOURCE_NOT_MEASURED: "파일 검사 결과가 있는 자료만 요청할 수 있습니다.",
  SOURCE_UNAVAILABLE: "원본 자료를 현재 사용할 수 없습니다. 등록 상태를 확인하세요.",
  UNSUPPORTED_ARTIFACT_KIND: "이 자료 종류는 준비 요청을 지원하지 않습니다.",
  UNSUPPORTED_SOURCE_PROFILE: "이 파일 형식은 준비 요청을 지원하지 않습니다.",
  INVALID_REQUEST_BOUNDS: "요청 범위가 자료의 네이티브 격자와 맞지 않습니다. 화면을 새로 고쳐 다시 확인하세요.",
  REQUEST_OUTSIDE_SOURCE: "요청 범위가 자료 범위를 벗어납니다.",
  OUTPUT_OUTSIDE_GRANT: "요청 범위가 허용된 권리 범위를 벗어납니다. 관리자에게 확인하세요.",
  CRS_MISMATCH: "좌표 기준이 맞지 않아 준비할 수 없습니다.",
  VERTICAL_REFERENCE_MISMATCH: "수직 기준이 맞지 않아 준비할 수 없습니다.",
  UNSUPPORTED_GRID: "지원하지 않는 격자입니다.",
  EMPTY_PIXEL_WINDOW: "요청 범위 안에 사용할 수 있는 셀이 없습니다.",
  EMPTY_VALID_WINDOW: "요청 범위 안에 유효한 값이 없습니다.",
  RESOURCE_LIMIT_EXCEEDED: "조직의 준비 한도를 넘었습니다. 기존 요청을 정리한 뒤 다시 시도하세요.",
  RETAINED_HISTORY_LIMIT_EXCEEDED: "보관 한도를 넘어 새 요청을 만들 수 없습니다. 기존 요청을 정리하세요.",
  INTEGRITY_MISMATCH: "파일 무결성 확인이 맞지 않아 준비할 수 없습니다.",
  AUDIT_UNAVAILABLE: "감사 기록을 확인할 수 없어 요청을 만들지 않았습니다.",
  STORAGE_UNAVAILABLE: "저장소 상태로 요청을 만들지 못했습니다. 잠시 후 다시 시도하세요.",
  CURRENTNESS_UNAVAILABLE: "현재 권리 상태를 확인할 수 없습니다. 잠시 후 다시 시도하세요.",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function formatBounds(bounds: SpatialDataBounds): string {
  return `[${bounds.map((value) => (Number.isInteger(value) ? String(value) : value.toPrecision(10))).join(", ")}]`;
}

function parseNonNegativeInt(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const value = Number(text.trim());
  return Number.isSafeInteger(value) ? value : null;
}

/**
 * 선택한 자료의 검사 격자에서 고른 유한 픽셀 창으로 "받기 요청"을 만든다.
 *
 * - 창은 실제 검사 affine/격자에서만 유도한다 — 전체 네이티브 범위를 통째로
 *   보내지 않고, 리샘플링·반올림·추측도 하지 않는다.
 * - 같은 화면에서 다시 눌러도 같은 Idempotency-Key를 쓴다 — 같은 요청이 두 번
 *   만들어지지 않는다(성공한 뒤에는 새 요청을 만들지 않고 상태만 알린다).
 * - 권리·정책·활성화 판단은 Core가 한다. 여기서는 사유를 사람 말로 옮기기만 한다.
 * - 준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않는다는 문구를 유지한다.
 */
export function SpatialDataRequestAction({
  siteId,
  workAreaId,
  assetRef,
  inspectedRaster,
  observedCrsIdentifier,
  observedCrsDigest,
  canRequest,
}: {
  siteId: string;
  workAreaId: string;
  assetRef: string;
  /** Core 검사 영수증의 실제 격자 — 없으면 요청 범위를 만들지 않는다. */
  inspectedRaster: InspectedRasterGrid | null;
  /** 사람용 표시 전용 — 권리 판단에 쓰지 않는다. */
  observedCrsIdentifier: string | null;
  /** Core가 요청 격자를 대조하는 기준 확인값 — 없으면 요청을 만들지 않는다. */
  observedCrsDigest: string | null;
  canRequest: boolean;
}) {
  const initial = inspectedRaster
    ? initialPixelWindowDims(inspectedRaster.width, inspectedRaster.height)
    : null;
  const [widthText, setWidthText] = useState(initial ? String(initial.width) : "0");
  const [heightText, setHeightText] = useState(initial ? String(initial.height) : "0");
  const [colText, setColText] = useState(initial ? String(initial.col) : "0");
  const [rowText, setRowText] = useState(initial ? String(initial.row) : "0");
  const [attemptKey] = useState(() => `sdreq-${crypto.randomUUID()}`);
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState<{ jobId: string; state: string } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const requestsHref = `/sites/${encodeURIComponent(siteId)}/spatial-data-requests?workAreaId=${encodeURIComponent(workAreaId)}`;

  const width = parseNonNegativeInt(widthText);
  const height = parseNonNegativeInt(heightText);
  const col = parseNonNegativeInt(colText);
  const row = parseNonNegativeInt(rowText);
  const resolution = resolveBoundedPixelWindow(inspectedRaster, {
    width: width ?? -1,
    height: height ?? -1,
    col: col ?? -1,
    row: row ?? -1,
  });
  const wholeGridAllowed = inspectedRaster !== null && canUseWholeGrid(inspectedRaster.width, inspectedRaster.height);
  const canSubmit = canRequest
    && resolution.ok
    && typeof observedCrsDigest === "string"
    && observedCrsDigest.length > 0
    && !busy
    && accepted === null;

  const request = async () => {
    if (!resolution.ok || typeof observedCrsDigest !== "string" || observedCrsDigest.length === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests`,
        {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json", "Idempotency-Key": attemptKey, Accept: "application/json" },
          body: JSON.stringify({
            assetRef,
            requestedBounds: resolution.value.requestedBounds,
            observedCrsDigest,
            resolutionMode: "NATIVE",
            purpose: "GENERAL_DATA_USE",
          }),
        },
      );
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const reason = isRecord(body) && typeof body.reason === "string"
          ? body.reason
          : isRecord(body) && typeof body.code === "string" ? body.code : null;
        setMessage(
          (reason && REASON_COPY[reason])
          ?? (response.status === 404
            ? "이 환경에서는 자료 준비 기능이 연결되어 있지 않거나 대상을 찾을 수 없습니다. 관리자에게 확인하세요."
            : null)
          ?? (isRecord(body) && typeof body.message === "string" ? body.message : null)
          ?? "받기 요청을 만들지 못했습니다. 현재 상태를 다시 확인하세요.",
        );
        return;
      }
      if (!isRecord(body) || typeof body.jobId !== "string" || !isSpatialDataExecutionState(body.executionState)) {
        setMessage("Core 응답의 요청 식별자 또는 상태를 확인할 수 없습니다. 구역 자료 준비에서 확인하세요.");
        return;
      }
      setAccepted({ jobId: body.jobId, state: body.executionState });
      setMessage(`받기 요청을 만들었습니다 · 상태 ${STATE_LABEL[body.executionState] ?? body.executionState}. 준비가 끝나면 구역 자료 준비에서 받을 수 있습니다.`);
    } catch {
      setMessage("Core 응답을 받지 못했습니다. 구역 자료 준비에서 현재 상태를 다시 확인하세요.");
    } finally {
      setBusy(false);
    }
  };

  if (!canRequest) {
    return <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-semibold">이 자료 받기 요청</h3>
      <div className="mt-2">
        <ActionUnavailable label="자료 받기 요청" description="자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다. 필요한 파일과 용도를 담당자에게 알려 주세요." />
      </div>
    </section>;
  }

  return <section className="rounded-lg border border-line bg-surface px-4 py-3">
    <h3 className="text-[13px] font-semibold">이 자료 받기 요청</h3>
    <p className="mt-1 text-[12px] leading-5 text-ink-2">
      검사된 격자에서 고른 유한 픽셀 창 그대로 준비를 요청합니다. Core가 현재 명시된 사용 권리와 범위를 확인한 뒤에만 작업을 만듭니다.
    </p>
    <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
      준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다. AI 반출 용도는 별도 동의 절차가 필요합니다.
    </p>
    {inspectedRaster
      ? <p className="mt-2 text-[12px] leading-5 text-ink-2">
        검사 격자 · {inspectedRaster.width} × {inspectedRaster.height} 네이티브 픽셀
        {observedCrsIdentifier ? <> · 기준 {observedCrsIdentifier}</> : null}
      </p>
      : <p className="mt-2 rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2" role="status">
        {PIXEL_WINDOW_BLOCKER_COPY.NO_INSPECTION}
      </p>}
    <fieldset className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2">
      <legend className="px-1 text-[12px] font-semibold">픽셀 창 설정</legend>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-28 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-pixel-window-width">
          너비 (1–{inspectedRaster ? Math.min(inspectedRaster.width, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM) : MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM})
          <input
            id="spatial-pixel-window-width"
            className="input min-h-11"
            inputMode="numeric"
            min={1}
            max={inspectedRaster ? Math.min(inspectedRaster.width, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM) : MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM}
            value={widthText}
            onChange={(event) => setWidthText(event.target.value)}
            disabled={busy || accepted !== null || inspectedRaster === null}
          />
        </label>
        <label className="flex min-w-28 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-pixel-window-height">
          높이 (1–{inspectedRaster ? Math.min(inspectedRaster.height, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM) : MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM})
          <input
            id="spatial-pixel-window-height"
            className="input min-h-11"
            inputMode="numeric"
            min={1}
            max={inspectedRaster ? Math.min(inspectedRaster.height, MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM) : MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM}
            value={heightText}
            onChange={(event) => setHeightText(event.target.value)}
            disabled={busy || accepted !== null || inspectedRaster === null}
          />
        </label>
        <label className="flex min-w-28 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-pixel-window-col">
          원점 열 (0부터)
          <input
            id="spatial-pixel-window-col"
            className="input min-h-11"
            inputMode="numeric"
            value={colText}
            onChange={(event) => setColText(event.target.value)}
            disabled={busy || accepted !== null || inspectedRaster === null}
          />
        </label>
        <label className="flex min-w-28 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-pixel-window-row">
          원점 행 (0부터)
          <input
            id="spatial-pixel-window-row"
            className="input min-h-11"
            inputMode="numeric"
            value={rowText}
            onChange={(event) => setRowText(event.target.value)}
            disabled={busy || accepted !== null || inspectedRaster === null}
          />
        </label>
        <button
          type="button"
          className="btn min-h-11"
          disabled={!wholeGridAllowed || busy || accepted !== null}
          onClick={() => {
            if (!inspectedRaster) return;
            setWidthText(String(inspectedRaster.width));
            setHeightText(String(inspectedRaster.height));
            setColText("0");
            setRowText("0");
          }}
        >
          전체 격자 사용
        </button>
      </div>
      {inspectedRaster && (resolution.ok
        ? <div className="mt-2 text-[12px] leading-5 text-ink-2">
          <p>픽셀 창 · 열 {resolution.value.window[0]}–{resolution.value.window[0] + resolution.value.width - 1},
            행 {resolution.value.window[1]}–{resolution.value.window[1] + resolution.value.height - 1}
            (원점 {resolution.value.window[0]}, {resolution.value.window[1]} · 너비 {resolution.value.width} × 높이 {resolution.value.height} 네이티브 픽셀)</p>
          <p className="mt-0.5 break-all">요청 범위(네이티브 좌표) · {formatBounds(resolution.value.requestedBounds)}</p>
          <p className="mt-0.5 text-[11.5px] text-ink-muted">
            실제 출력 범위는 준비가 끝난 뒤 구역 자료 준비의 출력 정보(실제 범위)에서 확인하세요.
          </p>
        </div>
        : <p className="mt-2 text-[12px] leading-5 text-high-ink" role="status">{PIXEL_WINDOW_BLOCKER_COPY[resolution.reason]}</p>)}
    </fieldset>
    <ResponsiveActionBoundary action="SPATIAL_DATA_REQUEST" reason="자료 받기 요청은 노트북 이상의 화면에서 진행하세요. 준비 상태는 모바일에서도 확인할 수 있습니다.">
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary min-h-11" disabled={!canSubmit} onClick={() => void request()}>
          {busy ? "요청 만드는 중…" : accepted ? "요청 만듦" : "받기 요청 만들기"}
        </button>
        <Link href={requestsHref} className="btn min-h-11">구역 자료 준비에서 확인</Link>
      </div>
    </ResponsiveActionBoundary>
    {message && <p role="status" aria-live="polite" className="mt-3 rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2">{message}</p>}
  </section>;
}
