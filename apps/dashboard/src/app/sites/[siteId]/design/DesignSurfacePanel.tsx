"use client";

import Link from "next/link";
import { useState } from "react";

import { StateBadge } from "@/components/ui/StatusBadge";
import {
  DESIGN_SURFACE_STATUS_LABEL,
  humanizeDesignSurfaceRejection,
  humanizeVerticalDatum,
  readableApiError,
} from "@/lib/core-api/labels";
import {
  DESIGN_SURFACE_UPLOAD_CONTENT_TYPE,
  declaredObservedRows,
  pendingVerification,
} from "@/lib/design-conformance";
import { formatKoreanDateTime } from "@/lib/datetime";
import { parseJsonSafe } from "@/lib/http";
import { usePolling } from "@/hooks/usePolling";
import type {
  DesignSurface,
  DesignSurfaceListResponse,
  DesignSurfaceRegisterResponse,
  DesignSurfaceSealResponse,
} from "@/lib/core-api/types";

/**
 * 설계 기준면 등록(선언 → 업로드 → 봉인) + **검증 상태 표시** + 선언 vs 관측 대조표.
 *
 * ## 이 화면이 절대 하지 않는 말: "업로드 완료"
 *
 * `SourceUploadPanel` 의 3단(등록 → 업로드 → 봉인)을 그대로 따르되, 마지막 단계의
 * 이름이 다르다. 브라우저의 `fetch` 가 성공한 것은 **이 브라우저에서 일어난
 * 일**이고, 그 시점에 서버가 아는 것은 "클라이언트가 다 올렸다고 말했다"뿐이다 —
 * 파일은 아무도 열어보지 않았다(`design_surfaces` 모듈 docstring: "SEALED 는
 * 사실이 아니라 주장이다").
 *
 * 그래서 화면을 두 칸으로 나눈다:
 *
 * - **이 브라우저에서 일어난 일** — 해시 계산·등록·전송·봉인 요청. 회색 진행 표시.
 * - **서버가 확인한 상태** — REGISTERED / 검증 대기 / 검증 완료 / 검증 실패.
 *   이 배지만이 durable 한 사실이고, 여기 "검증 완료"가 뜨기 전까지는 이 설계면으로
 *   아무것도 계산할 수 없다.
 *
 * 폴링 관용구는 `usePolling` 의 규약을 그대로 쓴다 — 아직 판정을 기다리는 설계면이
 * 있는 동안만 돌고, 전부 종단이 되면 스스로 멈춘다.
 */

type LocalPhase =
  | { kind: "idle" }
  | { kind: "hashing" }
  | { kind: "registering" }
  | { kind: "uploading" }
  | { kind: "sealing" }
  | { kind: "handed-off"; designSurfaceId: string }
  | { kind: "error"; message: string };

const LOCAL_PHASE_TEXT: Record<Exclude<LocalPhase["kind"], "error">, string> = {
  idle: "",
  hashing: "파일 해시를 계산하는 중… (파일 전체를 읽습니다)",
  registering: "선언 내용을 서버에 등록하는 중…",
  uploading: "파일을 저장소로 보내는 중… (대시보드 서버를 거치지 않습니다)",
  sealing: "업로드를 마쳤다고 서버에 알리는 중…",
  "handed-off": "이 브라우저가 할 일은 끝났습니다 — 이제 서버의 검증을 기다립니다.",
};

async function sha256Hex(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function formatMoment(iso: string | null): string {
  if (!iso) return "—";
  return formatKoreanDateTime(iso);
}

/** 선언 vs 관측 — **한 줄로 합치지 않는 것이 이 표의 존재 이유다.** */
function DeclaredObservedTable({ surface }: { surface: DesignSurface }) {
  const rows = declaredObservedRows(surface);
  const measured = surface.observed !== null;
  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b border-line pb-1 text-[11px] font-bold break-keep text-ink-muted">
        <span>항목</span>
        <span>적어 낸 값(주장)</span>
        <span>{measured ? "파일에서 읽은 값(확인됨)" : "파일에서 읽은 값"}</span>
      </div>
      {rows.map((row) => (
        <div
          key={row.label}
          className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b border-line py-1.5 text-[11.5px] last:border-b-0"
        >
          <span className="break-keep text-ink-muted">{row.label}</span>
          <span className="num break-token">{row.declared}</span>
          <span className={row.observed === null ? "break-keep text-ink-muted" : "num break-token"}>
            {row.observed ?? "아직 아무도 재지 않았습니다"}
          </span>
        </div>
      ))}
      {/* 수직기준은 파일에서 관측할 수 없다 — 그 사실 자체를 표에 남긴다. */}
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 py-1.5 text-[11.5px]">
        <span className="break-keep text-ink-muted">높이 기준</span>
        <span className="break-keep">
          {humanizeVerticalDatum(surface.declared.verticalReference.datum)}
          <span className="block text-[11px] text-ink-muted">
            근거: {surface.declared.verticalReference.basis}
          </span>
        </span>
        <span className="break-keep text-ink-muted">
          높이 자료 파일은 이 값을 담지 않습니다 — 확인할 방법이 없어 끝까지 주장으로
          남습니다.
        </span>
      </div>
    </div>
  );
}

