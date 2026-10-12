"use client";

import { ExternalUseBlockerCard } from "@/components/external-results/ExternalUseBlockerCard";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { putExternalEvidenceFile } from "@/lib/external-evidence-upload";

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
  basis: string;
  keys: readonly [string, string, string];
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

const coreValue = (value?: string | null) => value || "Core 기록 없음";

function DecisionSubjectBinding({
  label,
  subject,
  digest,
}: {
  label: string;
  subject?: DecisionSubject;
  digest?: string;
}) {
  if (!subject) return <p>{label}: Core 기록 없음</p>;
  return (
    <div>
      <p>{label}: 조직 {subject.organizationId} · 현장 {subject.siteId} · 작업 {subject.workOrderId}</p>
      <p>제출 {subject.submissionId} · rev {subject.revision} · 제출 다이제스트 {subject.submissionDigest}</p>
      <p>매니페스트 다이제스트 {subject.manifestDigest} · 대상 다이제스트 {coreValue(digest)}</p>
    </div>
  );
}

function DecisionBindings({ decision }: { decision: Decision }) {
  const pair = Boolean(decision.baselineSubject || decision.currentSubject);
  const inspectionBindings = pair
    ? [
        ["기준 검사 보고서 다이제스트", decision.baselineInspectionReportDigest],
        ["현재 검사 보고서 다이제스트", decision.currentInspectionReportDigest],
      ]
    : [["검사 보고서 다이제스트", decision.inspectionReportDigest]];
  const displayBindings = pair
    ? [
        ["기준 표시 영수증 다이제스트", decision.baselineSanitizedDisplayReceiptDigest],
        ["현재 표시 영수증 다이제스트", decision.currentSanitizedDisplayReceiptDigest],
      ]
    : [["표시 영수증 다이제스트", decision.sanitizedDisplayReceiptDigest]];

  return (
    <div className="mt-2 border-t border-line pt-2">
      <p>결정 ID: {decision.decisionId}</p>
      <p>결정 다이제스트: {coreValue(decision.decisionDigest)}</p>
      <p>계약 버전: {coreValue(decision.contractVersion)}</p>
      {pair ? (
        <>
          <DecisionSubjectBinding label="순서 있는 기준 대상" subject={decision.baselineSubject} digest={decision.baselineSubjectDigest} />
          <DecisionSubjectBinding label="순서 있는 현재 대상" subject={decision.currentSubject} digest={decision.currentSubjectDigest} />
        </>
      ) : (
        <DecisionSubjectBinding label="대상" subject={decision.subject} digest={decision.subjectDigest} />
      )}
      <p>정책 다이제스트: {coreValue(decision.policyDigest)}</p>
      {inspectionBindings.map(([label, value]) => <p key={label}>{label}: {coreValue(value)}</p>)}
      <p>증거 기록 다이제스트: {decision.evidenceRecordDigests?.join(", ") || "Core 기록 없음"}</p>
      {displayBindings.map(([label, value]) => <p key={label}>{label}: {coreValue(value)}</p>)}
      {pair && (
        <>
          <p>
            봉인 작업구역: {decision.zone ? `${decision.zone.zoneId} · rev ${decision.zone.revision}` : "Core 기록 없음"}
          </p>
          <p>작업구역 정의 다이제스트: {coreValue(decision.zone?.definitionDigest)}</p>
          <p>관측 좌표계 다이제스트: {coreValue(decision.zone?.observedCrsDigest)}</p>
          <p>관측 수직 기준 다이제스트: {coreValue(decision.zone?.observedVerticalReferenceDigest)}</p>
          <p>호환성 매핑 다이제스트: {coreValue(decision.compatibilityMappingDigest)}</p>
        </>
      )}
    </div>
  );
}

function DecisionReceipt({ decision, historical = false }: { decision: Decision; historical?: boolean }) {
  return (
    <div className="rounded border border-line p-2 text-ink-2">
      <p>
        {historical ? "과거 불변 Core 결정" : "현재 Core 결정"}: {decision.use} · {decision.verdict} · {decision.decidedAt}
      </p>
      {decision.verdict === "BLOCKED" ? (
        <ExternalUseBlockerCard reasons={decision.reasons} remediations={decision.remediations} />
      ) : (
        <>
          <p>사유: {decision.reasons.join(", ") || "없음"}</p>
          <p>조치: {decision.remediations.join(", ") || "없음"}</p>
        </>
      )}
      {historical && <DecisionBindings decision={decision} />}
      {historical && <p>과거 기록은 현재 사용 권한이나 실행 권한이 아닙니다.</p>}
    </div>
  );
}

