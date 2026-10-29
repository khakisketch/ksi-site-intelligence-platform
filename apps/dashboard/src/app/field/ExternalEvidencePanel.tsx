"use client";

import { ExternalUseBlockerCard } from "@/components/external-results/ExternalUseBlockerCard";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { FilePickerField } from "@/components/ui/FilePickerField";
import { putExternalEvidenceFile } from "@/lib/external-evidence-upload";
import { formatKoreanDateTime } from "@/lib/datetime";
import {
  describeArtifactKinds,
  duplicateSealedTargetKeys,
  formatRegistrationVersion,
  formatSealedTargetLabel,
  sealedTargetSubjectKey,
  decisionUseLabel,
  decisionVerdictLabel,
} from "@/app/field/registration-language";

type Revision = {
  submissionRef: string;
  state: "REGISTERED" | "SEALED";
  submission: {
    revision: number;
    artifacts?: { artifactId: string; kind: string; fileName: string }[];
  };
};

type EvidenceMeasurementSummary = {
  coreVerdict: string;
  measuredCheckpointCount: number;
  meanErrorM: number;
  maeM: number;
  rmseM: number;
  recordedAt: string;
};

type Evidence = {
  evidenceRef: string;
  state: "DECLARED" | "SEALED_BYTE_OBSERVED";
  targetDsmArtifactId: string;
  declaredContentDigest: string;
  declaredContentType: string;
  independenceBasis: string;
  measurementSummaries?: EvidenceMeasurementSummary[];
};

type DecisionSubject = {
  organizationId: string;
  siteId: string;
  workOrderId: string;
  submissionId: string;
  revision: number;
  submissionDigest: string;
  manifestDigest: string;
};

type DecisionZone = {
  zoneId: string;
  revision: number;
  definitionDigest: string;
  observedCrsDigest: string;
  observedVerticalReferenceDigest: string;
};

type Decision = {
  contractVersion?: string;
  decisionId: string;
  decisionDigest?: string;
  use: string;
  verdict: string;
  reasons: string[];
  remediations: string[];
  decidedAt: string;
  subject?: DecisionSubject;
  subjectDigest?: string;
  baselineSubject?: DecisionSubject;
  baselineSubjectDigest?: string;
  currentSubject?: DecisionSubject;
  currentSubjectDigest?: string;
  policyDigest?: string;
  inspectionReportDigest?: string;
  baselineInspectionReportDigest?: string;
  currentInspectionReportDigest?: string;
  evidenceRecordDigests?: string[];
  sanitizedDisplayReceiptDigest?: string;
  baselineSanitizedDisplayReceiptDigest?: string;
  currentSanitizedDisplayReceiptDigest?: string;
  zone?: DecisionZone;
  compatibilityMappingDigest?: string;
};

type Area = { workAreaId: string; name: string; status: "ACTIVE" | "ARCHIVED" };
type Pair = { value: string; label: string; workOrderId: string; revision: Revision };
type UploadAttempt = {
  file: File;
  digest: string;
  target: string;
  workOrderId: string;
  submissionRef: string;
  revision: number;
  artifactId: string;
  basis: string;
  keys: readonly [string, string, string];
  // 첫 시도 화면의 서버 파생 신원 비교값 — 재시도는 이 값을 그대로 보내 BFF가
  // 현재 세션과 비교한다. 원문 식별자는 클라이언트에 내보내지 않는다.
  continuity: string | null;
  // 첫 전송을 시작했으면 이후 401/403/404/422 거부는 이번 재시도만 확정하고
  // 이전 모호한 요청의 기록 여부를 단정하지 않는다.
  posted: boolean;
};
type EvidenceLoad = {
  phase: "loading" | "none" | "ready" | "error";
  items: Evidence[];
};
type DecisionSlot =
  | { phase: "pending" }
  | { phase: "ready"; decision: Decision }
  | { phase: "error" };

type PairLoadPhase = "loading" | "ready" | "partial" | "error";
type PairLoadFailure = { workOrderId: string; label: string };
type DecisionUse = "DISPLAY" | "HEIGHT" | "VISUAL_COMPARISON" | "RELATIVE_VOLUME" | "SINGLE_VOLUME";

const subject = (revision: Revision) => `${revision.submissionRef}:${revision.submission.revision}`;
const hasDsm = (revision: Revision) =>
  Boolean(revision.submission.artifacts?.some((artifact) => artifact.kind === "dsm"));
const makeKey = () => `console-${crypto.randomUUID()}`;

async function fileDigest(file: File, signal: AbortSignal): Promise<string> {
  const bytes = await file.arrayBuffer();
  if (signal.aborted) throw new DOMException("abort", "AbortError");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;
}

const coreValue = (value?: string | null) => value || "분석 시스템 기록 없음";

function DecisionSubjectBinding({
  label,
  subject,
  digest,
}: {
  label: string;
  subject?: DecisionSubject;
  digest?: string;
}) {
  if (!subject) return <p>{label}: 분석 시스템 기록 없음</p>;
  return (
    <div>
      <p className="break-all font-mono text-[12px] text-ink-2">{label} · {formatRegistrationVersion(subject.revision)}</p>
      <p>제출 식별자 {subject.submissionId} · 제출 확인값(해시) {subject.submissionDigest}</p>
      <p>목록 확인값(해시) {subject.manifestDigest} · 대상 확인값(해시) {coreValue(digest)}</p>
      <p className="break-all font-mono text-[12px] text-ink-2">원본 보관용 식별자 · 조직 {subject.organizationId} · 현장 {subject.siteId} · 작업 {subject.workOrderId}</p>
    </div>
  );
}

function DecisionBindings({ decision }: { decision: Decision }) {
  const pair = Boolean(decision.baselineSubject || decision.currentSubject);
  const inspectionBindings = pair
    ? [
        ["기준 검사 보고서 확인값(해시)", decision.baselineInspectionReportDigest],
        ["현재 검사 보고서 확인값(해시)", decision.currentInspectionReportDigest],
      ]
    : [["검사 보고서 확인값(해시)", decision.inspectionReportDigest]];
  const displayBindings = pair
    ? [
        ["기준 표시 영수증 확인값(해시)", decision.baselineSanitizedDisplayReceiptDigest],
        ["현재 표시 영수증 확인값(해시)", decision.currentSanitizedDisplayReceiptDigest],
      ]
    : [["표시 영수증 확인값(해시)", decision.sanitizedDisplayReceiptDigest]];

  return (
    <div className="mt-2 border-t border-line pt-2">
      <p>판정 식별자: {decision.decisionId}</p>
      <p>판정 확인값(해시): {coreValue(decision.decisionDigest)}</p>
      <p>계약 버전: {coreValue(decision.contractVersion)}</p>
      {pair ? (
        <>
          <DecisionSubjectBinding label="순서 있는 기준 대상" subject={decision.baselineSubject} digest={decision.baselineSubjectDigest} />
          <DecisionSubjectBinding label="순서 있는 현재 대상" subject={decision.currentSubject} digest={decision.currentSubjectDigest} />
        </>
      ) : (
        <DecisionSubjectBinding label="대상" subject={decision.subject} digest={decision.subjectDigest} />
      )}
      <p>정책 확인값(해시): {coreValue(decision.policyDigest)}</p>
      {inspectionBindings.map(([label, value]) => <p key={label}>{label}: {coreValue(value)}</p>)}
      <p>증거 기록 확인값(해시): {decision.evidenceRecordDigests?.join(", ") || "분석 시스템 기록 없음"}</p>
      {displayBindings.map(([label, value]) => <p key={label}>{label}: {coreValue(value)}</p>)}
      {pair && (
        <>
          <p>
            비교 구역: {decision.zone ? `${decision.zone.zoneId} · 구역 버전 ${decision.zone.revision}` : "분석 시스템 기록 없음"}
          </p>
          <p>작업구역 정의 확인값(해시): {coreValue(decision.zone?.definitionDigest)}</p>
          <p>관측 좌표계 확인값(해시): {coreValue(decision.zone?.observedCrsDigest)}</p>
          <p>관측 수직 기준 확인값(해시): {coreValue(decision.zone?.observedVerticalReferenceDigest)}</p>
          <p>호환성 매핑 확인값(해시): {coreValue(decision.compatibilityMappingDigest)}</p>
        </>
      )}
    </div>
  );
}

function DecisionReceipt({ decision, historical = false }: { decision: Decision; historical?: boolean }) {
  const headline = `${decisionUseLabel(decision.use)} · ${decisionVerdictLabel(decision.verdict)} · ${formatKoreanDateTime(decision.decidedAt, { dateStyle: "medium", timeStyle: "short" })}`;
  return (
    <div className="rounded border border-line p-2 text-ink-2">
      <p>
        {historical ? "과거 판정 기록" : "현재 분석 시스템 판정"}: {headline}
      </p>
      <p className="mt-1 text-[12px] text-ink-2">처리용 원본 코드 {decision.use} · {decision.verdict}는 파일 정보에서 확인할 수 있습니다.</p>
      {decision.verdict === "BLOCKED" ? (
        <ExternalUseBlockerCard reasons={decision.reasons} remediations={decision.remediations} />
      ) : (
        <>
          <p>사유: {decision.reasons.join(", ") || "없음"}</p>
          <p>조치: {decision.remediations.join(", ") || "없음"}</p>
        </>
      )}
      {historical && <details className="mt-2 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">파일 정보 · 처리 상세</summary><DecisionBindings decision={decision} /></details>}
      {historical && <p>과거 기록은 현재 사용 권한이나 실행 권한이 아닙니다.</p>}
    </div>
  );
}

function EvidenceItemState({ item }: { item: Evidence }) {
  const summaries = item.measurementSummaries ?? [];

  return (
    <div className="mt-2 rounded border border-line p-2 text-ink-2">
      <p>제출자가 적은 독립 근거: {item.independenceBasis}</p>
      <p>이 내용은 제출자가 적은 것으로, 분석 시스템이 독립성을 증명한 것은 아닙니다.</p>
      {item.state === "DECLARED" ? (
        <p>파일 제출 마무리 대기</p>
      ) : summaries.length === 0 ? (
        <p>분석 시스템 집계 대기</p>
      ) : (
        summaries.map((summary) => (
          <div key={`${summary.recordedAt}:${summary.coreVerdict}`} className="mt-2">
            <p className="font-semibold">분석 시스템 측정 집계</p>
            <p>판정: {decisionVerdictLabel(summary.coreVerdict)} (원본 {summary.coreVerdict})</p>
            <p>
              검사점 {summary.measuredCheckpointCount}개 · 평균 오차 {summary.meanErrorM}m · MAE {summary.maeM}m · RMSE {summary.rmseM}m
            </p>
            <p>분석 시스템 기록 시각: {formatKoreanDateTime(summary.recordedAt, { dateStyle: "medium", timeStyle: "short" })}</p>
          </div>
        ))
      )}
    </div>
  );
}

