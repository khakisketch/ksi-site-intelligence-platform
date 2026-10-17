"use client";

import { useMemo, useState } from "react";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import {
  ResponsiveActionBoundary,
  ResponsiveNotice,
} from "@/components/responsive/ResponsiveActionBoundary";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { COMPARISON_ZONE_CRS, toZonePolygon } from "@/lib/comparison-submit";
import { readableApiError } from "@/lib/core-api/labels";
import { parseJsonSafe } from "@/lib/http";
import { formatKoreanDateTime } from "@/lib/datetime";
import { toDisplayVertices, type DisplayVerticesResult } from "@/lib/geo/display-geometry";
import { WORK_AREA_STATUS_LABEL, partitionWorkAreas, polygonToVertices } from "@/lib/work-areas";
import type {
  AoiVertex,
  WorkArea,
  WorkAreaListResponse,
  WorkAreaResponse,
} from "@/lib/core-api/types";

/**
 * 작업구역 등록·보관(M4-C) — **기하가 굳는 자리**다.
 *
 * `DesignSurfacePanel` 과 형태는 같지만(등록 폼 + 목록) 규율이 하나 더 있다:
 * **수정 버튼이 없다.** 잘못 그린 구역은 고치는 게 아니라 새로 등록하고
 * `supersedes` 로 이전 것을 가리킨다 — 제자리 수정을 허용하면 이미 그 구역으로
 * 낸 리포트가 가리키는 범위가 사후에 바뀐다. 화면에서 "다시 그리기"가 폼을 여는
 * 것이지 그 구역을 여는 게 아닌 이유가 그것이다.
 *
 * 폴링이 없다 — 등록·보관 응답이 곧 최종 상태다(뒤에서 도는 계산이 없다).
 * 딱 한 자리만 예외로 목록을 다시 읽는다: **대체 등록**은 새 구역 생성과 이전
 * 구역 보관, 두 건을 한 번에 바꾸는데 응답은 앞의 것만 싣고 온다. 뒤의 것을
 * 화면이 짐작해서 칠하면 서버 규칙을 여기에 복제하는 셈이라, 짐작 대신 읽는다.
 */

/**
 * 정정 실패 시 다음 행동 안내 — `toDisplayVertices` 의 reason(기하·CRS 사실)에
 * 이 호출자가 덧붙인다. 읽기 전용 미리보기는 reason만 그대로 보여준다.
 */
const CORRECTION_RETRY_HINT =
  "대신할 범위를 처음부터 그려 주세요. (원래 구역은 그대로 남아 있습니다.)";

