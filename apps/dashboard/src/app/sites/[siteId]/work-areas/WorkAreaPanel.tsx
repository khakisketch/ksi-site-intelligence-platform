"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AoiPolygonMap, type AoiMapPendingState, type AoiRawSnapshot } from "@/components/map/AoiPolygonMap";
import {
  ResponsiveActionBoundary,
  ResponsiveNotice,
} from "@/components/responsive/ResponsiveActionBoundary";
import { workAreaUuid } from "./work-area-uuid";
import { readArchiveJournal, appendArchiveAttempt, settleArchiveAttempt, type ArchiveAttempt } from "./work-area-archive-journal";
import { readEpisodeJournal, ensureFirstArchived, firstMigrationId, appendAttempt, settleAttempt } from "./work-area-episode-journal";
import { readEditDraft, readEditDraftRaw, writeEditDraft, readFirstSubmission, writeFirstSubmission, clearFirstSubmission, type EditDraft } from "./work-area-session-storage";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/ToastProvider";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { COMPARISON_ZONE_CRS, toZonePolygon } from "@/lib/comparison-submit";
import { readableApiError } from "@/lib/core-api/labels";
import { parseJsonSafe } from "@/lib/http";
import { formatKoreanDateTime } from "@/lib/datetime";
import { toDisplayVertices, type DisplayVerticesResult } from "@/lib/geo/display-geometry";
import {
  WORK_AREA_STATUS_LABEL,
  classifyWorkAreaSubmitOutcome,
  parseWorkAreaList,
  partitionWorkAreas,
  polygonToVertices,
} from "@/lib/work-areas";
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
  archiveBlockedByDraft,
  correcting,
  previewOpen,
  previewResult,
  onTogglePreview,
  onCorrect,
  onArchive,
  archiveError,
}: {
  area: WorkArea;
  canWrite: boolean;
  /** 이 구역의 보관 요청이 진행 중인가. */
  archiving: boolean;
  /** 다른 요청이 진행 중이라 지금은 누를 수 없는가. */
  disabled: boolean;
  /** 미반영 지도 입력이 보관 대기 중 지도 리마운트로 사라지는 것을 막는다. */
  archiveBlockedByDraft: boolean;
  /** 지금 위 폼이 이 구역을 대신할 새 구역을 그리는 중인가. */
  correcting: boolean;
  /** 이 구역의 읽기 전용 미리보기를 펼쳤는가(작은 화면에서도 열린다). */
  previewOpen: boolean;
  /** 열린 미리보기의 표시 변환 결과 — null이면 아직 고르지 않은 상태다. */
  previewResult: DisplayVerticesResult | null;
  /** 이 구역의 보관 실패 메시지 — 해당 카드에만 둔다(한 복사본만). */
  archiveError: string | null;
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
          reason="작업구역 변경(다시 그리기·보관)은 노트북에서 같은 계정으로 이 현장의 ‘작업구역’ 화면을 열어 이어가세요. 작은 화면에서는 목록과 구역 범위 보기로 확인만 할 수 있습니다. 입력 중인 내용·임시 기록은 이 탭에만 있어 다른 기기로 이어지지 않습니다."
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
              disabled={disabled || archiveBlockedByDraft}
              onClick={() => onArchive(area)}
            >
              {archiving ? "보관하는 중…" : "구역 보관"}
            </button>
          </div>
          {archiveBlockedByDraft && (
            <p className="text-[12px] break-keep text-ink-2">
              입력 중인 경계를 반영하거나 되돌린 뒤 구역을 보관할 수 있습니다.
            </p>
          )}
        </ResponsiveActionBoundary>
      )}
      {archiveError && (
        <div
          role="alert"
          className="rounded-md bg-crit-bg px-3 py-2 text-[12px] break-keep text-crit-ink"
        >
          <p className="font-semibold leading-5">{archiveError}</p>
          <button
            type="button"
            className="btn mt-2 w-fit"
            disabled={disabled || archiveBlockedByDraft}
            onClick={() => onArchive(area)}
          >
            보관 다시 시도
          </button>
        </div>
      )}
    </li>
  );
}

/**
 * 서버 확인 계정 비교값 형식 — `@/lib/core-api/work-order-continuity`의
 * `FINGERPRINT_PATTERN` 과 같은 값이어야 한다. 공유 파일이 server-only라
 * 클라이언트에서 직접 import할 수 없어 미러로 둔다(일치는 pin 테스트가 고정).
 */
const CONTINUITY_FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;

/** 서버가 확인한 비교값이면 그대로, 아니면 null — 화면은 원문을 만들지 않는다. */
// Core archive changes only status; compare JSON values independent of object key order.
function sameJsonValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((value, index) => sameJsonValue(value, b[index]));
  }
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && sameJsonValue(left[key], right[key]));
}

function validArchiveEcho(body: Partial<WorkAreaResponse>, target: WorkArea, siteId: string): boolean {
  if (body.verdict !== "ARCHIVED" || target.siteId !== siteId) return false;
  const parsed = parseWorkAreaList({workAreas: [body.workArea]}, siteId);
  const returned = parsed?.[0];
  return !!returned && returned.status === "ARCHIVED" && returned.workAreaId === target.workAreaId &&
    typeof returned.schemaVersion === "string" && returned.schemaVersion !== "" && returned.schemaVersion === target.schemaVersion && returned.name === target.name && returned.crs === target.crs &&
    returned.createdAt === target.createdAt && returned.supersedes === target.supersedes && sameJsonValue(returned.polygon, target.polygon);
}

const ARCHIVE_UNKNOWN = "보관 결과를 확인하지 못했습니다. 서버에 도착해 보관됐을 수도 있습니다. 이전 요청의 결과는 다시 보내기 전에 목록에서 확인하세요. 목록은 조회 시점의 상태이며 요청의 최종 결과를 증명하지 않습니다.";

function validContinuityFingerprint(value: unknown): string | null {
  return typeof value === "string" && CONTINUITY_FINGERPRINT_PATTERN.test(value) ? value : null;
}

