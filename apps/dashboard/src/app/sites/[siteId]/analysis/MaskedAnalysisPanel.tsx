"use client";

import { CoverageGridView } from "@/components/analysis/CoverageGridView";

import { useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { StateBadge } from "@/components/ui/StatusBadge";
import {
  formatBytesKo,
  formatCountKo,
  formatNumberKo,
  formatSignificantKo,
} from "@/lib/number-format";
import {
  cancelMaskedCalculation,
  canonicalSubjectDigest,
  clearMaskedContinuity,
  createMaskedCalculation,
  declareMaskChild,
  getMaskChild,
  getMaskedCalculation,
  getMaskInspectionStatus,
  getMaskSourceContext,
  maskedErrorCode,
  maskInspectionReasonMessage,
  MaskedConflictError,
  MaskedForbiddenError,
  MaskedNotFoundError,
  MaskedRequestError,
  parseMaskedDeltaSourceRef,
  readMaskedContinuity,
  requestMaskUploadGrant,
  sha256HexOfBytes,
  uploadMaskBytes,
  validateMaskFile,
  writeMaskedContinuity,
  type MaskChildDeclarationWire,
  type MaskChildViewWire,
  type MaskedCalculationCreateWire,
  type MaskedCalculationDetailWire,
  type MaskedContinuityScope,
  type MaskedDeltaSourceRefWire,
  type MaskedDisposition,
  type MaskedExecutionStatus,
  type MaskedSourceContext,
  type MaskInspectionStatusWire,
} from "@/lib/core-api/masked-analysis";

/**
 * 독립 마스크 계산(V3) 패널 — 기존 V2 결과 화면과 분리된 별도 영역이다.
 *
 * 원본은 부모가 `boundMaskedSourceIdentity`(AP assessment의 봉인 V2 계산
 * 신원 확인값, V2 수치 완료 불필요)에서 내려준 확인값 문자열 하나다.
 * 선언 subject·기준선은 원본 맥락 GET에서 받은 봉인 subject 그대로만
 * 쓰며(격자·CRS·검사 진실 발명 금지), 맥락 조회 역시 명시적 사용자 동작의
 * 읽기 전용 GET이다. 마운트 시 자동 요청을 만들지 않는다.
 *
 * - TIFF를 복호화하지 않는다. 원시 바이트 해시만 계산하고, 실제 검사는
 *   Core 관찰 보고서가 판정한다.
 * - 수치 보고서는 `AVAILABLE`일 때만 표시한다. 내보내기 상태는 수치 표시에
 *   관여하지 않으며, 발행 인계는 부모가 compose하는 기존 내보내기 패널에
 *   `onDeltaHandoff`·`onResult`로만 넘긴다(DeltaPublicationPanel을 중첩하지
 *   않는다 — 타 에이전트 소유).
 * - props 변경은 진행 중 호출을 중단한다. 폴링하지 않는다.
 */

export type MaskedAnalysisPanelProps = {
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  /** 쓰기 허용 — 거짓이면 쓰기 동작을 안내로 둔다(읽기는 그대로 둔다). */
  canRequest: boolean;
  /**
   * 부모의 `boundMaskedSourceIdentity(detail, pages)` 결과. V2 수치 완료·
   * 검토 대상이 전제 조건이 아니다. null이면 마스크 입력 연결 전으로 둔다.
   */
  sourceCalculationIdentityDigest: string | null;
  baselineLabel?: string | null;
  currentLabel?: string | null;
  /** 명시적 서버 업로드 예산(바이트) — 없으면 파일 선택을 막는다. */
  maskBudgetBytes: number | null;
  initialChild: MaskChildViewWire | null;
  initialCalculation: MaskedCalculationDetailWire | null;
  /** 부모가 주도한 흐름의 자식 id — 인계 참조에 쓴다(자체 흐름이면 선언에서 안다). */
  maskChildId?: string | null;
  /** 부모가 기존 내보내기 패널을 compose한다 — AVAILABLE일 때만 호출된다. */
  onDeltaHandoff?: (ref: MaskedDeltaSourceRefWire) => void;
  /** 부모 화면 상태 합성용 — 사용자 동작으로 검증된 현재 화면을 매번 알린다.
   *  AVAILABLE뿐 아니라 재평가·실패·취소 화면도 그대로 전달하므로, 부모는
   *  낡은 AVAILABLE 내보내기 출처를 무효화할 수 있다. 마운트·props 변경 시
   *  자동 호출하지 않는다(부모는 source 키로 리마운트한다). */
  onResult?: (detail: MaskedCalculationDetailWire) => void;
  /**
   * 검사 실패·권한 상실 알림 — terminal 검사 실패를 확인했거나 저장된 작업이
   * 사라져 복원할 수 없을 때 호출된다. 부모는 낡은 가용 표시를 지운다.
   * 수치·검사 성공 경로에서는 호출하지 않는다.
   */
  onInvalidated?: () => void;
  /**
   * 서버 세션의 범위(조직·주체) — 부모가 기존 세션 props에서 내려준다.
   * 마지막 작업의 불투명 식별자를 이 범위 키로만 기억한다. 없으면 복원을
   * 내놓지 않으며, 주체를 추측하거나 기본 조직을 두지 않는다.
   */
  sessionScope?: { organizationId: string; principalId: string } | null;
};

function opaqueId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function formatVolume(value: number): string {
  const rendered = Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3)
    : formatNumberKo(value, 1);
  return `${rendered} m³`;
}

function formatArea(value: number): string {
  const rendered = value > 0 && value < 0.1 ? formatSignificantKo(value, 3) : formatNumberKo(value, 1);
  return `${rendered} m²`;
}