function EvidenceState({ load }: { load: EvidenceLoad | undefined }) {
  if (!load || load.phase === "loading") return <p>독립 검사점 증거를 읽는 중입니다.</p>;
  if (load.phase === "error") return <p role="alert">독립 검사점 증거를 읽지 못했습니다.</p>;
  if (load.phase === "none") return <p>독립 검사점 증거 없음</p>;
  return <>{load.items.map((item) => <EvidenceItemState key={item.evidenceRef} item={item} />)}</>;
}

// 확인 요청 한 건의 성패·경고는 그 요청 버튼 바로 옆에 둔다. 하단 공용
// 안내까지 스크롤해야 보이면 짧은 화면에서 복구 안내를 놓친다.
function DecisionUseMessage({ text, alert }: { text: string | null; alert: boolean }) {
  if (!text) return null;
  return <p role={alert ? "alert" : "status"}>{text}</p>;
}

function FreshDecisionConfirm({ hasFrozenRetry, onConfirm, onRetry, onKeep }: {
  hasFrozenRetry: boolean;
  onConfirm: () => void;
  onRetry: () => void;
  onKeep: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
      <p>새로 요청하면 같은 조건이라도 다른 판정 기록이 생길 수 있습니다. 기록에 이미 판정이 있는지 먼저 확인하세요. 같은 기록을 다시 보려면 과거 판정 기록 조회를 쓰세요.</p>
      <div className="flex flex-wrap gap-2">
        <button className="btn" onClick={onConfirm}>새 확인 요청 계속</button>
        {hasFrozenRetry && <button className="btn" onClick={onRetry}>같은 요청으로 다시 시도 (새 기록 없음)</button>}
        <button className="btn" onClick={onKeep}>유지</button>
      </div>
    </div>
  );
}