export function WorkAreaPanel({
  siteId,
  siteCrs,
  canWrite,
  initialWorkAreas,
  workAreaListError,
  accountIdentity = null,
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
  /**
   * 페이지 서버 렌더 시점에 확인한 계정 비교값. 명시적 재전송에만 싣는다.
   * null이면 재전송 보호를 걸 수 없으므로 재전송은 fail-closed(막힘)하고
   * 읽기(목록 확인)는 열어 둔다.
   */
  accountIdentity?: { fingerprint: string } | null;
}) {
  const [draftGate, setDraftGate] = useState<"checking" | "ready" | "failed">("checking");
  const [draftMounted, setDraftMounted] = useState(!canWrite);
  const [boundScope, setBoundScope] = useState<{siteId:string; identity:string; canWrite:boolean} | null>(null);
  const [draftMessage, setDraftMessage] = useState<string | null>(null);
  const [restoredSnapshot, setRestoredSnapshot] = useState<AoiRawSnapshot | undefined>();
  const draftIdentity = useRef<string | null>(null);
  const draftSite = useRef(siteId);
  const draftRef = useRef<EditDraft>({ name: "", vertices: [], correctionId: null, correctionReady: false, snapshot: null });
  const draftWritable = useRef(false);
  const draftStorageFailed = useRef(false);
  const archiveRecoveryRequired = useRef(false);
  const liveScope = useRef({ siteId, fingerprint: accountIdentity?.fingerprint, canWrite });
  liveScope.current = { siteId, fingerprint: accountIdentity?.fingerprint, canWrite };
  const identityEpoch = useRef(0);
  const identityActive = useRef(false);
  const identityVerified = useRef(false);
  const sensitiveRootRef = useRef<HTMLDivElement>(null);
  const recheckIdentity = useRef<(() => void) | null>(null);
  const firstSubmissionRaw = useRef<string | null>(null);
  function saveDraft(patch: Partial<EditDraft>) {
    draftRef.current = { ...draftRef.current, ...patch };
    mapBlockedRef.current = true;
    const identity = draftIdentity.current;
    if (!identity || !draftWritable.current) return;
    try {
      if (writeEditDraft(window.sessionStorage, siteId, identity, draftRef.current)) return;
    } catch { /* storage access can throw */ }
    draftWritable.current = false;
    draftStorageFailed.current = true;
    setDraftMessage("임시 저장에 실패했습니다. 기존 저장 내용은 유지되지만 현재 입력은 이동하면 사라질 수 있습니다.");
  }
  const initialAreasRef = useRef(initialWorkAreas);
  useEffect(() => { initialAreasRef.current = initialWorkAreas; }, [initialWorkAreas]);
  const [workAreas, setWorkAreas] = useState<WorkArea[]>(initialWorkAreas);
  const [name, setName] = useState("");
  const [vertices, setVertices] = useState<AoiVertex[]>([]);
  // Persisted vertices bypass Leaflet's commit path. Until the same geometry
  // verdict used by the map is available, no restored boundary may be posted.
  const [recoveredGeometry, setRecoveredGeometry] = useState<"valid" | "checking" | "invalid">("valid");
  const recoveredGeometryRef = useRef<"valid" | "checking" | "invalid">("valid");
  const geometryGeneration = useRef(0);
  const syncMapPending = useRef<AoiMapPendingState>({blocked:false, reason:null});
  const committedChangePending = useRef(false);
  const rawPendingValidator = useRef<typeof import("@/components/map/AoiPolygonMapInner").computeKeyboardPending | null>(null);
  const refreshList = useCallback(async (): Promise<WorkArea[] | null> => {
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas?include_archived=true`,
      );
      if (!response.ok) return null;
      const body = await parseJsonSafe<WorkAreaListResponse>(response);
      // 깨진 본문·다른 현장 ID 항목으로는 화면을 갱신하지 않는다 — 틀린 목록이
      // "등록됐다"는 오판을 만든다.
      return parseWorkAreaList(body, siteId);
    } catch {
      return null;
    }
  }, [siteId]);

  useEffect(() => {
    let active = true;
    void import("@/components/map/AoiPolygonMapInner").then(module => {
      if (active) rawPendingValidator.current = module.computeKeyboardPending;
    }).catch(() => { /* Fail closed if the map verifier is unavailable. */ });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (draftRef.current.vertices === vertices) committedChangePending.current = false;
  }, [vertices]);
  function validateRecoveredGeometry(points: AoiVertex[]) {
    const ticket = ++geometryGeneration.current;
    if (points.length < 3) { recoveredGeometryRef.current = "valid"; setRecoveredGeometry("valid"); return; }
    recoveredGeometryRef.current = "checking"; setRecoveredGeometry("checking");
    void import("@/components/map/AoiPolygonMapInner").then(({evaluateRingGeometry}) => {
      if (ticket !== geometryGeneration.current) return;
      const valid = points.length <= 256 && evaluateRingGeometry(points, null).kind === "ok";
      recoveredGeometryRef.current = valid ? "valid" : "invalid";
      setRecoveredGeometry(recoveredGeometryRef.current);
    }).catch(() => {
      if (ticket !== geometryGeneration.current) return;
      recoveredGeometryRef.current = "invalid"; setRecoveredGeometry("invalid");
    });
  }
  function acceptMapVertices(next: AoiVertex[]) {
    // The map's explicit commit path validates before emitting this value.
    ++geometryGeneration.current;
    recoveredGeometryRef.current = "valid"; setRecoveredGeometry("valid");
    committedChangePending.current = true;
    saveDraft({ vertices: next }); setVertices(next);
  }

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
  const [archiveTarget, setArchiveTarget] = useState<WorkArea | null>(null);
  const [archiveError, setArchiveError] = useState<{ areaId: string; message: string } | null>(null);
  const archiveLock = useRef(false);
  const unconfirmedArchives = useRef(new Set<string>());
  const [archiveAttempts, setArchiveAttempts] = useState<ArchiveAttempt[]>([]);
  const [unconfirmedArchiveKeys, setUnconfirmedArchiveKeys] = useState<string[]>([]);
  const archiveReadLock = useRef(false);
  const [archiveReadMessage, setArchiveReadMessage] = useState<string | null>(null);
  const [archiveReceiptWarning, setArchiveReceiptWarning] = useState<string | null>(null);
  const [archiveReading, setArchiveReading] = useState(false);
  const { notify } = useToast();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /**
   * 결과 불명 제출의 원래 요청 보존 — 응답을 잃으면 서버에 닿았는지 알 수 있다.
   * 같은 내용을 다시 보내면 구역이 두 개 생길 수 있으므로, 입력은 그대로 두고
   * 이 패널에서만 다음 행동을 고르게 한다(자동 성공·같은 키 재시도 주장·이름/기하
   * 매칭 단정 금지). 명시적 재전송 뒤에도 첫 불명은 별도로 남긴다 — 두 번째
   * 요청의 성공이 첫 요청의 등록까지 증명하지 않으므로.
   *
   * `continuity` 는 첫 제출 화면을 서버 렌더한 시점에 확인한 계정 비교값이다.
   * 재전송에만 싣는다 — 다른 탭에서 계정을 바꾸면 BFF가 Core 호출 없이 끊어
   * 조용한 중복 생성을 막는다. 첫 POST에는 싣지 않는다(새 요청의 기존 계약).
   */
  const [unknownSubmission, setUnknownSubmission] = useState<{
    name: string;
    vertexCount: number;
    /**
     * 첫 POST에 실은 기하 원본 — 명시적 재전송도 이 값을 쓴다. 응답 유실 뒤
     * 지도가 바뀌어도 현재 입력으로 재구성하지 않는다(두 번째 요청의 성공이
     * 첫 요청의 등록을 증명하지 않으므로, 원본을 덮으면 무엇이 등록됐는지
     * 잃는다). 새 구역 재전송이 멱등이 아니라는 안내는 그대로 둔다.
     */
    polygon: Record<string, unknown>;
    /**
     * 첫 요청의 좌표 배열 스냅샷 — 대기·불명 화면의 읽기 전용 지도와 수량이
     * 전송 A를 표시하는 재료다. 재전송 본문(`polygon`)과 같은 원본의 다른
     * 모양일 뿐이며, 따로 추측·보정하지 않는다.
     */
    vertices: AoiVertex[];
    crs: string;
    supersedes: string | null;
    supersedesName: string | null;
    continuity: string | null;
  } | null>(null);
  /**
   * 제출 순간(첫 요청)의 입력 스냅샷 — 응답을 기다리는 동안 지도가 바뀌어도
   * 대기 화면의 읽기 전용 지도는 전송 A를 보여준다. 확정 실패·성공·초기화로
   * 풀리고, 불명 확정분은 `unknownSubmission.vertices`가 이어받는다.
   */
  const [frozenVertices, setFrozenVertices] = useState<AoiVertex[] | null>(null);
  /**
   * 지도 미반영·진행 중 상태 — `AoiPolygonMap`이 알린다. 기존 유효 `vertices`가
   * 있어도 이 값이 막히면 제출하지 않는다(미완성 B가 아닌 A가 나가는 일을
   * 막는 자리). transient UI 상태라 초안·서버에 두지 않는다.
   */
  const [mapPending, setMapPending] = useState<AoiMapPendingState>({
    blocked: false,
    reason: null,
  });
  /**
   * 이탈 확인 — 미반영 B(키보드 입력·포인터 진행 중)는 컴포넌트 로컬이라
   * 지도 리마운트(다른 구역으로 범위 바꾸기·그만두기)에 조용히 사라진다.
   * 기존 A·등록 구역은 보존되므로, 버리기 전에 명시적 확인을 받는다.
   * 계속 입력하기(취소) / 입력 버리고 이동하기(확정) 중 고르게 한다.
   */
  const [abandonConfirm, setAbandonConfirm] = useState<
    null | { action: "correct"; area: WorkArea } | { action: "reset" }
  >(null);
  const abandonRef = useRef<HTMLDivElement>(null);
  /**
   * 인라인 확인의 포커스 왕복 — 모달이 아니므로 배경을 비활성화하지 않는다.
   * 열리면 확인 영역으로, 닫히면 원래 버튼(취소)·바뀐 폼 제목(확정)으로 돌린다.
   * dialog 역할을 쓰지 않으므로 트랩·불활성화 의무가 없고, Esc는 취소다.
   */
  const invokerRef = useRef<HTMLElement | null>(null);
  const focusAfterCloseRef = useRef<HTMLElement | null>(null);
  const formHeadingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (abandonConfirm !== null) {
      abandonRef.current?.focus();
      return;
    }
    const target = focusAfterCloseRef.current;
    focusAfterCloseRef.current = null;
    target?.focus();
  }, [abandonConfirm]);
  // beforeunload는 리마운트와 무관하게 현재 막힘을 봐야 하므로 ref로 둔다.
  // 미반영 입력뿐 아니라 불명 원본(메모리 전용)도 새로고침·탭 닫기로 사라지므로
  // 함께 경고한다. 앱 내부 링크 이동은 App Router가 가로채 beforeunload가
  // 닿지 않으므로(전역 라우터 변경 없이 막을 수 없음) 잔여 한계로 남기고,
  // 위 확인 UI가 그 자리를 맡는다.
  const mapBlockedRef = useRef(false);
  // 새로고침·탭 닫기 때 미반영 B 손실을 브라우저에 확인시킨다. 앱 내부
  // 링크 이동은 App Router가 가로채 beforeunload가 닿지 않으므로(전역 라우터
  // 변경 없이 막을 수 없음) 잔여 한계로 남기고, 위 확인 UI가 그 자리를 맡는다.
  useEffect(() => {
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (!mapBlockedRef.current) return;
      event.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);
  /**
   * 확인값을 받지 못한 재전송 시도의 fail-closed 안내 — POST를 보내지 않는다.
   * 읽기(목록 확인)는 계속할 수 있다.
   */
  const [continuityBlocked, setContinuityBlocked] = useState<string | null>(null);
  /**
   * 명시적 새 요청(재전송)들의 결과 이력 — 첫 불명과 별개로 **빠짐없이** 기록한다.
   * 2차의 성공이 첫 요청의 등록까지 증명하지 않으므로, 3번째 이후 요청의 결과도
   * '둘'로 축소하지 않고 건수로 말한다. 해소됐다고 추측하지 않는다.
   */
  type RetryRecord =
    | { seq: number; kind: "success"; workAreaId: string; name: string }
    | { seq: number; kind: "failure"; message: string }
    | { seq: number; kind: "unknown" };
  const [retryHistory, setRetryHistory] = useState<RetryRecord[]>([]);
  /**
   * 화면을 떠나기 전 보관한 확인 기록 — '입력 비우고 새로 시작'해도 사라지지
   * 않는다. 확정된 등록 ID와 아직 불명인 요청 수를 묶음 단위로 남기며, 새 입력·
   * 다음 별도 요청과는 섞지 않는다. 다른 계정의 목록 접근 가능 여부나 원래
   * 요청의 성공은 추정하지 않으며, 이 기록은 화면 메모리에만 있어 새로고침·
   * 화면 이탈 시 사라진다.
   */
  interface ArchivedEpisode {
    /** 화면 내 묶음 번호 — 새 입력과 이전 이력을 섞지 않기 위한 구분자다. */
    episode: number;
    /** 그 묶음의 첫 요청 이름(원래 요청 식별용 메모, 소유권 증명이 아니다). */
    name: string;
    /** 그 묶음에서 서버 응답으로 확정된 등록. */
    confirmed: { workAreaId: string; name: string }[];
    /** 그 묶음에서 확인되지 않은 채 남긴 요청 수(첫 불명 + 불명 재전송). */
    unresolvedCount: number;
    /** 원래 전송 본문·계정 확인값과 그 후속 시도는 새 입력과 섞지 않고 보존한다. */
    original: NonNullable<typeof unknownSubmission> | null;
    retries: RetryRecord[];
  }
  const [episodeLog, setEpisodeLog] = useState<ArchivedEpisode[]>([]);
  const viewingEpisode = useRef<number | null>(null);
  const abandonLock = useRef(false);
  useEffect(() => { abandonLock.current = false; }, [unknownSubmission]);
  const loadArchived = useCallback((journal: Extract<ReturnType<typeof readEpisodeJournal>, {kind: "found"}>["journal"]): ArchivedEpisode[] => {
    return journal.episodes.map((entry, index) => {
      const first = entry.first;
      const body = JSON.parse(first.body) as {name:string; polygon:Record<string,unknown>; crs:string; supersedes:string | null};
      const retries: RetryRecord[] = entry.attempts.map((attempt, i) => {
        const outcome = attempt.outcome;
        if (outcome.kind === "success") return {seq:i+1, kind:"success", workAreaId:outcome.workAreaId, name:outcome.name};
        if (outcome.kind === "failure") return {seq:i+1, kind:"failure", message:outcome.message};
        return {seq:i+1, kind:"unknown"};
      });
      return {episode:index+1, name:body.name, confirmed:retries.filter((r):r is Extract<RetryRecord,{kind:"success"}> => r.kind === "success").map(r=>({workAreaId:r.workAreaId,name:r.name})), unresolvedCount:1+retries.filter(r=>r.kind === "unknown").length,
        original:{name:body.name,vertexCount:first.vertices.length,polygon:body.polygon,vertices:first.vertices,crs:body.crs,supersedes:body.supersedes,supersedesName:first.supersedesName,continuity:first.identity}, retries};
    });
  }, []);

  useEffect(() => {
    let active = true;
    let generation = 0;
    let loaded = false;
    let blurred = false;
    identityActive.current = true;
    identityVerified.current = false;
    const expected = validContinuityFingerprint(accountIdentity?.fingerprint);
    function concealNow() {
      const root = sensitiveRootRef.current;
      if (root) { root.hidden = true; root.style.display = "none"; }
    }
    function invalidate() {
      if (archiveLock.current) archiveRecoveryRequired.current = true;
      setArchiveTarget(null);
      ++generation;
      identityEpoch.current += 1;
      identityVerified.current = false;
      draftWritable.current = false;
      concealNow();
      setDraftGate("checking");
    }
    async function check() {
      concealNow();
      if (archiveLock.current) archiveRecoveryRequired.current = true;
      const ticket = ++generation;
      identityEpoch.current += 1;
      identityVerified.current = false;
      draftWritable.current = false;
      setDraftGate("checking");
      if (blurred || document.visibilityState === "hidden") return;
      try {
        const response = await fetch("/api/account-identity", { cache: "no-store" });
        const body = response.ok ? await response.json() : null;
        if (!active || ticket !== generation) return;
        if (!expected || validContinuityFingerprint(body?.fingerprint) !== expected ||
            (draftIdentity.current !== null && (draftIdentity.current !== expected || draftSite.current !== siteId))) throw new Error("identity");
        const archiveJournal = readArchiveJournal(window.sessionStorage, siteId, expected);
        if (archiveJournal.kind === "invalid" || archiveJournal.kind === "unavailable") throw new Error("archive storage");
        const savedAttempts = archiveJournal.kind === "found" ? archiveJournal.journal.attempts : [];
        setArchiveAttempts(savedAttempts);
        unconfirmedArchives.current = new Set(savedAttempts.filter(a => a.outcome === "pending").map(a => JSON.stringify([siteId, expected, a.area.workAreaId])));
        setUnconfirmedArchiveKeys(Array.from(unconfirmedArchives.current));
        if (archiveRecoveryRequired.current) {
          // A pending mutation may still commit after a GET: wait for it to settle,
          // then read under a fresh identity verification, never repeat the POST.
          if (archiveLock.current) return;
          const list = await refreshList();
          const verified = await fetch("/api/account-identity", { cache: "no-store" });
          const verifiedBody = verified.ok ? await verified.json() : null;
          if (!active || ticket !== generation) return;
          if (!list || validContinuityFingerprint(verifiedBody?.fingerprint) !== expected) throw new Error("archive recovery");
          setWorkAreas(list);
          archiveRecoveryRequired.current = false;
        }
        if (!loaded && canWrite) {
          const journal = readEpisodeJournal(window.sessionStorage, siteId, expected);
          if (journal.kind === "invalid" || journal.kind === "unavailable") throw new Error("episode storage");
          const pending = readFirstSubmission(window.sessionStorage, siteId, expected);
          if (pending.kind === "invalid" || pending.kind === "unavailable") throw new Error("submission storage");
          if (journal.kind === "found") {
            if (pending.kind === "found" && pending.record.version === 1 && journal.journal.episodes.some(entry => entry.first.version === 1 && entry.first.body === pending.record.body)) throw new Error("ambiguous legacy migration");
            if (pending.kind === "found" && pending.record.version === 2 && journal.journal.episodes.some(entry => entry.first.version === 2 && entry.first.requestId === pending.record.requestId && entry.sourceRaw !== pending.raw)) throw new Error("conflicting request identity");
            const archived = loadArchived(journal.journal);
            // 중단된 이관의 두 복사본은 하나의 요청이다. 원본은 유지하되
            // 이관 완료 전까지 기존 불명 패널에만 보인다.
            const moving = pending.kind === "found" ? firstMigrationId(pending.raw) : null;
            setEpisodeLog(archived.filter((_, index) => journal.journal.episodes[index]?.id !== moving));
            episodeId.current = archived.length;
          }
          if (pending.kind === "found") {
            const sent = JSON.parse(pending.record.body) as {name: string; polygon: Record<string, unknown>; crs: string; supersedes: string | null};
            firstSubmissionRaw.current = pending.raw;
            setUnknownSubmission({name: sent.name, vertexCount: pending.record.vertices.length, polygon: sent.polygon, vertices: pending.record.vertices, crs: sent.crs, supersedes: sent.supersedes, supersedesName: pending.record.supersedesName, continuity: expected});
            setFrozenVertices(pending.record.vertices);
          }
          const result = readEditDraft(window.sessionStorage, siteId, expected);
          if (result.kind !== "empty" && result.kind !== "found") throw new Error("storage");
          const movingEpisode = pending.kind === "found" && journal.kind === "found"
            ? journal.journal.episodes.find(entry => entry.id === firstMigrationId(pending.raw) && entry.sourceRaw === pending.raw)
            : undefined;
          const preservedDraft = movingEpisode?.sourceDraftRaw ? (JSON.parse(movingEpisode.sourceDraftRaw) as {payload: EditDraft}).payload : null;
          if (preservedDraft !== null || result.kind === "found") {
            const draft = preservedDraft ?? (result.kind === "found" ? result.draft : draftRef.current);
            const correction = draft.correctionId === null ? null : initialAreasRef.current.find(a => a.siteId === siteId && a.workAreaId === draft.correctionId) ?? null;
            if (draft.correctionId !== null && correction === null) throw new Error("correction");
            draftRef.current = draft;
            setName(draft.name);
            validateRecoveredGeometry(draft.vertices);
            setVertices(draft.vertices);
            setCorrecting(correction);
            setCorrectionReady(draft.correctionReady);
            setRestoredSnapshot(draft.snapshot ?? undefined);
            if (draft.snapshot) {
              syncMapPending.current = {blocked:true, reason:"복구한 원문을 확인하고 지도에 반영하거나 되돌리세요."};
              setMapPending(syncMapPending.current);
            }
          }
          loaded = true;
          setDraftMounted(true);
        }
        loaded = true;
        draftIdentity.current = expected;
        draftSite.current = siteId;
        setBoundScope({siteId, identity:expected, canWrite});
        identityVerified.current = true;
        draftWritable.current = canWrite && !draftStorageFailed.current;
        if (!draftStorageFailed.current) setDraftMessage(null);
        setDraftGate("ready");
        const root = sensitiveRootRef.current;
        if (root) { root.hidden = false; root.style.display = ""; }
      } catch (error) {
        if (!active || ticket !== generation) return;
        draftWritable.current = false;
        const ambiguous = error instanceof Error && (error.message === "ambiguous legacy migration" || error.message === "conflicting request identity");
        setDraftMessage(ambiguous ? "이전 요청 기록이 같은 요청인지 별도 요청인지 확인할 수 없어 입력을 잠갔습니다. 원본은 삭제하거나 덮어쓰지 않았습니다." : !canWrite ? "현재 계정을 확인하지 못했습니다. 기존 목록을 표시하지 않습니다." : loaded ? "현재 계정을 확인하지 못해 입력을 숨겼습니다. 저장된 원문은 변경하지 않았습니다." : "계정 또는 임시 저장 내용을 확인하지 못했습니다. 저장된 원문을 표시하거나 덮어쓰지 않습니다. 이 화면의 입력은 이동하면 사라질 수 있습니다.");
        setDraftGate("failed");
      }
    }
    function onFocus() { blurred = false; void check(); }
    function onBlur() { blurred = true; invalidate(); }
    function onVisibility() {
      if (document.visibilityState === "hidden") invalidate();
      else if (!blurred) void check();
    }
    recheckIdentity.current = () => { void check(); };
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibility);
    void check();
    return () => {
      if (archiveLock.current) archiveRecoveryRequired.current = true;
      active = false;
      recheckIdentity.current = null;
      ++generation;
      identityEpoch.current += 1;
      identityActive.current = false;
      identityVerified.current = false;
      draftWritable.current = false;
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [siteId, accountIdentity?.fingerprint, canWrite, loadArchived, refreshList]);
  useEffect(() => {
    // 새 입력으로 전환한 뒤에도 이 화면 안의 원래 요청과 확인 기록은
    // 메모리에만 있으므로 새로고침·탭 닫기 전에 계속 경고한다.
    mapBlockedRef.current = mapPending.blocked || name !== "" || vertices.length > 0 || unknownSubmission !== null || episodeLog.length > 0;
  }, [mapPending.blocked, name, vertices, unknownSubmission, episodeLog]);
  const episodeId = useRef(0);
  const [verifying, setVerifying] = useState(false);
  const [unknownVerifyMessage, setUnknownVerifyMessage] = useState<string | null>(null);
  /** 동기 single-flight — 연속 클릭이 2회 POST를 보내지 못하게 `submitting`
   *  state(비동기 반영)보다 먼저 동기 ref로 잠근다. */
  const submitLock = useRef(false);
  const { active, archived } = useMemo(() => partitionWorkAreas(workAreas), [workAreas]);
  const busy = submitting || archivingId !== null || archiveReading;
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
    ++geometryGeneration.current;
    recoveredGeometryRef.current = "valid"; setRecoveredGeometry("valid");
    syncMapPending.current = {blocked:false, reason:null};
    committedChangePending.current = false;
    saveDraft({ name: "", vertices: [], correctionId: null, correctionReady: false, snapshot: null });
    setRestoredSnapshot(undefined);
    setName("");
    setVertices([]);
    setCorrecting(null);
    setCorrectionReady(false);
    setFrozenVertices(null);
    // 지도도 함께 리마운트되므로 clean이 다시 보고되지만, 한 렌더라도
    // 낡은 막힘이나 이탈 확인이 남지 않게 여기서 즉시 푼다.
    setMapPending({ blocked: false, reason: null });
    setAbandonConfirm(null);
    setMapKey((key) => key + 1);
  }

  function requestCorrection(area: WorkArea) {
    // 미반영 B가 있으면 리마운트로 조용히 사라지므로 먼저 확인받는다.
    // 카드 버튼은 busy·불명 때 비활성화라 여기서는 미반영만 본다.
    if (mapPending.blocked) {
      invokerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setAbandonConfirm({ action: "correct", area });
      return;
    }
    startCorrection(area);
  }

  function requestResetForm() {
    if (mapPending.blocked) {
      invokerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setAbandonConfirm({ action: "reset" });
      return;
    }
    confirmResetForm();
  }

  function confirmResetForm() {
    resetForm();
    setError(null);
  }

  function resolveAbandon(proceed: boolean) {
    const target = abandonConfirm;
    setAbandonConfirm(null);
    if (!proceed || target === null) {
      focusAfterCloseRef.current = invokerRef.current;
      invokerRef.current = null;
      return;
    }
    focusAfterCloseRef.current = formHeadingRef.current;
    invokerRef.current = null;
    if (target.action === "correct") startCorrection(target.area);
    else confirmResetForm();
  }

  function startCorrection(area: WorkArea) {
    // U02 — 등록된 CRS 그대로 표시 변환한다. 투영좌표(m)를 위경도(°)로 잘못
    // 읽으면 지도가 수평선이 되고, 사용자는 엉뚱한 범위를 고쳐 그리게 된다.
    // 변환이 안 되면 빈 지도에서 새로 그린다 — 원래 구역은 그대로 남는다.
    //
    // 다음 행동 안내는 여기서 붙인다. 헬퍼의 reason은 읽기 전용 미리보기와
    // 공유하는 기하·CRS 사실이므로, "다시 그리기" 문구는 이 호출자의 몫이다.
    const display = toDisplayVertices(area.polygon, area.crs);
    validateRecoveredGeometry(display.ok ? display.vertices : []);
    saveDraft({ name: area.name, correctionId: area.workAreaId, correctionReady: display.ok, vertices: display.ok ? display.vertices : [], snapshot: null });
    setRestoredSnapshot(undefined);
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


  async function handleSubmit(options?: { explicitRetry?: boolean }) {
    const snapshot = draftRef.current.snapshot;
    let rawBlocked = false;
    if (snapshot !== null) {
      try {
        rawBlocked = snapshot.rejectedDraws.length > 0 || rawPendingValidator.current === null ||
          rawPendingValidator.current(snapshot.rows, draftRef.current.vertices).blocked;
      } catch { rawBlocked = true; }
    }
    if (!options?.explicitRetry && (syncMapPending.current.blocked || committedChangePending.current || rawBlocked || recoveredGeometryRef.current !== "valid")) {
      setError("입력한 경계를 확인하고 지도에 반영하거나 되돌린 뒤 등록하세요. 원본은 그대로 남아 있습니다.");
      return;
    }
    // 명시적 재전송은 첫 요청의 동결 원본으로만 보낸다 — 응답 유실 뒤 지도가
    // 바뀌어도 현재 입력으로 재구성하지 않는다(두 번째 요청의 성공이 첫 요청의
    // 등록을 증명하지 않으므로 원본을 덮으면 무엇이 등록됐는지 잃는다).
    // UI 경로상 재전송은 불명 패널이 열렸을 때만 가능하므로 원본이 없으면
    // 보내지 않는다.
    const retrySource = options?.explicitRetry === true ? unknownSubmission : null;
    if (options?.explicitRetry === true && retrySource === null) return;
    // 재전송은 동결 원본 그대로, 첫 요청은 현재 입력의 스냅샷으로 고정한다 —
    // 응답 대기·유실 뒤 입력이 바뀌어도 원본이 오염되지 않는다. null 자체도
    // 원본이면 그대로 보존한다(`??`로 현재값에 떨어뜨리지 않는다).
    const snapshotVertices: AoiVertex[] = retrySource
      ? retrySource.vertices
      : vertices.map((v) => ({ ...v }));
    const trimmed = (retrySource?.name ?? name).trim();
    if (trimmed === "") {
      setError("이름을 적으세요 — 이후 비교에서 이 이름으로 구역을 고릅니다.");
      return;
    }
    const polygon = retrySource?.polygon ?? toZonePolygon(snapshotVertices);
    if (polygon === null) {
      setError("꼭짓점을 3개 이상 찍어야 구역이 됩니다.");
      return;
    }

    const supersedes = retrySource ? retrySource.supersedes : (correcting?.workAreaId ?? null);
    const supersedesName = retrySource ? retrySource.supersedesName : (correcting?.name ?? null);
    // 모든 변이 POST는 첫 화면에서 확인한 계정 확인값을 싣는다. 첫 POST도 예외가
    // 아니다 — 페이지 렌더 뒤 다른 탭에서 계정을 바꾸면 그 POST는 새 계정으로
    // Core에 기록되지만 prop은 옛 계정 그대로라, 무헤더로 보내면 불명 기록이
    // 엉뚱한 계정에 묶인다. BFF가 같은 토큰으로 확인값·현재 세션을 대조해
    // 다르면 Core 호출 없이 끊는다. 확인할 값이 없으면 보내지 않고 fail-closed로
    // 안내한다(읽기는 계속할 수 있다).
    const continuity =
      retrySource !== null
        ? (retrySource.continuity ?? null)
        : validContinuityFingerprint(accountIdentity?.fingerprint);
    // 결과 불명 패널에서 "새 요청으로 다시 등록"을 누른 경우가 아니면, 불명이
    // 해소되지 않은 채 위 등록 버튼으로 다시 들어올 수 없게 막는다(canSubmit).
    // 그래도 코드 경로로 들어오면 같은 취지로 경고한다.
    if (unknownSubmission !== null && !options?.explicitRetry) return;
    if (continuity === null) {
      // 계정 확인값을 받지 못했다 — 보호 없이 보낼 수 없으므로 POST하지 않는다.
      // 이번 요청이 서버에 닿지 않았으므로 '결과 불명'이 아니라 미전송이다.
      if (options?.explicitRetry) {
        setContinuityBlocked(
          "계정 확인값을 받지 못해 재전송 보호 없이 보낼 수 없습니다. 같은 내용을 " +
            "지금 보내면 계정이 바뀌었을 때 중복이 생길 수 있습니다. 화면을 새로고침해 " +
            "서버에서 확인값을 다시 받은 뒤 목록을 먼저 확인하세요. 새로고침하면 입력 중인 " +
            "내용과 이 화면의 기록이 사라집니다. 목록 읽기는 계속할 수 있습니다.",
        );
      } else {
        setError(
          "계정 확인값을 받지 못해 등록을 보낼 수 없습니다. 같은 내용을 지금 보내면 " +
            "계정이 바뀌었을 때 중복이 생길 수 있습니다. 화면을 새로고침해 서버에서 " +
            "확인값을 다시 받은 뒤 목록을 먼저 확인하세요. 새로고침하면 입력 중인 " +
            "내용이 사라집니다. 목록 읽기는 계속할 수 있습니다.",
        );
      }
      return;
    }
    // 초안 저장 실패 상태에서는 추가 전송을 막는다. 전송 본문은 아래에서
    // 별도 기록에 저장하고 확인한 뒤에만 보낸다.
    let draftSaved = false;
    if (draftWritable.current && !draftStorageFailed.current && draftIdentity.current === continuity) {
      try { draftSaved = writeEditDraft(window.sessionStorage, siteId, continuity, draftRef.current); } catch { /* unavailable */ }
    }
    if (!draftSaved) {
      draftWritable.current = false;
      draftStorageFailed.current = true;
      setDraftMessage("임시 저장을 확인하지 못해 요청을 보내지 않았습니다. 현재 화면의 입력을 유지하고, 이동 전 따로 확인하세요.");
      return;
    }
    if (options?.explicitRetry) {
      setContinuityBlocked("재전송 기록의 복구는 아직 지원하지 않아 새 요청을 보내지 않습니다. 목록에서 먼저 확인하세요.");
      return;
    }
    if (retryHistory.length > 0) {
      setError("이전 요청 기록을 보존한 채 새 요청을 저장하는 기능은 아직 지원하지 않아 보내지 않았습니다.");
      return;
    }
    if (submitLock.current) return;
    submitLock.current = true;
    const requestBody = JSON.stringify({ name: trimmed, polygon, crs: COMPARISON_ZONE_CRS, supersedes });
    // 새 요청은 본문이 같아도 독립적인 식별자를 가진다. 기존 저널을
    // 먼저 검증하고 식별자 충돌 시에는 전송하지 않는다.
    let requestId: string;
    try {
      requestId = workAreaUuid();
      const journal = readEpisodeJournal(window.sessionStorage, siteId, continuity);
      if (journal.kind === "invalid" || journal.kind === "unavailable" ||
          (journal.kind === "found" && journal.journal.episodes.some(e => (e.first.version === 2 && e.first.requestId === requestId) || e.attempts.some(attempt => attempt.id === requestId)))) {
        submitLock.current = false;
        setError("이전 요청 기록이나 새 요청 식별자를 확인하지 못해 보내지 않았습니다.");
        return;
      }
    } catch {
      submitLock.current = false;
      setError("요청 식별자 또는 이전 기록을 확인하지 못해 새 요청을 보내지 않았습니다.");
      return;
    }
    let writeAhead: string | null = null;
    try {
      writeAhead = writeFirstSubmission(window.sessionStorage, {version: 2, requestId, siteId, identity: continuity, body: requestBody, vertices: snapshotVertices, supersedesName});
    } catch { /* unavailable */ }
    if (writeAhead === null) {
      submitLock.current = false;
      setError("첫 요청의 임시 기록을 저장하지 못했거나 이전 요청 기록이 남아 있어 보내지 않았습니다. 입력과 기존 기록을 확인하세요.");
      return;
    }
    firstSubmissionRaw.current = writeAhead;
    const submitIdentityEpoch = identityEpoch.current;
    const canHandleResult = () => identityActive.current && identityVerified.current &&
      identityEpoch.current === submitIdentityEpoch && draftIdentity.current === continuity;
    const retainAsUnknown = () => {
      if (identityActive.current) {
        setUnknownSubmission({name: trimmed, vertexCount: snapshotVertices.length, polygon, vertices: snapshotVertices, crs: COMPARISON_ZONE_CRS, supersedes, supersedesName, continuity});
        setRetryHistory([]);
      }
    };
    // 첫 요청만 동결한다 — 재전송은 이미 동결된 원본을 쓴다. 확인값이 없어
    // 미전송으로 끝날 때는 동결하지 않는다(위에서 반환됐다).
    if (!retrySource) setFrozenVertices(snapshotVertices);
    // 동기 single-flight — 같은 tick의 연속 클릭도 두 번째는 여기서 끊는다.
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setContinuityBlocked(null);
    if (!options?.explicitRetry) {
      setUnknownVerifyMessage(null);
    }
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        // 첫 POST·재전송 모두 원래 화면 계정의 확인값을 싣는다. BFF가 같은
        // 요청 토큰으로 현재 세션과 대조해 다르면 Core 호출 없이 끊는다.
        "x-ksi-continuity-fingerprint": continuity,
      };
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas`, {
        method: "POST",
        headers,
        body: requestBody,
      });
      const body = await parseJsonSafe<WorkAreaResponse>(response);
      const outcome = classifyWorkAreaSubmitOutcome({
        fetchThrew: false,
        status: response.status,
        body,
        siteId,
        request: { name: trimmed, crs: COMPARISON_ZONE_CRS, polygon, supersedes },
      });
      // 대체 등록의 추가 목록 조회도 비동기다. 완료 뒤 동일한 화면과
      // 신원을 다시 확인한 다음에만 원래 write-ahead를 정리한다.
      if (!canHandleResult()) { retainAsUnknown(); return; }
      const successList = outcome.kind === "success" && supersedes !== null ? await refreshList() : null;
      // 응답을 받을 당시 화면과 신원 확인 세대가 그대로여야 결과를 화면에
      // 전달하고 기록을 정리할 수 있다. 그 밖에는 원본을 보수적으로 남긴다.
      if (!canHandleResult()) { retainAsUnknown(); return; }
      if (outcome.kind !== "unknown") {
        let cleared = false;
        try { cleared = clearFirstSubmission(window.sessionStorage, siteId, continuity, writeAhead); } catch { /* keep record */ }
        if (cleared) firstSubmissionRaw.current = null;
        else setDraftMessage("요청 결과를 받았지만 임시 요청 기록을 정리하지 못했습니다. 재진입 시 불명으로 표시될 수 있으니 목록을 확인하세요.");
      }
      if (outcome.kind === "success" && !options?.explicitRetry) {
        applySuccessfulRegistration(outcome.workArea, supersedes, successList);
        return;
      }
      if (outcome.kind === "success") {
        // 명시적 재전송의 성공 — 첫 불명은 해소되지 않았다. 재전송 기록에 남기고
        // 건수로 말한다('둘'로 축소 금지). 이전 기록을 덮지 않는다.
        const list = await refreshList();
        if (list !== null) setWorkAreas(list);
        const seq = retryHistory.length + 1;
        const unresolved = 1 + retryHistory.filter((h) => h.kind === "unknown").length;
        setRetryHistory((prev) => [
          ...prev,
          { seq, kind: "success", workAreaId: outcome.workArea.workAreaId, name: outcome.workArea.name },
        ]);
        setNotice(
          `새 요청 #${seq}으로 "${outcome.workArea.name}"을 등록했습니다(기술 참조 ${outcome.workArea.workAreaId}). ` +
            `첫 요청을 포함해 확인되지 않은 요청이 모두 ${unresolved}건 있어 구역이 더 생겼을 수 있습니다. ` +
            "목록에서 기술 참조(workAreaId)로 확인하세요.",
        );
        return;
      }
      if (outcome.kind === "unknown") {
        // 서버에 닿았을 수도 있다 — 성공도 실패도 아니다. 입력은 그대로 두고
        // 읽기 전용 확인 + 명시적 새 요청 선택으로만 푼다. 이름·기하가 같아도
        // 같은 구역이라고 단정하지 않는다(증명은 서버 발급 workAreaId뿐이다).
        // 화면을 서버 렌더한 시점의 계정 확인값을 함께 보관해, 다른 탭에서
        // 계정이 바뀌어도 재전송이 조용히 새 계정으로 나가지 않게 한다.
        if (!options?.explicitRetry) {
          setUnknownSubmission({
            name: trimmed,
            vertexCount: snapshotVertices.length,
            polygon,
            vertices: snapshotVertices,
            crs: COMPARISON_ZONE_CRS,
            supersedes,
            supersedesName,
            continuity,
          });
          setRetryHistory([]);
          setContinuityBlocked(null);
        } else {
          const seq = retryHistory.length + 1;
          const unresolved = 2 + retryHistory.filter((h) => h.kind === "unknown").length;
          setRetryHistory((prev) => [...prev, { seq, kind: "unknown" }]);
          setNotice(
            `새 요청 #${seq}의 결과도 확인하지 못했습니다. ` +
              `확인되지 않은 요청이 모두 ${unresolved}건입니다(첫 요청 포함). ` +
              "목록에서 기술 참조(workAreaId)로 확인하세요.",
          );
        }
        setError(null);
        return;
      }
      // 확정 거부 — 이 요청은 쓰지 않았다. 다만 첫 불명이 있으면 그 요청은
      // 여전히 미확인이므로 패널을 남긴다.
      if (!options?.explicitRetry) {
        // 동결을 풀고 라이브 입력으로 돌아간다 — 거부된 요청의 스냅샷을
        // 지도에 남기지 않는다.
        setFrozenVertices(null);
        setError(readableApiError(body, "작업구역 등록에 실패했습니다"));
        return;
      }
      {
        const seq = retryHistory.length + 1;
        const unresolved = 1 + retryHistory.filter((h) => h.kind === "unknown").length;
        setRetryHistory((prev) => [
          ...prev,
          {
            seq,
            kind: "failure",
            message: readableApiError(body, "작업구역 등록에 실패했습니다"),
          },
        ]);
        setNotice(
          `새 요청 #${seq}은 거부됐습니다. ` +
            `첫 요청을 포함해 확인되지 않은 요청이 모두 ${unresolved}건 남아 있습니다. ` +
            "목록에서 먼저 확인하세요.",
        );
      }
    } catch {
      // 응답 자체가 없다 — 만들었을지 모른다. 입력·지도는 그대로 둔다.
      if (!options?.explicitRetry) {
        setUnknownSubmission({
          name: trimmed,
          vertexCount: snapshotVertices.length,
          polygon,
          vertices: snapshotVertices,
          crs: COMPARISON_ZONE_CRS,
          supersedes,
          supersedesName,
          continuity,
        });
        setRetryHistory([]);
        setContinuityBlocked(null);
      } else {
        const seq = retryHistory.length + 1;
        const unresolved = 2 + retryHistory.filter((h) => h.kind === "unknown").length;
        setRetryHistory((prev) => [...prev, { seq, kind: "unknown" }]);
        setNotice(
          `새 요청 #${seq}의 결과도 확인하지 못했습니다(응답 없음). ` +
            `확인되지 않은 요청이 모두 ${unresolved}건입니다(첫 요청 포함). ` +
            "목록에서 기술 참조(workAreaId)로 확인하세요.",
        );
      }
      setError(null);
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  }

  /** 검증된 성공 등록의 후처리.
   *
   *  대체 등록은 새 구역 생성 + 이전 구역 보관 두 건인데 응답은 앞의 것만 싣고
   *  오므로, 뒤의 것은 목록을 다시 읽어 **관측**한다. 목록이 곧 현재 상태이며
   *  임의로 바꾸지 않는다: 이전 ID가 그 목록에 ARCHIVED로 보일 때만 보관을
   *  확정하고, ACTIVE로 보이거나 목록에 없거나 읽기에 실패하면 새 구역 등록만
   *  확정하고 이전 보관은 미확인(관측 상태 그대로)으로 안내한다.
   */
  function applySuccessfulRegistration(created: WorkArea, supersedes: string | null, list: WorkArea[] | null) {
    if (supersedes === null) {
      setWorkAreas(
        (prev) => [created, ...prev.filter((a) => a.workAreaId !== created.workAreaId)],
      );
      setNotice(null);
      notify(`작업구역 "${created.name}"을 등록했습니다.`);
      setUnknownSubmission(null);
      setUnknownVerifyMessage(null);
      setRetryHistory([]);
      setContinuityBlocked(null);
      resetForm();
      return;
    }
    if (list === null) {
      setWorkAreas(
        (prev) => [created, ...prev.filter((a) => a.workAreaId !== created.workAreaId)],
      );
      setNotice(
        `새 구역 "${created.name}"을 등록했습니다 — 다만 이전 구역이 보관됐는지는 확인하지 못했습니다(목록을 다시 읽지 못했습니다). 화면을 새로고침하면 확인할 수 있습니다.`,
      );
    } else {
      // 목록이 곧 현재 상태다 — 임의로 바꾸지 않는다. 원래 site+workAreaId로
      // 정확히 대조해 ARCHIVED로 관측될 때만 보관을 확정한다.
      setWorkAreas(list);
      const previous = list.find((a) => a.siteId === siteId && a.workAreaId === supersedes) ?? null;
      if (previous !== null && previous.status === "ARCHIVED") {
        setNotice(null);
        notify("새 작업구역을 등록하고 이전 구역을 보관했습니다.");
      } else if (previous !== null) {
        setNotice(
          `새 구역 "${created.name}"을 등록했습니다. 다만 대신하려던 구역(기술 참조 ${supersedes})은 목록에서 아직 사용 중으로 보입니다 — 보관이 확인되지 않았습니다. 목록에서 상태를 확인하세요.`,
        );
      } else {
        setNotice(
          `새 구역 "${created.name}"을 등록했습니다. 다만 대신하려던 구역(기술 참조 ${supersedes})이 지금 계정의 목록에 없어 보관 여부를 확인하지 못했습니다. 목록에서 확인하세요.`,
        );
      }
    }
    setUnknownSubmission(null);
    setUnknownVerifyMessage(null);
    setRetryHistory([]);
    setContinuityBlocked(null);
    resetForm();
  }

  /** 결과 불명 패널의 읽기 전용 확인 — 목록을 다시 읽어 화면과 원장을 맞춘다.
   *
   *  이 조회는 GET뿐이라 서버를 바꾸지 않는다. 다만 보여주는 것은 **지금 이
   *  계정·이 현장 범위로 읽은 현재 상태**다 — 같은 이름·모양이 있어도 원래 요청의
   *  구역이라고 단정하지 않고(증명은 workAreaId뿐), 목록에 없다고 등록되지
   *  않았다고도 말하지 않는다(권한·조회 범위·읽기 실패로 보이지 않을 수 있다).
   */
  async function handleVerifyUnknown() {
    if (verifying || !identityVerified.current) return;
    const epoch = identityEpoch.current;
    const identity = draftIdentity.current;
    const current = () => identityActive.current && identityVerified.current && identityEpoch.current === epoch && draftIdentity.current === identity && liveScope.current.siteId === siteId && liveScope.current.fingerprint === accountIdentity?.fingerprint && liveScope.current.canWrite === canWrite;
    setVerifying(true);
    try {
      const list = await refreshList();
      if (!current()) return;
      if (list === null) {
        setUnknownVerifyMessage(
          "목록을 다시 읽지 못했습니다. 네트워크를 확인한 뒤 다시 눌러주세요. " +
            "확인이 끝나기 전에는 같은 내용을 다시 보내지 마세요.",
        );
        return;
      }
      setWorkAreas(list);
      const activeCount = list.filter((area) => area.status === "ACTIVE").length;
      const archivedCount = list.length - activeCount;
      setUnknownVerifyMessage(
        `목록을 ${list.length}건(사용 중 ${activeCount}건·보관 ${archivedCount}건)으로 다시 읽었습니다. ` +
          "이 목록은 지금 이 계정·이 현장 범위로 읽은 현재 상태입니다. " +
          "같은 이름·모양이 있어도 원래 요청의 구역이라고 단정하지 마세요 — 목록의 기술 참조(workAreaId)로만 확인하세요. " +
          "목록에 없더라도 등록되지 않았다는 증명이 아닙니다(조회 권한·범위·읽기 실패로 보이지 않을 수 있습니다). " +
          (unknownSubmission?.supersedes !== null
            ? "대체 등록은 새 구역과 이전 구역 보관 두 건이므로, 대신할 구역의 상태도 목록에서 확인하세요."
            : "목록 확인 뒤에도 판단이 서지 않으면 새 요청으로 다시 등록할 수 있습니다(중복 가능)."),
      );
    } finally {
      setVerifying(false);
    }
  }

  /**
   * 결과 불명 뒤의 명시적 새 요청 — 첫 불명을 지우지 않고 새 요청을 보낸다.
   * 원래 화면 계정의 확인값이 있어야 서버에 닿는다. 확인할 값이 없으면
   * 보호 없이 보낼 수 없으므로 POST하지 않고 fail-closed로 안내한다(읽기는
   * 목록 확인으로 계속할 수 있다).
   */
  async function handleExplicitRetry() {
    const original = unknownSubmission;
    const identity = original?.continuity ?? null;
    if (!original || !identity || !identityVerified.current || !draftWritable.current || draftIdentity.current !== identity || submitLock.current) {
      setContinuityBlocked("원래 계정과 임시 저장 상태를 확인한 뒤 다시 시도하세요.");
      return;
    }
    submitLock.current = true;
    let episodeIndex: number;
    let attemptIndex: number;
    let requestBody: string;
    try {
      if (firstSubmissionRaw.current !== null) {
        const first = readFirstSubmission(window.sessionStorage, siteId, identity);
        if (first.kind !== "found" || first.raw !== firstSubmissionRaw.current) throw new Error("first");
        const prior = readEpisodeJournal(window.sessionStorage, siteId, identity);
        if (prior.kind === "invalid" || prior.kind === "unavailable") throw new Error("journal");
        const previous = prior.kind === "found" ? prior.journal.episodes.find(e => e.id === firstMigrationId(first.raw) && e.sourceRaw === first.raw) : undefined;
        const draftRaw = previous?.sourceDraftRaw ?? readEditDraftRaw(window.sessionStorage, siteId, identity);
        if (!draftRaw || !ensureFirstArchived(window.sessionStorage, first.record, first.raw, draftRaw)) throw new Error("archive");
        const checked = readEpisodeJournal(window.sessionStorage, siteId, identity);
        if (checked.kind !== "found") throw new Error("readback");
        episodeIndex = checked.journal.episodes.findIndex(e => e.id === firstMigrationId(first.raw) && e.sourceRaw === first.raw);
        if (episodeIndex < 0 || !clearFirstSubmission(window.sessionStorage, siteId, identity, first.raw)) throw new Error("clear");
        firstSubmissionRaw.current = null;
        viewingEpisode.current = episodeIndex + 1;
        const preserved = loadArchived(checked.journal);
        setEpisodeLog(preserved);
        setRetryHistory(preserved[episodeIndex]?.retries ?? []);
      } else {
        if (viewingEpisode.current === null) throw new Error("episode");
        episodeIndex = viewingEpisode.current - 1;
      }
      const before = readEpisodeJournal(window.sessionStorage, siteId, identity);
      if (before.kind !== "found") throw new Error("journal");
      const episode = before.journal.episodes[episodeIndex];
      if (!episode || episode.first.identity !== identity || episode.first.siteId !== siteId ||
          episode.first.body !== JSON.stringify({name:original.name, polygon:original.polygon, crs:original.crs, supersedes:original.supersedes})) throw new Error("binding");
      requestBody = episode.first.body;
      attemptIndex = episode.attempts.length;
      const actionId = workAreaUuid();
      if (!appendAttempt(window.sessionStorage, siteId, identity, episodeIndex, actionId)) throw new Error("attempt");
      const checked = readEpisodeJournal(window.sessionStorage, siteId, identity);
      if (checked.kind !== "found" || checked.journal.episodes[episodeIndex]?.attempts[attemptIndex]?.id !== actionId) throw new Error("attempt readback");
      const archived = loadArchived(checked.journal);
      setEpisodeLog(archived); setRetryHistory(archived[episodeIndex]?.retries ?? []);
    } catch {
      submitLock.current = false;
      setContinuityBlocked("이전 원본과 새 시도 기록을 확인하지 못해 재전송하지 않았습니다. 저장된 기록을 유지합니다.");
      return;
    }
    const epoch = identityEpoch.current;
    setSubmitting(true); setContinuityBlocked(null);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas`, {
        method:"POST", headers:{"Content-Type":"application/json", "x-ksi-continuity-fingerprint":identity}, body:requestBody,
      });
      const body = await parseJsonSafe<WorkAreaResponse>(response);
      const result = classifyWorkAreaSubmitOutcome({fetchThrew:false,status:response.status,body,siteId,request:{name:original.name,polygon:original.polygon,crs:original.crs,supersedes:original.supersedes}});
      if (!identityActive.current || !identityVerified.current || identityEpoch.current !== epoch || draftIdentity.current !== identity) return;
      const outcome = result.kind === "success" ? {kind:"success" as const,workAreaId:result.workArea.workAreaId,name:result.workArea.name}
        : result.kind === "definiteFailure" ? {kind:"failure" as const,message:readableApiError(body,"작업구역 등록에 실패했습니다")} : {kind:"unknown" as const};
      if (!settleAttempt(window.sessionStorage, siteId, identity, episodeIndex, attemptIndex, outcome)) {
        setContinuityBlocked("재전송 결과의 저장을 확인하지 못했습니다. 결과를 불명으로 두고 목록에서 확인하세요."); return;
      }
      const latest=readEpisodeJournal(window.sessionStorage,siteId,identity);
      if (latest.kind !== "found") { setContinuityBlocked("재전송 기록을 다시 읽지 못했습니다. 목록에서 확인하세요."); return; }
      const archived=loadArchived(latest.journal);setEpisodeLog(archived);setRetryHistory(archived[episodeIndex]?.retries ?? []);
      setNotice("별도 새 요청의 결과를 기록했습니다. 첫 요청은 여전히 확인되지 않았으며 중복 구역이 생겼을 수 있습니다.");
    } catch {
      // 전송 후 예외는 pending 상태로 보존한다. 복구 시 불명으로 표시된다.
      if (identityActive.current && identityVerified.current && identityEpoch.current === epoch) {
        setContinuityBlocked("새 요청의 응답을 확인하지 못했습니다. 첫 요청과 새 요청 모두 등록됐을 수 있습니다.");
      }
    } finally {
      submitLock.current = false;
      if (identityActive.current) setSubmitting(false);
    }
  }

  /** 입력은 비우되 확인 기록은 묶음으로 보관한다 — 확정 ID·불명 건수를 잃지 않는다.
   *
   *  '입력 비우고 새로 시작'은 로컬 폼만 비운다. 첫 불명과 재전송 이력은 아래
   *  '이전 확인 기록' 묶음으로 옮겨 새 입력과 섞지 않고 남긴다. 서버에 만들어졌을
   *  수 있는 구역은 사라지지 않으므로, 목록에서 기술 참조로 확인해야 한다.
   */
  function handleAbandonUnknown() {
    if (!identityVerified.current || !draftWritable.current || !draftIdentity.current || unknownSubmission === null || abandonLock.current) return;
    abandonLock.current = true;
    if (viewingEpisode.current !== null) {
      try {
        const blank: EditDraft = {name:"", vertices:[], correctionId:null, correctionReady:false, snapshot:null};
        if (!writeEditDraft(window.sessionStorage, siteId, draftIdentity.current, blank)) throw new Error("draft reset");
      } catch {
        abandonLock.current = false;
        setContinuityBlocked("새 입력의 임시 저장을 확인하지 못해 원래 요청 화면을 유지합니다.");
        return;
      }
      viewingEpisode.current = null;
      setUnknownSubmission(null); setRetryHistory([]); setContinuityBlocked(null); resetForm();
      return;
    }
    if (firstSubmissionRaw.current !== null) {
      try {
        const stored = readFirstSubmission(window.sessionStorage, siteId, draftIdentity.current);
        if (stored.kind !== "found" || stored.raw !== firstSubmissionRaw.current) throw new Error("source");
        const before = readEpisodeJournal(window.sessionStorage, siteId, draftIdentity.current);
        if (before.kind === "invalid" || before.kind === "unavailable") throw new Error("journal");
        const existing = before.kind === "found" ? before.journal.episodes.find(e => e.id === firstMigrationId(stored.raw) && e.sourceRaw === stored.raw) : undefined;
        const draftRaw = existing?.sourceDraftRaw ?? readEditDraftRaw(window.sessionStorage, siteId, draftIdentity.current);
        if (!draftRaw || !ensureFirstArchived(window.sessionStorage, stored.record, stored.raw, draftRaw)) throw new Error("archive");
        const journal = readEpisodeJournal(window.sessionStorage, siteId, draftIdentity.current);
        if (journal.kind !== "found") throw new Error("readback");
        const blank: EditDraft = {name:"", vertices:[], correctionId:null, correctionReady:false, snapshot:null};
        if (!writeEditDraft(window.sessionStorage, siteId, draftIdentity.current, blank)) throw new Error("draft reset");
        if (!clearFirstSubmission(window.sessionStorage, siteId, draftIdentity.current, stored.raw)) throw new Error("clear");
        const archived = loadArchived(journal.journal);
        episodeId.current = archived.length;
        firstSubmissionRaw.current = null;
        setEpisodeLog(archived);
        setUnknownSubmission(null); setUnknownVerifyMessage(null); setRetryHistory([]); setContinuityBlocked(null); resetForm();
        setNotice("첫 요청은 이 탭의 이전 확인 기록에 남겼습니다. 결과는 여전히 알 수 없으니 목록에서 확인하세요.");
      } catch {
        abandonLock.current = false;
        setContinuityBlocked("이전 요청의 임시 보관을 확인하지 못해 새 입력을 열지 않았습니다. 기존 원본을 유지합니다.");
      }
      return;
    }
    if (unknownSubmission !== null || retryHistory.length > 0) {
      const confirmed = retryHistory
        .filter((h): h is Extract<RetryRecord, { kind: "success" }> => h.kind === "success")
        .map((h) => ({ workAreaId: h.workAreaId, name: h.name }));
      const unresolvedCount =
        (unknownSubmission !== null ? 1 : 0) +
        retryHistory.filter((h) => h.kind === "unknown").length;
      episodeId.current += 1;
      const archived: ArchivedEpisode = {
        episode: episodeId.current,
        name: unknownSubmission?.name ?? "(이름 없음)",
        confirmed,
        unresolvedCount,
        original: unknownSubmission,
        retries: [...retryHistory],
      };
      setEpisodeLog((prev) => [...prev, archived]);
    }
    setUnknownSubmission(null);
    setUnknownVerifyMessage(null);
    setRetryHistory([]);
    setContinuityBlocked(null);
    resetForm();
    setNotice(
      "입력을 비웠습니다. 이전 요청의 확인 기록(확정 ID·불명 건수)은 아래에 남겨 두었습니다 — " +
        "서버에 구역이 만들어졌을 수도 있어 목록에서 먼저 확인하세요. 새로 입력하는 내용은 " +
        "지금 이 브라우저에 로그인된 계정으로 등록되며, 계정을 바꿨다면 목록이 다르게 " +
        "보일 수 있습니다.",
    );
  }

  function restoreEpisode(episode: ArchivedEpisode) {
    // 새 입력이 있으면 어떤 부분도 덮지 않는다. 버튼이 비활성이더라도
    // 오래된 이벤트가 들어올 수 있어 같은 조건을 다시 확인한다.
    if (
      !canWrite || busy || unknownSubmission !== null || mapPending.blocked ||
      correcting !== null || name !== "" || vertices.length > 0 || episode.original === null
    ) return;
    const original = episode.original;
    setUnknownSubmission(original);
    setRetryHistory([...episode.retries]);
    viewingEpisode.current = episode.episode;
    setName(original.name);
    setVertices(original.vertices.map((vertex) => ({ ...vertex })));
    setFrozenVertices(original.vertices.map((vertex) => ({ ...vertex })));
    setUnknownVerifyMessage(null);
    setContinuityBlocked(null);
    setNotice("이전 원래 요청을 다시 확인합니다. 다시 보내는 행동은 별도 선택이며 중복 구역이 생길 수 있습니다.");
  }

  async function handleArchiveListRead() {
    if (archiveReadLock.current || submitLock.current || archiveLock.current || !identityActive.current || !identityVerified.current) return;
    const epoch = identityEpoch.current;
    const identity = draftIdentity.current;
    const current = () => identityActive.current && identityVerified.current && identityEpoch.current === epoch &&
      draftIdentity.current === identity && liveScope.current.siteId === siteId &&
      liveScope.current.fingerprint === accountIdentity?.fingerprint && liveScope.current.canWrite === canWrite;
    archiveReadLock.current = true;
    setArchiveReading(true);
    try {
      const before = await fetch("/api/account-identity", {cache:"no-store"});
      const beforeBody = before.ok ? await before.json() : null;
      if (!current()) return;
      if (validContinuityFingerprint(beforeBody?.fingerprint) !== identity) { recheckIdentity.current?.(); return; }
      const list = await refreshList();
      const after = await fetch("/api/account-identity", {cache:"no-store"});
      const afterBody = after.ok ? await after.json() : null;
      if (!current()) return;
      if (validContinuityFingerprint(afterBody?.fingerprint) !== identity) { recheckIdentity.current?.(); return; }
      if (!list) {
        setArchiveReadMessage("목록을 확인하지 못했습니다. 이전 보관 요청의 결과는 여전히 미확인입니다.");
        return;
      }
      setWorkAreas(list);
      setArchiveReadMessage("현재 계정으로 목록을 다시 읽었습니다. 이 목록은 조회 시점의 상태이며 이전 요청의 최종 결과를 증명하지 않습니다.");
    } catch {
      if (current()) setArchiveReadMessage("목록을 확인하지 못했습니다. 이전 보관 요청의 결과는 여전히 미확인입니다.");
    } finally {
      archiveReadLock.current = false;
      if (identityActive.current) setArchiveReading(false);
    }
  }

  async function handleArchive(area: WorkArea) {
    if (archiveLock.current || archiveReadLock.current || !identityActive.current || !identityVerified.current || !canWrite || !draftIdentity.current) return;
    const epoch = identityEpoch.current;
    const identity = validContinuityFingerprint(draftIdentity.current);
    if (!identity || identity !== validContinuityFingerprint(accountIdentity?.fingerprint)) return;
    const current = () => identityActive.current && identityVerified.current && identityEpoch.current === epoch && draftIdentity.current === identity && liveScope.current.siteId === siteId && liveScope.current.fingerprint === accountIdentity?.fingerprint && liveScope.current.canWrite === canWrite;
    if (!current()) return;
    const archiveKey = JSON.stringify([siteId, identity, area.workAreaId]);
    const recordUnknown = () => {
      unconfirmedArchives.current.add(archiveKey);
      setUnconfirmedArchiveKeys(Array.from(unconfirmedArchives.current));
      setArchiveError({ areaId: area.workAreaId, message: ARCHIVE_UNKNOWN });
    };
    // 보관 대기 중 지도는 읽기 전용으로 전환된다. 아직 반영하지 않은 B가
    // 있다면 편집기가 언마운트되어 입력이 사라지므로 보관 요청을 보내지 않는다.
    // 확인창을 연 뒤 상태가 바뀐 경우도 이 방어선에서 다시 막는다.
    if (mapPending.blocked) {
      setArchiveError({ areaId: area.workAreaId, message: "입력 중인 경계를 반영하거나 되돌린 뒤 구역을 보관하세요." });
      return;
    }
    // 보관 대기 중 폼이 잠기므로, 열려 있던 이탈 확인은 닫는다(재개 시
    // 낡은 확인이 튀어나오지 않게).
    setAbandonConfirm(null);
    archiveLock.current = true;
    let attemptId: string;
    try {
      attemptId = workAreaUuid();
      if (!appendArchiveAttempt(window.sessionStorage, siteId, identity, {id: attemptId, area, outcome: "pending"})) throw new Error("archive storage");
      const written = readArchiveJournal(window.sessionStorage, siteId, identity);
      if (written.kind !== "found" || !written.journal.attempts.some(a => a.id === attemptId)) throw new Error("archive storage");
      setArchiveAttempts(written.journal.attempts);
    } catch {
      archiveLock.current = false;
      setArchiveError({ areaId: area.workAreaId, message: "보관 요청 기록을 안전하게 저장하지 못해 이번 요청을 보내지 않았습니다. 기존 기록과 입력은 그대로 두었습니다." });
      return;
    }
    const settle = (outcome: "success" | "rejected"): boolean => {
      const stored = settleArchiveAttempt(window.sessionStorage, siteId, identity, attemptId, outcome);
      const updated = stored ? readArchiveJournal(window.sessionStorage, siteId, identity) : null;
      if (updated?.kind === "found" && updated.journal.attempts.some(a => a.id === attemptId && a.outcome === outcome)) {
        setArchiveAttempts(updated.journal.attempts);
        return true;
      }
      unconfirmedArchives.current.add(archiveKey);
      setUnconfirmedArchiveKeys(Array.from(unconfirmedArchives.current));
      setArchiveReceiptWarning(`${outcome === "success" ? "이번 화면에서 보관 성공 응답을 확인했습니다." : "이번 화면에서 요청 거부 응답을 확인했습니다."} 이번 응답이 탭 기록에 저장됐는지 확인하지 못했습니다. 같은 탭에 다시 들어오면 이 시도가 결과 미확인으로 표시될 수 있습니다. 기록은 이 탭에만 있으며 탭을 닫으면 사라질 수 있습니다.`);
      return false;
    };
    setArchivingId(area.workAreaId);
    if (!unconfirmedArchives.current.has(archiveKey)) setArchiveError(null);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(area.workAreaId)}/archive`,
        { method: "POST", headers: { "x-ksi-continuity-fingerprint": identity } },
      );
      const body = await parseJsonSafe<WorkAreaResponse & { code?: string }>(response);
      if (!current()) return;
      if (response.status === 409 && body.code === "ACCOUNT_CONTINUITY_MISMATCH") {
        settle("rejected");
        setArchiveError({ areaId: area.workAreaId, message: "계정이 바뀌어 이번 보관 요청을 보내지 않았습니다. 이전 요청의 결과는 별도로 목록에서 확인하세요." });
        recheckIdentity.current?.();
        return;
      }
      if (!response.ok) {
        // 5xx, timeouts and unclassified responses may occur after Core commit.
        if (![400, 401, 403, 404, 422].includes(response.status) && !(response.status === 409 && body.code === "ALREADY_ARCHIVED")) {
          recordUnknown();
          return;
        }
        settle("rejected");
        const rejected = readableApiError(body, "이번 보관 요청은 거부되었습니다.");
        const prior = unconfirmedArchives.current.has(archiveKey) ? ` ${ARCHIVE_UNKNOWN}` : "";
        setArchiveError({ areaId: area.workAreaId, message: `이번 보관 요청: ${rejected}${prior}` });
        return;
      }
      if (!validArchiveEcho(body, area, siteId)) {
        recordUnknown();
        return;
      }
      settle("success");
      setWorkAreas((prev) =>
        prev.map((a) => (a.workAreaId === area.workAreaId ? { ...area, status: "ARCHIVED" } : a)),
      );
      setNotice(null);
      setArchiveError(null);
      notify(`"${area.name}"을 보관했습니다.`);
      // 그 구역을 대신할 새 구역을 그리던 중이었다면 그 폼은 의미를 잃는다.
      if (correcting?.workAreaId === area.workAreaId) resetForm();
    } catch {
      if (current()) recordUnknown();
    } finally {
      const stale = !current();
      if (stale) {
        archiveRecoveryRequired.current = true;
        unconfirmedArchives.current.add(archiveKey);
        if (identityActive.current) setUnconfirmedArchiveKeys(Array.from(unconfirmedArchives.current));
      }
      archiveLock.current = false;
      if (identityActive.current) {
        setArchivingId(null);
        if (stale) recheckIdentity.current?.();
      }
    }
  }

  /** 결과 불명이 해소되기 전에는 폼을 잠근다 — 입력을 바꾸면 원래 요청이 사라진다. */
  const formLocked = busy || unknownSubmission !== null;
  /**
   * 지도에 올리는 값 — 대기·불명 중에는 동결된 전송 원본 A를 보여준다.
   * 응답 대기·유실 뒤 입력이 B로 바뀌어도 읽기 전용 지도와 수량은 전송 A를
   * 표시하고, 재전송도 A로만 나간다. 좌표를 추정·보정하지 않는다.
   */
  const displayedVertices =
    unknownSubmission?.vertices ?? (formLocked && frozenVertices ? frozenVertices : vertices);
  /**
   * 지도 미반영·진행 중이면 기존 유효 범위가 있어도 제출하지 않는다 —
   * 미완성 B가 아닌 A가 나가는 일을 막는 자리다. 불명 패널이 열리면 지도는
   * 읽기 전용이라 이 값은 거짓이다.
   */
  const mapBlocked = unknownSubmission === null && (mapPending.blocked || recoveredGeometry !== "valid");
  const canRestoreEpisode = canWrite && !busy && unknownSubmission === null && !mapPending.blocked &&
    correcting === null && name === "" && vertices.length === 0;
  const canSubmit =
    canWrite &&
    !busy &&
    unknownSubmission === null &&
    name.trim() !== "" &&
    vertices.length >= 3 &&
    !mapBlocked;

  const scopeReady = draftGate === "ready" && boundScope?.siteId === siteId && boundScope.canWrite === canWrite && boundScope.identity === validContinuityFingerprint(accountIdentity?.fingerprint);

  return (
    <>
    {!scopeReady && <div role="status" className="rounded-md border border-line bg-sunk p-3 text-ink-2">
      <p>{draftMessage ?? (canWrite ? "현재 계정과 임시 저장 내용을 확인하고 있습니다." : "현재 계정을 확인하고 있습니다.")}</p>
      {draftGate === "failed" && <><p>확인이 끝나기 전에는 이 화면에서 작업구역 목록도 볼 수 없습니다. 저장된 원문은 변경하지 않습니다.</p><button type="button" className="btn mt-2" onClick={() => recheckIdentity.current?.()}>{canWrite ? "계정과 저장 상태 다시 확인" : "계정 다시 확인"}</button></>}
    </div>}
    <div ref={sensitiveRootRef} hidden={!scopeReady} style={{display: !scopeReady ? "none" : undefined}} className="flex flex-col gap-5">
      {scopeReady && <p className="text-[12px] text-ink-2">이름과 경계 편집 원문 및 첫 전송 원본을 이 탭에 임시 저장합니다. 탭을 닫으면 사라질 수 있으며, 진행 중인 지도 포인터 동작은 복구되지 않습니다. 첫 요청과 재전송 기록은 이 탭에만 보관됩니다. 재전송은 별도의 비멱등 요청이므로 중복 구역이 생길 수 있습니다.</p>}
      {scopeReady && draftMessage && <p role="alert" className="rounded-md bg-crit-bg px-3 py-2 text-crit-ink">{draftMessage}</p>}
      {canWrite && scopeReady && error && (
        <p
          role="alert"
          className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink"
        >
          {error}
        </p>
      )}

      {canWrite && scopeReady && unknownSubmission && (
        <div
          role="alert"
          data-testid="work-area-unknown-panel"
          className="flex flex-col gap-2 rounded-md border border-line-strong bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-1"
        >
          <p className="font-bold">등록 결과를 확인하지 못했습니다</p>
          <p className="break-keep text-ink-2">
            서버에 등록됐을 수도 있습니다. 같은 내용을 다시 보내면 구역이 두 개 생길 수 있어
            위 등록 버튼을 잠시 막았습니다. 입력과 지도는 그대로 두었습니다.
          </p>
          <p className="break-keep text-ink-2">
            첫 요청 원본은 이 탭에 임시 보관됩니다. 탭을 닫으면 사라질 수 있습니다. 서버에 도착하거나 등록됐는지는 알 수 없습니다. 재전송은 별도 요청으로 기록되며 첫 요청의 불명을 해소하지 않습니다. 목록에서 기술 참조(workAreaId)를 먼저 확인하세요.
          </p>
          <dl className="grid gap-1 text-[12px] text-ink-2 sm:grid-cols-2">
            <div>
              <dt className="text-[11.5px] text-ink-muted">보낸 이름</dt>
              <dd className="font-medium break-keep">{unknownSubmission.name}</dd>
            </div>
            <div>
              <dt className="text-[11.5px] text-ink-muted">보낸 범위</dt>
              <dd className="num">
                꼭짓점 {unknownSubmission.vertexCount}개 · {unknownSubmission.crs}
              </dd>
            </div>
            {unknownSubmission.supersedes !== null && (
              <div className="sm:col-span-2">
                <dt className="text-[11.5px] text-ink-muted">대체 대상</dt>
                <dd className="break-keep">
                  {unknownSubmission.supersedesName ?? "이전 구역"}(
                  <span className="num break-token font-mono text-[11px]">
                    {unknownSubmission.supersedes}
                  </span>
                  ) — 보관됐는지 알 수 없습니다.
                </dd>
              </div>
            )}
          </dl>
          <p className="break-keep text-ink-2">
            이름·모양이 같아도 같은 구역이라고 단정하지 마세요 — 목록의 기술 참조(workAreaId)로
            확인하세요. 다른 계정·다른 브라우저에서는 목록이 다르게 보일 수 있습니다.
            재전송은 별도 요청으로 기록되며 중복 구역이 생길 수 있습니다.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="work-area-verify-button"
              className="btn w-fit"
              disabled={verifying || busy}
              onClick={() => void handleVerifyUnknown()}
            >
              {verifying ? "목록 확인 중…" : "작업구역 목록 다시 불러오기"}
            </button>
            {/* 쓰기(POST)는 노트북 경계 안으로 — 390px에서도 패널은 보이지만
                재전송 버튼은 `hidden lg:contents` 로 가려 키보드·클릭 모두 닿지
                않는다. 목록 확인(읽기 전용)은 경계 밖에 둔다. */}
            <ResponsiveActionBoundary
              action="SITE_DEVICE_TRANSITION"
              inlineNotice={false}
              reason="재전송은 원래 기록이 있는 이 탭에서 화면 폭 1024px 이상으로 넓힌 뒤 확인할 수 있습니다. 다른 기기의 같은 계정에서는 목록을 먼저 확인하세요. 임시 기록은 다른 기기로 옮겨가지 않습니다."
            >
              <button
                type="button"
                data-testid="work-area-retry-button"
                className="btn w-fit"
                disabled={verifying || busy}
                onClick={() => void handleExplicitRetry()}
              >
                새 요청으로 다시 등록
              </button>
            </ResponsiveActionBoundary>
            <button
              type="button"
              data-testid="work-area-abandon-button"
              className="btn w-fit"
              disabled={verifying || busy}
              onClick={handleAbandonUnknown}
            >
              입력 비우고 새로 시작
            </button>
          </div>
          <p className="text-[11.5px] break-keep text-ink-muted">
            새 요청으로 다시 등록하면 중복 구역이 생길 수 있습니다. 먼저 목록을 확인하세요.
            재전송은 별도 요청으로 기록되며 중복 구역이 생길 수 있습니다. 계정을 바꿨다면
            입력 비우기로 새로 시작하세요(새 입력은 지금 로그인된 계정으로 등록됩니다).
            입력을 비워도 서버에 만들어졌을 수 있는 구역은 사라지지 않으며, 지금까지의
            확인 기록은 아래 이전 확인 기록에 남습니다.
          </p>
          <p className="text-[11.5px] break-keep text-ink-muted lg:hidden">
            작은 화면에서는 새 요청 다시 등록이 열리지 않습니다. 노트북에서 같은 계정으로
            이 현장의 ‘작업구역’ 화면을 열어 목록을 먼저 확인하세요. 이 탭의 임시 기록은
            다른 기기로 옮겨가지 않습니다. 원래 기록으로 재전송하려면 이 탭의 화면 폭을 1024px 이상으로 넓히세요.
          </p>
          {continuityBlocked !== null && (
            <p
              data-testid="work-area-continuity-blocked"
              role="alert"
              className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2"
            >
              {continuityBlocked}
            </p>
          )}
          {retryHistory.length > 0 && (
            <p>첫 요청을 포함해 확인되지 않은 요청이 모두 {1 + retryHistory.filter(record => record.kind === "unknown").length}건입니다. 목록에서 확인하세요.</p>
          )}
          {retryHistory.length > 0 && (
            <div
              data-testid="work-area-retry-history"
              className="flex flex-col gap-1 rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2"
            >
              {retryHistory.map((record) => (
                <p key={record.seq} data-testid="work-area-retry-outcome" data-seq={record.seq}>
                  {record.kind === "success" &&
                    `새 요청 #${record.seq}으로 "${record.name}"을 등록했습니다(기술 참조 ${record.workAreaId}). ` +
                      "그러나 확인되지 않은 이전 요청도 등록됐을 수 있습니다. " +
                      "목록에서 기술 참조(workAreaId)로 확인하세요."}
                  {record.kind === "failure" &&
                    `새 요청 #${record.seq}은 거부됐습니다: ${record.message} ` +
                      "그러나 확인되지 않은 이전 요청은 여전히 등록됐을 수 있습니다. 목록에서 먼저 확인하세요."}
                  {record.kind === "unknown" &&
                    `새 요청 #${record.seq}의 결과도 확인하지 못했습니다. ` +
                      "확인되지 않은 요청이 그대로 남아 있습니다. 목록에서 기술 참조(workAreaId)로 확인하세요."}
                </p>
              ))}
            </div>
          )}
          {unknownVerifyMessage && (
            <p
              data-testid="work-area-verify-outcome"
              className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2"
            >
              {unknownVerifyMessage}
            </p>
          )}
        </div>
      )}

      {canWrite && scopeReady && notice && (
        <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-2">
          {notice}
        </p>
      )}

      {/* 이전 요청과 확인 기록은 새 입력과 별도 묶음으로 화면 메모리에 둔다. */}
      {canWrite && scopeReady && episodeLog.length > 0 && (
        <section
          aria-label="이전 확인 기록"
          data-testid="work-area-episode-log"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3"
        >
          <h2 className="text-[13px] font-bold break-keep text-ink-1">
            이전 확인 기록(새 입력과 별개)
          </h2>
          {episodeLog.map((episode) => (
            <div
              key={episode.episode}
              data-testid="work-area-episode-record"
              data-episode={episode.episode}
              className="flex flex-col gap-1 rounded-md border border-line bg-sunk px-2 py-1 text-[12px] break-keep text-ink-2"
            >
              <p className="font-semibold">
                묶음 {episode.episode} — 첫 요청 &ldquo;{episode.name}&rdquo;
              </p>
              {episode.confirmed.length > 0 ? (
                <ul className="flex flex-col gap-1">
                  {episode.confirmed.map((item) => (
                    <li key={item.workAreaId}>
                      확정된 등록: &ldquo;{item.name}&rdquo;(기술 참조{" "}
                      <span className="num break-token font-mono text-[11px]">
                        {item.workAreaId}
                      </span>
                      ) — 이 화면에서 서버 응답으로 확인한 등록입니다. 목록에서 기술 참조로 대조하세요.
                    </li>
                  ))}
                </ul>
              ) : (
                <p>확정된 등록 없음</p>
              )}
              <p>
                확인되지 않은 채 남긴 요청: {episode.unresolvedCount}건 — 등록됐을 수도 있고
                안 됐을 수도 있습니다. 목록에서 기술 참조(workAreaId)로 확인하세요.
              </p>
              {episode.original !== null && (
                <>
                  <details>
                    <summary className="cursor-pointer">원래 요청 상세 보기</summary>
                    <p>좌표계: {episode.original.crs} · 대체 대상: {episode.original.supersedes ?? "없음"}</p>
                    <ol>
                      {episode.original.vertices.map((point, index) => (
                        <li key={index}>꼭짓점 {index + 1}: 위도 {String(point.latDeg)}, 경도 {String(point.lonDeg)}</li>
                      ))}
                    </ol>
                  </details>
                  <button
                    type="button"
                    className="btn mt-1 w-fit"
                    aria-label={`묶음 ${episode.episode} 원래 요청 다시 확인`}
                    disabled={!canRestoreEpisode}
                    onClick={() => restoreEpisode(episode)}
                  >
                    원래 요청 다시 확인
                  </button>
                  {!canRestoreEpisode && (
                    <p>새 입력을 비우거나 현재 요청 확인을 마친 뒤 원래 요청을 다시 확인할 수 있습니다.</p>
                  )}
                </>
              )}
            </div>
          ))}
          <p className="text-[11.5px] break-keep text-ink-muted">
            이 기록은 이 탭에만 임시 보관되며 탭을 닫으면 사라질 수 있습니다. 다른 계정의 목록 접근 가능 여부나 원래 요청의 성공은 알 수 없습니다.
          </p>
        </section>
      )}

      {/* U03 — 변경 행동의 작은 화면 인계는 이 하나로 둔다. 등록 폼과 카드
          버튼은 아래 `SITE_DEVICE_TRANSITION` 경계 안에 있어 작은 화면에서
          가려지고, 목록·미리보기는 읽기 전용으로 남는다. */}
      {canWrite && (
        <ResponsiveNotice
          action="SITE_DEVICE_TRANSITION"
          reason="작업구역 등록·다시 그리기·보관은 노트북에서 같은 계정으로 이 현장의 ‘작업구역’ 화면을 열어 진행하세요. 작은 화면에서는 아래 목록과 구역 범위 보기로 확인만 할 수 있습니다. 입력 중인 내용·임시 기록은 이 탭에만 있어 다른 기기로 이어지지 않습니다. 재전송은 원래 기록이 있는 탭에서 확인하세요."
        />
      )}

      {(draftMounted || !canWrite) && <div hidden={canWrite && !scopeReady} style={{ display: canWrite && !scopeReady ? "none" : undefined }}>
      {canWrite ? (
        <ResponsiveActionBoundary
          action="SITE_DEVICE_TRANSITION"
          inlineNotice={false}
          reason="작업구역 등록과 다시 그리기는 노트북에서 같은 계정으로 이 현장의 ‘작업구역’ 화면을 열어 이어가세요. 입력 중인 내용·임시 기록은 이 탭에만 있어 다른 기기로 이어지지 않습니다."
        >
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h2
            ref={formHeadingRef}
            tabIndex={-1}
            className="text-[13px] font-bold tracking-tight break-keep text-ink-2"
          >
            {correcting ? "구역 다시 그리기" : "새 작업구역 등록"}
          </h2>

          {abandonConfirm !== null && (
            <div
              ref={abandonRef}
              tabIndex={-1}
              role="group"
              aria-label="입력 중인 내용 확인"
              data-testid="work-area-abandon-confirm"
              className="flex flex-col gap-2 rounded-md border border-line-strong bg-sunk px-3 py-2"
              onKeyDown={(event) => {
                if (event.key === "Escape") resolveAbandon(false);
              }}
            >
              <h3 className="text-[12.5px] font-bold break-keep text-ink-1">
                입력 중인 내용이 있습니다
              </h3>
              <p className="text-[12.5px] break-keep text-ink-2">
                지도에 반영하지 않은 입력은 이동하면 사라집니다. 기존에 반영된
                범위와 등록된 구역은 그대로 남습니다. Esc를 누르면 계속 입력합니다.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="btn w-fit"
                  onClick={() => resolveAbandon(false)}
                >
                  계속 입력하기
                </button>
                <button
                  type="button"
                  className="btn w-fit"
                  onClick={() => resolveAbandon(true)}
                >
                  입력 버리고 이동하기
                </button>
              </div>
            </div>
          )}

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
                disabled={formLocked}
                onClick={() => {
                  requestResetForm();
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
              disabled={formLocked}
              placeholder="3공구 성토부"
              onChange={(event) => { saveDraft({ name: event.target.value }); setName(event.target.value); }}
            />
          </label>

          <div className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              범위 — 지도에서 폴리곤을 그리세요(꼭짓점 3개 이상)
            </span>
            <AoiPolygonMap
              key={mapKey}
              value={displayedVertices}
              onChange={acceptMapVertices}
              initialSnapshot={restoredSnapshot}
              onSnapshotChange={(snapshot) => { saveDraft({ snapshot }); syncMapPending.current = { blocked: true, reason: "입력한 경계를 확인하고 지도에 반영하거나 되돌리세요." }; setMapPending(syncMapPending.current); }}
              onPendingChange={(pending) => { syncMapPending.current = pending; setMapPending(pending); }}
              // 제출 대기 중에도 지도를 바꾸면 첫 요청(A)과 화면(B)이 갈라진다 —
              // 응답 유실 뒤 재전송이 현재 입력을 재구성하지 않도록(동결 원본 사용)
              // 대기 중 입력 자체를 잠근다. 원래 값은 그대로 보존된다.
              readOnly={formLocked}
            />
            <span className="text-[11.5px] break-keep text-ink-muted">
              {displayedVertices.length >= 3
                ? `꼭짓점 ${displayedVertices.length}개 — 이 모양으로 굳습니다.`
                : "아직 구역이 되지 않았습니다 — 꼭짓점을 3개 이상 찍으세요."}{" "}
              좌표는 위경도(<span className="num">{COMPARISON_ZONE_CRS}</span>)로 저장됩니다
              (현장 등록 좌표계는 <span className="num break-token">{siteCrs}</span>입니다).
            </span>
            {mapBlocked && (
              <p
                role="status"
                data-testid="work-area-map-pending"
                className="rounded-md border border-line bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-1"
              >
                {recoveredGeometry === "checking" ? "복구한 경계를 확인하는 중입니다. 확인이 끝나기 전에는 등록할 수 없습니다." : recoveredGeometry === "invalid" ? "복구한 경계를 안전하게 확인하지 못했습니다. 원본을 확인한 뒤 지도에서 다시 반영하거나 그려 주세요." : mapPending.reason ?? "입력한 내용을 지도에 반영하거나 되돌리기 전에는 등록할 수 없습니다."}
              </p>
            )}
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
        <ActionUnavailable label="작업구역 등록" description="현재 계정으로는 작업구역을 등록하거나 보관할 수 없습니다. 현장 담당자에게 문의하세요." />
      )}</div>}

      {scopeReady && archiveReceiptWarning && <p role="alert" className="rounded-md border border-line bg-sunk p-3 text-ink-2">{archiveReceiptWarning}</p>}
      {scopeReady && unconfirmedArchiveKeys.some(key => {
        const [savedSite, savedIdentity] = JSON.parse(key) as [string, string, string];
        return savedSite === siteId && savedIdentity === boundScope?.identity;
      }) && <div className="rounded-md border border-line bg-sunk p-3 text-ink-2">
        <p>이전 보관 요청의 결과가 미확인입니다. 목록을 다시 읽어 현재 상태를 확인할 수 있습니다.</p>
        <ul>{archiveAttempts.map((attempt, index) => <li key={attempt.id}>시도 {index + 1}: {attempt.area.name} · {attempt.area.workAreaId} · {attempt.area.crs} · {polygonToVertices(attempt.area.polygon).length}개 꼭짓점 — {attempt.outcome === "pending" ? "결과 미확인" : attempt.outcome === "success" ? "이 시도 응답 확인" : "이 시도 거부"}</li>)}</ul>
        <p>기록은 이 탭에만 남습니다. 재전송은 별도 시도로 기록되며 이전 미확인을 해소하지 않습니다.</p>
        <button type="button" className="btn mt-2" disabled={busy} onClick={() => void handleArchiveListRead()}>보관 상태 목록 다시 읽기</button>
        {archiveReadMessage && <p role="status">{archiveReadMessage}</p>}
      </div>}
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
            {canWrite ? (
              <>
                아직 등록된 작업구역이 없습니다. 위 지도에서 이름과 범위를 정해 등록하세요.
                <span className="mt-1 block lg:hidden">
                  작은 화면에서는 등록 폼이 열리지 않으므로, 목록 확인만 할 수 있습니다.
                  노트북에서 같은 계정으로 이 현장의 ‘작업구역’ 화면을 열어 이어가세요.
                </span>
              </>
            )
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
                disabled={busy || unknownSubmission !== null || !scopeReady}
                archiveBlockedByDraft={mapPending.blocked && unknownSubmission === null}
                correcting={correcting?.workAreaId === area.workAreaId}
                previewOpen={previewId === area.workAreaId}
                previewResult={previewId === area.workAreaId ? previewResult : null}
                onTogglePreview={togglePreview}
                onCorrect={requestCorrection}
                onArchive={(target) => setArchiveTarget(target)}
                archiveError={archiveError?.areaId === area.workAreaId ? archiveError.message : null}
              />
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={archiveTarget !== null}
        title="구역을 보관할까요?"
        description={archiveTarget ? <>“{archiveTarget.name}”을 보관하면 이 화면에서 되돌릴 수 없습니다. 새 비교에서 고를 수 없게 되며, 이미 낸 리포트는 그대로 유지됩니다.{unconfirmedArchiveKeys.includes(JSON.stringify([siteId, boundScope?.identity, archiveTarget.workAreaId])) && " 이번 행동은 별도 전송이며 이전 요청의 결과를 증명하지 않습니다."}</> : null}
        confirmLabel="구역 보관"
        pending={archivingId !== null}
        onCancel={() => setArchiveTarget(null)}
        onConfirm={() => {
          const target = archiveTarget;
          setArchiveTarget(null);
          if (target) void handleArchive(target);
        }}
      />

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
                disabled={busy || !scopeReady}
                archiveBlockedByDraft={false}
                correcting={false}
                previewOpen={previewId === area.workAreaId}
                previewResult={previewId === area.workAreaId ? previewResult : null}
                onTogglePreview={togglePreview}
                onCorrect={requestCorrection}
                onArchive={(target) => setArchiveTarget(target)}
                archiveError={archiveError?.areaId === area.workAreaId ? archiveError.message : null}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
    </>
  );
}