function statusBadge(status: MaskedExecutionStatus): { label: string; tone: "neutral" | "progress" | "positive" | "warning" } {
  switch (status) {
    case "QUEUED": return { label: "대기 중", tone: "neutral" };
    case "RUNNING": return { label: "계산 중", tone: "progress" };
    case "COMPLETED": return { label: "계산 완료", tone: "positive" };
    case "FAILED": return { label: "실패", tone: "warning" };
    case "CANCELED": return { label: "취소됨", tone: "warning" };
  }
}

function dispositionNote(disposition: MaskedDisposition): string | null {
  switch (disposition) {
    case "AVAILABLE": return null;
    case "PENDING": return "승인이 대기 중입니다. 수치 내용은 아직 없습니다.";
    case "REASSESSMENT_REQUIRED": return "현장 적합성 재평가가 필요합니다. 이 기록의 수치·상태는 그대로 둡니다.";
    case "FAILED": return "처리가 실패했습니다. 같은 요청을 바로 반복하지 마세요.";
    case "CANCELED": return "취소되었습니다.";
    case "EXECUTION_DEADLINE_EXPIRED": return "실행 기한이 지났습니다. 새로 요청하세요.";
    case "EXECUTION_RETRY_EXHAUSTED": return "재시도 예산이 소진되었습니다. 운영자에게 문의하세요.";
  }
}