function EvidenceItemState({ item }: { item: Evidence }) {
  const summaries = item.measurementSummaries ?? [];

  return (
    <div className="mt-2 rounded border border-line p-2 text-ink-2">
      <p>독립성 근거 선언: {item.independenceBasis}</p>
      <p>이 선언은 Core가 독립성을 증명한 사실이 아닙니다.</p>
      {item.state === "DECLARED" ? (
        <p>CSV 바이트 봉인 대기</p>
      ) : summaries.length === 0 ? (
        <p>Core 측정 집계 대기</p>
      ) : (
        summaries.map((summary) => (
          <div key={`${summary.recordedAt}:${summary.coreVerdict}`} className="mt-2">
            <p className="font-semibold">Core 측정 집계</p>
            <p>Core 판정: {summary.coreVerdict}</p>
            <p>
              검사점 {summary.measuredCheckpointCount}개 · 평균 오차 {summary.meanErrorM}m · MAE {summary.maeM}m · RMSE {summary.rmseM}m
            </p>
            <p>Core 기록 시각: {summary.recordedAt}</p>
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

export function ExternalEvidencePanel({
  workOrderId,
  siteId,
  revisions,
  canWrite,
  newIntentAllowed = true,
  onRelativeVolumeDecisionChange,
  onSingleVolumeDecisionChange,
}: {
  workOrderId: string;
  siteId: string;
  revisions: Revision[];
  canWrite: boolean;
  newIntentAllowed?: boolean;
  onRelativeVolumeDecisionChange?: (decision: Decision | null) => void;
  onSingleVolumeDecisionChange?: (decision: Decision | null) => void;
}) {
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
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
  const [message, setMessage] = useState("");
  const [historyRef, setHistoryRef] = useState("");
  const [history, setHistory] = useState<Decision | null>(null);
  const [busy, setBusy] = useState(false);

  const sealed = useMemo(() => revisions.filter((revision) => revision.state === "SEALED"), [revisions]);
  const current = target ? subject(target) : "";
  const choices = pairs.filter((item) => !target || item.value !== `${workOrderId}:${subject(target)}`);

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
    if (!siteId) return;
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
                    label: `${row.order.name ?? "관측 작업"} · ${row.order.cycleNumber ?? ""}회차 · ${revision.submission.artifacts?.map((artifact) => artifact.fileName).join(", ") ?? "산출물"}`,
                  }))
              : [],
          ),
        );
        const failures = loaded
          .filter((row) => !row.revisions)
          .map((row) => ({
            workOrderId: row.order.workOrderId,
            label: row.order.name ?? `관측 작업 ${row.order.workOrderId}`,
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
  }, [pairReload, siteId]);

  const reset = () => {
    generation.current += 1;
    const controller = active.current;
    active.current = null;
    controller?.abort();
    setBusy(false);
    historyRequest.current?.abort();
    setTries({});
    setDecisions({});
    onRelativeVolumeDecisionChange?.(null);
    onSingleVolumeDecisionChange?.(null);
    setHistory(null);
    setHistoryRef("");
    setMessage("");
  };

  const retryPairChoices = () => {
    setPairLoad("loading");
    setPairLoadFailures([]);
    setPairReload((value) => value + 1);
  };

  const decisionIntent = (
    use: DecisionUse,
    selected?: Pair,
    selectedZone?: string,
  ) => [
    current,
    use,
    selected?.value ?? "",
    use === "RELATIVE_VOLUME" || use === "SINGLE_VOLUME" ? selectedZone ?? "" : "",
  ].join("|");

  const currentSlot = (use: string) =>
    Object.entries(decisions).find(([intent]) => intent.startsWith(`${current}|${use}|`))?.[1];

  const uploadEvidence = async () => {
    if (!target || !file || !basis.trim() || !hasDsm(target) || busy) return;
    if (!newIntentAllowed && !upload) {
      setMessage("업무 종료 상태에서는 새 증거 선언을 시작할 수 없습니다.");
      return;
    }
    const controller = new AbortController();
    const scope = generation.current;
    active.current?.abort();
    active.current = controller;
    setBusy(true);
    try {
      let attempt = upload;
      if (!attempt) {
        attempt = {
          file,
          digest: await fileDigest(file, controller.signal),
          target: subject(target),
          basis: basis.trim(),
          keys: [makeKey(), makeKey(), makeKey()],
        };
        setUpload(attempt);
      }
      if (attempt.target !== subject(target)) throw new Error("attempt target changed");
      const artifact = target.submission.artifacts?.find((item) => item.kind === "dsm");
      if (!artifact) throw new Error("DSM no longer selected");
      const root = `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(target.submissionRef)}/revisions/${target.submission.revision}/evidence`;
      const declared = await fetch(root, {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": attempt.keys[0] },
        body: JSON.stringify({
          targetDsmArtifactId: artifact.artifactId,
          declaredContentDigest: attempt.digest,
          declaredContentType: "text/csv",
          independenceBasis: attempt.basis,
        }),
        signal: controller.signal,
      });
      if (!declared.ok) throw new Error("declaration failed");
      const item = await declared.json() as Evidence;
      if (
        item.targetDsmArtifactId !== artifact.artifactId ||
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
          setFile(null);
          setBasis("");
          setMessage("Core가 동일 CSV 바이트를 이미 봉인했습니다.");
        }
        return;
      }
      const grant = await fetch(`${root}/${encodeURIComponent(item.evidenceRef)}/upload-grant`, {
        method: "POST",
        headers: { "idempotency-key": attempt.keys[1] },
        signal: controller.signal,
      });
      if (!grant.ok) throw new Error("grant failed");
      await putExternalEvidenceFile(await grant.json(), attempt.file, controller.signal);
      const seal = await fetch(`${root}/${encodeURIComponent(item.evidenceRef)}/seal`, {
        method: "POST",
        headers: { "idempotency-key": attempt.keys[2] },
        signal: controller.signal,
      });
      if (!seal.ok) throw new Error("seal failed");
      const sealedItem = await seal.json() as Evidence;
      if (sealedItem.evidenceRef !== item.evidenceRef || sealedItem.state !== "SEALED_BYTE_OBSERVED") {
        throw new Error("seal binding changed");
      }
      await loadEvidence(controller.signal);
      if (generation.current === scope) {
        setUpload(null);
        setFile(null);
        setBasis("");
        setMessage("Core가 CSV 바이트를 봉인했습니다. 측정 집계는 Core 기록 후 표시됩니다.");
      }
    } catch {
      if (!controller.signal.aborted && generation.current === scope) {
        setMessage("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.");
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        if (generation.current === scope) setBusy(false);
      }
    }
  };

  const decide = async (use: DecisionUse, fresh = false) => {
    if (!target || busy) return;
    const pair = use === "VISUAL_COMPARISON" || use === "RELATIVE_VOLUME";
    const singleVolume = use === "SINGLE_VOLUME";
    // A single-epoch volume never binds a baseline, even when one is selected for another use.
    const selected = singleVolume ? undefined : choices.find((item) => item.value === baseline);
    if (pair && !selected) {
      setMessage("비교 기준 봉인 재구성을 선택하세요.");
      return;
    }
    if (use === "RELATIVE_VOLUME" && !zone) {
      setMessage("상대 물량 작업구역을 선택하세요.");
      return;
    }
    if (singleVolume && !singleZone) {
      setMessage("단일 시점 체적 작업구역을 선택하세요.");
      return;
    }
    if ((use === "HEIGHT" || use === "RELATIVE_VOLUME" || singleVolume) && !hasDsm(target)) {
      setMessage("DSM이 없어 이 결정을 요청할 수 없습니다.");
      return;
    }
    const intent = decisionIntent(use, selected, singleVolume ? singleZone : zone);
    if (!newIntentAllowed && (!tries[intent] || fresh)) {
      setMessage("업무 종료 상태에서는 새 사용 결정을 요청할 수 없습니다.");
      return;
    }
    const idempotencyKey = !fresh && tries[intent] ? tries[intent] : makeKey();
    if (!tries[intent] || fresh) setTries((previous) => ({ ...previous, [intent]: idempotencyKey }));
    const controller = new AbortController();
    const scope = generation.current;
    active.current?.abort();
    active.current = controller;
    setBusy(true);
    if (use === "RELATIVE_VOLUME") onRelativeVolumeDecisionChange?.(null);
    if (singleVolume) onSingleVolumeDecisionChange?.(null);
    setDecisions((previous) => ({ ...previous, [intent]: { phase: "pending" } }));
    try {
      const root = `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(target.submissionRef)}/revisions/${target.submission.revision}/use-decisions`;
      const response = singleVolume
        ? await fetch(`${root}/single-volume`, {
            method: "POST",
            headers: { "content-type": "application/json", "idempotency-key": idempotencyKey },
            body: JSON.stringify({ zoneId: singleZone }),
            signal: controller.signal,
          })
        : pair
        ? await fetch(`${root}/pair`, {
            method: "POST",
            headers: { "content-type": "application/json", "idempotency-key": idempotencyKey },
            body: JSON.stringify({
              use,
              baselineWorkOrderId: selected!.workOrderId,
              baselineSubmissionRef: selected!.revision.submissionRef,
              baselineRevision: selected!.revision.submission.revision,
              ...(use === "RELATIVE_VOLUME" ? { zoneId: zone } : {}),
            }),
            signal: controller.signal,
          })
        : await fetch(`${root}/single`, {
            method: "POST",
            headers: { "content-type": "application/json", "idempotency-key": idempotencyKey },
            body: JSON.stringify({ use }),
            signal: controller.signal,
          });
      if (!response.ok) throw new Error("decision failed");
      const value = (await response.json() as { decision: Decision }).decision;
      if (generation.current === scope && active.current === controller) {
        setDecisions((previous) => ({ ...previous, [intent]: { phase: "ready", decision: value } }));
        if (use === "RELATIVE_VOLUME") onRelativeVolumeDecisionChange?.(value);
        if (singleVolume) onSingleVolumeDecisionChange?.(value);
      }
    } catch {
      if (!controller.signal.aborted && generation.current === scope && active.current === controller) {
        setDecisions((previous) => ({ ...previous, [intent]: { phase: "error" } }));
        setMessage("Core 결정을 요청하지 못했습니다. 같은 결정 요청을 다시 시도하세요.");
      }
    } finally {
      if (active.current === controller) {
        active.current = null;
        if (generation.current === scope) setBusy(false);
      }
    }
  };

  const loadHistoricalDecision = async () => {
    if (!target) return;
    if (!/^external-use-decision-[0-9a-f]{32}$/.test(historyRef)) {
      setMessage("유효한 과거 결정 참조를 입력하세요.");
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
        setMessage("과거 Core 결정을 읽지 못했습니다.");
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
        {sealed.map((revision) => (
          <li key={subject(revision)}>
            <button
              className="btn max-w-full whitespace-normal break-all text-left"
              onClick={() => {
                reset();
                setTarget(revision);
                setUpload(null);
              }}
            >
              현재 작업 · 봉인 재구성 rev {revision.submission.revision} · {revision.submission.artifacts?.map((artifact) => artifact.fileName).join(", ")}
            </button>
            {!hasDsm(revision) && <p>DSM 없음: 표시는 가능하지만 독립 검사점·높이·상대 물량은 제한됩니다.</p>}
            <EvidenceState load={evidence[subject(revision)]} />
          </li>
        ))}
      </ul>

      {pairLoad === "loading" && <p>비교 기준과 작업구역을 읽는 중입니다.</p>}
      {(pairLoad === "error" || pairLoad === "partial") && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <p>비교 기준 또는 작업구역을 읽지 못했습니다.</p>
          {pairLoad === "partial" && (
            <p>
              일부 같은 현장 작업의 비교 기준을 읽지 못했습니다: {pairLoadFailures.map((failure) => failure.label).join(", ")}. 목록이 완전하지 않습니다.
            </p>
          )}
          <button className="btn" onClick={retryPairChoices}>비교 기준 다시 시도</button>
        </div>
      )}

      {target && (
        <>
          <details>
            <summary>과거 불변 Core 결정 조회</summary>
            <input
              aria-label="과거 Core 결정 참조"
              value={historyRef}
              onChange={(event) => setHistoryRef(event.target.value)}
            />
            <button onClick={() => void loadHistoricalDecision()}>과거 결정 조회</button>
            {history && <DecisionReceipt decision={history} historical />}
          </details>

          {canWrite && (
            <ResponsiveActionBoundary
              action="EXTERNAL_RECONSTRUCTION_MUTATION"
              reason="노트북에서 같은 계정으로 이 작업 상세를 열어 증거 확인과 사용 결정 요청을 이어가세요."
            >
              <div>
                {hasDsm(target) && (
                  <>
                    <label>
                      독립 검사점 CSV
                      <input
                        aria-label="독립 검사점 CSV"
                        type="file"
                        accept=".csv,text/csv"
                        disabled={busy || Boolean(upload) || !newIntentAllowed}
                        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                      />
                    </label>
                    <label>
                      독립성 근거 선언
                      <input
                        aria-label="독립성 근거 선언"
                        value={basis}
                        disabled={busy || Boolean(upload) || !newIntentAllowed}
                        onChange={(event) => setBasis(event.target.value)}
                      />
                    </label>
                    <button
                      className="btn"
                      disabled={!file || !basis.trim() || busy || (!newIntentAllowed && !upload)}
                      onClick={() => void uploadEvidence()}
                    >
                      CSV 선언·업로드·봉인
                    </button>
                  </>
                )}

                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("DISPLAY")?.phase !== "error"}
                  onClick={() => void decide("DISPLAY", currentSlot("DISPLAY")?.phase === "ready")}
                >
                  표시 결정 다시 평가
                </button>
                {hasDsm(target) && (
                  <button
                    className="btn"
                    disabled={!newIntentAllowed && currentSlot("HEIGHT")?.phase !== "error"}
                    onClick={() => void decide("HEIGHT", currentSlot("HEIGHT")?.phase === "ready")}
                  >
                    높이 결정 다시 평가
                  </button>
                )}

                <select
                  aria-label="비교 기준 봉인 재구성"
                  value={baseline}
                  disabled={!newIntentAllowed}
                  onChange={(event) => {
                    reset();
                    setBaseline(event.target.value);
                  }}
                >
                  <option value="">비교 기준 선택</option>
                  {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("VISUAL_COMPARISON")?.phase !== "error"}
                  onClick={() => void decide("VISUAL_COMPARISON", currentSlot("VISUAL_COMPARISON")?.phase === "ready")}
                >
                  시각 비교 결정 다시 평가
                </button>

                {hasDsm(target) && (
                  <>
                    <select
                      aria-label="상대 물량 작업구역"
                      value={zone}
                      disabled={!newIntentAllowed}
                      onChange={(event) => {
                        reset();
                        setZone(event.target.value);
                      }}
                    >
                      <option value="">작업구역 선택</option>
                      {areas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
                    </select>
                    <button
                      className="btn"
                      disabled={!newIntentAllowed && currentSlot("RELATIVE_VOLUME")?.phase !== "error"}
                      onClick={() => void decide("RELATIVE_VOLUME", currentSlot("RELATIVE_VOLUME")?.phase === "ready")}
                    >
                      상대 물량 결정 다시 평가
                    </button>
                  </>
                )}

                <select
                  aria-label="단일 시점 체적 작업구역"
                  value={singleZone}
                  disabled={!newIntentAllowed}
                  onChange={(event) => {
                    reset();
                    setSingleZone(event.target.value);
                  }}
                >
                  <option value="">작업구역 선택</option>
                  {areas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
                </select>
                <button
                  className="btn"
                  disabled={!newIntentAllowed && currentSlot("SINGLE_VOLUME")?.phase !== "error"}
                  onClick={() => void decide("SINGLE_VOLUME", currentSlot("SINGLE_VOLUME")?.phase === "ready")}
                >
                  단일 시점 체적 결정 다시 평가
                </button>
              </div>
            </ResponsiveActionBoundary>
          )}

          {(["DISPLAY", "HEIGHT", "VISUAL_COMPARISON", "RELATIVE_VOLUME", "SINGLE_VOLUME"] as const).map((use) => {
            const slot = currentSlot(use);
            if (!slot) return null;
            if (slot.phase === "pending") return <p key={use} role="status">{use} Core 결정 요청 중</p>;
            if (slot.phase === "error") return <p key={use} role="alert">{use} Core 결정을 읽지 못했습니다.</p>;
            return <DecisionReceipt key={use} decision={slot.decision} />;
          })}
        </>
      )}

      {message && <p role="status">{message}</p>}
    </section>
  );
}