function SurfaceCard({ surface }: { surface: DesignSurface }) {
  const status = DESIGN_SURFACE_STATUS_LABEL[surface.status];
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold break-keep">
          {surface.name} <span className="text-ink-muted">· {surface.revision}</span>
        </span>
        <StateBadge label={status.label} tone={status.tone} />
      </div>

      <p className="text-[12px] break-keep text-ink-2">{status.description}</p>

      <p className="text-[11.5px] break-keep text-ink-muted">
        입력: {surface.format === "landxml" ? "LandXML TIN" : "GeoTIFF"}
        {surface.format === "landxml" && surface.surfaceSelector
          ? ` · Surface: ${surface.surfaceSelector}`
          : ""}
        {surface.sourceLineage
          ? ` · 정규화: ${surface.sourceLineage.normalizationProfile}`
          : ""}
      </p>

      {surface.status === "REJECTED" && (
        <p
          role="alert"
          className="rounded-md bg-crit-bg px-2.5 py-2 text-[12.5px] font-semibold break-keep text-crit-ink"
        >
          {humanizeDesignSurfaceRejection(surface.rejectionReason)}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px] sm:grid-cols-4">
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">식별자</dt>
          <dd className="num break-token">{surface.designSurfaceId}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">등록</dt>
          <dd className="num">{formatMoment(surface.registeredAt)}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">봉인(업로드 주장)</dt>
          <dd className="num">{formatMoment(surface.sealedAt)}</dd>
        </div>
        <div className="flex flex-col">
          <dt className="break-keep text-ink-muted">검증 완료</dt>
          <dd className="num">{formatMoment(surface.verifiedAt)}</dd>
        </div>
      </dl>

      <DeclaredObservedTable surface={surface} />
    </li>
  );
}