export function MaskedAnalysisPanel({
  siteId,
  workAreaId,
  workAreaName,
  canRequest,
  sourceCalculationIdentityDigest,
  baselineLabel = null,
  currentLabel = null,
  maskBudgetBytes,
  initialChild,
  initialCalculation,
  maskChildId: maskChildIdProp = null,
  onDeltaHandoff,
  onResult,
  onInvalidated,
  sessionScope = null,
}: MaskedAnalysisPanelProps) {
  const [child, setChild] = useState<MaskChildViewWire | null>(initialChild);
  const [calculation, setCalculation] = useState<MaskedCalculationDetailWire | null>(initialCalculation);
  const [sourceContext, setSourceContext] = useState<MaskedSourceContext | null>(null);
  const [inspection, setInspection] = useState<MaskInspectionStatusWire | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [declared, setDeclared] = useState<{ sha256: string; sizeBytes: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionCode, setActionCode] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  // 멱등 의도 — 같은 입력에는 같은 본문을 재사용한다. 타임아웃 뒤 재시도가
  // 새 자식·새 계산을 만들지 않으며, 파일·맥락·원본이 바뀌거나 수락 뒤
  // 명시적 새 요청에서만 새로 만든다. 권한이 아니라서 캐시하지 않는다.
  const declareIntentRef = useRef<{ key: string; body: MaskChildDeclarationWire } | null>(null);
  const createIntentRef = useRef<{ key: string; body: MaskedCalculationCreateWire } | null>(null);
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);
  const onInvalidatedRef = useRef(onInvalidated);
  useEffect(() => {
    onInvalidatedRef.current = onInvalidated;
  }, [onInvalidated]);

  // 연속성 범위 — 세션 주체가 있을 때만 만든다. 없으면 복원을 내놓지
  // 않으며, 주체를 추측하거나 기본 조직을 두지 않는다.
  const continuityScope: MaskedContinuityScope | null =
    sessionScope && sourceCalculationIdentityDigest
      ? {
        organizationId: sessionScope.organizationId,
        principalId: sessionScope.principalId,
        siteId,
        workAreaId,
        sourceCalculationIdentityDigest,
      }
      : null;
  const scopeFingerprint = continuityScope ? JSON.stringify(continuityScope) : null;
  const [continuity, setContinuity] = useState(() =>
    continuityScope ? readMaskedContinuity(continuityScope) : null,
  );

  const [prevInitials, setPrevInitials] = useState({ child: initialChild, calc: initialCalculation, scopeFp: scopeFingerprint });
  if (
    prevInitials.child !== initialChild
    || prevInitials.calc !== initialCalculation
    || prevInitials.scopeFp !== scopeFingerprint
  ) {
    // 렌더 중 동기화(공식 권장 패턴): 부모 값·범위가 바뀌면 진행 중 호출을
    // 버리고 화면을 부모 값에 맞춘다. 자동 요청은 만들지 않는다.
    setPrevInitials({ child: initialChild, calc: initialCalculation, scopeFp: scopeFingerprint });
    setChild(initialChild);
    setCalculation(initialCalculation);
    setInspection(null);
    setSelectedFile(null);
    setDeclared(null);
    setActionError(null);
    setActionCode(null);
    setNotice(null);
    setContinuity(continuityScope ? readMaskedContinuity(continuityScope) : null);
  }

  // props·범위 변경은 진행 중 호출을 중단한다(부수 효과만 — setState 없음).
  useEffect(() => {
    seqRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
  }, [initialChild, initialCalculation, scopeFingerprint]);

  const runAction = async (label: string, task: (signal: AbortSignal, seq: number) => void | Promise<void>) => {
    const seq = seqRef.current + 1;
    seqRef.current = seq;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(label);
    setActionError(null);
    setActionCode(null);
    setNotice(null);
    try {
      await task(controller.signal, seq);
    } catch (error) {
      if (seqRef.current !== seq || controller.signal.aborted) return;
      if (
        error instanceof MaskedRequestError
        || error instanceof MaskedNotFoundError
        || error instanceof MaskedForbiddenError
        || error instanceof MaskedConflictError
      ) {
        setActionError(error.message);
        setActionCode(maskedErrorCode(error));
      } else if (error instanceof Error) {
        setActionError(error.message);
        setActionCode(maskedErrorCode(error));
      } else {
        setActionError("마스크 요청을 처리하지 못했습니다.");
        setActionCode(null);
      }
    } finally {
      if (seqRef.current === seq) setBusy(null);
    }
  };

  const emitCurrent = (detail: MaskedCalculationDetailWire) => {
    // 항상 현재 화면을 그대로 전달한다 — AVAILABLE이 아니면 부모가 낡은
    // 내보내기 출처를 무효화한다. onDeltaHandoff는 AVAILABLE일 때만 둔다.
    onResultRef.current?.(detail);
  };

  const connected = sourceCalculationIdentityDigest !== null;
  // 유효 예산 = min(서버 설정, 원본 맥락 원시 상한). 설정이 없으면 쓰기를
  // 막되 맥락 읽기는 그대로 둔다. 정책 기본값을 발명하지 않는다.
  const effectiveBudget = maskBudgetBytes === null
    ? null
    : sourceContext
      ? Math.min(maskBudgetBytes, sourceContext.maxMaskBytes)
      : maskBudgetBytes;
  const effectiveMaskChildId = maskChildIdProp ?? child?.declaration.maskChildId ?? null;
  const manifest = child?.manifest ?? null;
  const detail = calculation;
  const report = detail?.disposition === "AVAILABLE" ? detail.report : null;

  // 저장된 작업이 현재 화면과 다를 때만 복원을 내놓는다. 읽기 전용이며,
  // 파일·업로드·자동 요청을 만들지 않는다.
  const needsRestore = continuity !== null && (
    child?.declaration.maskChildId !== continuity.maskChildId
    || (continuity.requestId !== null && detail?.requestId !== continuity.requestId)
  );

  // V3 생성 게이트 — 실제 manifest와 COMPLETED 검사가 manifest 확인값까지
  // 일치해야 열린다. 검사 상태를 모르면 닫는다(추측 생성 없음).
  const inspectionSealed = inspection !== null
    && inspection.status === "COMPLETED"
    && manifest !== null
    && inspection.manifestDigest !== null
    && inspection.manifestDigest === manifest.manifestDigest;

  const handoffRef = (() => {
    if (!detail || detail.disposition !== "AVAILABLE" || !report || !detail.admission) return null;
    if (!effectiveMaskChildId) return null;
    try {
      return parseMaskedDeltaSourceRef({
        sourceCalculationIdentityDigest: detail.admission.sourceCalculationIdentityDigest,
        sourceNumericResultIdentityDigest: report.numericResultIdentityDigest,
        sourceCoverageWitnessDigest: report.numericResult.coverage.coverageWitnessDigest,
        maskChildId: effectiveMaskChildId,
      });
    } catch {
      return null;
    }
  })();

  const dropContinuity = (message: string) => {
    // 범위가 어긋나거나 사라진 기록은 지우고 솔직히 둔다. 수치 표시는 건드리지 않는다.
    if (continuityScope) clearMaskedContinuity(continuityScope);
    setContinuity(null);
    setNotice(message);
  };

  const notifyInvalidated = () => {
    onInvalidatedRef.current?.();
  };

  /**
   * 자식+검사 상태를 독립 병렬 GET으로 읽는다. 어느 한쪽의 404/403도 권한
   * 상실로 보고 버리며, 수치 실패로 바꾸지 않는다.
   */
  const fetchChildAndStatus = async (
    maskChildId: string,
    signal: AbortSignal,
  ): Promise<{ childView: MaskChildViewWire; statusView: MaskInspectionStatusWire }> => {
    const [childView, statusView] = await Promise.all([
      getMaskChild(siteId, workAreaId, maskChildId, { signal }),
      getMaskInspectionStatus(siteId, workAreaId, maskChildId, { signal }),
    ]);
    if (
      childView.declaration.siteId !== siteId
      || childView.declaration.workAreaId !== workAreaId
    ) {
      throw new MaskedNotFoundError("마스크 기록의 요청 범위를 확인할 수 없습니다.");
    }
    return { childView, statusView };
  };

  const restoreContinuity = () => {
    // 명시적 읽기 전용 복원 — GET만 하며 자동 변경·업로드·파일 접근을 만들지 않는다.
    if (!continuity || !continuityScope || busy) return;
    const wanted = continuity;
    const wantedScope = continuityScope;
    void runAction("restore", async (signal, seq) => {
      let restored: { childView: MaskChildViewWire; statusView: MaskInspectionStatusWire };
      try {
        restored = await fetchChildAndStatus(wanted.maskChildId, signal);
      } catch (error) {
        if (seqRef.current !== seq) return;
        if (error instanceof MaskedNotFoundError || error instanceof MaskedForbiddenError) {
          dropContinuity("이전 마스크 작업을 찾을 수 없거나 접근할 수 없습니다. 기록을 지웠습니다.");
          notifyInvalidated();
          return;
        }
        throw error;
      }
      if (seqRef.current !== seq) return;
      if (restored.childView.declaration.organizationId !== wantedScope.organizationId) {
        dropContinuity("이전 작업의 범위가 바뀌어 기록을 지웠습니다. 새로 선언하세요.");
        notifyInvalidated();
        return;
      }
      setChild(restored.childView);
      setInspection(restored.statusView);
      if (wanted.requestId === null) {
        if (seqRef.current !== seq) return;
        if (restored.statusView.status === "REJECTED" || restored.statusView.status === "FAILED") {
          notifyInvalidated();
        }
        setNotice(`이전 마스크 선언을 불러왔습니다 · ${restored.childView.declaration.maskChildId}. 검사가 끝나기 전에는 계산을 요청하지 않습니다.`);
        return;
      }
      let current: MaskedCalculationDetailWire;
      try {
        current = await getMaskedCalculation(siteId, workAreaId, wanted.requestId, { signal });
      } catch (error) {
        if (seqRef.current !== seq) return;
        if (error instanceof MaskedNotFoundError || error instanceof MaskedForbiddenError) {
          dropContinuity("이전 마스크 작업을 찾을 수 없거나 접근할 수 없습니다. 기록을 지웠습니다.");
          notifyInvalidated();
          return;
        }
        throw error;
      }
      if (seqRef.current !== seq) return;
      if (
        current.organizationId !== wantedScope.organizationId
        || (current.admission !== null
          && current.admission.sourceCalculationIdentityDigest !== wantedScope.sourceCalculationIdentityDigest)
      ) {
        dropContinuity("이전 작업의 원본이 바뀌어 기록을 지웠습니다. 새로 선언하세요.");
        notifyInvalidated();
        return;
      }
      setCalculation(current);
      emitCurrent(current);
      setNotice(`이전 마스크 작업을 불러왔습니다 · ${wanted.requestId}.`);
    });
  };

  const fetchSourceContext = () => {
    if (!sourceCalculationIdentityDigest || busy) return;
    void runAction("context", async (signal, seq) => {
      const context = await getMaskSourceContext(siteId, workAreaId, sourceCalculationIdentityDigest, { signal });
      if (seqRef.current !== seq) return;
      setSourceContext(context);
      setNotice("원본 맥락을 불러왔습니다. 확인된 원본 정보 그대로 선언에 씁니다.");
    });
  };

  const pickFile = (file: File | null) => {
    setActionError(null);
    setActionCode(null);
    setNotice(null);
    setDeclared(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const guard = validateMaskFile(file, effectiveBudget);
    if (guard) {
      setSelectedFile(null);
      setActionError(guard);
      return;
    }
    setSelectedFile(file);
  };

  const hashSelected = () => {
    if (!selectedFile || busy) return;
    void runAction("hash", async (_signal, seq) => {
      const bytes = new Uint8Array(await selectedFile.arrayBuffer());
      if (seqRef.current !== seq) return;
      if (bytes.byteLength !== selectedFile.size || bytes.byteLength <= 0) {
        throw new MaskedRequestError("파일 크기를 확인하지 못했습니다. 파일을 다시 선택하세요.");
      }
      const sha256 = await sha256HexOfBytes(bytes);
      if (seqRef.current !== seq) return;
      setDeclared({ sha256, sizeBytes: bytes.byteLength });
      setNotice(`선언 준비됨 · ${formatBytesKo(bytes.byteLength)} · 확인값 ${sha256.slice(0, 19)}…`);
    });
  };

  const submitDeclare = () => {
    if (!selectedFile || !declared || !sourceCalculationIdentityDigest || busy) return;
    if (!sourceContext) {
      setActionError("원본 맥락 연결 전입니다. 기준선 바인딩이 내려오면 선언할 수 있습니다.");
      setActionCode(null);
      return;
    }
    if (effectiveBudget !== null && declared.sizeBytes > effectiveBudget) {
      setActionError(`마스크 파일 크기는 ${effectiveBudget}바이트 이하여야 합니다.`);
      setActionCode(null);
      return;
    }
    void runAction("declare", async (signal, seq) => {
      // 부모는 통상 현재 subject로 둔다(기준-부모도 허용되지만, 원본 맥락의
      // 현재본이 일상 경로다). 선언 subject·기준선은 봉인 그대로만 쓴다.
      // 같은 입력에는 같은 본문을 재사용한다 — 모호한 응답 뒤 재시도가 새
      // 자식을 만들지 않는다. 수락된 자식이 있으면 명시적 새 선언으로 본다.
      const intentKey = JSON.stringify([
        sourceCalculationIdentityDigest,
        sourceContext.currentSubject,
        sourceContext.baselineSubject,
        sourceContext.baselineDsmArtifactId,
        declared.sha256,
        declared.sizeBytes,
      ]);
      let intent = declareIntentRef.current;
      let reused = false;
      if (intent && intent.key === intentKey && child?.declaration.maskChildId !== intent.body.maskChildId) {
        reused = true;
      } else {
        intent = {
          key: intentKey,
          body: {
            contractVersion: "external-mask-child-declaration.v1",
            declarationId: opaqueId("decl"),
            organizationId: sourceContext.currentSubject.organizationId,
            siteId,
            workAreaId,
            childKind: "MASK_CHILD",
            maskChildId: opaqueId("mask"),
            maskArtifactId: opaqueId("mask-artifact"),
            parentSubject: sourceContext.currentSubject,
            targetBaselineSubject: sourceContext.baselineSubject,
            targetBaselineDsmArtifactId: sourceContext.baselineDsmArtifactId,
            declaredSha256: declared.sha256,
            declaredSizeBytes: declared.sizeBytes,
            declarationDigest: null,
          },
        };
        declareIntentRef.current = intent;
      }
      const view = await declareMaskChild(siteId, workAreaId, intent.body, { signal });
      if (seqRef.current !== seq) return;
      setChild(view);
      // A newly accepted mask is a new selection, not the previous result's
      // mask. Preserve old Core records without presenting/exporting their
      // numerics as this draft's result.
      setCalculation(null);
      setInspection(null);
      notifyInvalidated();
      // Core 수락 뒤에만 기억한다(선언 전에는 쓰지 않는다).
      if (continuityScope) {
        writeMaskedContinuity(continuityScope, { maskChildId: view.declaration.maskChildId, requestId: null });
        setContinuity(readMaskedContinuity(continuityScope));
      }
      setNotice(`마스크 입력을 선언했습니다 · ${view.declaration.maskChildId}${reused ? " · 같은 선언으로 다시 시도했습니다" : ""}. 검사가 끝나기 전에는 계산을 요청하지 않습니다.`);
    });
  };

  const submitGrantAndUpload = () => {
    if (!selectedFile || !declared || !child || busy) return;
    void runAction("upload", async (signal, seq) => {
      const declaration = child.declaration;
      const subjectDigest = await canonicalSubjectDigest(declaration.parentSubject);
      if (seqRef.current !== seq) return;
      const grant = await requestMaskUploadGrant(siteId, workAreaId, declaration.maskChildId, {
        maskArtifactId: declaration.maskArtifactId,
        subjectDigest,
        declaredSha256: declared.sha256,
        declaredSizeBytes: declared.sizeBytes,
      }, { signal });
      if (seqRef.current !== seq) return;
      await uploadMaskBytes(siteId, workAreaId, declaration.maskChildId, grant.grantId, selectedFile, {
        maskArtifactId: declaration.maskArtifactId,
        declaredSha256: declared.sha256,
        declaredSizeBytes: declared.sizeBytes,
      }, { signal });
      if (seqRef.current !== seq) return;
      const { childView, statusView } = await fetchChildAndStatus(declaration.maskChildId, signal);
      if (seqRef.current !== seq) return;
      setChild(childView);
      setInspection(statusView);
      if (statusView.status === "REJECTED" || statusView.status === "FAILED") {
        notifyInvalidated();
        setNotice(
          statusView.reasonCode
            ? `${maskInspectionReasonMessage(statusView.reasonCode)} (검사: ${statusView.status})`
            : `마스크 검사가 종료됐습니다(검사: ${statusView.status}). 새 파일로 다시 등록하세요.`,
        );
        return;
      }
      setNotice(
        childView.manifest
          ? `업로드·검사가 완료됐습니다 · ${childView.manifest.maskChildId}. 이제 V3 계산을 요청할 수 있습니다.`
          : statusView.status === "RUNNING"
            ? `검사가 진행 중입니다 · ${declaration.maskChildId}. 끝난 뒤 새로고침으로 확인하세요.`
            : `업로드가 봉인됐습니다 · ${declaration.maskChildId}. 검사가 끝나면 새로고침으로 확인하세요.`,
      );
    });
  };

  const refreshChild = () => {
    if (!child || busy) return;
    void runAction("refresh-child", async (signal, seq) => {
      const { childView, statusView } = await fetchChildAndStatus(child.declaration.maskChildId, signal);
      if (seqRef.current !== seq) return;
      setChild(childView);
      setInspection(statusView);
      if (statusView.status === "REJECTED" || statusView.status === "FAILED") {
        notifyInvalidated();
        setNotice(
          statusView.reasonCode
            ? `${maskInspectionReasonMessage(statusView.reasonCode)} (검사: ${statusView.status})`
            : `마스크 검사가 종료됐습니다(검사: ${statusView.status}). 새 파일로 다시 등록하세요.`,
        );
        return;
      }
      setNotice(
        childView.manifest && statusView.status === "COMPLETED"
          ? "검사 완료(봉인됨) 상태입니다."
          : statusView.status === "RUNNING"
            ? "검사가 진행 중입니다. 끝난 뒤 새로고침으로 확인하세요."
            : "아직 검사 대기 중입니다.",
      );
    });
  };

  const submitCreate = () => {
    if (!sourceCalculationIdentityDigest || !effectiveMaskChildId || busy) return;
    void runAction("create", async (signal, seq) => {
      // 같은 원본+자식에는 같은 요청 본문을 재사용한다 — POST 타임아웃이나
      // 생성 뒤 화면 조회 실패 뒤 재시도가 새 작업을 만들지 않는다.
      // 알려진 종료(COMPLETED·FAILED·CANCELED) 뒤에는 명시적 새 요청으로 본다.
      const intentKey = `${sourceCalculationIdentityDigest}|${effectiveMaskChildId}`;
      const terminal = detail !== null
        && (detail.status === "COMPLETED" || detail.status === "FAILED" || detail.status === "CANCELED");
      let intent = createIntentRef.current;
      let reused = false;
      if (intent && intent.key === intentKey && !terminal) {
        reused = true;
      } else {
        intent = {
          key: intentKey,
          body: {
            maskedCalculationId: opaqueId("masked"),
            sourceCalculationIdentityDigest,
            maskChildId: effectiveMaskChildId,
            requestId: opaqueId("req"),
            idempotencyKey: opaqueId("idem"),
          },
        };
        createIntentRef.current = intent;
      }
      const created = await createMaskedCalculation(siteId, workAreaId, intent.body, { signal });
      // 수락된 요청 id는 화면 조회 전에 기억한다 — GET이 실패해도 같은 id로
      // 다시 물을 수 있다. 캐시는 권한이 아니라서 자동 읽기를 만들지 않는다.
      if (continuityScope) {
        writeMaskedContinuity(continuityScope, { maskChildId: effectiveMaskChildId, requestId: created.requestId });
        setContinuity(readMaskedContinuity(continuityScope));
      }
      if (seqRef.current !== seq) return;
      const current = await getMaskedCalculation(siteId, workAreaId, created.requestId, { signal });
      if (seqRef.current !== seq) return;
      setCalculation(current);
      emitCurrent(current);
      setNotice(`V3 계산을 접수했습니다 · ${created.requestId}${reused ? " · 같은 요청으로 다시 시도했습니다" : ""}. 결과는 새로고침으로 확인하세요.`);
    });
  };

  const refreshCalculation = () => {
    if (!detail || busy) return;
    void runAction("refresh-calc", async (signal, seq) => {
      const current = await getMaskedCalculation(siteId, workAreaId, detail.requestId, { signal });
      if (seqRef.current !== seq) return;
      setCalculation(current);
      emitCurrent(current);
      setNotice("V3 화면을 새로 불러왔습니다.");
    });
  };

  const submitCancel = () => {
    if (!detail || busy) return;
    void runAction("cancel", async (signal, seq) => {
      await cancelMaskedCalculation(siteId, workAreaId, detail.requestId, { signal });
      if (seqRef.current !== seq) return;
      const current = await getMaskedCalculation(siteId, workAreaId, detail.requestId, { signal }).catch(() => null);
      if (seqRef.current !== seq) return;
      if (current) {
        setCalculation(current);
        emitCurrent(current);
      }
      setNotice("V3 변경 취소를 요청했습니다. 수치 표시는 마지막 검증 화면을 그대로 둡니다.");
    });
  };

  const executionBadge = detail ? statusBadge(detail.status) : null;

  return <section className="rounded-lg border border-line bg-surface" aria-label="독립 마스크 계산">
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-[15px] font-bold">독립 마스크 계산</h2>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">V3 · 기존 V2 결과와 분리된 별도 계산입니다. V2 수치 성공 없이도 요청할 수 있습니다.</p>
        <p className="mt-0.5 text-[12px] text-ink-2">{workAreaName}</p>
      </div>
      {executionBadge && detail && <StateBadge label={executionBadge.label} tone={executionBadge.tone} />}
    </div>

    <p role="status" aria-live="polite" className="sr-only">{notice ?? actionError ?? "독립 마스크 계산 영역"}</p>

    {!connected && <div className="border-t border-line px-4 py-3" role="note">
      <p className="text-[12.5px] leading-5 text-ink-2">마스크 입력 연결 전입니다. AP 사전확인의 원본 계산 신원을 먼저 선택하면 독립 마스크 계산을 요청할 수 있습니다.</p>
    </div>}

    {sourceCalculationIdentityDigest && <div className="border-t border-line px-4 py-3">
      <h3 className="text-[13px] font-bold">원본 계산 신원</h3>
      {(baselineLabel || currentLabel) && <p className="mt-1 text-[12px] leading-5 text-ink-2">기준 {baselineLabel ?? "—"} · 현재 {currentLabel ?? "—"}</p>}
      <details className="mt-1 text-[11.5px] text-ink-muted">
        <summary className="tap-target cursor-pointer font-semibold">원본 계산 신원 확인값(AP 사전확인)</summary>
        <p className="mt-1 break-all">{sourceCalculationIdentityDigest}</p>
      </details>
      {!sourceContext && <div className="mt-2">
        <p className="text-[12px] leading-5 text-ink-muted">원본 맥락 연결 전입니다. 확인된 원본 정보가 내려오면 선언할 수 있습니다.</p>
        <button type="button" className="btn mt-2" disabled={busy !== null} onClick={fetchSourceContext}>
          {busy === "context" ? "불러오는 중" : "마스크 설정 불러오기"}
        </button>
      </div>}
      {sourceContext && <div className="mt-2 text-[12px] leading-5 text-ink-2">
        <p>원본 맥락 확인됨 · 기준 자료 {sourceContext.baselineDsmArtifactId} · 원시 상한 {formatBytesKo(sourceContext.maxMaskBytes)}</p>
        <p className="mt-0.5 text-ink-muted">
          {sourceContext.sourceDisposition === "ADMIT_EVALUATED"
            ? "원본 승인 상태: 평가됨 — 물량 정확도 보증·정산 승인을 뜻하지 않습니다."
            : "원본 승인 상태: 임시 허용 — 품질 인증이 아닙니다. 정확도 검증·정산·완료 승인을 뜻하지 않습니다."}
        </p>
      </div>}
    </div>}

    {connected && needsRestore && <div className="border-t border-line px-4 py-3">
      <h3 className="text-[13px] font-bold">이전 마스크 작업</h3>
      <p className="mt-1 text-[12px] leading-5 text-ink-2">
        자식 {continuity?.maskChildId}{continuity?.requestId ? ` · 요청 ${continuity.requestId}` : " · 계산 요청 전"}.
        불러오기는 읽기 전용이며 파일·업로드를 만들지 않습니다.
      </p>
      <button type="button" className="btn mt-2" disabled={busy !== null} onClick={restoreContinuity}>
        {busy === "restore" ? "불러오는 중" : "이전 마스크 작업 불러오기"}
      </button>
    </div>}

    {connected && <div className="border-t border-line px-4 py-3">
      <h3 className="text-[13px] font-bold">마스크 파일 입력</h3>
      <p className="mt-1 text-[12px] leading-5 text-ink-muted">
        uint8 단일 밴드 TIFF만 가능하며{effectiveBudget !== null ? `, ${formatBytesKo(effectiveBudget)} 이하만 받습니다` : " — 서버 업로드 예산이 설정되지 않아 선택할 수 없습니다"}. 픽셀을 미리 읽거나 격자를 선언하지 않습니다.
      </p>
      <ResponsiveActionBoundary
        action="ANALYSIS_REQUEST"
        title="노트북에서 계속"
        reason="마스크 입력·계산 요청은 전체 Operations Console이 필요한 쓰기 작업입니다."
      >
        {canRequest ? <div className="mt-3 grid gap-3">
          <label className="text-[12.5px] font-semibold" htmlFor="masked-file-input">마스크 TIFF 선택
            <input
              id="masked-file-input"
              type="file"
              accept=".tif,.tiff,image/tiff"
              className="input mt-1 w-full"
              disabled={busy !== null || effectiveBudget === null}
              onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn" disabled={busy !== null || !selectedFile} onClick={hashSelected}>
              {busy === "hash" ? "확인 중" : "파일 확인값 계산"}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy !== null || !selectedFile || !declared || !sourceContext}
              onClick={submitDeclare}
            >
              {busy === "declare" ? "선언 중" : "마스크 입력 선언"}
            </button>
            {!sourceContext && <span className="text-[11.5px] text-ink-muted">원본 맥락 연결 전입니다. 기준선 바인딩이 내려오면 선언할 수 있습니다.</span>}
            {!selectedFile && <span className="text-[11.5px] text-ink-muted">파일을 선택하면 확인값을 계산할 수 있습니다.</span>}
          </div>
          {declared && <p className="break-all text-[12px] text-ink-2">선언 크기 {formatBytesKo(declared.sizeBytes)} · 선언 확인값 {declared.sha256}</p>}
          {child && <div className="rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12px] leading-5 text-ink-2">
            <p>자식 {child.declaration.maskChildId} · 선언됨</p>
            {!inspection && <p className="mt-0.5">검사 상태를 새로고침으로 확인하세요. 검사 완료(봉인)가 확인되기 전에는 계산을 요청하지 않습니다.</p>}
            {inspection?.status === "COMPLETED" && <p className="mt-0.5">검사 완료(봉인됨) — V3 계산을 요청할 수 있습니다.</p>}
            {inspection?.status === "RUNNING" && <p className="mt-0.5">검사가 진행 중입니다. 끝난 뒤 새로고침으로 확인하세요.</p>}
            {inspection?.status === "PENDING" && <p className="mt-0.5">검사 대기 중 — 업로드 후 새로고침으로 확인하세요.</p>}
            {(inspection?.status === "REJECTED" || inspection?.status === "FAILED") && <p className="mt-0.5" role="alert">
              {inspection.reasonCode ? maskInspectionReasonMessage(inspection.reasonCode) : `마스크 검사가 종료됐습니다(검사: ${inspection.status}).`} 새 파일로 다시 등록하세요.
            </p>}
            <div className="mt-2 flex flex-wrap gap-2">
              {inspection?.status !== "REJECTED" && inspection?.status !== "FAILED" && <button type="button" className="btn" disabled={busy !== null} onClick={submitGrantAndUpload}>
                {busy === "upload" ? "업로드 중" : manifest ? "마스크 다시 업로드" : "마스크 업로드"}
              </button>}
              <button type="button" className="btn" disabled={busy !== null} onClick={refreshChild}>
                {busy === "refresh-child" ? "확인 중" : "검사 상태 새로고침"}
              </button>
            </div>
          </div>}
        </div> : <div className="mt-3"><ActionUnavailable label="마스크 입력 선언" description="마스크 입력 선언은 현장 쓰기 권한이 있는 담당자에게 요청하세요." /></div>}
      </ResponsiveActionBoundary>
      {actionError && <div className="mt-3 rounded-md border border-crit bg-crit-bg px-3 py-2" role="alert">
        <p className="text-[12px] leading-5 text-crit-ink">{actionError}</p>
        {actionCode && <details className="mt-1 text-[11.5px] text-crit-ink">
          <summary className="tap-target cursor-pointer font-semibold">오류 코드</summary>
          <p className="mt-1 break-all"><code>{actionCode}</code></p>
        </details>}
      </div>}
      {notice && <p role="status" className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12px] leading-5 text-ink-2">{notice}</p>}
    </div>}

    {connected && effectiveMaskChildId && manifest && canRequest && <div className="border-t border-line px-4 py-3">
      <h3 className="text-[13px] font-bold">V3 계산 요청</h3>
      <p className="mt-1 text-[12px] leading-5 text-ink-muted">원본 계산 신원 + 마스크 자식만으로 요청합니다. 마스크 바인딩은 Core가 봉인 manifest로부터 만듭니다.</p>
      {!inspectionSealed && <p className="mt-1 text-[12px] leading-5 text-ink-muted" role="note">V3 계산은 검사 완료(봉인)가 확인된 뒤 요청할 수 있습니다. 검사 상태를 새로고침하세요.</p>}
      <ResponsiveActionBoundary
        action="ANALYSIS_REQUEST"
        title="노트북에서 계속"
        reason="마스크 계산 요청은 전체 Operations Console이 필요한 쓰기 작업입니다."
      >
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className="btn btn-primary" disabled={busy !== null || !inspectionSealed} onClick={submitCreate}>
            {busy === "create" ? "요청 중" : detail ? "현재 원본으로 V3 다시 요청" : "V3 계산 요청"}
          </button>
          {detail && <button type="button" className="btn" disabled={busy !== null} onClick={refreshCalculation}>
            {busy === "refresh-calc" ? "확인 중" : "V3 화면 새로고침"}
          </button>}
          {detail && detail.status !== "COMPLETED" && detail.status !== "FAILED" && detail.status !== "CANCELED" && <button type="button" className="btn" disabled={busy !== null} onClick={submitCancel}>
            {busy === "cancel" ? "취소 중" : "V3 변경 취소"}
          </button>}
        </div>
      </ResponsiveActionBoundary>
    </div>}

    {detail && detail.disposition !== "AVAILABLE" && <div className="border-t border-line px-4 py-3" role="status">
      <p className="text-[12.5px] leading-5 text-ink-2">{dispositionNote(detail.disposition) ?? `V3 계산이 ${statusBadge(detail.status).label} 상태입니다.`}</p>
      {detail.admission && <p className="mt-1 text-[12px] leading-5 text-ink-muted">
        승인 {detail.admission.disposition === "ADMIT_EVALUATED" ? "평가됨" : detail.admission.disposition === "ADMIT_PROVISIONAL" ? "임시 허용" : detail.admission.disposition}
        {detail.admission.disposition !== "ADMIT_EVALUATED" ? " — 품질 인증이 아닙니다. 정확도 검증·정산·완료 승인을 뜻하지 않습니다." : " — 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다."}
      </p>}
    </div>}

    {report && detail && <section className="border-t border-line px-4 py-3" aria-label="독립 마스크 계산 결과">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[13px] font-bold">독립 마스크 계산 결과</h3>
        <StateBadge label={statusBadge(detail.status).label} tone={statusBadge(detail.status).tone} />
      </div>
      <p className="mt-1 text-[12px] leading-5 text-ink-muted">현재−기준 델타 · 단위 metre · 임계값 0 m 고정. 봉인된 V3 보고서에서만 읽으며, 내보내기 상태가 바뀌어도 이 표시는 바뀌지 않습니다.</p>
      <dl className="mt-2 grid gap-2 border-t border-line pt-2 sm:grid-cols-3 sm:gap-3">
        <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">절토</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatVolume(report.numericResult.metrics.cutM3)}</dd></div>
        <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">성토</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatVolume(report.numericResult.metrics.fillM3)}</dd></div>
        <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">순변화</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatVolume(report.numericResult.metrics.netM3)}</dd></div>
      </dl>
      {report.numericResult.metrics.uncertaintyM3 === null ? (
        <p className="mt-2 text-[12px] leading-5 text-ink-2">불확실성 미기록 — 기록된 값이 없으므로 0으로 볼 수 없습니다. 검사점 평가와 별개입니다.</p>
      ) : null}
      <dl className="mt-3 grid gap-2 text-[12px] text-ink-2 sm:grid-cols-2">
        <div><dt className="text-ink-muted">원본 선택 셀</dt><dd>{formatCountKo(report.numericResult.coverage.originalSelectedCellCount)} · {formatArea(report.numericResult.coverage.originalSelectedAreaM2)}</dd></div>
        <div><dt className="text-ink-muted">마스크 제외 셀</dt><dd>{formatCountKo(report.numericResult.coverage.maskExcludedCellCount)}</dd></div>
        <div><dt className="text-ink-muted">유효 셀(원본−마스크)</dt><dd>{formatCountKo(report.numericResult.coverage.effectiveSelectedCellCount)} · {formatArea(report.numericResult.coverage.effectiveSelectedAreaM2)}</dd></div>
        <div><dt className="text-ink-muted">공통 유효 셀</dt><dd>{formatCountKo(report.numericResult.coverage.commonValidCellCount)} · 유효 커버리지 100%</dd></div>
      </dl>
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">작업구역 구멍이 먼저 제외되고 마스크가 그 다음에 제외됩니다. 확인할 수 없는 셀은 없습니다.</p>
      <details className="mt-3 text-xs text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold">V3 계산·마스크 제외 영역 보기</summary>
        <CoverageGridView witness={report.numericResult.coverage} />
      </details>
      {!report.numericResult.impact.unmaskedImpactKnown ? <div className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2.5 text-[12.5px] leading-5 text-ink-2">
        <p className="font-semibold text-ink-1">제외 영역의 원래 수치는 확인할 수 없음</p>
        <p className="mt-1">원본 구역에 값이 없던 셀이 있어 마스크를 씌우지 않았을 때의 수치를 확정할 수 없습니다. 알 수 없는 값은 0으로 표시하지 않습니다.</p>
      </div> : <dl className="mt-3 grid gap-2 text-[12px] text-ink-2 sm:grid-cols-3">
        <div><dt className="font-semibold text-ink-muted">마스크 없음 절토</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.unmaskedCutM3 ?? 0)}</dd></div>
        <div><dt className="font-semibold text-ink-muted">마스크 없음 성토</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.unmaskedFillM3 ?? 0)}</dd></div>
        <div><dt className="font-semibold text-ink-muted">마스크 없음 순변화</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.unmaskedNetM3 ?? 0)}</dd></div>
        <div><dt className="font-semibold text-ink-muted">제외된 절토</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.excludedCutM3 ?? 0)}</dd></div>
        <div><dt className="font-semibold text-ink-muted">제외된 성토</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.excludedFillM3 ?? 0)}</dd></div>
        <div><dt className="font-semibold text-ink-muted">제외된 순변화</dt><dd className="num mt-1 break-words text-[14px] font-bold text-ink-1">{formatVolume(report.numericResult.impact.excludedNetM3 ?? 0)}</dd></div>
      </dl>}
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">
        {detail.admission?.disposition === "ADMIT_EVALUATED"
          ? "독립 평가 근거가 있습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다."
          : "임시 허용이며 품질 인증이 아닙니다. 정확도 검증·정산·완료 승인을 뜻하지 않습니다."}
      </p>
      {handoffRef && onDeltaHandoff && <div className="mt-3 border-t border-line pt-3">
        <p className="text-[12px] leading-5 text-ink-muted">이 V3 결과를 기존 내보내기 패널로 넘기면, 부모가 세 확인값과 자식으로 발행 경로를 compose합니다.</p>
        <button type="button" className="btn mt-2" onClick={() => onDeltaHandoff(handoffRef)}>내보내기로 인계</button>
      </div>}
      {detail.disposition === "AVAILABLE" && !handoffRef && <p className="mt-3 text-[12px] leading-5 text-ink-muted" role="note">인계 참조를 만들 수 없습니다(승인 또는 자식 식별자 확인 불가). 수치 표시는 그대로 둡니다.</p>}
      <details className="mt-2 text-[11.5px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold text-ink-muted">처리 상세</summary>
        <div className="mt-1 grid gap-1 border-l-2 border-line pl-3 sm:grid-cols-2">
          <div className="min-w-0"><p className="text-ink-muted">수치 결과 확인값</p><p className="break-all">{report.numericResultIdentityDigest}</p></div>
          <div className="min-w-0"><p className="text-ink-muted">범위 근거 확인값</p><p className="break-all">{report.numericResult.coverage.coverageWitnessDigest}</p></div>
          <div className="min-w-0"><p className="text-ink-muted">마스크 바인딩 확인값</p><p className="break-all">{report.numericResult.maskBindingDigest}</p></div>
          <div className="min-w-0"><p className="text-ink-muted">보고서 확인값</p><p className="break-all">{report.reportDigest}</p></div>
        </div>
      </details>
    </section>}

    {detail?.disposition === "AVAILABLE" && !report && <div className="border-t border-line px-4 py-3">
      <p role="alert" className="text-[12.5px] leading-5 text-crit-ink">사용 가능 표시인데 수치 내용을 확인하지 못했습니다. 수치를 0으로 해석하지 말고 화면을 새로고침하세요.</p>
    </div>}
  </section>;
}