export function ExternalEvidencePanel({
  workOrderId,
  siteId,
  revisions,
  canWrite,
  newIntentAllowed = true,
  accountIdentity = null,
  legacyDecisionClosed = false,
  onRelativeVolumeDecisionChange,
  onSingleVolumeDecisionChange,
}: {
  workOrderId: string;
  siteId: string;
  revisions: Revision[];
  canWrite: boolean;
  newIntentAllowed?: boolean;
  accountIdentity?: { fingerprint: string } | null;
  /**
   * OIDC-first 배포 경계: registry 발급(scoped) 신원에는 Core가 기존 사용 결정
   * 경로를 닫는다. 참이면 확정 403이 되는 요청 버튼·기록 조회를 내놓지 않고,
   * 닫힘 안내와 지원 분석 경로로 연결한다. 증거·검사·봉인 기록은 그대로 둔다.
   */
  legacyDecisionClosed?: boolean;
  onRelativeVolumeDecisionChange?: (decision: Decision | null) => void;
  onSingleVolumeDecisionChange?: (decision: Decision | null) => void;
}) {
  const FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;
  // 첫 시도 화면의 서버 파생 신원 비교값 — 호출자 입력이 아니라 page가 서버에서
  // 읽은 값이다. 재시도는 이 값을 그대로 보내 BFF가 현재 세션과 비교한다.
  // 원문 식별자는 클라이언트에 내보내지 않는다.
  const boundFingerprint = accountIdentity?.fingerprint;
  const canBindNewAttempt =
    typeof boundFingerprint === "string" && FINGERPRINT_PATTERN.test(boundFingerprint);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  // 같은 확인의 연속 클릭·이중 전송을 막는다. busy는 비동기 상태라 빠른 두 번
  // 누름을 막지 못한다 — ref 잠금으로 dispatch 자체를 한 번만 허용한다.
  const decideLock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
      historyRequest.current?.abort();
    };
  }, []);
  const evidenceLoadGeneration = useRef(0);
  const pairLoadGeneration = useRef(0);
  const [target, setTarget] = useState<Revision | null>(null);
  const [baseline, setBaseline] = useState("");
  const [zone, setZone] = useState("");
  const [singleZone, setSingleZone] = useState("");
  const [areas, setAreas] = useState<Area[]>([]);
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [pairLoad, setPairLoad] = useState<PairLoadPhase>("loading");
  const [pairLoadFailures, setPairLoadFailures] = useState<PairLoadFailure[]>([]);
  const [pairReload, setPairReload] = useState(0);
  const [evidence, setEvidence] = useState<Record<string, EvidenceLoad>>({});
  const [file, setFile] = useState<File | null>(null);
  const [basis, setBasis] = useState("");
  const [upload, setUpload] = useState<UploadAttempt | null>(null);
  const [tries, setTries] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, DecisionSlot>>({});
  // 동결된 확인 시도 — 원래 키·내용·연산·묶인 첫 신원이 응답 미확인·401/403/
  // 404/422·같은 주체 재인증·BFF 검증 실패 뒤에도 복구 가능해야 한다. 키만
  // 남기면 내용이 바뀌어 다른 기록이 생긴다. 새로고침·이탈하면 사라진다.
  // 원래 작업·제출·개정·경로도 함께 동결한다 — 화면 속성이 바뀌어도 동결된
  // 같은 키 재시도가 다른 경로로 나가지 않는다(아래 실행은 동결 경로를 쓴다).
  const [attempts, setAttempts] = useState<
    Record<string, {
      key: string;
      body: Record<string, unknown>;
      continuity: string | null;
      posted: boolean;
      workOrderId: string;
      siteId: string;
      submissionRef: string;
      revision: number;
      endpoint: "single" | "pair" | "single-volume";
    }>
  >({});
  // 명시적 새 의도 확인 — 같은 조건의 재시도가 아니라 다른 기록을 만들 수
  // 있으니 경고 없이 새 키를 만들지 않는다.
  const [pendingFresh, setPendingFresh] = useState<{ use: DecisionUse; intent: string } | null>(null);
  // 동결된 증거 시도의 명시적 파기 확인 — 모호한 시도는 기록됐을 수 있으니
  // 경고 없이 해제하지 않는다. 확인 전까지 해제·자동 변이는 없다.
  const [confirmingEvidenceRestart, setConfirmingEvidenceRestart] = useState(false);
  const [message, setMessage] = useState("");
  // 검증·요청 실패는 alert로, 접수·완료 안내는 status로 읽힌다.
  const [messageAlert, setMessageAlert] = useState(false);
  // 확인 요청 메시지가 어느 사용 용도의 버튼 옆에 속하는지. 있으면 그 버튼
  // 옆에 직접 보여주고 하단 공용 안내는 비운다 — 긴 목록 아래에 묻히면
  // 짧은 화면에서 복구 안내를 놓친다. 없으면 하단 공용 안내에 둔다.
  const [messageUse, setMessageUse] = useState<DecisionUse | null>(null);
  const say = (text: string, alert = false) => {
    setMessage(text);
    setMessageAlert(alert);
    setMessageUse(null);
  };
  // 확인 요청 한 건의 성패·경고는 그 요청 버튼 옆에 둔다.
  const sayForUse = (use: DecisionUse, text: string, alert = false) => {
    setMessage(text);
    setMessageAlert(alert);
    setMessageUse(use);
  };
  const [historyRef, setHistoryRef] = useState("");
  const [history, setHistory] = useState<Decision | null>(null);
  const [busy, setBusy] = useState(false);

  const sealed = useMemo(() => revisions.filter((revision) => revision.state === "SEALED"), [revisions]);
  const current = target ? subject(target) : "";
  const choices = pairs.filter((item) => !target || item.value !== `${workOrderId}:${subject(target)}`);
  // 같은 작업에 제출 참조가 여럿 있을 수 있고 revision·파일명이 같을 수 있다.
  // 겹치는 보기 라벨에만 전체 제출 식별자를 덧붙인다. 기본은 식별자를 내보내지 않는다.
  const duplicateTargetKeys = useMemo(
    () => duplicateSealedTargetKeys(
      sealed.map((revision) => ({
        submissionRef: revision.submissionRef,
        revision: revision.submission.revision,
        artifacts: revision.submission.artifacts,
      })),
    ),
    [sealed],
  );

  const loadEvidence = useCallback(async (signal?: AbortSignal) => {
    const request = ++evidenceLoadGeneration.current;
    const loaded = await Promise.all(
      sealed.map(async (revision) => {
        try {
          const response = await fetch(
            `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/evidence`,
            { signal, cache: "no-store" },
          );
          if (!response.ok) return [subject(revision), { phase: "error", items: [] }] as const;
          const payload = (await response.json()) as { items: Evidence[] };
          return [
            subject(revision),
            { phase: payload.items.length === 0 ? "none" : "ready", items: payload.items },
          ] as const;
        } catch {
          return [subject(revision), { phase: "error", items: [] }] as const;
        }
      }),
    );
    if (!signal?.aborted && evidenceLoadGeneration.current === request) setEvidence(Object.fromEntries(loaded));
  }, [sealed, workOrderId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadEvidence(controller.signal);
    return () => controller.abort();
  }, [loadEvidence]);

  useEffect(() => {
    if (!siteId || legacyDecisionClosed) return;
    const controller = new AbortController();
    const request = ++pairLoadGeneration.current;
    void (async () => {
      try {
        const [areaResponse, orderResponse] = await Promise.all([
          fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas`, { signal: controller.signal, cache: "no-store" }),
          fetch(`/api/sites/${encodeURIComponent(siteId)}/observation-work-orders`, { signal: controller.signal, cache: "no-store" }),
        ]);
        if (!areaResponse.ok || !orderResponse.ok) throw new Error("could not read scoped choices");
        const orders = (await orderResponse.json()) as {
          workOrders: { workOrderId: string; name?: string; cycleNumber?: number }[];
        };
        const loaded = await Promise.all(
          orders.workOrders.map(async (order) => {
            try {
              const response = await fetch(
                `/api/observation-work-orders/${encodeURIComponent(order.workOrderId)}/external-reconstruction-submissions`,
                { signal: controller.signal, cache: "no-store" },
              );
              if (!response.ok) return { order, revisions: null };
              return { order, revisions: (await response.json() as { submissions: Revision[] }).submissions };
            } catch {
              return { order, revisions: null };
            }
          }),
        );
        if (controller.signal.aborted || pairLoadGeneration.current !== request) return;
        setAreas(((await areaResponse.json()) as { workAreas: Area[] }).workAreas.filter((area) => area.status === "ACTIVE"));
        setPairs(
          loaded.flatMap((row) =>
            row.revisions
              ? row.revisions
                  .filter((revision) => revision.state === "SEALED")
                  .map((revision) => ({
                    value: `${row.order.workOrderId}:${subject(revision)}`,
                    workOrderId: row.order.workOrderId,
                    revision,
                    label: `${row.order.name ?? "관측 작업"} · ${describeArtifactKinds(revision.submission.artifacts)} · ${formatRegistrationVersion(revision.submission.revision)} · ${revision.submission.artifacts?.map((artifact) => artifact.fileName).join(", ") ?? "산출물"}`,
                  }))
              : [],
          ),
        );
        const failures = loaded
          .filter((row) => !row.revisions)
          .map((row) => ({
            workOrderId: row.order.workOrderId,
            label: row.order.name ?? "이름 없는 관측 작업",
          }));
        setPairLoadFailures(failures);
        setPairLoad(failures.length === 0 ? "ready" : "partial");
      } catch {
        if (!controller.signal.aborted && pairLoadGeneration.current === request) {
          setPairLoadFailures([]);
          setPairLoad("error");
        }
      }
    })();
    return () => controller.abort();
  }, [pairReload, siteId, legacyDecisionClosed]);

  const reset = () => {
    generation.current += 1;
    const controller = active.current;
    active.current = null;
    controller?.abort();
    setBusy(false);
    decideLock.current = false;
    historyRequest.current?.abort();
    // 표시 상태(판정 슬롯·안내·조회)는 지우지만, 복구 재료(시도 키·동결된
    // 원래 키·내용·연속성)는 유지한다. 같은 화면에서 대상을 바꿨다가
    // 돌아와도 같은 요청으로 재시도할 수 있다. 새로고침·이탈하면 사라진다.
    // 부모의 발급 상태는 아래 동기화 effect가 현재 선택과 맞춰 정리한다.
    setDecisions({});
    setHistory(null);
    setHistoryRef("");
    setPendingFresh(null);
    setConfirmingEvidenceRestart(false);
    setMessage("");
    setMessageAlert(false);
    setMessageUse(null);
  };

  // 전송 실패 뒤에는 같은 파일·선언으로 재시도하는 것이 기본이다. 동결된
  // 시도가 모호하면(응답 미확인·거부된 재시도) 이미 접수됐을 수 있으니,
  // 해제 전에 먼저 경고하고 명시적 확인을 받는다. 확인 전까지는 해제하지
  // 않고, 버튼 한 번으로 새 키·새 요청이 나가지 않는다.
  const restartEvidence = () => {
    if (busy) return;
    setConfirmingEvidenceRestart(true);
  };
  const confirmEvidenceRestart = () => {
    if (busy) return;
    setConfirmingEvidenceRestart(false);
    setUpload(null);
    say("다른 파일·선언으로 새로 시작합니다. 이전 요청이 이미 접수됐을 수 있으니 목록 상태에서 증거가 있는지 먼저 확인하세요. 새로 시작하면 다른 증거 요청으로 등록되고 새 키를 사용합니다.");
  };
  const keepEvidenceAttempt = () => {
    setConfirmingEvidenceRestart(false);
  };

  const retryPairChoices = () => {
    setPairLoad("loading");
    setPairLoadFailures([]);
    setPairReload((value) => value + 1);
  };

  const decisionIntent = useCallback((
    use: DecisionUse,
    selected?: Pair,
    selectedZone?: string,
  ) => [
    current,
    use,
    selected?.value ?? "",
    use === "RELATIVE_VOLUME" || use === "SINGLE_VOLUME" ? selectedZone ?? "" : "",
  ].join("|"), [current]);

  // 슬롯 조회·확인이 쓰는 현재 선택의 의도. 동결 의도와 같은 규칙으로 묶는다:
  // 기준은 비교 두 시점에만, 구역은 체적 측정에만 쓴다.
  const draftIntentFor = useCallback((use: DecisionUse): string => {
    const pairForDraft = use === "VISUAL_COMPARISON" || use === "RELATIVE_VOLUME";
    const singleVolumeForDraft = use === "SINGLE_VOLUME";
    const selectedForDraft = pairForDraft
      ? choices.find((item) => item.value === baseline)
      : undefined;
    return decisionIntent(
      use,
      selectedForDraft,
      singleVolumeForDraft ? singleZone : zone,
    );
  }, [choices, baseline, zone, singleZone, decisionIntent]);

  // 발행(issue)에는 현재 선택과 정확히 묶인 준비 완료 판정만 부모에
  // 노출한다. 늦게 도착한 이전 조건의 응답이나 바뀐 선택이 부모의 발급
  // 상태를 오염시키지 않는다. 판정 슬롯 표시와 달리 폴백하지 않는다.
  // 늦은 응답은 도착 시점의 실제 선택과 비교하므로 오래된 클로저를 믿지
  // 않는다. 동결된 재시도 키·화면 표시는 그대로 둔다.
  // 판정 식별은 결정 ID만이 아니라 확인값·판정 결과까지 묶는다. 같은 ID라도
  // 확인값이 바뀌거나 usable 판정을 잃으면 부모에 새로 알려 fail-closed로
  // 닫는다 — 오래된 적격 판정을 현재 선택인 것처럼 유지하지 않는다.
  const notifiedIssuance = useRef<{ relative: string | null; single: string | null }>({ relative: null, single: null });
  const issuanceKey = (decision: Decision | null) =>
    decision ? `${decision.decisionId}|${decision.decisionDigest ?? ""}|${decision.verdict}` : null;

  useEffect(() => {
    const match = (use: "RELATIVE_VOLUME" | "SINGLE_VOLUME"): Decision | null => {
      const intent = draftIntentFor(use);
      // 부모 발급은 현재 문맥과 정확히 묶인 준비 완료 판정만 받는다. 동결된
      // 시도의 원래 작업·제출·개정이 현재 선택과 다르면 새 요청 없이 닫는다 —
      // 다른 작업의 판정이 현재 작업의 발급으로 둔갑하지 않는다.
      const frozenAttempt = attempts[intent];
      if (frozenAttempt && (frozenAttempt.workOrderId !== workOrderId || !target || frozenAttempt.submissionRef !== target.submissionRef || frozenAttempt.revision !== target.submission.revision)) {
        return null;
      }
      const slot = decisions[intent];
      return slot && slot.phase === "ready" ? slot.decision : null;
    };
    const matched = match("RELATIVE_VOLUME");
    const matchedKey = issuanceKey(matched);
    if (matchedKey !== notifiedIssuance.current.relative) {
      notifiedIssuance.current.relative = matchedKey;
      onRelativeVolumeDecisionChange?.(matched);
    }
    const matchedSingle = match("SINGLE_VOLUME");
    const matchedSingleKey = issuanceKey(matchedSingle);
    if (matchedSingleKey !== notifiedIssuance.current.single) {
      notifiedIssuance.current.single = matchedSingleKey;
      onSingleVolumeDecisionChange?.(matchedSingle);
    }
  }, [decisions, draftIntentFor, attempts, workOrderId, target, onRelativeVolumeDecisionChange, onSingleVolumeDecisionChange]);

  const slotEntriesFor = (use: DecisionUse) =>
    Object.entries(decisions).filter(([intent]) => intent.startsWith(`${current}|${use}|`));

  const currentSlot = (use: DecisionUse) => {
    const entries = slotEntriesFor(use);
    if (entries.length === 0) return undefined;
    // 같은 용도의 시도가 여럿이면 현재 선택과 정확히 맞는 것부터 보여준다.
    // 먼저 만든 오류 칸이 뒤에 만든 판정 기록을 가리면 새 기록을 확인할 수 없다.
    const draftIntent = draftIntentFor(use);
    return entries.find(([intent]) => intent === draftIntent)?.[1]
      ?? entries.find(([, slot]) => slot.phase === "ready")?.[1]
      ?? entries[0]?.[1];
  };

  // 슬롯이 가리키는 실제 판정의 의도. 현재 선택과 다르면 보존된 다른 조건의
  // 기록이므로 현재 선택의 기록처럼 보이지 않는다.
  const currentSlotIntent = (use: DecisionUse): string | null => {
    const entries = slotEntriesFor(use);
    if (entries.length === 0) return null;
    const draftIntent = draftIntentFor(use);
    return entries.find(([intent]) => intent === draftIntent)?.[0]
      ?? entries.find(([, slot]) => slot.phase === "ready")?.[0]
      ?? entries[0]?.[0] ?? null;
  };

  // 동결된 증거 시도와 현재 선택의 관계 — 다르면 같은 화면 복구는 동결된
  // 원래 경로·내용으로만 나가고, 현재 선택으로는 새 선언을 만들지 않는다.
  const frozenRevision = upload
    ? revisions.find((revision) => revision.submissionRef === upload.submissionRef && revision.submission.revision === upload.revision) ?? null
    : null;
  const uploadTargetMismatch = target !== null && upload !== null &&
    (upload.workOrderId !== workOrderId || upload.submissionRef !== target.submissionRef || upload.revision !== target.submission.revision);

  // 동결된 시도를 버리지 않고 원래 등록본 문맥으로 되돌린다. reset은 표시만
  // 정리하고 동결된 키·내용·경로·연속성은 유지한다. 결과는 모호하므로 단정하지
  // 않고 같은 요청 재시도·기록 확인 경로를 안내한다.
  const returnToFrozenUploadTarget = () => {
    if (!upload || !frozenRevision) return;
    reset();
    setTarget(frozenRevision);
    say("이전 증거 요청의 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 다시 시도하거나, 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.", true);
  };

  const uploadEvidence = async (fromFrozenContext = false) => {
    if (busy) return;
    if (!fromFrozenContext) {
      if (!target || !file || !basis.trim() || !hasDsm(target)) return;
    } else if (!upload) {
      return;
    }
    if (!newIntentAllowed && !upload) {
      say("업무 종료 상태에서는 새 증거 선언을 시작할 수 없습니다.", true);
      return;
    }
    // 새 선언은 묶인 첫 신원과 함께 만든다. 재시도는 동결된 원래 키·내용·경로·연속성을
    // 그대로 쓴다 — 현재 선택이 바뀌어도 다른 기록이 생기지 않는다. 신원
    // 확인값을 받지 못한 화면에서는 새 선언을 시작하지 않는다(동결된 재시도만 허용).
    // 이는 중복 방지 가드이며 Core 권한·범위 판단을 대신하지 않는다.
    if (!upload && !canBindNewAttempt) {
      say("계정을 확인하지 못해 새 증거 선언을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 이미 시작한 제출의 같은 증거 재시도는 계속할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.", true);
      return;
    }
    const controller = new AbortController();
    const scope = generation.current;
    active.current?.abort();
    active.current = controller;
    setBusy(true);
    const readCode = (value: unknown) =>
      value && typeof value === "object" && "code" in value
        ? String((value as { code?: unknown }).code ?? "")
        : "";
    try {
      let attempt = upload;
      if (!attempt) {
        // 동결 경로(fromFrozenContext)는 시도 없이는 도달하지 않는다. 새 선언
        // 경로는 현재 화면의 파일·대상이 있어야 만든다.
        if (!target || !file) throw new Error("evidence context changed");
        const artifactForNew = target.submission.artifacts?.find((item) => item.kind === "dsm");
        if (!artifactForNew) throw new Error("DSM no longer selected");
        attempt = {
          file,
          digest: await fileDigest(file, controller.signal),
          target: subject(target),
          workOrderId,
          submissionRef: target.submissionRef,
          revision: target.submission.revision,
          artifactId: artifactForNew.artifactId,
          basis: basis.trim(),
          keys: [makeKey(), makeKey(), makeKey()],
          continuity: boundFingerprint ?? null,
          posted: false,
        };
        setUpload(attempt);
      }
      const isRetry = attempt.posted;
      // 이후 401/403/404/422 거부는 이번 재시도만 확정한다. 이전 모호한 요청이
      // 이미 증거를 만들었을 수 있으므로 동결을 유지하고 기록 확인 경로를 살린다.
      setUpload({ ...attempt, posted: true });
      // 동결된 원래 경로·대상·내용으로 보낸다. 현재 작업·선택이 바뀌어도 같은
      // 선언으로 재시도하므로 다른 기록이 생기지 않는다.
      const root = `/api/observation-work-orders/${encodeURIComponent(attempt.workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(attempt.submissionRef)}/revisions/${attempt.revision}/evidence`;
      // 호출자 주장(principal 문자열)은 보내지 않는다. 비교값만 보내고, 현재
      // 신원은 BFF가 같은 요청의 세션 토큰 하나로 확인한다.
      const continuityHeaders: Record<string, string> = attempt.continuity
        ? { "x-ksi-continuity-fingerprint": attempt.continuity }
        : {};
      const declaredResponse = await fetch(root, {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": attempt.keys[0], ...continuityHeaders },
        body: JSON.stringify({
          targetDsmArtifactId: attempt.artifactId,
          declaredContentDigest: attempt.digest,
          declaredContentType: "text/csv",
          independenceBasis: attempt.basis,
        }),
        signal: controller.signal,
      });
      const declaredValue: unknown = await declaredResponse.json().catch(() => null);
      const declaredCode = readCode(declaredValue);
      // 계정이 바뀐 같은 키 재시도는 BFF가 Core 선언 없이 끊는다. 원래 키·내용을
      // 버리면 중복 기록으로 이어지므로 동결을 유지한다. 이는 중복 방지 가드이며
      // Core 권한·범위 판단을 대신하지 않는다.
      if (declaredResponse.status === 409 && declaredCode === "ACCOUNT_CONTINUITY_MISMATCH") {
        if (generation.current === scope && active.current === controller) {
          say("계정이 바뀌어 같은 증거 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 파일과 선언으로 다시 시도하세요. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.", true);
        }
        return;
      }
      if (declaredResponse.status === 400 && declaredCode === "INVALID_CONTINUITY_CLAIM") {
        if (generation.current === scope && active.current === controller) {
          say("계정 연속성 확인값이 올바르지 않아 증거 요청을 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 증거가 이미 있는지 확인하세요. 화면을 새로고침하면 서버에서 새 확인값을 받아옵니다. 새로고침하면 입력과 요청이 사라집니다.", true);
        }
        return;
      }
      // 같은 400 코드는 BFF의 사전 거절일 수도, Core에서 전달된 오류일 수도
      // 있다. 코드만으로 출처나 기록 여부를 단정하지 않고 원래 시도를 유지한다.
      if (declaredResponse.status === 400 && (declaredCode === "INVALID_EVIDENCE_INTENT")) {
        if (generation.current === scope && active.current === controller) {
          say(isRetry
            ? "다시 보낸 요청이 요청 형식 확인을 통과하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다."
            : "증거 선언 요청이 거부되어 결과를 확인하지 못했습니다. 기록되었는지 확인할 수 없으니 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요. 입력과 요청은 이 화면에 그대로 있습니다. 같은 파일과 선언으로는 같은 요청으로 다시 시도할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.", true);
        }
        return;
      }
      // 401/403/404/422는 첫 시도와 재시도를 구분한다. 첫 시도에서 받은 거부는
      // 확정적이다 — BFF 세션 게이트·BFF 검증·Core 권한 검사가 선언 본체보다
      // 먼저 거부하므로 어느 경우에도 증거가 기록되지 않았다. 반면 동결된
      // 시도(attempt.posted)의 재시도가 거부를 받으면, 그 거부는 이번 재시도만
      // 확정할 뿐이다. 이전 모호한 요청이 이미 증거를 만들었을 수 있으므로,
      // 원래 동결을 유지하고 같은 키 재시도·기록 확인 경로를 살린다.
      if (declaredResponse.status === 401 || declaredResponse.status === 403 || declaredResponse.status === 404 || declaredResponse.status === 422) {
        if (generation.current === scope && active.current === controller) {
          const definitive = !isRetry;
          if (declaredResponse.status === 401) {
            say(definitive
              ? "세션이 만료되어 증거 선언을 보내지 못했습니다. 증거는 기록되지 않았습니다. 입력과 요청은 이 화면에 그대로 있습니다. 같은 계정으로 다시 로그인한 뒤 같은 파일과 선언으로 다시 시도하세요."
              : "다시 보낸 증거 요청이 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 같은 계정으로 다시 로그인한 뒤 같은 파일과 선언으로 다시 시도하세요. 계정을 바꾸기 전에 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.", true);
          } else if (declaredResponse.status === 403) {
            say(definitive
              ? "이 증거를 선언할 권한이 없습니다. 증거는 기록되지 않았습니다. 현장 담당자에게 권한을 확인하세요. 등록된 증거와 이미 기록된 판정은 그대로 볼 수 있습니다."
              : "다시 보낸 증거 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 같은 파일과 선언으로 다시 시도하거나, 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.", true);
          } else if (declaredResponse.status === 404) {
            say(definitive
              ? "선언 대상을 찾지 못해 요청하지 못했습니다. 증거는 기록되지 않았습니다. 목록을 새로고침한 뒤 대상을 다시 선택하세요."
              : "다시 보낸 증거 요청에서 선언 대상을 찾지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.", true);
          } else {
            say(definitive
              ? "요청 내용이 확인 기준에 맞지 않아 접수되지 않았습니다. 증거는 기록되지 않았습니다. 입력값을 확인한 뒤 다른 파일·선언으로 새로 시작하세요."
              : "다시 보낸 증거 요청이 확인 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 확인 기준이나 정책이 바뀌면 이미 접수된 요청의 같은 키 재시도도 거부될 수 있습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.", true);
          }
        }
        return;
      }
      if (!declaredResponse.ok || !declaredValue || typeof declaredValue !== "object" || !("evidenceRef" in declaredValue)) throw new Error("declaration failed");
      const item = declaredValue as Evidence;
      if (
        item.targetDsmArtifactId !== attempt.artifactId ||
        item.declaredContentDigest !== attempt.digest ||
        item.declaredContentType !== "text/csv" ||
        item.independenceBasis !== attempt.basis
      ) {
        throw new Error("Core declaration binding changed");
      }
      if (item.state === "SEALED_BYTE_OBSERVED") {
        await loadEvidence(controller.signal);
        if (generation.current === scope) {
          setUpload(null);
          setConfirmingEvidenceRestart(false);
          setFile(null);
          setBasis("");
          // 성공 표시가 현재 다른 선택을 원래 요청의 주인으로 둔갑시키지
          // 않는다. 동결된 원래 작업·제출을 이름으로 밝히고 원래 기록을
          // 확인하게 한다. 목록 새로고침은 현재 작업 기준으로만 된다.
          const completedOutsideCurrentSelection =
            !target ||
            attempt.workOrderId !== workOrderId ||
            attempt.submissionRef !== target.submissionRef ||
            attempt.revision !== target.submission.revision;
          say(completedOutsideCurrentSelection
            ? `원래 요청(작업 ${attempt.workOrderId} · 제출 ${attempt.revision}회차 · ${attempt.artifactId})의 증거를 분석 시스템이 이미 받았습니다. 현재 선택한 등록본의 기록이 아니라 원래 요청의 기록을 확인하세요.`
            : "분석 시스템이 같은 파일을 이미 받았습니다.", false);
        }
        return;
      }
      const stepRefusal = (status: number, code: string, step: "grant" | "seal"): boolean => {
        if (status >= 200 && status < 300) return false;
        if (!mounted.current || generation.current !== scope || active.current !== controller) return true;
        const stepLabel = step === "grant" ? "파일 업로드 승인" : "파일 제출 마무리";
        if (status === 409 && code === "ACCOUNT_CONTINUITY_MISMATCH") {
          say(`계정이 바뀌어 같은 증거 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 파일과 선언으로 다시 시도하세요. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다. (${stepLabel} 단계)`, true);
          return true;
        }
        if (status === 400 && code === "INVALID_CONTINUITY_CLAIM") {
          say(`계정 연속성 확인값이 올바르지 않아 증거 요청을 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 증거가 이미 있는지 확인하세요. 화면을 새로고침하면 서버에서 새 확인값을 받아옵니다. 새로고침하면 입력과 요청이 사라집니다. (${stepLabel} 단계)`, true);
          return true;
        }
        // 승인·봉인 단계의 401/403/404/422는 선언이 같은 실행·이전 실행에서
        // 이미 접수됐을 수 있으므로 첫 시도라도 기록 여부를 단정하지 않는다.
        if (status === 401) {
          say(`${stepLabel} 단계에서 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 같은 계정으로 다시 로그인한 뒤 같은 파일과 선언으로 다시 시도하세요.`, true);
          return true;
        }
        if (status === 403) {
          say(`${stepLabel} 단계에서 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 같은 파일과 선언으로 다시 시도하거나, 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.`, true);
          return true;
        }
        if (status === 404) {
          say(`${stepLabel} 단계에서 확인 대상을 찾지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.`, true);
          return true;
        }
        if (status === 422) {
          say(`${stepLabel} 단계에서 확인 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.`, true);
          return true;
        }
        if (status === 400) {
          say(`${stepLabel} 단계에서 요청 형식 확인을 통과하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.`, true);
          return true;
        }
        return false;
      };
      const grant = await fetch(`${root}/${encodeURIComponent(item.evidenceRef)}/upload-grant`, {
        method: "POST",
        headers: { "idempotency-key": attempt.keys[1], ...continuityHeaders },
        signal: controller.signal,
      });
      const grantValue: unknown = await grant.json().catch(() => null);
      if (stepRefusal(grant.status, readCode(grantValue), "grant")) return;
      if (!grant.ok || !grantValue || typeof grantValue !== "object") throw new Error("grant failed");
      await putExternalEvidenceFile(grantValue as Parameters<typeof putExternalEvidenceFile>[0], attempt.file, controller.signal);
      const seal = await fetch(`${root}/${encodeURIComponent(item.evidenceRef)}/seal`, {
        method: "POST",
        headers: { "idempotency-key": attempt.keys[2], ...continuityHeaders },
        signal: controller.signal,
      });
      const sealValue: unknown = await seal.json().catch(() => null);
      if (stepRefusal(seal.status, readCode(sealValue), "seal")) return;
      if (!seal.ok) throw new Error("seal failed");
      const sealedValue: unknown = sealValue;
      if (!sealedValue || typeof sealedValue !== "object" || !("evidenceRef" in sealedValue)) throw new Error("seal binding changed");
      const sealedItem = sealedValue as Evidence;
      // 봉인 응답도 선언 때와 같은 내용물(대상·다이제스트·형식·근거)을 동결
      // 시도와 대조한다. 같은 식별자라도 내용이 다르면 봉인 확정으로 두지 않고
      // 원래 동결을 유지한 채 모름으로 둔다(생산 계약 ExternalEvidenceView가
      // 이 필드들을 실어 보내는 경우에 한해 검증되며, 계약이 바꾸면 다시 본다).
      if (sealedItem.evidenceRef !== item.evidenceRef || sealedItem.state !== "SEALED_BYTE_OBSERVED"
        || sealedItem.targetDsmArtifactId !== attempt.artifactId
        || sealedItem.declaredContentDigest !== attempt.digest
        || sealedItem.declaredContentType !== "text/csv"
        || sealedItem.independenceBasis !== attempt.basis) {
        throw new Error("seal binding changed");
      }
      await loadEvidence(controller.signal);
      if (generation.current === scope) {
        setUpload(null);
        setConfirmingEvidenceRestart(false);
        setFile(null);
        setBasis("");
        // 성공 표시가 현재 다른 선택을 원래 요청의 주인으로 둔갑시키지
        // 않는다. 동결된 원래 작업·제출을 이름으로 밝히고 원래 기록을
        // 확인하게 한다. 목록 새로고침은 현재 작업 기준으로만 된다.
        const completedOutsideCurrentSelection =
          !target ||
          attempt.workOrderId !== workOrderId ||
          attempt.submissionRef !== target.submissionRef ||
          attempt.revision !== target.submission.revision;
        say(completedOutsideCurrentSelection
          ? `원래 요청(작업 ${attempt.workOrderId} · 제출 ${attempt.revision}회차 · ${attempt.artifactId})의 증거를 분석 시스템이 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다. 현재 선택한 등록본의 기록이 아니라 원래 요청의 기록을 확인하세요.`
          : "분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.", false);
      }
    } catch {
      if (!controller.signal.aborted && generation.current === scope) {
        say("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.", true);
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        if (generation.current === scope) setBusy(false);
      }
    }
  };

  // 응답 미확인(모호한 제출) 뒤에는 같은 키 재시도가 기본이다. 동결된 원래
  // 내용·키·연속성으로 보내므로, 재시도 전에 선택을 바꿔도 다른 기록이
  // 생기지 않는다. 명시적인 새 의도만이 새 키를 만든다 — 기록에 이미 판정이
  // 있을 수 있으니 먼저 확인하고, 경고 뒤에 두 번 눌러 계속한다.
  const confirmFreshDecision = () => {
    const pending = pendingFresh;
    setPendingFresh(null);
    if (!pending) return;
    // 경고 뒤에 선택이 바뀌면 바뀐 조건에 대해 다시 경고하고 보내지 않는다.
    // 확인은 본 조건에 대해서만 유효하다.
    const now = draftIntentFor(pending.use);
    if (now !== pending.intent) {
      setPendingFresh({ use: pending.use, intent: now });
      sayForUse(pending.use, "선택이 바뀌었습니다. 새로 요청하면 바뀐 조건으로 다른 판정 기록이 생길 수 있습니다. 기록에 이미 판정이 있는지 먼저 확인하세요. 같은 기록을 다시 보려면 과거 판정 기록 조회를 쓰세요.", true);
      return;
    }
    void decide(pending.use, true, true);
  };

  const buildDecisionBody = (
    use: DecisionUse,
    selected: Pair | undefined,
    zoneValue: string,
    singleZoneValue: string,
  ): Record<string, unknown> | null => {
    if (use === "SINGLE_VOLUME") return { zoneId: singleZoneValue };
    if (use === "VISUAL_COMPARISON" || use === "RELATIVE_VOLUME") {
      if (!selected) return null;
      return {
        use,
        baselineWorkOrderId: selected.workOrderId,
        baselineSubmissionRef: selected.revision.submissionRef,
        baselineRevision: selected.revision.submission.revision,
        ...(use === "RELATIVE_VOLUME" ? { zoneId: zoneValue } : {}),
      };
    }
    return { use };
  };

  const decide = async (use: DecisionUse, fresh = false, confirmed = false) => {
    if (!target || busy || decideLock.current) return;
    const pair = use === "VISUAL_COMPARISON" || use === "RELATIVE_VOLUME";
    const singleVolume = use === "SINGLE_VOLUME";
    // A single-epoch volume never binds a baseline, even when one is selected for another use.
    // 단일 확인(DISPLAY·HEIGHT)의 기준 선택도 전송 내용과 무관한 화면
    // 선택이라 동결 의도에 넣지 않는다 — 동결은 실제 POST 본문에만 묶는다.
    const selected = pair ? choices.find((item) => item.value === baseline) : undefined;
    if (pair && !selected) {
      sayForUse(use, "비교할 이전 등록 버전을 선택하세요.", true);
      return;
    }
    if (use === "RELATIVE_VOLUME" && !zone) {
      sayForUse(use, "변화 분석 구역을 선택하세요.", true);
      return;
    }
    if (singleVolume && !singleZone) {
      sayForUse(use, "한 시점 측정 구역을 선택하세요.", true);
      return;
    }
    if ((use === "HEIGHT" || use === "RELATIVE_VOLUME" || singleVolume) && !hasDsm(target)) {
      sayForUse(use, "DSM이 없어 이 확인을 요청할 수 없습니다.", true);
      return;
    }
    const intent = decisionIntent(use, selected, singleVolume ? singleZone : zone);
    if (!newIntentAllowed && (!tries[intent] || fresh)) {
      sayForUse(use, "업무 종료 상태에서는 새 사용 결정을 요청할 수 없습니다.", true);
      return;
    }
    const frozen = attempts[intent];
    // 새 키가 필요한 모든 경우(명시적 fresh·바뀐 조건)에는 같은 용도·대상의
    // 이전 시도가 있으면 먼저 경고한다. 같은 조건의 재시도(frozen)는 새 기록을
    // 만들지 않으므로 경고 없이 같은 키로 보낸다. 경고 뒤에 선택이 바뀌면
    // 바뀐 조건에 대해 다시 경고한다. 다른 용도의 시도는 막지 않는다.
    // 문구는 확정된 기록과 모호한 시도를 구분한다: 준비 완료 판정이 실제로
    // 알려져 있을 때만 기록 존재를 말하고, 그 외에는 이전 요청이 있었고
    // 기록됐을 수 있다는 가능성만 말한다. 응답을 잃은 시도·확정 거부 뒤의
    // 재시도는 이전 요청의 성패를 단정하지 않는다.
    const priorSameSubjectAttempt = Object.keys(tries).some(
      (key) => key !== intent && key.startsWith(`${current}|${use}|`),
    );
    const needsNewKey = fresh || !frozen;
    const confirmedForIntent =
      confirmed && pendingFresh !== null && pendingFresh.use === use && pendingFresh.intent === intent;
    const readyKnown = currentSlot(use)?.phase === "ready";
    if (needsNewKey && (tries[intent] || priorSameSubjectAttempt) && !confirmedForIntent) {
      setPendingFresh({ use, intent });
      if (readyKnown) {
        sayForUse(use, "이미 확인된 판정 기록이 있습니다. 새로 요청하면 같은 조건이라도 다른 판정 기록이 생길 수 있습니다. 같은 기록을 다시 보려면 아래에서 같은 요청으로 다시 시도하거나 과거 판정 기록 조회를 쓰세요. 기록에 이미 판정이 있는지 먼저 확인하세요.", true);
      } else {
        sayForUse(use, "이전에 확인 요청을 보냈습니다. 결과를 확인하지 못했다면 판정이 이미 기록됐을 수 있습니다. 새로 요청하면 다른 판정 기록이 생길 수 있으니, 기록에 이미 판정이 있는지 먼저 확인하세요. 같은 기록을 다시 보려면 과거 판정 기록 조회를 쓰세요.", true);
      }
      return;
    }
    if (needsNewKey) setPendingFresh(null);
    // 새 키는 묶인 첫 신원과 함께 만든다. 재시도는 동결된 원래 키·내용·연속성을
    // 그대로 쓴다 — 현재 선택이 바뀌어도 다른 기록이 생기지 않는다. 신원
    // 확인값을 받지 못한 화면에서는 새 요청을 시작하지 않는다(재시도만 허용).
    if ((!frozen || fresh) && !canBindNewAttempt) {
      sayForUse(use, "계정을 확인하지 못해 새 확인 요청을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 새로고침하면 입력과 요청이 사라집니다.", true);
      return;
    }
    const body = (!fresh && frozen) ? frozen.body : buildDecisionBody(use, selected, zone, singleZone);
    if (!body) {
      sayForUse(use, "비교할 이전 등록 버전을 선택하세요.", true);
      return;
    }
    const attempt = (!fresh && frozen)
      ? frozen
      : {
        key: makeKey(),
        body,
        continuity: boundFingerprint ?? null,
        posted: false,
        workOrderId,
        siteId,
        submissionRef: target.submissionRef,
        revision: target.submission.revision,
        endpoint: (singleVolume ? "single-volume" : pair ? "pair" : "single") as "single" | "pair" | "single-volume",
      };
    const isRetry = attempt.posted;
    if (!tries[intent] || fresh) setTries((previous) => ({ ...previous, [intent]: attempt.key }));
    setAttempts((previous) => ({ ...previous, [intent]: { ...attempt, posted: true } }));
    decideLock.current = true;
    const controller = new AbortController();
    const scope = generation.current;
    active.current?.abort();
    active.current = controller;
    setBusy(true);
    // 부모의 발급 상태는 아래 동기화 effect가 현재 선택과 맞춰 정리한다.
    // 여기서 직접 비우면 늦게 도착한 이전 조건의 응답이 다시 덮어쓸 수 있다.
    setDecisions((previous) => ({ ...previous, [intent]: { phase: "pending" } }));
    try {
      // 동결된 재시도는 동결된 원래 작업·제출·개정·경로로만 나간다. 화면 속성
      // (작업·선택)이 바뀌어도 다른 경로로 새 요청을 보내지 않는다.
      // decisionIntent에는 작업 식별자를 넣지 않으므로(상태 키일 뿐), 경로는
      // 반드시 동결 값으로 재구성한다.
      const root = `/api/observation-work-orders/${encodeURIComponent(attempt.workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(attempt.submissionRef)}/revisions/${attempt.revision}/use-decisions`;
      const headers: Record<string, string> = {
        "content-type": "application/json",
        "idempotency-key": attempt.key,
      };
      // 호출자 주장(principal 문자열)은 보내지 않는다. 비교값만 보내고, 현재
      // 신원은 BFF가 같은 요청의 세션 토큰 하나로 확인한다.
      if (attempt.continuity) headers["x-ksi-continuity-fingerprint"] = attempt.continuity;
      const response = attempt.endpoint === "single-volume"
        ? await fetch(`${root}/single-volume`, {
            method: "POST",
            headers,
            body: JSON.stringify(attempt.body),
            signal: controller.signal,
          })
        : attempt.endpoint === "pair"
        ? await fetch(`${root}/pair`, {
            method: "POST",
            headers,
            body: JSON.stringify(attempt.body),
            signal: controller.signal,
          })
        : await fetch(`${root}/single`, {
            method: "POST",
            headers,
            body: JSON.stringify(attempt.body),
            signal: controller.signal,
          });
      const value: unknown = await response.json().catch(() => null);
      const responseCode = value && typeof value === "object" && "code" in value
        ? String((value as { code?: unknown }).code ?? "")
        : "";
      // 계정이 바뀐 같은 키 재시도는 BFF가 Core 결정 없이 끊는다. 원래 키·내용을
      // 버리면 중복 기록으로 이어지므로 동결을 유지한다. 이는 중복 방지 가드이며
      // Core 권한·범위 판단을 대신하지 않는다.
      if (response.status === 409 && responseCode === "ACCOUNT_CONTINUITY_MISMATCH") {
        if (mounted.current && generation.current === scope && active.current === controller) {
          setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
          sayForUse(use, "계정이 바뀌어 같은 확인 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 다른 탭에서 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.", true);
        }
        return;
      }
      if (response.status === 400 && responseCode === "INVALID_CONTINUITY_CLAIM") {
        if (mounted.current && generation.current === scope && active.current === controller) {
          setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
          sayForUse(use, "계정 연속성 확인값이 올바르지 않아 요청을 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 판정이 이미 있는지 확인하세요. 화면을 새로고침하면 서버에서 새 확인값을 받아옵니다. 새로고침하면 입력과 요청이 사라집니다.", true);
        }
        return;
      }
      // 같은 400 코드는 BFF의 사전 거절일 수도, Core에서 전달된 오류일 수도
      // 있다. 코드만으로 출처나 기록 여부를 단정하지 않고 원래 시도·키·내용을
      // 유지한다. 재시도 거절도 이전 요청의 결과를 증명하지 않는다.
      if (response.status === 400 && (responseCode === "INVALID_EXTERNAL_USE_INTENT" || responseCode === "INVALID_EXTERNAL_PAIR_INTENT" || responseCode === "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT")) {
        if (mounted.current && generation.current === scope && active.current === controller) {
          setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
          if (isRetry) {
            sayForUse(use, "다시 보낸 요청이 요청 형식 확인을 통과하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.", true);
          } else {
            sayForUse(use, "확인 요청이 거부되어 결과를 확인하지 못했습니다. 기록되었는지 확인할 수 없으니 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요. 입력과 요청은 이 화면에 그대로 있습니다. 같은 선택에서는 같은 요청으로 다시 시도할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.", true);
          }
        }
        return;
      }
      // 401/403/404/422는 첫 시도와 재시도를 구분한다. 첫 시도에서 받은 거부는
      // 확정적이다 — BFF 세션 게이트·BFF 검증·Core 권한 검사가 결정 본체보다
      // 먼저 거부하므로 어느 경우에도 판정이 기록되지 않았다. 반면 동결된
      // 시도(attempt.posted)의 재시도가 거부를 받으면, 그 거부는 이번 재시도만
      // 확정할 뿐이다. 이전 모호한 요청이 이미 판정을 만들었을 수 있으므로,
      // 원래 동결을 유지하고 같은 키 재시도·기록 확인 경로를 살린다.
      if (response.status === 401 || response.status === 403 || response.status === 404 || response.status === 422) {
        if (mounted.current && generation.current === scope && active.current === controller) {
          setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
          const definitive = !isRetry;
          if (response.status === 401) {
            sayForUse(use, definitive
              ? "세션이 만료되어 확인 요청을 보내지 못했습니다. 판정은 기록되지 않았습니다. 입력과 요청은 이 화면에 그대로 있습니다. 같은 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하세요."
              : "다시 보낸 요청이 세션 만료로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 같은 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하세요. 계정을 바꾸기 전에 기록에서 원래 요청의 판정이 이미 있는지 먼저 확인하세요.", true);
          } else if (response.status === 403) {
            sayForUse(use, definitive
              ? "이 확인을 요청할 권한이 없습니다. 판정은 기록되지 않았습니다. 현장 담당자에게 권한을 확인하세요. 증거와 이미 기록된 판정은 그대로 볼 수 있습니다. 새로운 정량 비교는 현장의 분석 화면에서 진행합니다."
              : "다시 보낸 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 같은 요청으로 다시 시도하거나, 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요. 증거와 이미 기록된 판정은 그대로 볼 수 있습니다.", true);
          } else if (response.status === 404) {
            sayForUse(use, definitive
              ? "확인 대상을 찾지 못해 요청하지 못했습니다. 판정은 기록되지 않았습니다. 목록을 새로고침한 뒤 대상을 다시 선택하세요."
              : "다시 보낸 요청에서 확인 대상을 찾지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요.", true);
          } else {
            sayForUse(use, definitive
              ? "요청 내용이 확인 기준에 맞지 않아 접수되지 않았습니다. 판정은 기록되지 않았습니다. 입력값을 확인한 뒤 새로 요청하세요."
              : "다시 보낸 요청이 확인 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 확인 기준이나 정책이 바뀌면 이미 접수된 요청의 같은 키 재시도도 거부될 수 있습니다. 입력과 요청은 이 화면에 그대로 있습니다. 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요.", true);
          }
        }
        return;
      }
      if (!response.ok || !value || typeof value !== "object" || !("decision" in value)) throw new Error("decision failed");
      const decision = (value as { decision: Decision }).decision;
      // 생산 계약은 후보 전체를 그대로 실어 보낸다(Core model_dump → BFF
      // 직렬화, TS 타입은 정적 부분집합). 원래 요청과 대조할 수 있는 것은
      // use·decisionId·판정 형태·표시 필드, 그리고 subject 계열의
      // workOrderId·siteId·revision과 구역(zoneId)이다.
      // submissionId는 Core 내부 불투명 식별자로, 화면이 가진 제출 참조와
      // 변환·대조하지 않는다(독립 증인 없음).
      const responseRecord = (decision && typeof decision === "object" ? decision : null) as unknown as Record<string, unknown> | null;
      const responseUse = responseRecord?.use;
      const responseId = responseRecord?.decisionId;
      const responseVerdict = responseRecord?.verdict;
      const expectedResponseUse = attempt.endpoint === "single-volume"
        ? "SINGLE_VOLUME"
        : (attempt.body as { use?: unknown }).use;
      const subjectOf = (name: string): Record<string, unknown> | null => {
        const candidate = responseRecord?.[name];
        return candidate && typeof candidate === "object" ? (candidate as Record<string, unknown>) : null;
      };
      const subjectMatches = (candidate: Record<string, unknown> | null, workOrderIdValue: unknown, siteIdValue: unknown, revisionValue: unknown): boolean =>
        !!candidate
        && typeof candidate.workOrderId === "string" && candidate.workOrderId === workOrderIdValue
        && typeof candidate.siteId === "string" && candidate.siteId === siteIdValue
        && typeof candidate.revision === "number" && candidate.revision === revisionValue;
      const zoneOf = subjectOf("zone");
      const zoneIdOf = zoneOf && typeof zoneOf.zoneId === "string" ? zoneOf.zoneId : null;
      const frozenBody = attempt.body as { use?: unknown; baselineWorkOrderId?: unknown; baselineRevision?: unknown; zoneId?: unknown };
      // 표시·부모 전달 전에 join되므로 사유·조치 항목은 문자열이어야 한다.
      const stringArrayOf = (value: unknown): value is string[] =>
        Array.isArray(value) && value.every((item) => typeof item === "string");
      let scopeBound = !!decision && typeof responseId === "string" && responseId.length > 0
        && responseUse === expectedResponseUse
        && (responseVerdict === "ELIGIBLE" || responseVerdict === "RESTRICTED" || responseVerdict === "BLOCKED")
        && stringArrayOf(responseRecord?.reasons) && stringArrayOf(responseRecord?.remediations)
        && typeof responseRecord?.decidedAt === "string" && (responseRecord?.decidedAt as string).length > 0
        && typeof responseRecord?.decisionDigest === "string" && (responseRecord?.decisionDigest as string).length > 0;
      if (scopeBound) {
        if (attempt.endpoint === "single" || attempt.endpoint === "single-volume") {
          scopeBound = subjectMatches(subjectOf("subject"), attempt.workOrderId, attempt.siteId, attempt.revision);
          if (scopeBound && (attempt.endpoint === "single-volume" || expectedResponseUse === "RELATIVE_VOLUME")) {
            // 구역이 계약상 존재하는 경우(단일 체적·상대 체적의 적격 판정)에만
            // 동결 구역과 대조한다. BLOCKED는 구역 없이도 차단 표시를 살린다.
            // 비교 확인(VISUAL_COMPARISON)은 구역을 요구하지 않는다.
            scopeBound = responseVerdict === "BLOCKED" || zoneIdOf === frozenBody.zoneId;
          } else if (scopeBound && expectedResponseUse === "VISUAL_COMPARISON") {
            scopeBound = zoneOf === null;
          }
        } else {
          const baselineSubject = subjectOf("baselineSubject");
          const currentSubject = subjectOf("currentSubject");
          // 동결 siteId는 두 subject 모두의 실제 증인이다(쌍 workOrder 목록이
          // 현장 범위로 얼고, Core도 쌍의 조직·현장 일치를 강제한다).
          // 조직은 따로 얼린 증인이 없으므로, 양쪽이 원문으로 있을 때만 서로
          // 대조한다. submissionId(불투명 내부 식별자)는 대조하지 않는다.
          const baselineOrg = baselineSubject?.organizationId;
          const currentOrg = currentSubject?.organizationId;
          scopeBound = subjectMatches(currentSubject, attempt.workOrderId, attempt.siteId, attempt.revision)
            && !!baselineSubject
            && baselineSubject.workOrderId === frozenBody.baselineWorkOrderId
            && baselineSubject.revision === frozenBody.baselineRevision
            && baselineSubject.siteId === attempt.siteId
            && (typeof baselineOrg !== "string" || typeof currentOrg !== "string" || baselineOrg === currentOrg);
          if (scopeBound && expectedResponseUse === "RELATIVE_VOLUME") {
            scopeBound = responseVerdict === "BLOCKED" || zoneIdOf === frozenBody.zoneId;
          } else if (scopeBound) {
            scopeBound = zoneOf === null;
          }
        }
      }
      // 다른 용도·범위·구역·현장·조직의 2xx, 빈 식별자, 계약에 없는 판정·형태는
      // 이 요청의 준비 완료가 될 수 없으므로 원래 동결을 유지한 채 모름으로
      // 둔다. 발급 경로 오염을 막는다. 부모가 이미 적격 판정을 가졌다면
      // effect가 null로 닫는다. submissionId(불투명 내부 식별자)·단일 subject의
      // 조직(대조할 다른 subject 없음)·구역 밖 식별자는 대조하지 않는다.
      if (!scopeBound) {
        throw new Error("decision binding changed");
      }
      if (generation.current === scope && active.current === controller) {
        setDecisions((previous) => ({ ...previous, [intent]: { phase: "ready", decision } }));
        // 부모의 발급 상태는 아래 동기화 effect가 현재 선택과 맞춰 정리한다.
        // 늦게 도착한 응답이라도 도착 시점의 실제 선택과 비교되므로, 오래된
        // 조건의 판정이 현재 선택의 발급으로 둔갑하지 않는다.
      }
    } catch {
      if (!controller.signal.aborted && mounted.current && generation.current === scope && active.current === controller) {
        setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
        sayForUse(use, "응답을 확인하지 못했습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 같은 요청으로 다시 시도하세요. 먼저 기록에서 판정이 이미 있는지 확인하면 중복을 피할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.", true);
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        decideLock.current = false;
        if (mounted.current && generation.current === scope) setBusy(false);
      }
    }
  };

  const loadHistoricalDecision = async () => {
    if (!target) return;
    if (!/^external-use-decision-[0-9a-f]{32}$/.test(historyRef)) {
      say("유효한 과거 판정 기록 참조를 입력하세요.", true);
      return;
    }
    const scope = generation.current;
    const controller = new AbortController();
    historyRequest.current?.abort();
    historyRequest.current = controller;
    try {
      const response = await fetch(
        `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(target.submissionRef)}/revisions/${target.submission.revision}/use-decisions/${historyRef}`,
        { signal: controller.signal, cache: "no-store" },
      );
      if (!response.ok) throw new Error("history lookup failed");
      const value = (await response.json() as { decision: Decision }).decision;
      if (generation.current === scope && historyRequest.current === controller) setHistory(value);
    } catch {
      if (!controller.signal.aborted && generation.current === scope && historyRequest.current === controller) {
        setHistory(null);
        say("과거 판정 기록을 읽지 못했습니다.", true);
      }
    } finally {
      if (historyRequest.current === controller) historyRequest.current = null;
    }
  };

  return (
    <section id="external-evidence" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
      <h2 className="text-[16px] font-bold">독립 검사점 증거와 사용 결정</h2>
      {!newIntentAllowed && <p className="rounded-lg border border-line bg-sunk px-3 py-2 leading-5 text-ink-2">업무 종료 상태입니다. 새 증거와 사용 결정은 요청할 수 없지만, 기록과 이미 시작한 봉인 상태는 계속 확인할 수 있습니다.</p>}
      <ul>
        {sealed.map((revision) => {
          const isSelected = target !== null && subject(target) === subject(revision);
          return (
          <li key={subject(revision)}>
            <button
              className="btn max-w-full flex-col items-start whitespace-normal break-all text-left"
              aria-current={isSelected ? "true" : undefined}
              onClick={() => {
                // reset은 표시만 정리하고 동결된 증거 시도·결정 시도는 유지한다.
                // 대상을 바꿔도 모호한 시도가 조용히 버려지지 않는다. 원래
                // 문맥으로 돌아가면 같은 키·내용으로 재시도할 수 있다.
                reset();
                setTarget(revision);
              }}
            >
              <span className="block font-semibold">{formatSealedTargetLabel(revision.submission.revision, revision.submission.artifacts)}{isSelected ? " · 선택됨" : ""}</span>
              <span className="mt-0.5 block break-all text-[12px] text-ink-2">{revision.submission.artifacts?.map((artifact) => artifact.fileName).join(", ")}</span>
              {duplicateTargetKeys.has(sealedTargetSubjectKey({ submissionRef: revision.submissionRef, revision: revision.submission.revision })) && (
                <span className="mt-0.5 block break-all font-mono text-[11.5px] text-ink-muted">제출 식별자 · {revision.submissionRef}</span>
              )}
            </button>
            {!hasDsm(revision) && <p>DSM 없음: 표시는 가능하지만 독립 검사점·높이 확인·변화 분석은 제한됩니다.</p>}
            <EvidenceState load={evidence[subject(revision)]} />
          </li>
          );
        })}
      </ul>

      {!legacyDecisionClosed && pairLoad === "loading" && <p>비교할 이전 등록 버전과 작업구역을 읽는 중입니다.</p>}
      {!legacyDecisionClosed && (pairLoad === "error" || pairLoad === "partial") && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <p>비교할 이전 등록 버전 또는 작업구역을 읽지 못했습니다.</p>
          {pairLoad === "partial" && (
            <p>
              일부 같은 현장 작업의 비교 대상을 읽지 못했습니다: {pairLoadFailures.map((failure) => failure.label).join(", ")}. 목록이 완전하지 않습니다.
            </p>
          )}
          <button className="btn" onClick={retryPairChoices}>비교 대상 다시 시도</button>
        </div>
      )}

      {target && (
        <>
          <h3 className="text-[14px] font-bold">선택한 등록본 · {formatSealedTargetLabel(target.submission.revision, target.submission.artifacts)}</h3>
          {/* 동결된 증거 시도가 현재 선택과 다른 문맥이면, 조용히 버리는 대신
              원래 요청의 복구 경로를 내놓는다. 선택만으로는 어떤 변이도 나가지
              않는다. 동결은 이 화면의 메모리에만 있어 새로고침·이탈·다른 기기에는
              이어지지 않는다. */}
          {uploadTargetMismatch && upload && (
            <div role="alert" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
              <p>다른 등록본에서 시작한, 전송 상태를 확인하지 못한 증거 요청이 있습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.</p>
              <p className="break-all text-[12px] leading-5 text-ink-2">원래 요청 · 작업 {upload.workOrderId} · 제출 {upload.revision}회차 · {upload.artifactId} · {upload.file.name}</p>
              <p className="text-[12px] leading-5 text-ink-2">이 요청은 이 화면의 메모리에만 있습니다. 새로고침·화면 이탈·다른 기기에서는 같은 요청으로 이어지지 않습니다.</p>
              {/* 재시도 변이는 쓰기 권한과 노트북 화면 경계 안에만 둔다. 알림과
                  돌아가기는 읽기 전용이라 그대로 둔다. */}
              {canWrite ? (
                <ResponsiveActionBoundary
                  action="EXTERNAL_RECONSTRUCTION_MUTATION"
                  reason="이 화면을 유지한 채 노트북 크기로 넓혀 원래 계정으로 다시 시도하세요. 화면을 떠나면 이 요청은 사라집니다."
                >
                  <div className="flex flex-wrap gap-2">
                    <button className="btn" disabled={busy} onClick={() => void uploadEvidence(true)}>같은 요청으로 다시 시도</button>
                  </div>
                </ResponsiveActionBoundary>
              ) : (
                <p className="text-[12px] leading-5 text-ink-2">읽기 전용 화면에서는 다시 시도할 수 없습니다. 이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면 노트북 크기에서 같은 요청으로 다시 시도할 수 있습니다.</p>
              )}
              <div className="flex flex-wrap gap-2">
                {upload.workOrderId === workOrderId && frozenRevision && (
                  <button className="btn" onClick={returnToFrozenUploadTarget}>원래 등록본으로 돌아가기</button>
                )}
              </div>
            </div>
          )}
          {/* 같은 문맥의 동결된 증거 시도는 읽기 전용에서도 복구 경로를 잃지
              않는다. 불확실·기록 확인은 그대로 두고 변이는 내놓지 않는다. */}
          {!uploadTargetMismatch && upload && !canWrite && (
            <div role="status" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
              <p>전송 상태를 확인하지 못한 증거 요청이 있습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요.</p>
              <p className="break-all text-[12px] leading-5 text-ink-2">원래 요청 · 작업 {upload.workOrderId} · 제출 {upload.revision}회차 · {upload.artifactId} · {upload.file.name}</p>
              <p className="text-[12px] leading-5 text-ink-2">읽기 전용 화면에서는 다시 시도할 수 없습니다. 이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면 같은 요청으로 다시 시도할 수 있습니다. 새로고침·화면 이동·기기 변경 시 이 화면의 요청은 사라집니다.</p>
            </div>
          )}
          {/* 확인하지 못한 사용 결정도 읽기 전용에서 모름·기록 확인을 잃지
              않는다. 재시도 버튼은 쓰기 경계 안에만 있다. */}
          {!canWrite && (["DISPLAY", "HEIGHT", "VISUAL_COMPARISON", "RELATIVE_VOLUME", "SINGLE_VOLUME"] as const).some((use) => currentSlot(use)?.phase === "error") && (
            <div role="status" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
              <p>확인하지 못한 사용 결정 요청이 있습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 먼저 기록에서 원래 요청의 판정이 이미 있는지 확인하세요. 이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면 같은 요청으로 다시 시도할 수 있습니다. 새로고침·화면 이동·기기 변경 시 이 화면의 요청은 사라집니다.</p>
            </div>
          )}
          {/* 사용 결정 기록 조회(GET)도 scoped 배포 범위 밖이라 닫혀 있다. 확정
              403 조회를 내놓지 않고 닫힘 안내로 연결한다. */}
          {!legacyDecisionClosed && (
          <details>
            <summary>과거 판정 기록 조회</summary>
            <label className="flex flex-col gap-1 font-semibold">과거 판정 기록 참조
              <input
                aria-label="과거 판정 기록 참조"
                value={historyRef}
                placeholder="external-use-decision-…(32자리 16진수)"
                onChange={(event) => setHistoryRef(event.target.value)}
              />
            </label>
            <p className="text-[12px] leading-5 text-ink-2">판정 영수증에 있는 전체 참조를 붙여넣으세요.</p>
            <button className="btn w-fit" onClick={() => void loadHistoricalDecision()}>과거 기록 조회</button>
            {history && <DecisionReceipt decision={history} historical />}
          </details>
          )}

          {canWrite && (
            <>
              {legacyDecisionClosed && (
                <div role="status" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
                  <h3 className="text-[14px] font-bold">사용 결정 요청 닫힘</h3>
                  <p className="text-[12px] leading-5 text-ink-2">이 화면의 사용 결정 요청(화면·높이·비교·측정 확인)은 현재 계정의 배포 범위에 열려 있지 않아 보낼 수 없습니다. 이 화면에서는 새로운 사용 결정 요청을 보내지 않습니다. 노트북 화면에서도 마찬가지입니다. 등록된 증거·검사 상태·봉인 기록은 그대로 볼 수 있습니다.</p>
                  <p className="text-[12px] leading-5 text-ink-2">새로운 두 시점 관측 변화 분석은 현장의 분석 화면에서 진행합니다.</p>
                  <a className="btn w-fit" href={`/sites/${encodeURIComponent(siteId)}/analysis`}>분석 화면 열기</a>
                </div>
              )}
            <ResponsiveActionBoundary
              action="EXTERNAL_RECONSTRUCTION_MUTATION"
              reason={legacyDecisionClosed
                ? "증거 확인은 노트북 크기에서 진행하세요. 이 화면의 미확인 요청은 새로고침·화면 이동·기기 변경 시 사라집니다."
                : "증거 확인과 사용 결정 요청은 노트북 크기에서 진행하세요. 이 화면의 미확인 요청은 새로고침·화면 이동·기기 변경 시 사라집니다."}
            >
              <div>
                {!legacyDecisionClosed && (
                  <>
                <p className="text-[12px] leading-5 text-ink-2">같은 조건의 확인 요청은 같은 요청으로 재시도됩니다.</p>
                {canWrite && !canBindNewAttempt && (
                  <p role="alert" className="text-[12px] leading-5 text-high-ink">계정을 확인하지 못해 새 확인 요청을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 이미 시작한 요청의 같은 키 재시도는 계속할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.</p>
                )}
                  </>
                )}
                {hasDsm(target) && (
                  <>
                    <h3 className="text-[14px] font-bold">독립 검사점 증거 (선택)</h3>
                    {canWrite && !canBindNewAttempt && !upload && (
                      <p role="alert" className="text-[12px] leading-5 text-high-ink">계정을 확인하지 못해 새 증거 선언을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 이미 시작한 제출의 같은 증거 재시도는 계속할 수 있습니다. 새로고침하면 입력과 요청이 사라집니다.</p>
                    )}
                    <FilePickerField
                      label="독립 검사점 CSV"
                      ariaLabel="독립 검사점 CSV"
                      accept=".csv,text/csv"
                      disabled={busy || Boolean(upload) || !newIntentAllowed}
                      onSelect={(selected) => setFile(selected)}
                      selectedFileName={file?.name ?? null}
                    />
                    <label>
                      독립성 근거 선언
                      <input
                        aria-label="독립성 근거 선언"
                        value={basis}
                        disabled={busy || Boolean(upload) || !newIntentAllowed}
                        onChange={(event) => setBasis(event.target.value)}
                      />
                    </label>
                    {uploadTargetMismatch && upload && (
                      <p className="text-[12px] leading-5 text-ink-2">현재 선택은 원래 요청(작업 {upload.workOrderId} · 제출 {upload.revision}회차)과 다릅니다. 아래 제출 버튼은 동결된 원래 키·내용·경로를 그대로 다시 보내며, 접수 여부는 분석 시스템 기록으로만 확인합니다.</p>
                    )}
                    <button
                      className="btn"
                      disabled={!file || !basis.trim() || busy || (!newIntentAllowed && !upload)}
                      onClick={() => void uploadEvidence()}
                    >
                      파일 제출 마치기
                    </button>
                    <p className="text-[12px] leading-5 text-ink-2">마치면 파일 검사가 준비됩니다. 검증 완료를 뜻하지 않습니다.</p>
                    <p className="text-[12px] leading-5 text-ink-2">같은 파일·선언으로는 같은 증거 요청으로 재시도됩니다.</p>
                    {upload && !confirmingEvidenceRestart && (
                      <>
                        <button className="btn w-fit" disabled={busy} onClick={restartEvidence}>다른 파일·선언으로 새로 시작</button>
                        <p className="text-[12px] leading-5 text-ink-2">이미 접수된 증거가 있을 수 있으니 목록 상태를 먼저 확인하세요. 새로 시작하면 다른 증거 요청으로 등록됩니다.</p>
                      </>
                    )}
                    {upload && confirmingEvidenceRestart && (
                      <div role="alert" className="flex flex-col gap-2 rounded-lg border border-line bg-sunk px-3 py-2">
                        <p>이전 증거 요청이 이미 접수됐을 수 있습니다. 새로 시작하면 다른 증거 요청으로 등록되고 새 키를 사용합니다. 먼저 기록에서 원래 요청의 증거가 이미 있는지 확인하세요. 그래도 새로 시작하시겠습니까?</p>
                        <div className="flex flex-wrap gap-2">
                          <button className="btn" disabled={busy} onClick={confirmEvidenceRestart}>새로 시작 확인</button>
                          <button className="btn" onClick={keepEvidenceAttempt}>유지</button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {!legacyDecisionClosed && (
                  <>
                <h3 className="text-[14px] font-bold">화면·높이 확인</h3>
                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("DISPLAY")?.phase !== "error"}
                  onClick={() => void decide("DISPLAY", currentSlot("DISPLAY")?.phase === "ready")}
                >
                  화면 표시 다시 확인
                </button>
                <DecisionUseMessage text={messageUse === "DISPLAY" ? message : null} alert={messageAlert} />
                {pendingFresh?.use === "DISPLAY" ? (
                  <FreshDecisionConfirm
                    hasFrozenRetry={Boolean(attempts[pendingFresh.intent])}
                    onConfirm={() => confirmFreshDecision()}
                    onRetry={() => { if (pendingFresh) void decide(pendingFresh.use, false); }}
                    onKeep={() => setPendingFresh(null)}
                  />
                ) : null}
                {hasDsm(target) && (
                  <>
                  <button
                    className="btn"
                    disabled={!newIntentAllowed && currentSlot("HEIGHT")?.phase !== "error"}
                    onClick={() => void decide("HEIGHT", currentSlot("HEIGHT")?.phase === "ready")}
                  >
                    높이 다시 확인
                  </button>
                  <DecisionUseMessage text={messageUse === "HEIGHT" ? message : null} alert={messageAlert} />
                  {pendingFresh?.use === "HEIGHT" ? (
                    <FreshDecisionConfirm
                      hasFrozenRetry={Boolean(attempts[pendingFresh.intent])}
                      onConfirm={() => confirmFreshDecision()}
                      onRetry={() => { if (pendingFresh) void decide(pendingFresh.use, false); }}
                      onKeep={() => setPendingFresh(null)}
                    />
                  ) : null}
                  </>
                )}

                <h3 className="text-[14px] font-bold">두 시점 비교</h3>
                <label className="flex flex-col gap-1 font-semibold">비교할 이전 등록 버전
                <select
                  aria-label="비교할 이전 등록 버전"
                  value={baseline}
                  disabled={!newIntentAllowed}
                  onChange={(event) => {
                    // 선택을 바꿔도 동결된 원래 시도는 유지한다 — 재시도는
                    // 동결된 원래 내용으로 나가므로 다른 기록이 생기지 않는다.
                    // 새 조건으로 새로 요청하려면 명시적 새 의도를 쓴다.
                    setPendingFresh(null);
                    setBaseline(event.target.value);
                  }}
                >
                  <option value="">이전 등록 버전 선택</option>
                  {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
                </label>
                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("VISUAL_COMPARISON")?.phase !== "error"}
                  onClick={() => void decide("VISUAL_COMPARISON", currentSlot("VISUAL_COMPARISON")?.phase === "ready")}
                >
                  눈으로 비교 다시 확인
                </button>
                <DecisionUseMessage text={messageUse === "VISUAL_COMPARISON" ? message : null} alert={messageAlert} />
                {pendingFresh?.use === "VISUAL_COMPARISON" ? (
                  <FreshDecisionConfirm
                    hasFrozenRetry={Boolean(attempts[pendingFresh.intent])}
                    onConfirm={() => confirmFreshDecision()}
                    onRetry={() => { if (pendingFresh) void decide(pendingFresh.use, false); }}
                    onKeep={() => setPendingFresh(null)}
                  />
                ) : null}

                {hasDsm(target) && (
                  <>
                    <label className="flex flex-col gap-1 font-semibold">변화 분석 구역
                    <select
                      aria-label="변화 분석 구역"
                      value={zone}
                      disabled={!newIntentAllowed}
                      onChange={(event) => {
                        setPendingFresh(null);
                        setZone(event.target.value);
                      }}
                    >
                      <option value="">작업구역 선택</option>
                      {areas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
                    </select>
                    </label>
                    <button
                      className="btn"
                      disabled={!newIntentAllowed && currentSlot("RELATIVE_VOLUME")?.phase !== "error"}
                      onClick={() => void decide("RELATIVE_VOLUME", currentSlot("RELATIVE_VOLUME")?.phase === "ready")}
                    >
                      변화 분석 다시 확인
                    </button>
                    <DecisionUseMessage text={messageUse === "RELATIVE_VOLUME" ? message : null} alert={messageAlert} />
                    {pendingFresh?.use === "RELATIVE_VOLUME" ? (
                      <FreshDecisionConfirm
                        hasFrozenRetry={Boolean(attempts[pendingFresh.intent])}
                        onConfirm={() => confirmFreshDecision()}
                        onRetry={() => { if (pendingFresh) void decide(pendingFresh.use, false); }}
                        onKeep={() => setPendingFresh(null)}
                      />
                    ) : null}
                  </>
                )}

                <h3 className="text-[14px] font-bold">한 시점 측정</h3>
                <label className="flex flex-col gap-1 font-semibold">한 시점 측정 구역
                <select
                  aria-label="한 시점 측정 구역"
                  value={singleZone}
                  disabled={!newIntentAllowed}
                  onChange={(event) => {
                    setPendingFresh(null);
                    setSingleZone(event.target.value);
                  }}
                >
                  <option value="">작업구역 선택</option>
                  {areas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
                </select>
                </label>
                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("SINGLE_VOLUME")?.phase !== "error"}
                  onClick={() => void decide("SINGLE_VOLUME", currentSlot("SINGLE_VOLUME")?.phase === "ready")}
                >
                  한 시점 측정 다시 확인
                </button>
                <DecisionUseMessage text={messageUse === "SINGLE_VOLUME" ? message : null} alert={messageAlert} />
                {pendingFresh?.use === "SINGLE_VOLUME" ? (
                  <FreshDecisionConfirm
                    hasFrozenRetry={Boolean(attempts[pendingFresh.intent])}
                    onConfirm={() => confirmFreshDecision()}
                    onRetry={() => { if (pendingFresh) void decide(pendingFresh.use, false); }}
                    onKeep={() => setPendingFresh(null)}
                  />
                ) : null}
                  </>
                )}
              </div>
            </ResponsiveActionBoundary>
            </>
          )}

          {(["DISPLAY", "HEIGHT", "VISUAL_COMPARISON", "RELATIVE_VOLUME", "SINGLE_VOLUME"] as const).map((use) => {
            const slot = currentSlot(use);
            if (!slot) return null;
            if (slot.phase === "pending") return <p key={use} role="status">{decisionUseLabel(use)} 확인 요청 중</p>;
            if (slot.phase === "error") {
              // 같은 용도의 구체 안내가 버튼 옆에 있으면 중복하지 않는다.
              if (messageUse === use && message) return null;
              return <p key={use} role="alert">{decisionUseLabel(use)} 확인 결과를 읽지 못했습니다.</p>;
            }
            // 다른 조건의 보존 기록을 현재 선택의 기록처럼 보이지 않는다.
            // 새 조건의 판정이 있으면 정확히 맞는 쪽이 보인다.
            const matched = currentSlotIntent(use) === draftIntentFor(use);
            return <DecisionReceipt key={use} decision={slot.decision} historical={!matched} />;
          })}
        </>
      )}

      {!messageUse && message && <p role={messageAlert ? "alert" : "status"}>{message}</p>}
    </section>
  );
}