function WorkAreaCard({
  area,
  canWrite,
  archiving,
  disabled,
  correcting,
  previewOpen,
  previewResult,
  onTogglePreview,
  onCorrect,
  onArchive,
}: {
  area: WorkArea;
  canWrite: boolean;
  /** 이 구역의 보관 요청이 진행 중인가. */
  archiving: boolean;
  /** 다른 요청이 진행 중이라 지금은 누를 수 없는가. */
  disabled: boolean;
  /** 지금 위 폼이 이 구역을 대신할 새 구역을 그리는 중인가. */
  correcting: boolean;
  /** 이 구역의 읽기 전용 미리보기를 펼쳤는가(작은 화면에서도 열린다). */
  previewOpen: boolean;
  /** 열린 미리보기의 표시 변환 결과 — null이면 아직 고르지 않은 상태다. */
  previewResult: DisplayVerticesResult | null;
  onTogglePreview: (area: WorkArea) => void;
  onCorrect: (area: WorkArea) => void;
  onArchive: (area: WorkArea) => void;
}) {
  const status = WORK_AREA_STATUS_LABEL[area.status];
  const vertexCount = polygonToVertices(area.polygon).length;

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold break-keep">{area.name}</span>
        <StateBadge label={status.label} tone={status.tone} />
      </div>

      <p className="text-[12px] break-keep text-ink-2">{status.description}</p>

      <details className="text-[12px] text-ink-2">
      <summary className="tap-target cursor-pointer">구역 등록 정보</summary>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px] sm:grid-cols-4">
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">기술 참조</dt>
          <dd className="num break-token font-mono text-[10.5px] text-ink-muted">{area.workAreaId}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">등록</dt>
          <dd className="num">{formatKoreanDateTime(area.createdAt)}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">좌표계</dt>
          <dd className="num break-token">{area.crs}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">꼭짓점</dt>
          <dd className="num">{vertexCount > 0 ? `${vertexCount}개` : "읽지 못함"}</dd>
        </div>
      </dl>

      {area.supersedes !== null && (
        <p className="text-[11.5px] break-keep text-ink-muted">
          이전 구역을 대신해 등록된 구역입니다 — 기술 참조 ·{" "}
          <span className="num break-token font-mono text-[10.5px]">{area.supersedes}</span>
        </p>
      )}

      </details>

      {/* 읽기 전용 미리보기 — 카드마다 지도를 두지 않고, 고른 구역 하나만 펼친다.
          작은 화면에서도 열리므로 현장에서 "어디 범위인지"를 먼저 확인할 수 있다. */}
      <button
        type="button"
        className="btn w-fit"
        aria-expanded={previewOpen}
        onClick={() => onTogglePreview(area)}
      >
        {previewOpen ? "구역 범위 접기" : "구역 범위 보기"}
      </button>
      {previewOpen &&
        (previewResult !== null && previewResult.ok ? (
          <AoiPolygonMap readOnly value={previewResult.vertices} />
        ) : (
          <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] break-keep text-ink-2">
            {previewResult !== null && !previewResult.ok
              ? previewResult.reason
              : "이 구역의 모양을 지도에 올리지 못했습니다."}
          </p>
        ))}

      {/* 변경 행동(다시 그리기·보관)은 노트북 이상의 화면에서만 — 작은 화면에서는
          위 미리보기와 목록 위 인계 안내만 남는다. 안내는 카드마다 두지 않고
          목록 위 `ResponsiveNotice` 하나로 둔다. */}
      {canWrite && area.status === "ACTIVE" && (
        <ResponsiveActionBoundary
          action="SITE_DEVICE_TRANSITION"
          inlineNotice={false}
          reason="작업구역 변경은 노트북 이상의 화면에서 진행합니다."
        >
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn w-fit"
              disabled={disabled || correcting}
              onClick={() => onCorrect(area)}
            >
              {correcting ? "위 폼에서 그리는 중…" : "범위 바꾸기(새 구역)"}
            </button>
            <button
              type="button"
              className="btn btn-danger w-fit"
              disabled={disabled}
              onClick={() => onArchive(area)}
            >
              {archiving ? "보관하는 중…" : "구역 보관"}
            </button>
          </div>
        </ResponsiveActionBoundary>
      )}
    </li>
  );
}