export function DesignSurfacePanel({
  siteId,
  siteCrs,
  canWrite,
  initialSurfaces,
}: {
  siteId: string;
  /** 현장에 등록된 좌표계 — 폼의 초기값으로만 쓴다(설계 도면이 다를 수 있다). */
  siteCrs: string;
  canWrite: boolean;
  initialSurfaces: DesignSurface[];
}) {
  const [surfaces, setSurfaces] = useState<DesignSurface[]>(initialSurfaces);
  const [name, setName] = useState("");
  const [revision, setRevision] = useState("");
  const [crs, setCrs] = useState(siteCrs);
  const [basis, setBasis] = useState("");
  const [heightKind, setHeightKind] = useState<"ellipsoidal" | "orthometric">("ellipsoidal");
  const [sourceFormat, setSourceFormat] = useState<"geotiff" | "landxml">("geotiff");
  const [surfaceSelector, setSurfaceSelector] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<LocalPhase>({ kind: "idle" });

  // 아직 판정을 기다리는 설계면이 있는 동안만 돈다. 토큰이 **바뀌는 것**이 유일한
  // 재시작 경로다(usePolling 모듈 docstring) — 봉인할 때마다 새 토큰을 넣는다.
  const [pollToken, setPollToken] = useState<string | null>(() =>
    pendingVerification(initialSurfaces) ? "initial" : null,
  );

  usePolling(
    pollToken,
    async () => {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/design-surfaces`);
      if (!response.ok) return null;
      const body = await parseJsonSafe<DesignSurfaceListResponse>(response);
      return body.surfaces ?? null;
    },
    (list) => !pendingVerification(list),
    (list) => {
      setSurfaces(list);
      if (!pendingVerification(list)) setPollToken(null);
    },
  );

  const busy =
    phase.kind === "hashing" ||
    phase.kind === "registering" ||
    phase.kind === "uploading" ||
    phase.kind === "sealing";
  const canSubmit =
    canWrite &&
    !busy &&
    file !== null &&
    name.trim() !== "" &&
    revision.trim() !== "" &&
    crs.trim() !== "" &&
    basis.trim() !== "" &&
    (sourceFormat === "geotiff" || surfaceSelector.trim() !== "");

  async function handleSubmit() {
    if (file === null) return;
    setPhase({ kind: "hashing" });
    try {
      const sha256 = await sha256Hex(file);

      setPhase({ kind: "registering" });
      const registerResponse = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/design-surfaces`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name.trim(),
            revision: revision.trim(),
            sourceFormat,
            // LandXML 안에 여러 TIN Surface가 있어도 서버가 추측하지 않는다.
            // 직접 GeoTIFF에는 selector 자체를 보내지 않는다.
            surfaceSelector: sourceFormat === "landxml" ? surfaceSelector.trim() : null,
            declared: {
              crs: crs.trim(),
              lengthUnit: "meter",
              sha256,
              verticalReference: {
                // 사용자가 고른 것을 그대로 보낸다. 해발을 고르면 KNGeoid24 로
                // 실현한 정표고라고 선언되고, 잔량 계산이 그 격자로 되돌린다 —
                // 선언과 실제로 쓰는 격자가 같은 이름을 가리켜야 한다.
                datum:
                  heightKind === "orthometric" ? "orthometric_kngeoid2024" : "ellipsoidal",
                basis: basis.trim(),
                source: "user_declared",
              },
            },
          }),
        },
      );
      const registerBody = await parseJsonSafe<DesignSurfaceRegisterResponse>(registerResponse);
      if (
        !registerResponse.ok ||
        registerBody.verdict !== "REGISTERED" ||
        !registerBody.uploadUrl ||
        !registerBody.designSurfaceId
      ) {
        setPhase({
          kind: "error",
          message: readableApiError(registerBody, "설계 기준면 등록에 실패했습니다"),
        });
        return;
      }
      const designSurfaceId = registerBody.designSurfaceId;

      // 바이트는 대시보드 서버를 거치지 않는다 — 브라우저가 스토리지로 직접 PUT.
      // Content-Type 은 서명에 포함된 값이라 파일의 MIME 을 쓰면 안 된다
      // (design-conformance.ts DESIGN_SURFACE_UPLOAD_CONTENT_TYPE).
      setPhase({ kind: "uploading" });
      const put = await fetch(registerBody.uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": DESIGN_SURFACE_UPLOAD_CONTENT_TYPE },
        body: file,
      });
      if (!put.ok) {
        setPhase({
          kind: "error",
          message: `저장소 업로드에 실패했습니다 (HTTP ${put.status}). 같은 내용으로 다시 시도하면 이어서 진행됩니다.`,
        });
        return;
      }

      setPhase({ kind: "sealing" });
      const sealResponse = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/design-surfaces/${encodeURIComponent(designSurfaceId)}/seal`,
        { method: "POST" },
      );
      const sealBody = await parseJsonSafe<DesignSurfaceSealResponse>(sealResponse);
      const sealed = sealBody.surface;
      if (!sealResponse.ok || !sealed) {
        setPhase({
          kind: "error",
          message: readableApiError(sealBody, "봉인에 실패했습니다"),
        });
        return;
      }

      setSurfaces((prev) => [
        sealed,
        ...prev.filter((s) => s.designSurfaceId !== designSurfaceId),
      ]);
      setPhase({ kind: "handed-off", designSurfaceId });
      setFile(null);
      // 토큰을 새로 넣어 폴링을 (다시) 시작한다 — 판정이 나면 스스로 멈춘다.
      setPollToken(`seal-${designSurfaceId}-${Date.now()}`);
    } catch {
      setPhase({
        kind: "error",
        message: "요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.",
      });
    }
  }

  const verifiedCount = surfaces.filter((s) => s.status === "VERIFIED").length;

  return (
    <div className="flex flex-col gap-5">
      {canWrite ? (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h2 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
            새 설계 기준면 올리기
          </h2>
          <p className="text-[12.5px] break-keep text-ink-muted">
            아래 값은 전부 <strong className="font-bold">사용자가 적어 내는 주장</strong>입니다
            — 올린 뒤 서버가 파일을 직접 열어 재고 대조합니다. 맞지 않으면 그 자리에서
            거부되고, 무엇이 어긋났는지 아래 목록에 뜹니다.
          </p>

          <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">이름</span>
              <input
                className="input"
                value={name}
                disabled={busy}
                placeholder="A공구 계획고"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                개정 표기 — 같은 이름·개정으로 다른 내용은 받지 않습니다
              </span>
              <input
                className="input"
                value={revision}
                disabled={busy}
                placeholder="Rev.C"
                onChange={(event) => setRevision(event.target.value)}
              />
            </label>
          </div>

          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[11.5px] break-keep text-ink-muted">설계면 입력 형식</legend>
            <label className="flex items-start gap-2 text-[12.5px] break-keep">
              <input
                type="radio"
                name="design-surface-format"
                className="mt-1"
                checked={sourceFormat === "geotiff"}
                disabled={busy}
                onChange={() => {
                  setSourceFormat("geotiff");
                  setFile(null);
                  setPhase({ kind: "idle" });
                }}
              />
              <span>GeoTIFF 높이자료 — 이미 정규화된 계획고 래스터를 올립니다.</span>
            </label>
            <label className="flex items-start gap-2 text-[12.5px] break-keep">
              <input
                type="radio"
                name="design-surface-format"
                className="mt-1"
                checked={sourceFormat === "landxml"}
                disabled={busy}
                onChange={() => {
                  setSourceFormat("landxml");
                  setFile(null);
                  setPhase({ kind: "idle" });
                }}
              />
              <span>LandXML TIN Surface — 원본 XML은 보존하고 서버가 0.5 m GeoTIFF로 정규화합니다.</span>
            </label>
          </fieldset>

          {sourceFormat === "landxml" && (
            <label className="flex flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                사용할 TIN Surface 이름 — LandXML에 적힌 이름을 정확히 입력하세요
              </span>
              <input
                className="input"
                value={surfaceSelector}
                disabled={busy}
                placeholder="Finished Grade"
                onChange={(event) => setSurfaceSelector(event.target.value)}
              />
              <span className="text-[11.5px] break-keep text-ink-muted">
                여러 Surface가 있어도 서버는 임의로 고르지 않습니다. 선택한 이름·원본 digest·정규화 결과가 함께 기록됩니다.
              </span>
            </label>
          )}

          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              도면의 좌표계 — 현장 등록값을 기본으로 채웠습니다. 도면이 다르면 고치세요.
            </span>
            <input
              className="input"
              value={crs}
              disabled={busy}
              placeholder="EPSG:5186"
              onChange={(event) => setCrs(event.target.value)}
            />
          </label>

          {/* 높이 기준을 고르게 하는 것이 이 폼에서 가장 중요한 자리다. 선택지를
              하나로 줄여 놓고 "타원체 기준"으로 강제하면, 해발 높이 도면을 가진
              사용자가 사실이 아닌 것을 적어 내게 되고 그 순간 20~30 m 가 조용히
              결과에 들어간다.

              2026-08-12 부터 해발 높이도 받는다 — 국가 지오이드 모델(KNGeoid24)을
              정식 경로로 확보·검증했고(전국 기준점 10점 전원 통과), 잔량 계산이
              그 격자로 셀마다 되돌린 뒤 차분한다. 사용자가 고른 값이 그대로
              선언으로 저장되므로 여기서 거짓을 적을 이유가 없다. */}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[11.5px] break-keep text-ink-muted">
              이 도면의 높이는 무엇을 기준으로 하나요
            </legend>
            <label className="flex items-start gap-2 text-[12.5px] break-keep">
              <input
                type="radio"
                name="height-kind"
                className="mt-1"
                checked={heightKind === "ellipsoidal"}
                disabled={busy}
                onChange={() => setHeightKind("ellipsoidal")}
              />
              <span>
                타원체 기준 높이 — 드론 측량(RTK)이 그대로 내는 높이와 같은 기준입니다.
              </span>
            </label>
            <label className="flex items-start gap-2 text-[12.5px] break-keep">
              <input
                type="radio"
                name="height-kind"
                className="mt-1"
                checked={heightKind === "orthometric"}
                disabled={busy}
                onChange={() => setHeightKind("orthometric")}
              />
              <span>해발 높이(표고) — 국내 측량 성과·설계도면에서 흔히 쓰는 기준입니다.</span>
            </label>
            {heightKind === "orthometric" && (
              <p className="rounded-md bg-sunk px-2.5 py-2 text-[12.5px] break-keep text-ink-2">
                해발 높이 도면은 계산할 때{" "}
                <strong className="font-bold">국가 지오이드 모델(KNGeoid24)</strong>로 드론
                측량과 같은 기준으로 자동으로 맞춥니다 — 지점마다 다른 보정값을 격자에서
                읽어 적용하며, 얼마를 적용했는지는 결과 화면에 그대로 남습니다. 이 모델이
                연결되지 않은 환경에서는 숫자를 내는 대신 그 사유로 멈춥니다.
              </p>
            )}
          </fieldset>

          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              그 기준을 어떻게 아는지 — 비워둘 수 없습니다
            </span>
            <input
              className="input"
              value={basis}
              disabled={busy}
              placeholder="설계사 제공 도면 표제부에 타원체고 명시"
              onChange={(event) => setBasis(event.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11.5px] break-keep text-ink-muted">
              {sourceFormat === "landxml"
                ? "LandXML 파일(TIN Surface · XML 1.0~1.2)"
                : "계획고 파일(GeoTIFF · 높이 자료 1밴드)"}
            </span>
            <input
              type="file"
              accept={
                sourceFormat === "landxml"
                  ? ".xml,.landxml,application/xml,text/xml"
                  : ".tif,.tiff,image/tiff,application/octet-stream"
              }
              disabled={busy}
              className="text-[12.5px]"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setPhase({ kind: "idle" });
              }}
            />
            {sourceFormat === "geotiff" && (
              <>
            {/* IFC 를 여기서 직접 받도록 확장하지 않는다 — 서버가 IFC 를 받는 순간
                검증·잔량 계산 전체(래스터 전제)를 이원화해야 한다. IFC 는 CLI 변환
                도구로 GeoTIFF 를 만들어 이 경로에 태운다(도구가 좌표 기준 없는
                파일을 거부하고, 결정적 바이트라 해시 대조도 그대로 성립한다). */}
            <span className="text-[11.5px] break-keep text-ink-muted">
              BIM/CAD 설계 파일(IFC)은 이 화면이 직접 받지 않습니다 — 저장소의 변환
              도구(<span className="num">tools/convert_ifc_design_surface.py</span>)로 높이
              GeoTIFF 를 만든 뒤 올리세요. 파일 안에 좌표 기준이 없으면 변환 단계에서
              거부됩니다.
            </span>
              </>
            )}
            {sourceFormat === "landxml" && (
              <span className="text-[11.5px] break-keep text-ink-muted">
                DTD·외부 entity·비미터 단위·깨진 삼각면은 서버가 거부합니다. DWG/DXF는 직접 받지 않으므로 LandXML 또는 GeoTIFF로 내보내세요.
              </span>
            )}
          </label>

          <button
            type="button"
            className="btn btn-primary w-fit"
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {busy ? "진행 중…" : "올리고 검증 요청"}
          </button>

          {/* ── 이 브라우저에서 일어난 일 ─────────────────────────────────
              서버가 확인한 사실(아래 목록의 배지)과 **시각적으로 분리한다** —
              여기 초록불이 떠도 파일은 아직 아무도 열어보지 않았다. */}
          {phase.kind !== "idle" && (
            <div className="flex flex-col gap-1 rounded-md border border-dashed border-line-strong bg-sunk px-3 py-2">
              <span className="text-[11px] font-bold break-keep text-ink-muted">
                이 브라우저에서 일어난 일
              </span>
              {phase.kind === "error" ? (
                <p role="alert" className="text-[12.5px] font-semibold break-keep text-crit-ink">
                  {phase.message}
                </p>
              ) : (
                <p className="text-[12.5px] break-keep text-ink-2">
                  {LOCAL_PHASE_TEXT[phase.kind]}
                </p>
              )}
              {phase.kind === "handed-off" && (
                <p className="text-[12px] break-keep text-ink-muted">
                  이 화면을 열어두지 않아도 됩니다 — 다시 방문하면 판정 결과를 보여줍니다.
                </p>
              )}
            </div>
          )}
        </section>
      ) : (
        <p className="text-[12.5px] break-keep text-ink-muted">
          설계 기준면을 올리려면 현장 등록 권한(SITES_WRITE)이 필요합니다. 아래 목록은
          읽기 전용입니다.
        </p>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-bold break-keep">등록된 설계 기준면</h2>
          <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
            전체 {surfaces.length}건 · 검증 완료 {verifiedCount}건
          </span>
        </div>

        {surfaces.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-8 text-center text-[13px] break-keep text-ink-muted">
            아직 등록된 설계 기준면이 없습니다.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {surfaces.map((surface) => (
              <SurfaceCard key={surface.designSurfaceId} surface={surface} />
            ))}
          </ul>
        )}

        {verifiedCount > 0 && (
          <p className="text-[12.5px] break-keep text-ink-muted">
            검증이 끝난 설계 기준면은 임무 화면의{" "}
            <strong className="font-bold">설계 대비 잔량</strong>에서 고를 수 있습니다 —
            같은 현장에서 촬영·재구성이 끝난 임무로 가세요.{" "}
            <Link
              href={`/missions?siteId=${encodeURIComponent(siteId)}`}
              className="font-semibold text-accent-text hover:underline"
            >
              이 현장의 임무 보기
            </Link>
          </p>
        )}
      </section>
    </div>
  );
}