export function WorkAreaPanel({
  siteId,
  siteCrs,
  canWrite,
  initialWorkAreas,
  workAreaListError,
}: {
  siteId: string;
  /** 현장에 등록된 좌표계 — 참고로만 적는다. 지도가 내는 좌표는 항상 WGS84 경위도다. */
  siteCrs: string;
  canWrite: boolean;
  initialWorkAreas: WorkArea[];
  workAreaListError: {
    message: string;
    tone: "crit" | "high" | "idle";
    retryable: boolean;
    retryAfterSeconds?: number;
  } | null;
}) {
  const [workAreas, setWorkAreas] = useState<WorkArea[]>(initialWorkAreas);
  const [name, setName] = useState("");
  const [vertices, setVertices] = useState<AoiVertex[]>([]);
  /** null 이 아니면 "이 구역을 대신할 새 구역"을 그리는 중이다(제출 시 supersedes). */
  const [correcting, setCorrecting] = useState<WorkArea | null>(null);
  /**
   * 정정 폼이 기존 구역의 모양을 지도에 올려 두었는가.
   *
   * `toDisplayVertices` 가 실패하면(알 수 없는 기하·좌표계) 폼은 빈 지도에서
   * 새로 그리는 자리가 된다 — 원래 구역은 그대로 남아 있고, "그만두기"로
   * unrelated 새 구역 등록으로 돌아갈 수 있다.
   */
  const [correctionReady, setCorrectionReady] = useState(false);
  /** 읽기 전용 미리보기를 펼친 구역 — 한 번에 하나만(카드마다 지도를 두지 않는다). */
  const [previewId, setPreviewId] = useState<string | null>(null);
  /**
   * 지도를 통째로 다시 마운트하기 위한 열쇠.
   *
   * `AoiPolygonMap` 의 그리기 컨트롤은 **마운트 시점의 value 만** 초기값으로 읽는다
   * (`AoiPolygonMapInner` 의 DrawControl). 그래서 상태만 갈아끼우면 지도에 이미
   * 그려진 폴리곤이 그대로 남는다 — 폼을 비우거나 기존 구역을 불러올 때는 이 값을
   * 올려 지도를 새로 태운다.
   */
  const [mapKey, setMapKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { active, archived } = useMemo(() => partitionWorkAreas(workAreas), [workAreas]);
  const busy = submitting || archivingId !== null;
  const previewResult = useMemo<DisplayVerticesResult | null>(() => {
    if (previewId === null) return null;
    const target = workAreas.find((area) => area.workAreaId === previewId) ?? null;
    if (target === null) return null;
    return toDisplayVertices(target.polygon, target.crs);
  }, [previewId, workAreas]);

  function togglePreview(area: WorkArea) {
    setPreviewId((current) => (current === area.workAreaId ? null : area.workAreaId));
  }

  function resetForm() {
    setName("");
    setVertices([]);
    setCorrecting(null);
    setCorrectionReady(false);
    setMapKey((key) => key + 1);
  }

  function startCorrection(area: WorkArea) {
    // U02 — 등록된 CRS 그대로 표시 변환한다. 투영좌표(m)를 위경도(°)로 잘못
    // 읽으면 지도가 수평선이 되고, 사용자는 엉뚱한 범위를 고쳐 그리게 된다.
    // 변환이 안 되면 빈 지도에서 새로 그린다 — 원래 구역은 그대로 남는다.
    //
    // 다음 행동 안내는 여기서 붙인다. 헬퍼의 reason은 읽기 전용 미리보기와
    // 공유하는 기하·CRS 사실이므로, "다시 그리기" 문구는 이 호출자의 몫이다.
    const display = toDisplayVertices(area.polygon, area.crs);
    setCorrecting(area);
    setName(area.name);
    if (display.ok) {
      setVertices(display.vertices);
      setCorrectionReady(true);
      setError(null);
    } else {
      setVertices([]);
      setCorrectionReady(false);
      setError(`${display.reason} ${CORRECTION_RETRY_HINT}`);
    }
    setMapKey((key) => key + 1);
    setNotice(null);
  }

  async function refreshList(): Promise<WorkArea[] | null> {
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas?include_archived=true`,
      );
      if (!response.ok) return null;
      const body = await parseJsonSafe<WorkAreaListResponse>(response);
      return body.workAreas ?? null;
    } catch {
      return null;
    }
  }

  async function handleSubmit() {
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("이름을 적으세요 — 이후 비교에서 이 이름으로 구역을 고릅니다.");
      return;
    }
    const polygon = toZonePolygon(vertices);
    if (polygon === null) {
      setError("꼭짓점을 3개 이상 찍어야 구역이 됩니다.");
      return;
    }

    const supersedes = correcting?.workAreaId ?? null;
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmed,
          polygon,
          // 지도가 내는 좌표는 WGS84 경위도다 — 현장 좌표계(siteCrs)로 적으면
          // 서버가 그 좌표계로 읽어 구역이 엉뚱한 곳에 놓인다.
          //
          // CRS 선택 기록: 대체 등록도 WGS84로 낸다. 지도 출력을 원래 구역의
          // 투영좌표계로 되돌리면 이중 변환 오차가 들어가고, 원래 구역·CRS는
          // supersede+보관으로 그대로 남으므로 되돌릴 이유가 없다.
          crs: COMPARISON_ZONE_CRS,
          supersedes,
        }),
      });
      const body = await parseJsonSafe<WorkAreaResponse>(response);
      const created = body.workArea;
      if (!response.ok || !created) {
        setError(readableApiError(body, "작업구역 등록에 실패했습니다"));
        return;
      }

      let list: WorkArea[] | null = null;
      let message = `작업구역을 등록했습니다: "${created.name}" — 이제 비교할 때 이 구역을 고를 수 있습니다.`;
      if (supersedes !== null) {
        // 대체 등록은 두 건을 바꾼다(새 구역 생성 + 이전 구역 보관). 응답은 앞의
        // 것만 싣고 오므로 뒤의 것은 짐작하지 않고 목록을 다시 읽는다.
        list = await refreshList();
        message =
          list === null
            ? `새 구역을 등록했습니다: "${created.name}" — 다만 이전 구역이 보관됐는지는 확인하지 못했습니다(목록을 다시 읽지 못했습니다). 화면을 새로고침하면 확인할 수 있습니다.`
            : `새 구역을 등록하고 이전 구역을 보관했습니다: "${created.name}" — 이미 낸 리포트는 이전 구역의 범위를 그대로 가리킵니다.`;
      }

      setWorkAreas(
        (prev) => list ?? [created, ...prev.filter((a) => a.workAreaId !== created.workAreaId)],
      );
      setNotice(message);
      resetForm();
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleArchive(area: WorkArea) {
    setArchivingId(area.workAreaId);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(area.workAreaId)}/archive`,
        { method: "POST" },
      );
      const body = await parseJsonSafe<WorkAreaResponse>(response);
      const updated = body.workArea;
      if (!response.ok || !updated) {
        setError(readableApiError(body, "작업구역 보관에 실패했습니다"));
        return;
      }
      setWorkAreas((prev) =>
        prev.map((a) => (a.workAreaId === updated.workAreaId ? updated : a)),
      );
      setNotice(
        `보관했습니다: "${updated.name}" — 새 비교에서 고를 수 없게 됐을 뿐, 이미 낸 리포트는 그대로입니다.`,
      );
      // 그 구역을 대신할 새 구역을 그리던 중이었다면 그 폼은 의미를 잃는다.
      if (correcting?.workAreaId === updated.workAreaId) resetForm();
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setArchivingId(null);
    }
  }

  const canSubmit = canWrite && !busy && name.trim() !== "" && vertices.length >= 3;

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <p
          role="alert"
          className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink"
        >
          {error}
        </p>
      )}

      {notice && (
        <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-2">
          {notice}
        </p>
      )}

      {/* U03 — 변경 행동의 작은 화면 인계는 이 하나로 둔다. 등록 폼과 카드
          버튼은 아래 `SITE_DEVICE_TRANSITION` 경계 안에 있어 작은 화면에서
          가려지고, 목록·미리보기는 읽기 전용으로 남는다. */}
      {canWrite && (
        <ResponsiveNotice
          action="SITE_DEVICE_TRANSITION"
          reason="작업구역 등록·다시 그리기·보관은 노트북 이상의 화면에서 진행합니다. 작은 화면에서는 아래 목록에서 범위를 확인한 뒤, 노트북에서 같은 현장 화면을 열어 이어가세요."
        />
      )}

      {canWrite ? (
        <ResponsiveActionBoundary
          action="SITE_DEVICE_TRANSITION"
          inlineNotice={false}
          reason="작업구역 등록과 다시 그리기는 노트북 이상의 화면에서 진행합니다."
        >
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h2 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
            {correcting ? "구역 다시 그리기" : "새 작업구역 등록"}
          </h2>

          {correcting ? (
            <div className="flex flex-col gap-2 rounded-md border border-dashed border-line-strong bg-sunk px-3 py-2">
              <p className="text-[12.5px] break-keep text-ink-2">
                <strong className="font-bold">{correcting.name}</strong>을 대신할 새 구역을
                그립니다 —{" "}
                {correctionReady
                  ? "지도에 그 구역의 지금 모양을 올려 두었습니다."
                  : "그 구역의 모양을 지도에 올리지 못해 빈 지도에서 새로 그립니다(원래 구역은 그대로 남아 있습니다)."}
                등록하면 새 구역이 생기고 이전 구역은 자동으로 보관되며,{" "}
                <strong className="font-bold">이미 낸 리포트는 이전 구역의 범위를 그대로</strong>{" "}
                가리킵니다.
              </p>
              <button
                type="button"
                className="btn w-fit"
                disabled={busy}
                onClick={() => {
                  resetForm();
                  setError(null);
                }}
              >
                그만두고 새 구역으로 등록
              </button>
            </div>
          ) : (
            <p className="text-[12.5px] break-keep text-ink-muted">
              이름을 붙여 등록해 두면 이후 비교마다 이 구역을 고르기만 하면 됩니다.{" "}
              <strong className="font-bold">등록한 모양은 고칠 수 없습니다</strong> — 잘못
              그렸으면 목록에서 &ldquo;다시 그리기&rdquo;로 대신할 구역을 등록하세요.
            </p>
          )}

          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              이름 — 현장에서 부르는 말로 적으세요(예: 3공구 성토부)
            </span>
            <input
              className="input"
              value={name}
              disabled={busy}
              placeholder="3공구 성토부"
              onChange={(event) => setName(event.target.value)}
            />
          </label>

          <div className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              범위 — 지도에서 폴리곤을 그리세요(꼭짓점 3개 이상)
            </span>
            <AoiPolygonMap key={mapKey} value={vertices} onChange={setVertices} />
            <span className="text-[11.5px] break-keep text-ink-muted">
              {vertices.length >= 3
                ? `꼭짓점 ${vertices.length}개 — 이 모양으로 굳습니다.`
                : "아직 구역이 되지 않았습니다 — 꼭짓점을 3개 이상 찍으세요."}{" "}
              좌표는 위경도(<span className="num">{COMPARISON_ZONE_CRS}</span>)로 저장됩니다
              (현장 등록 좌표계는 <span className="num break-token">{siteCrs}</span>입니다).
            </span>
          </div>

          <button
            type="button"
            className="btn btn-primary w-fit"
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {submitting ? "등록하는 중…" : correcting ? "대신할 구역으로 등록" : "등록"}
          </button>
        </section>
        </ResponsiveActionBoundary>
      ) : (
        <p className="text-[12.5px] break-keep text-ink-muted">
          작업구역을 등록하거나 보관하려면 현장 등록 권한(SITES_WRITE)이 필요합니다. 아래
          목록은 읽기 전용입니다.
        </p>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-bold break-keep">사용 중인 작업구역</h2>
          <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
            {workAreaListError ? "확인할 수 없음" : `${active.length}건`}
          </span>
        </div>

        {workAreaListError ? (
          <ErrorState
            message={workAreaListError.message}
            tone={workAreaListError.tone}
            retryable={workAreaListError.retryable}
            retryAfterSeconds={workAreaListError.retryAfterSeconds}
          />
        ) : active.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-8 text-center text-[13px] break-keep text-ink-muted">
            {canWrite
              ? "아직 등록된 작업구역이 없습니다. 위 지도에서 이름과 범위를 정해 등록하세요."
              : "이 현장에 등록된 작업구역이 없습니다. 현장 담당자에게 구역 등록을 요청하세요."}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {active.map((area) => (
              <WorkAreaCard
                key={area.workAreaId}
                area={area}
                canWrite={canWrite}
                archiving={archivingId === area.workAreaId}
                disabled={busy}
                correcting={correcting?.workAreaId === area.workAreaId}
                previewOpen={previewId === area.workAreaId}
                previewResult={previewId === area.workAreaId ? previewResult : null}
                onTogglePreview={togglePreview}
                onCorrect={startCorrection}
                onArchive={(target) => void handleArchive(target)}
              />
            ))}
          </ul>
        )}
      </section>

      {archived.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-[15px] font-bold break-keep">보관된 작업구역</h2>
            <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
              {archived.length}건
            </span>
          </div>
          <p className="text-[12.5px] break-keep text-ink-muted">
            보관은 삭제가 아닙니다 — 새 비교에서 고를 수 없게 될 뿐, 이 구역으로 이미 낸
            리포트는 그대로 남아 그때의 범위를 가리킵니다.
          </p>
          <ul className="flex flex-col gap-2">
            {archived.map((area) => (
              <WorkAreaCard
                key={area.workAreaId}
                area={area}
                canWrite={canWrite}
                archiving={false}
                disabled={busy}
                correcting={false}
                previewOpen={previewId === area.workAreaId}
                previewResult={previewId === area.workAreaId ? previewResult : null}
                onTogglePreview={togglePreview}
                onCorrect={startCorrection}
                onArchive={(target) => void handleArchive(target)}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
