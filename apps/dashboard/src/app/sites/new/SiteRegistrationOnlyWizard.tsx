"use client";

import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSiteListRefresh } from "@/components/nav/SiteListContext";

import { WizardShell } from "@/components/wizard/WizardShell";
import { AoiPolygonMap, type AoiMapPendingState, type AoiRawSnapshot } from "@/components/map/AoiPolygonMap";
import { ErrorState } from "@/components/ui/ErrorState";
import { useDraftState } from "@/hooks/useDraftState";
import { DRAFT_BINDING_BACKUP_KEY, MAP_BACKUP_KEY, MAP_STORAGE_KEY, parseMapRecord, writeMapRecord, type MapRecord } from "./site-registration-map-storage";
import { SiteRegistrationStorageGate } from "./SiteRegistrationStorageGate";
import { SiteRegistrationRecoveryGuidance } from "./SiteRegistrationRecoveryGuidance";
import { buildDataResidencyInput, type EgressChoice } from "@/lib/data-residency";
import { isConvexPolygon } from "@/lib/geometry";
import type { SiteRegistrationMode } from "@/lib/core-api/permissions";
import {
  buildSitePostAttempt,
  classifyLegacySitePost,
  digestSitePostPayload,
  EGRESS_CHOICE_OPTIONS,
  Field,
  isValidPriorUnknown,
  MAX_PRIOR_UNKNOWNS,
  removePriorUnknown,
  SITE_ID_PATTERN,
  parseJsonSafe,
  upsertPriorUnknown,
  verifySitePostEcho,
  type PriorUnknownRequest,
  type SitePostAttempt,
  type SitePostEchoExpectation,
  type SitePostPayloadInput,
} from "@/lib/site-registration/shared";
import type { AoiVertex, SiteFrame } from "@/lib/core-api/types";

// 현장 등록은 기본정보 → AOI/좌표계 → 확인의 3단계로 끝낸다. 베이스라인 조사는
// 등록 성공 뒤 현장 작업공간에서 별도로 시작한다. 현장 등록과 Mission 발급을 한
// Wizard에 묶지 않는 것은 ADR-KSI-026의 작업 경계다.
const STEP_LABELS = ["기본정보", "현장 범위·좌표계", "확인·등록"];
const DRAFT_STORAGE_KEY = "ksi-wizard-site-registration-only";
const CANONICAL_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * 성공 확인 영수증 — 검증된 2xx 결속 뒤에만 쓴다. 권한·조회 실패로 완성 화면이
 * unmount됐다가 같은 탭에서 마법사가 다시 마운트되면 확인 결과를 되살리는 데
 * 쓴다. 같은 탭의 확인 기록일 뿐 소유권 증명이 아니며, 읽기 전용 이동에만 쓴다.
 */
const SUCCESS_RECEIPT_KEY = `${DRAFT_STORAGE_KEY}:success`;
const SUCCESS_DRAFT_BACKUP_KEY = `${DRAFT_STORAGE_KEY}:success-draft-backup`;

interface RegistrationSuccessReceipt {
  mode: Exclude<SiteRegistrationMode, "DENIED">;
  siteId: string;
  name: string;
  /**
   * 확인 당시의 원래 신원 지문. 복원은 이 값이 현재 페이지 신원 prop과 일치할
   * 때만 한다 — 같은 탭 A→B 전환 뒤 B 화면에 A의 성공을 복원·표시하지 않는다
   * (INV-060: B에게 A의 siteId를 노출하지 않는다). null이면(지문 없이 성공한
   * 구 경로) 외부 경계를 넘어 복원하지 않는다 — fake success 저장 금지.
   */
  fingerprint: string | null;
  draftBinding?: string;
}

function readSuccessReceipt(): RegistrationSuccessReceipt | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    const raw = sessionStorage.getItem(SUCCESS_RECEIPT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      ((parsed as { mode?: unknown }).mode === "MAPPED_BOOTSTRAP" ||
        (parsed as { mode?: unknown }).mode === "LEGACY_SITE_ID") &&
      ((parsed as { draftBinding?: unknown }).draftBinding === undefined ||
        (typeof (parsed as { draftBinding?: unknown }).draftBinding === "string" && /^v1-[0-9a-f]{64}$/.test((parsed as { draftBinding: string }).draftBinding))) &&
      typeof (parsed as { siteId?: unknown }).siteId === "string" &&
      (parsed as { siteId: string }).siteId.length > 0 &&
      typeof (parsed as { name?: unknown }).name === "string" &&
      ((parsed as { fingerprint?: unknown }).fingerprint === null ||
        (typeof (parsed as { fingerprint?: unknown }).fingerprint === "string" &&
          FINGERPRINT_PATTERN.test((parsed as { fingerprint: string }).fingerprint)))
    ) {
      const receipt = parsed as RegistrationSuccessReceipt;
      return {
        mode: receipt.mode,
        siteId: receipt.siteId,
        name: receipt.name,
        fingerprint: receipt.fingerprint,
        draftBinding: receipt.draftBinding,
      };
    }
    return null;
  } catch {
    return null;
  }
}

function writeSuccessReceipt(receipt: RegistrationSuccessReceipt): boolean {
  try {
    const existing = sessionStorage.getItem(SUCCESS_RECEIPT_KEY);
    if (existing !== null) {
      const previous = readSuccessReceipt();
      if (!previous || !receipt.fingerprint || previous.fingerprint !== receipt.fingerprint || previous.mode !== receipt.mode || !receipt.draftBinding || previous.draftBinding !== receipt.draftBinding) return false;
    }
    const serialized = JSON.stringify(receipt);
    sessionStorage.setItem(SUCCESS_RECEIPT_KEY, serialized);
    return sessionStorage.getItem(SUCCESS_RECEIPT_KEY) === serialized;
  } catch {
    // 저장 실패해도 이번 세션 메모리 상태로는 동작한다 — 새로고침 경계에서만
    // 복원이 안 되므로, 호출부가 화면에 유지 고지를 남긴다.
    return false;
  }
}

function clearSuccessReceipt(fingerprint: string | null, mode: RegistrationSuccessReceipt["mode"], draftBinding: string): void {
  try {
    const receipt = readSuccessReceipt();
    if (fingerprint && receipt?.fingerprint === fingerprint && receipt.mode === mode && receipt.draftBinding === draftBinding) sessionStorage.removeItem(SUCCESS_RECEIPT_KEY);
  } catch {
    // no-op
  }
}

interface FormState {
  siteId: string;
  mapDraftId?: string;
  bootstrapRequestId?: string;
  /**
   * 원래 신원 지문 — 첫 POST 전에 확정해 초안과 함께 저장한다. 재시도는 이 값을
   * `x-ksi-continuity-fingerprint`로 실어 보내고, BFF가 현재 세션 신원과 다르면
   * Core POST 없이 409로 끊는다(응답 유실 뒤 계정 교체가 별도 현장을 만드는
   * 것을 막는다). 서버 발급 페이지 prop에서만 채우고, 저장된 값이 있으면 그걸
   * 우선한다(페이지 prop 자동 갱신은 원래 신원을 덮어쓰지 않는다).
   */
  originFingerprint?: string;
  /**
   * 주체 미상 표시 — 저장된 초안에 원래 신원이 확인되지 않을 때 migrate가 세운다.
   * 빈 신규 초안과 구분하기 위한 것으로, 이름·범위·요청 키·미해결 기록 중
   * 어느 것이라도 있으면 "이미 쓰인" 초안으로 보고 현재 계정의 것으로
   * 추측·결속하지 않는다. 원본 payload와 모호한 키는 재작성 없이 잠근다.
   * 이 플래그가 있는 동안은 어떤 계정으로도 표시·전송하지 않는다.
   */
  originUnknown?: boolean;
  /**
   * 확인되지 않은 이전 요청 목록 — "모른다"를 파기하지 않는다. 키 회전·계정 교체·
   * 성공이 이 목록을 지우지 않으며, 검증된 성공은 자기 (kind, key, origin) 항목만
   * 제거한다. draft와 함께 저장되므로 같은 탭 remount 뒤에도 유지된다.
   */
  priorUnknowns?: PriorUnknownRequest[];
  /**
   * 형식이 달라 목록에 올리지 못한 이전 기록의 원문 보관소. isValidPriorUnknown을
   * 통과하지 못한 값(null 지문·깨진 모양 등)을 있는 그대로 보존한다.
   * UI는 개수만 보여주고 내용·삭제·어느 계정으로의 귀속도 열지 않는다(안전 잠금).
   */
  quarantinedUnknowns?: unknown[];
  name: string;
  aoi: AoiVertex[];
  crs: string;
  verticalDatum: string;
  transformVersion: string;
  /** 데이터 반출 선언(INV-050) — "unset" 은 미응답, 등록 후 다시 물을 경로가 없다. */
  egressChoice: EgressChoice;
  jurisdiction: string;
  aiEgressAllowed: boolean;
}

const INITIAL_FORM: FormState = {
  siteId: "",
  name: "",
  aoi: [],
  crs: "",
  verticalDatum: "",
  transformVersion: "1.0.0",
  egressChoice: "unset",
  jurisdiction: "",
  aiEgressAllowed: false,
};

/** 초안 원문과 요청 키를 결속한다. 목록/격리 기록은 별도 보존되며 본문과 독립적이다. */
function receiptDraftBinding(form: FormState): string {
  const body = JSON.stringify([form.siteId, form.bootstrapRequestId ?? null, form.name, form.aoi,
    form.crs, form.verticalDatum, form.transformVersion, form.egressChoice, form.jurisdiction,
    form.aiEgressAllowed, form.originFingerprint ?? null]);
  return `v1-${bytesToHex(sha256(utf8ToBytes(body)))}`;
}

/** 구 영수증은 초안이 없을 때만 확인 화면으로 복원한다. */
function isEmptyRegistrationDraft(form: FormState): boolean {
  return form.siteId === "" && !form.bootstrapRequestId && !form.originFingerprint && !form.originUnknown &&
    form.name === "" && form.aoi.length === 0 && form.crs === "" && form.verticalDatum === "" &&
    form.transformVersion === INITIAL_FORM.transformVersion && form.egressChoice === "unset" &&
    form.jurisdiction === "" && !form.aiEgressAllowed;
}

/**
 * `randomUUID()` is restricted to secure contexts, but this Console is also
 * intentionally served over tailnet-only HTTP in the local workflow. Keep the
 * same cryptographic randomness there via `getRandomValues()`; never fall back
 * to `Math.random()` for request or Site identifiers.
 */
export function createRegistrationUuid(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi.randomUUID === "function") {
    try {
      return cryptoApi.randomUUID();
    } catch {
      // Some browsers expose the method but reject it outside secure contexts.
      // `getRandomValues()` remains available there and preserves CSPRNG quality.
    }
  }

  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  // RFC 9562 UUID v4 version and variant bits.
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * A generated identifier is a starting point, not a server-side identity.
 * It is saved with the browser draft and may always be edited before posting.
 */
export function createGeneratedSiteId(now = Date.now()): string {
  const randomSegment = createRegistrationUuid().replaceAll("-", "").slice(0, 8);
  return `site-${now.toString(36)}-${randomSegment}`;
}

const FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}$/;

function migrateRegistrationDraft(stored: unknown): FormState {
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) throw new Error("invalid draft");
  const candidate = stored as Partial<FormState> & { quarantinedUnknowns?: unknown };
  for (const field of ["siteId", "name", "crs", "verticalDatum", "transformVersion", "egressChoice", "jurisdiction", "bootstrapRequestId", "originFingerprint"] as const) {
    if (candidate[field] !== undefined && typeof candidate[field] !== "string") throw new Error("invalid draft field");
  }
  for (const field of ["aoi", "priorUnknowns", "quarantinedUnknowns"] as const) {
    if (candidate[field] !== undefined && !Array.isArray(candidate[field])) throw new Error("invalid draft collection");
  }
  if (candidate.mapDraftId !== undefined && (typeof candidate.mapDraftId !== "string" || !CANONICAL_UUID_PATTERN.test(candidate.mapDraftId))) throw new Error("invalid map draft id");
  // 이전 요청 키를 모양만 보고 버리면, 이후 편집 시 불명 요청이 새 키로
  // 바뀔 수 있다. 해석하지 못하는 저장 원문은 수화 단계에서 잠근다.
  if (candidate.bootstrapRequestId !== undefined && !CANONICAL_UUID_PATTERN.test(candidate.bootstrapRequestId)) throw new Error("invalid draft request key");
  if (Array.isArray(candidate.aoi) && candidate.aoi.some((vertex) => !vertex || typeof vertex !== "object" || typeof vertex.latDeg !== "number" || !Number.isFinite(vertex.latDeg) || typeof vertex.lonDeg !== "number" || !Number.isFinite(vertex.lonDeg))) throw new Error("invalid draft geometry");
  if (candidate.egressChoice !== undefined && !["unset", "allow", "deny"].includes(candidate.egressChoice)) throw new Error("invalid draft choice");
  if (candidate.originUnknown !== undefined && typeof candidate.originUnknown !== "boolean") throw new Error("invalid draft origin state");
  if (candidate.aiEgressAllowed !== undefined && typeof candidate.aiEgressAllowed !== "boolean") throw new Error("invalid draft choice");
  const originFingerprint =
    typeof candidate.originFingerprint === "string" &&
    FINGERPRINT_PATTERN.test(candidate.originFingerprint)
      ? candidate.originFingerprint
      : undefined;
  // 검증 실패 항목은 버리지 않고 원문 그대로 별도 목록에 보존한다(안전 잠금).
  // null 지문·깨진 모양이 "정상 구조인 척" 목록에 섞이는 것을 막으면서, 저장된
  // 기록 자체는 파기하지 않는다. UI는 개수만 보여주고 내용·삭제·귀속을 열지 않는다.
  const rawUnknowns = Array.isArray(candidate.priorUnknowns) ? candidate.priorUnknowns : [];
  const priorUnknowns = rawUnknowns.filter(isValidPriorUnknown);
  const quarantinedUnknowns = rawUnknowns.filter((item) => !isValidPriorUnknown(item));
  // 이전 버전이 별도 키로 남긴 격리분이 있으면 합쳐 보존한다(형식은 검증하지 않는다).
  const carriedQuarantine = Array.isArray(candidate.quarantinedUnknowns)
    ? candidate.quarantinedUnknowns
    : [];
  // 주체 미상 기존 초안의 판별 — 실제 최초 기본값과 다른 모든 본문 값을
  // 입력으로 취급한다(공백도 원문이다). 유효한 원래 지문이 없으면 현재 계정의 것으로 추측·
  // 결속하지 않고 잠근다. 원본 payload·모호한 키는 재작성하지 않는다.
  // 미해결·격리 기록 목록 자체는 별도 결속 규칙을 따르므로 여기서는 세지 않는다
  // (입력 본문이 비어 있으면 표시할 것이 없어 게이트할 이유가 없다).
  const hasLegacyContent =
    (typeof candidate.siteId === "string" && candidate.siteId !== "") ||
    candidate.mapDraftId !== undefined ||
    (typeof candidate.bootstrapRequestId === "string" && candidate.bootstrapRequestId.trim() !== "") ||
    (typeof candidate.originFingerprint === "string" && !originFingerprint) ||
    (typeof candidate.name === "string" && candidate.name !== "") ||
    (Array.isArray(candidate.aoi) && candidate.aoi.length > 0) ||
    (candidate.crs !== undefined && candidate.crs !== INITIAL_FORM.crs) ||
    (candidate.verticalDatum !== undefined && candidate.verticalDatum !== INITIAL_FORM.verticalDatum) ||
    (candidate.transformVersion !== undefined && candidate.transformVersion !== INITIAL_FORM.transformVersion) ||
    (candidate.egressChoice !== undefined && candidate.egressChoice !== INITIAL_FORM.egressChoice) ||
    (candidate.jurisdiction !== undefined && candidate.jurisdiction !== INITIAL_FORM.jurisdiction) ||
    candidate.aiEgressAllowed === true;
  const originUnknown = candidate.originUnknown === true || (!originFingerprint && hasLegacyContent) ? true : undefined;
  return {
    ...INITIAL_FORM,
    ...candidate,
    originFingerprint,
    originUnknown,
    priorUnknowns,
    quarantinedUnknowns:
      quarantinedUnknowns.length > 0 || carriedQuarantine.length > 0
        ? [...quarantinedUnknowns, ...carriedQuarantine]
        : undefined,
    bootstrapRequestId:
      typeof candidate.bootstrapRequestId === "string" &&
      CANONICAL_UUID_PATTERN.test(candidate.bootstrapRequestId)
        ? candidate.bootstrapRequestId
        : undefined,
    aoi: Array.isArray(candidate.aoi) ? candidate.aoi : INITIAL_FORM.aoi,
    aiEgressAllowed:
      typeof candidate.aiEgressAllowed === "boolean"
        ? candidate.aiEgressAllowed
        : INITIAL_FORM.aiEgressAllowed,
  };
}

const REGISTRATION_FIELDS = new Set(["siteId", "mapDraftId", "bootstrapRequestId", "originFingerprint", "originUnknown", "priorUnknowns", "quarantinedUnknowns", "name", "aoi", "crs", "verticalDatum", "transformVersion", "egressChoice", "jurisdiction", "aiEgressAllowed"]);
function supportedDraftShape(form: FormState): boolean {
  return Object.keys(form).every((key) => REGISTRATION_FIELDS.has(key));
}

const inputClassName = "input";

type SubmitPhase = "idle" | "pending" | "error" | "success";

export function SiteRegistrationOnlyWizard({
  mode,
}: {
  mode: Exclude<SiteRegistrationMode, "DENIED">;
  /**
   * 이 페이지를 렌더한 세션의 서버 확인 신원 지문 — 재시도 연속성 가드와 성공
   * 확인 복원이 원래 신원과 대조하는 재료다. 생략·null이면 이전 계약(보호 없음)
   * 으로 동작한다.
   */
  accountFingerprint?: string | null;
}) {
  const router = useRouter();
  const refreshShellSites = useSiteListRefresh();
  const [form, setForm, , storageStatus] = useDraftState<FormState>(
    DRAFT_STORAGE_KEY,
    INITIAL_FORM,
    migrateRegistrationDraft,
  );
  // 성공 확인 복원 — 새로고침 뒤 권한·조회 실패로 완성 화면이 unmount됐다가 같은
  // 탭에서 마법사가 다시 마운트되면, 영수증으로 확인 화면을 되살린다. 영수증은
  // 검증된 결속 뒤에만 쓰이므로 "성공했을지 모른다"가 아니라 "확인됐다"의 복원이다.
  // 읽기 전용 이동에만 쓰며, 다시 등록하려면 이전 단계로 돌아가면 지워진다.
  // SSR/hydration 일치: 첫 렌더는 서버와 같은 미확인 상태로 두고, 저장소 수화는
  // 마운트 뒤 effect에서만 한다(useDraftState와 같은 관습). 복원은 영수증 지문이
  // 현재 확인된 신원과 일치할 때만 — A→B 전환 뒤 B 화면에 A의 성공을 복원하지
  // 않으며, 불일치해도 영수증을 지우지 않는다(A 복귀 복원을 위해 보존한다).
  const [currentStep, setCurrentStep] = useState(0);
  const [draftReady, setDraftReady] = useState(false);
  const restoreCheckedRef = useRef(false);
  // 현재 인스턴스에서 시작된 작업은 늦은 영수증 복원으로 가리지 않는다.
  const [interacted, setInteracted] = useState(false);
  /**
   * 지도 미반영·편집 중 상태 — 순수 transient다. 초안·영수증·priorUnknowns 어디에도
   * 쓰지 않으므로 계정 결속·복원 흐름과 충돌하지 않는다. step 1에 머무는 동안만
   * 의미가 있고, 화면을 떠나면 지도 컴포넌트가 다시 마운트될 때 새로 보고한다.
   */
  const [aoiPending, setAoiPending] = useState<AoiMapPendingState>({ blocked: false, reason: null });
  const [mapStorage, setMapStorage] = useState<"loading" | "ready" | "failed">("loading");
  const [mapRecord, setMapRecord] = useState<MapRecord | null>(null);
  const [mapReceiptConflict, setMapReceiptConflict] = useState(false);
  const mapRawRef = useRef<string | null>(null);
  const mapFailedRef = useRef(false);
  const mapMountedRef = useRef(false);
  useEffect(() => {
    try {
      if (sessionStorage.getItem(MAP_BACKUP_KEY) !== null || sessionStorage.getItem(DRAFT_BINDING_BACKUP_KEY) !== null || sessionStorage.getItem(SUCCESS_DRAFT_BACKUP_KEY) !== null) throw new Error("unresolved map backup");
      const raw = sessionStorage.getItem(MAP_STORAGE_KEY);
      const record = raw === null ? null : parseMapRecord(raw);
      const receiptConflict = record !== null && sessionStorage.getItem(SUCCESS_RECEIPT_KEY) !== null;
      mapRawRef.current = raw;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate external tab storage
      setMapRecord(record);
      setMapReceiptConflict(receiptConflict);
      setMapStorage("ready");
      if (record) setAoiPending({ blocked: true, reason: "복구된 지도 입력을 확인하세요." });
    } catch {
      mapFailedRef.current = true;
      setMapStorage("failed");
    }
  }, []);

  const initialSiteIdResolvedRef = useRef(false);
  const [legacyIdReady, setLegacyIdReady] = useState(false);
  // 서버 prop은 오래될 수 있으므로 최초 확인과 포커스 복귀에 live 신원만 사용한다.
  const [liveFingerprint, setLiveFingerprint] = useState<string | null>(null);
  // 확인 중 또는 실패 시 fail-closed.
  const [liveChecking, setLiveChecking] = useState(true);
  const [liveFailed, setLiveFailed] = useState(false);
  const liveSeqRef = useRef(0);
  const effectiveIdentity =
    liveChecking || liveFailed ? null : liveFingerprint;
  // 비동기 POST 응답 도착 시점의 확인값을 읽기 위한 미러(클로저는 제출 시점 값).
  // 응답 역전(A 요청이 B 확인 뒤 도착)을 막기 위해 도착 시점에 다시 대조한다.
  const effectiveRef = useRef<string | null>(null);
  useEffect(() => {
    effectiveRef.current = effectiveIdentity;
  });
  // "이 실행에서 어떤 siteId로 이미 POST를 보냈나" — 409 확인 안내의 재료다.
  // siteId·원본 지문·관측 성공 여부만 남기며, 소유권 판정의 근거로 쓰지 않는다.
  // 409는 첫 충돌이든 관측 성공 뒤든 계정 일치가 확인되지 않으므로 자동 성공으로
  // 승격하지 않고 목록·상세 수동 확인으로만 안내한다.
  const postAttemptRef = useRef<SitePostAttempt | null>(null);
  // 버튼의 disabled 렌더보다 먼저 잠근다 — 같은 이벤트 묶음의 중복 POST 방지.
  const submissionLockRef = useRef(false);
  // mapped 응답 유실의 "모른다" — 같은 요청 키의 확정 실패가 이 기록을 덮지
  // 않게 키와 함께 남긴다(키가 바뀌면 무관해지므로 버린다).
  const mappedUnknownRef = useRef<{ requestKey: string; payloadDigest: string } | null>(null);
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [restoredSuccess, setRestoredSuccess] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitDetail, setSubmitDetail] = useState<string | null>(null);
  const [submitAction, setSubmitAction] = useState<{ label: string; href: string } | null>(null);
  // 계정 연속성 차단 — BFF가 Core POST 없이 409로 끊은 상태. 입력·요청 키는
  // 그대로 두고, 원래 계정 복귀 또는 명시적 현재-계정 재시작만 받는다.
  const [continuityBlocked, setContinuityBlocked] = useState(false);
  const [successOrigin, setSuccessOrigin] = useState<string | null>(null);
  const [registeredSiteId, setRegisteredSiteId] = useState<string | null>(null);
  const [registeredSiteName, setRegisteredSiteName] = useState<string | null>(null);
  // 영수증 저장 성공 여부 — 실패해도 성공 판정은 유지하되, 이 화면에서만
  // 유지된다는 점을 고지한다(새로고침 복원 불가).
  const [receiptPersisted, setReceiptPersisted] = useState(true);
  const [successStorageBlocked, setSuccessStorageBlocked] = useState(false);

  useEffect(() => {
    // useDraftState restores session storage in its own effect. Waiting one
    // task turn keeps a restored custom ID intact before we fill an empty legacy
    // draft, and the ref prevents re-generating after a person clears/edits it.
    const timer = window.setTimeout(() => setDraftReady(true), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (mapStorage !== "ready" || mapRecord || !draftReady || storageStatus !== "ready" || liveChecking || liveFailed || !effectiveIdentity || restoreCheckedRef.current || interacted || submitPhase !== "idle" || form.originUnknown || (form.originFingerprint && form.originFingerprint !== effectiveIdentity)) return;
    const receipt = readSuccessReceipt();
    if (!receipt || receipt.mode !== mode) return;
    // 불일치해도 영수증을 지우지 않는다 — B 방문이 A의 복원 재료를 파기하면
    // A 복귀 복원이 불가능해진다. 보여주지만 않고 보존한다.
    if (
      receipt.fingerprint === null ||
      receipt.fingerprint !== effectiveIdentity
    ) {
      return;
    }
    // 지문 없는 구 영수증은 현존 초안과 같은 요청인지 알 수 없다.
    // 결속이 있는 영수증도 저장된 현재 초안과 정확히 맞아야 복원한다.
    if (receipt.draftBinding ? receipt.draftBinding !== receiptDraftBinding(form) : !isEmptyRegistrationDraft(form)) return;
    restoreCheckedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- SSR 불가한 외부 storage의 일치 영수증 복원
    setSuccessOrigin(receipt.fingerprint);
    setRestoredSuccess(true);
    setRegisteredSiteId(receipt.siteId);
    setRegisteredSiteName(receipt.name);
    setSubmitPhase("success");
    setCurrentStep(2);
  }, [draftReady, mode, effectiveIdentity, liveChecking, liveFailed, storageStatus, form, submitPhase, interacted, mapStorage, mapRecord]);

  // 최신 live 응답만 반영한다.
  useEffect(() => {
    function invalidateLiveIdentity() {
      // 가려지거나 포커스를 잃기 전에 보던 계정을 다음 전경 프레임의
      // 근거로 쓰지 않는다. 진행 중인 이전 확인도 무효화한다.
      liveSeqRef.current += 1;
      effectiveRef.current = null;
      // 브라우저가 다음 화면을 그리기 전에 숨김 상태를 반영한다. 지도
      // 단계의 인스턴스는 아래 hidden/inert 경계에서 그대로 보존된다.
      flushSync(() => setLiveChecking(true));
    }
    async function refreshLiveIdentity() {
      const seq = liveSeqRef.current + 1;
      liveSeqRef.current = seq;
      effectiveRef.current = null;
      setLiveChecking(true);
      try {
        const res = await fetch("/api/account-identity", { cache: "no-store" });
        if (!res || !res.ok) throw new Error("identity check failed");
        const body: unknown = await res.json().catch(() => null);
        if (
          !body ||
          typeof body !== "object" ||
          typeof (body as { fingerprint?: unknown }).fingerprint !== "string" ||
          !FINGERPRINT_PATTERN.test((body as { fingerprint: string }).fingerprint)
        ) {
          throw new Error("identity check returned an unusable body");
        }
        // 가장 최근 요청이 아니면 버린다 — 느린 이전 응답이 새 확인을 덮으면
        // B에게 A 화면을 다시 보여주게 된다.
        if (liveSeqRef.current !== seq) return;
        setLiveFingerprint((body as { fingerprint: string }).fingerprint);
        setLiveChecking(false);
        setLiveFailed(false);
      } catch {
        if (liveSeqRef.current !== seq) return;
        setLiveChecking(false);
        // 실패는 미확인으로 둔다 — prop 추측으로 표시를 되돌리지 않는다.
        setLiveFailed(true);
      }
    }
    function onVisibilityChange() {
      if (document.visibilityState === "visible") void refreshLiveIdentity();
      else invalidateLiveIdentity();
    }
    function onFocus() {
      if (document.visibilityState === "visible") void refreshLiveIdentity();
    }
    if (document.visibilityState === "visible") void refreshLiveIdentity();
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", invalidateLiveIdentity);
    return () => {
      liveSeqRef.current += 1;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", invalidateLiveIdentity);
    };
  }, []);

  useEffect(() => {
    if (mode !== "LEGACY_SITE_ID" || mapStorage !== "ready" || mapRecord || !supportedDraftShape(form) || !draftReady || storageStatus !== "ready" || !effectiveIdentity || form.originUnknown || (form.originFingerprint && form.originFingerprint !== effectiveIdentity) || initialSiteIdResolvedRef.current) return;
    initialSiteIdResolvedRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 수화 및 live 신원 확인 뒤 ID 초기화가 끝나기 전 입력 노출을 막는다.
    if (form.siteId.trim()) { setLegacyIdReady(true); return; }
    // 다른 계정의 확인 영수증만 남은 빈 화면에서는 ID를 자동 저장하지 않는다.
    // 그 저장 자체가 현재 계정의 초안을 만들어 원래 계정 복원을 가릴 수 있다.
    const existingReceipt = readSuccessReceipt();
    if (!form.originFingerprint && existingReceipt?.fingerprint && (existingReceipt.fingerprint !== effectiveIdentity || (existingReceipt.mode === mode && isEmptyRegistrationDraft(form)))) {
      setLegacyIdReady(true);
      return;
    }
    // 자동 생성 ID도 저장되는 입력이므로 계정을 결속한다 — 기존 요청 지문은
    // 건드리지 않는다. live 신원 확인 뒤 ref 가드로 1회만 돈다.
    setLegacyIdReady(true);
    setForm(
      form.originFingerprint || !effectiveIdentity
        ? { ...form, siteId: createGeneratedSiteId() }
        : { ...form, siteId: createGeneratedSiteId(), originFingerprint: effectiveIdentity },
    );
  }, [draftReady, form, mode, setForm, effectiveIdentity, storageStatus, mapStorage, mapRecord]);

  function update(partial: Partial<FormState>) {
    if (!supportedDraftShape(form) || accountMismatch || mapConflict || mapStorage !== "ready") return;
    setInteracted(true);
    const payloadFields: (keyof FormState)[] = [
      "name",
      "aoi",
      "crs",
      "verticalDatum",
      "transformVersion",
      "egressChoice",
      "jurisdiction",
      "aiEgressAllowed",
    ];
    const payloadChanged = payloadFields.some(
      (field) =>
        Object.prototype.hasOwnProperty.call(partial, field) &&
        !Object.is(partial[field], form[field]),
    );
    const nextForm = { ...form, ...partial };
    // 다른 계정 영수증 때문에 빈 legacy ID 생성을 미룬 경우, 실제 편집이
    // 시작될 때만 현재 초안에 ID를 만든다. 직접 입력한 ID는 존중한다.
    if (mode === "LEGACY_SITE_ID" && !nextForm.siteId && !("siteId" in partial) && !nextForm.originUnknown) {
      nextForm.siteId = createGeneratedSiteId();
    }
    // 새로 저장되는 입력부터 확인된 계정에 결속한다 — 기존 요청 지문을 덮어쓰지
    // 않으며, 이 결속이 있어야 B 재진입 때 A 입력을 표시하지 않는다.
    // 단, 주체 미상으로 잠긴 초안은 결코 결속하지 않는다(현재 계정 소유로
    // 추측하는 것을 막는다). 확인할 수 없으면 결속하지 않는다.
    if (!nextForm.originFingerprint && !nextForm.originUnknown && effectiveIdentity) {
      nextForm.originFingerprint = effectiveIdentity;
    }
    if (mode === "MAPPED_BOOTSTRAP" && form.bootstrapRequestId && payloadChanged) {
      nextForm.bootstrapRequestId = undefined;
      // 키가 바뀌면 이전 키의 불명 기록은 이 시도의 확인 재료가 아니다.
      mappedUnknownRef.current = null;
      setRegisteredSiteId(null);
    }
    setForm(nextForm);
  }

  /** POST에 실을 계정 연속성 지문 — resolve된 원래 신원만 싣는다. */
  function continuityHeader(resolvedOrigin: string): Record<string, string> {
    return { "x-ksi-continuity-fingerprint": resolvedOrigin };
  }

  type OriginResolution = { origin: string } | { blocked: "old-attempt" | "no-identity" };

  function resolveMappedOrigin(input: {
    requestKey: string;
    priorKey: string | null;
  }): OriginResolution {
    if (form.originFingerprint) return { origin: form.originFingerprint };
    // 주체 미상 구 초안은 어떤 계정으로도 POST하지 않는다 — 빈 신규 초안과
    // 달리 원래 payload가 있어, 제출 자체가 귀속 추측이 된다.
    if (form.originUnknown === true) return { blocked: "old-attempt" };
    const candidates = (form.priorUnknowns ?? []).filter(
      (entry) =>
        entry.kind === "mapped" && entry.key === input.requestKey && entry.originFingerprint,
    );
    // 같은 키에 서로 다른 원래 신원의 기록이 있으면 현재 확인된 신원과
    // 일치하는 것을 쓴다 — 타 주체 기록으로 추측·귀속하지 않는다.
    const recorded =
      candidates.find((entry) => entry.originFingerprint === effectiveIdentity) ?? candidates[0];
    if (recorded?.originFingerprint) return { origin: recorded.originFingerprint };
    // 구 초안에 키만 있고 지문이 없으면 그 키의 원래 신원을 알 수 없다 —
    // 현재 값으로 추측해 POST하면 계정 교체 시 별도 현장을 만든다.
    if (input.priorKey !== null) return { blocked: "old-attempt" };
    // 새 미시도 초안만 현재 확인된 신원으로 시작할 수 있다. live 확인값이
    // 있으면 그걸 우선하고, 없으면 마운트 시점 prop을 쓴다.
    if (effectiveIdentity !== null) {
      return { origin: effectiveIdentity };
    }
    return { blocked: "no-identity" };
  }

  /** 확인 없이 POST를 막을 때 — 입력·초안은 그대로 두고 계정 확인을 안내한다. */
  function failOriginBlocked(kind: "old-attempt" | "no-identity") {
    setSubmitError(
      kind === "old-attempt"
        ? "이전 요청의 신원을 확인할 수 없어 같은 키로 다시 보내지 않았습니다. " +
          "서버에 등록됐을 수도 있습니다. 입력은 그대로 있습니다. 현장 목록에서 " +
          "입력한 이름이 있는지 먼저 확인하세요. 목록에 없어도 이 키로의 재시도는 " +
          "원래 계정 확인 없이는 하지 않습니다."
        : "계정을 확인하지 못해 등록 요청을 보내지 않았습니다. 입력은 그대로 있습니다. " +
          "화면을 새로고침해 계정 정보를 다시 받은 뒤 다시 시도하세요.",
    );
    setSubmitPhase("error");
  }

  async function runMappedSubmission() {
    setSubmitPhase("pending");
    setSubmitError(null);
    setSubmitDetail(null);
    setSubmitAction(null);
    setContinuityBlocked(false);
    setReceiptPersisted(true);
    // 확인 영수증은 검증된 성공에만 속한다 — 새 시도가 시작되면 이전 확인을
    // 복원하지 않는다(실패·불명으로 끝나면 영수증 없이 끝난다).
    // 미반영 지도 상태로는 보내지 않는다 — 다음 버튼이 1단계에서 막으므로
    // 정상 동선에서는 도달하지 않는 방어선이다. 커밋된 form.aoi만 보낸다.
    if (aoiPending.blocked || mapStorage !== "ready" || storageStatus !== "ready" || mapConflict) {
      setSubmitError(
        aoiPending.reason ??
          "지도 입력이 아직 반영되지 않았습니다. 1단계로 돌아가 완료·취소한 뒤 다시 시도하세요.",
      );
      setSubmitPhase("error");
      return;
    }

    clearSuccessReceipt(effectiveIdentity, mode, receiptDraftBinding(form));

    const priorKey = form.bootstrapRequestId ?? null;
    const bootstrapRequestId = form.bootstrapRequestId ?? createRegistrationUuid();
    const resolved = resolveMappedOrigin({ requestKey: bootstrapRequestId, priorKey });
    if ("blocked" in resolved) {
      failOriginBlocked(resolved.blocked);
      return;
    }
    // 상한 도달 시 신규 변이를 보내기 전에 차단한다 — 조용히 버리는 대신 막는다.
    // 같은 (kind, key, origin, digest) 요청의 재시도는 막지 않는다. 내용은
    // 달라도 키·신원이 같으면 같은 화면 흐름의 연속 시도일 수 있으나, 결속이
    // 다른 미확인 기록이므로 상한 계산에는 포함한다.
    const origin = resolved.origin;
    const payloadDigest = digestSitePostPayload({
      name: form.name.trim(),
      aoi: form.aoi,
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      transformVersion: form.transformVersion.trim(),
      egressChoice: form.egressChoice,
      jurisdiction: form.jurisdiction.trim(),
      aiEgressAllowed: form.aiEgressAllowed,
    });
    const alreadyTracked = (form.priorUnknowns ?? []).some(
      (entry) =>
        entry.kind === "mapped" &&
        entry.key === bootstrapRequestId &&
        entry.originFingerprint === origin &&
        entry.payloadDigest === payloadDigest,
    );
    if (!alreadyTracked && (form.priorUnknowns ?? []).length + (form.quarantinedUnknowns ?? []).length >= MAX_PRIOR_UNKNOWNS) {
      failCapacityBlocked("mapped");
      return;
    }
    const pendingForm: FormState = {
      ...form,
      bootstrapRequestId,
      originFingerprint: origin,
      // 전송을 시작한 뒤 응답 전에 화면이 사라져도 이 원본을 잃지 않는다.
      // 실제 전송 직전 중단도 보수적으로 "보냈을 수 있음"으로 남긴다.
      priorUnknowns: upsertPriorUnknown(form.priorUnknowns, {
        kind: "mapped",
        key: bootstrapRequestId,
        originFingerprint: origin,
        payloadDigest,
        name: form.name.trim(),
      }),
    };
    // 키가 바뀌면 이전 키의 in-memory 불명 기록은 이 시도의 확인 재료가 아니다 —
    // draft 목록에는 보존되어 있어 파기되지 않는다.

    // The retry key must reach the existing session draft before the POST can
    // have an unknown outcome; the draft hook also keeps it synchronized later.
    try {
      const serialized = JSON.stringify(pendingForm);
      sessionStorage.setItem(DRAFT_STORAGE_KEY, serialized);
      if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== serialized) throw new Error("draft write not confirmed");
    } catch {
      setSubmitError("등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도하세요.");
      setSubmitPhase("error");
      return;
    }
    // Flush the hook's prepared state before POST. A deferred older effect must
    // not overwrite the verified result after the response.
    flushSync(() => setForm(pendingForm));
    try {
      if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== JSON.stringify(pendingForm)) throw new Error("prepared draft changed");
    } catch {
      setSubmitError("등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도하세요.");
      setSubmitPhase("error");
      return;
    }

    const trimmedName = form.name.trim();
    const siteFrame: SiteFrame = {
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      unit: "meter",
      transformVersion: form.transformVersion.trim(),
    };
    const dataResidency = buildDataResidencyInput(form.egressChoice, form.jurisdiction);
    // 2xx 결속 기대값 — 서버 발급 ID라 siteId는 모양만 보고, 나머지는 보낸 값과
    // 엄격 대조한다(서버는 저장 필드를 정규화하지 않는다).
    const expectation: SitePostEchoExpectation = {
      requestedSiteId: null,
      name: trimmedName,
      siteFrame: { ...siteFrame },
      aoiVertices: form.aoi,
      dataResidency: dataResidency ?? undefined,
      aiEgressAllowed: form.aiEgressAllowed,
    };

    /** 이전 불명이 있으면 확정 실패 문구에 그 사실을 덧붙인다 — 덮지 않는다. */
    function priorUnknownDetail(): string | null {
      const sameKey =
        mappedUnknownRef.current?.requestKey === bootstrapRequestId ||
        (form.priorUnknowns ?? []).some(
          (entry) => entry.kind === "mapped" && entry.key === bootstrapRequestId,
        );
      const others = (form.priorUnknowns ?? []).filter(
        (entry) => !(entry.kind === "mapped" && entry.key === bootstrapRequestId),
      ).length;
      const sameNote = sameKey
        ? "이전 요청의 결과는 여전히 확인하지 못했습니다 — 목록에서 입력한 이름이 " +
          "있는지 먼저 확인하세요. 목록에 없으면 입력은 그대로 둔 채 같은 요청 키로 " +
          "다시 시도할 수 있습니다."
        : null;
      const othersNote = others > 0 ? ` 그 밖에 확인되지 않은 이전 요청이 ${others}건 있습니다.` : "";
      if (sameNote) return sameNote + othersNote;
      if (others > 0) {
        return (
          `확인되지 않은 이전 요청이 ${others}건 있습니다. 서버에 등록됐을 수도 있으니 ` +
          "목록에서 입력한 이름이 있는지 먼저 확인하세요."
        );
      }
      return null;
    }

    /** 불명 기록을 draft 목록에 보존한다 — 키 회전·계정 교체·성공이 파기하지 않는다. */
    function recordUnknown() {
      mappedUnknownRef.current = { requestKey: bootstrapRequestId, payloadDigest };
      setForm({
        ...form,
        bootstrapRequestId: pendingForm.bootstrapRequestId,
        originFingerprint: pendingForm.originFingerprint,
        priorUnknowns: upsertPriorUnknown(form.priorUnknowns, {
          kind: "mapped",
          key: bootstrapRequestId,
          originFingerprint: origin,
          payloadDigest,
          name: trimmedName,
        }),
      });
    }

    function failUnknown() {
      // Core bootstrap 멱등 namespace는 (organizationId, actor, requestKey)다.
      // 응답 유실 뒤 계정이 바뀌면 같은 키·같은 원본이어도 B namespace에서 별도
      // 현장을 만든다 — 그래서 "다시 시도해도 중복 등록이 되지 않는다"는 원래
      // 계정에서 같은 키로 재시도할 때만 참이다.
      recordUnknown();
      setSubmitError(
        "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
          "원래 계정에서, 내용을 바꾸지 않고 같은 요청 키로 다시 시도하면 중복 " +
          "등록이 되지 않습니다. 계정이 바뀌었다면 같은 키로 다시 보내지 마세요 — " +
          "현장 목록에서 입력한 이름이 있는지 먼저 확인하세요.",
      );
      setSubmitPhase("error");
    }

    function failDefinite(message: string) {
      // 이번 시도가 확정 실패여도 같은 결속의 이전 불명은 지우지 않는다.
      if (!alreadyTracked) setForm({ ...pendingForm, priorUnknowns: form.priorUnknowns });
      setSubmitError(message);
      const detail = priorUnknownDetail();
      setSubmitDetail(detail);
      setSubmitPhase("error");
    }

    let res: Response;
    try {
      res = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...continuityHeader(origin) },
        body: JSON.stringify({
          bootstrapRequestId,
          name: trimmedName,
          siteFrame,
          aoi: { vertices: form.aoi },
          dataResidency,
          aiEgressAllowed: form.aiEgressAllowed,
        }),
      });
    } catch {
      // 응답 자체가 없다 — 만들었을지 모른다. 요청 키는 입력에 남아 원래 계정의
      // 다음 재시도가 같은 키를 쓰므로, 이 불명을 확정 실패로 말하지 않는다.
      failUnknown();
      return;
    }

    if (!res.ok) {
      const body = await parseJsonSafe(res);
      if (res.status === 404) {
        failDefinite(
          "현장이 현재 부여된 접근 범위 밖에 있을 수 있습니다. KSI에 접근 권한 범위를 다시 발급해 달라고 요청하세요.",
        );
        return;
      }
      if (res.status === 409) {
        if (body.code === "ACCOUNT_CONTINUITY_MISMATCH") {
          // 다른 계정 차단 — BFF가 Core POST 없이 끊은 상태다. 입력·요청 키는
          // 그대로 두고, 원래 계정 복귀 또는 명시적 현재-계정 재시작만 받는다.
          setContinuityBlocked(true);
          failDefinite(
            "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. " +
              "입력은 그대로 있습니다. 원래 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하거나, " +
              "현장 목록에서 입력한 이름이 있는지 먼저 확인하세요.",
          );
          setSubmitAction({ label: "현장 목록에서 직접 확인하기", href: "/sites" });
          return;
        }
        failDefinite(
          body.code === "BOOTSTRAP_REQUEST_CONFLICT"
            ? "같은 등록 요청 키가 다른 내용으로 사용되어 현장을 등록하지 못했습니다. 내용을 확인한 뒤 다시 시도하세요."
            : body.code === "SITE_BOOTSTRAP_LIMIT_REACHED"
              ? "조직의 현장 등록 한도에 도달해 현장을 등록하지 못했습니다. 관리자에게 문의하세요."
              : "현장 등록 요청이 충돌했습니다. 내용을 확인한 뒤 다시 시도하세요.",
        );
        return;
      }
      if (res.status === 400 || res.status === 401 || res.status === 403 || res.status === 422) {
        // 확정 실패(검증·인증·인가) — 이 요청은 만들지 않았다. 다만 같은 키의
        // 이전 불명이 있으면 그 기록을 살려 함께 안내한다.
        failDefinite(body.message ?? "요청을 처리하지 못했습니다.");
        return;
      }
      // 그 밖(408·429·5xx 전체·알 수 없는 4xx)은 불명이다. 코드가 있다는 이유만으로
      // "쓰기 안 됨"을 단정하지 않는다.
      failUnknown();
      return;
    }

    let successBody: unknown = null;
    try {
      successBody = await res.json();
    } catch {
      successBody = null;
    }
    const responseSite =
      successBody !== null && typeof successBody === "object" && "site" in successBody
        ? (successBody as { site?: unknown }).site
        : undefined;
    // 2xx라도 보낸 원본과 결속되지 않으면 성공으로 올리지 않는다 — 이름·좌표계·
    // 범위·반출 선언이 하나라도 다르면(또는 본문이 깨졌으면) 무엇을 만들었는지 모른다.
    const verified = verifySitePostEcho(responseSite, expectation);
    if (!verified.ok) {
      failUnknown();
      return;
    }
    // 응답 역전 가드 — A가 보낸 요청의 응답이 B 확인 뒤에 도착하면 성공 화면을
    // 내지 않는다. BFF는 보낸 신원으로 검증했지만, 지금 이 화면을 보는 주체가
    // 바뀌었을 수 있다. 불명으로 기록하고 목록 확인으로 안내한다.
    if (effectiveRef.current === null || effectiveRef.current !== origin) {
      recordUnknown();
      setSubmitError(
        "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
          "화면의 계정 정보가 바뀌었을 수 있어 성공 화면을 표시하지 않았습니다. " +
          "현장 목록에서 입력한 이름이 있는지 먼저 확인하세요.",
      );
      setSubmitPhase("error");
      return;
    }

    const completed: FormState = {
      ...pendingForm,
      priorUnknowns: removePriorUnknown(pendingForm.priorUnknowns, "mapped", bootstrapRequestId, origin, payloadDigest),
    };
    const saved = persistVerifiedSuccess(pendingForm, completed, {
      mode, siteId: verified.siteId, name: trimmedName, fingerprint: origin,
      draftBinding: receiptDraftBinding(completed),
    });
    const mapCleared = saved && clearMapAfterSuccess();
    setReceiptPersisted(saved && mapCleared);
    setSuccessStorageBlocked(!saved || !mapCleared);
    if (saved) setForm(completed);
    setSuccessOrigin(origin);
    setRegisteredSiteId(verified.siteId);
    setRegisteredSiteName(trimmedName);
    setSubmitPhase("success");
    setCurrentStep(2);
    // 성공 뒤 자동 새로고침을 하지 않는다 — 셸(사이드바 현장 배지)은 다음 화면
    // 이동 때 서버 렌더로 반영되며, 그 사이 완성 화면이 unmount될 일이 없다.
    // 목록·건수가 바로 안 보여도 위 현장 ID로의 등록은 끝난 상태임을 고지한다.
  }

  async function runSubmission() {
    if (submissionLockRef.current) return;
    submissionLockRef.current = true;
    try {
      await performSubmission();
    } finally {
      submissionLockRef.current = false;
    }
  }

  async function performSubmission() {
    if (mode === "MAPPED_BOOTSTRAP") {
      await runMappedSubmission();
      return;
    }

    setSubmitPhase("pending");
    setSubmitError(null);
    setSubmitDetail(null);
    setSubmitAction(null);
    setContinuityBlocked(false);
    setReceiptPersisted(true);
    // 확인 영수증은 검증된 성공에만 속한다 — 새 시도가 시작되면 이전 확인을 복원하지 않는다.
    // 미반영 지도 상태로는 보내지 않는다 — 1단계 다음 버튼이 먼저 막으므로
    // 정상 동선에서는 도달하지 않는 방어선이다. 커밋된 form.aoi만 보낸다.
    if (aoiPending.blocked || mapStorage !== "ready" || storageStatus !== "ready" || mapConflict) {
      setSubmitError(
        aoiPending.reason ??
          "지도 입력이 아직 반영되지 않았습니다. 1단계로 돌아가 완료·취소한 뒤 다시 시도하세요.",
      );
      setSubmitPhase("error");
      return;
    }

    clearSuccessReceipt(effectiveIdentity, mode, receiptDraftBinding(form));

    const siteId = form.siteId.trim();
    const siteFrame: SiteFrame = {
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      unit: "meter",
      transformVersion: form.transformVersion.trim(),
    };
    // 원래 요청의 지문 — 확인 안내에서 "같은 요청"인지를 밝히는 재료다.
    // 이름·AOI·좌표계·반출 선언이 하나라도 바뀌면 다른 요청이다.
    // 계정은 여기에 담지 못한다(세션 토큰은 httpOnly라 클라이언트에서 읽을 수 없고
    // Core 응답에 귀속이 없다) — 그래서 409를 자동 성공으로 승격하지 않는다.
    // 계정 결속은 BFF 연속성 헤더(원래 신원 지문)가 맡는다.
    const payloadInput: SitePostPayloadInput = {
      name: form.name.trim(),
      aoi: form.aoi,
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      transformVersion: form.transformVersion.trim(),
      egressChoice: form.egressChoice,
      jurisdiction: form.jurisdiction.trim(),
      aiEgressAllowed: form.aiEgressAllowed,
    };
    const payloadDigest = digestSitePostPayload(payloadInput);
    // 원래 신원 확정 — 저장된 원래 지문·같은 siteId의 기록된 지문을 우선한다.
    // 주체 미상 구 초안은 어떤 계정으로도 POST하지 않는다(원본 payload가 있어
    // 제출 자체가 귀속 추측이 된다). 게이트가 UI를 먼저 막지만 여기서도
    // 한 번 더 막는다(방어 심층).
    if (form.originUnknown === true) {
      failOriginBlocked("old-attempt");
      return;
    }
    // legacy siteId는 전역 유일이라 확인된 신원 채택이 별도 현장을 만들지 않는다
    // (DUPLICATE→수동 확인 또는 결속 검증된 201뿐). prop마저 없으면 POST하지 않는다.
    // 같은 키에 서로 다른 원래 신원의 기록이 있으면 현재 확인된 신원과
    // 일치하는 것을 쓴다.
    const legacyCandidates = (form.priorUnknowns ?? []).filter(
      (entry) =>
        entry.kind === "legacy" && entry.key === siteId && entry.originFingerprint,
    );
    const recordedLegacy =
      legacyCandidates.find((entry) => entry.originFingerprint === effectiveIdentity) ??
      legacyCandidates[0];
    const origin =
      form.originFingerprint ?? recordedLegacy?.originFingerprint ?? effectiveIdentity ?? undefined;
    if (origin === undefined) {
      failOriginBlocked("no-identity");
      return;
    }
    // 상한 도달 시 신규 변이를 보내기 전에 차단한다 — 조용히 버리는 대신 막는다.
    // (kind, key, origin)까지 일치하는 추적만 재시도로 인정한다.
    const alreadyTrackedLegacy = (form.priorUnknowns ?? []).some(
      (entry) =>
        entry.kind === "legacy" &&
        entry.key === siteId &&
        entry.originFingerprint === origin &&
        entry.payloadDigest === payloadDigest,
    );
    if (!alreadyTrackedLegacy && (form.priorUnknowns ?? []).length + (form.quarantinedUnknowns ?? []).length >= MAX_PRIOR_UNKNOWNS) {
      failCapacityBlocked("legacy");
      return;
    }
    const pendingForm: FormState = {
      ...form,
      originFingerprint: origin,
      priorUnknowns: upsertPriorUnknown(form.priorUnknowns, {
        kind: "legacy",
        key: siteId,
        originFingerprint: origin,
        payloadDigest,
        name: payloadInput.name,
      }),
    };
    try {
      const serialized = JSON.stringify(pendingForm);
      sessionStorage.setItem(DRAFT_STORAGE_KEY, serialized);
      if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== serialized) throw new Error("draft write not confirmed");
    } catch {
      setSubmitError("등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도하세요.");
      setSubmitPhase("error");
      return;
    }
    // Flush the hook's prepared state before POST. A deferred older effect must
    // not overwrite the verified result after the response.
    flushSync(() => setForm(pendingForm));
    try {
      if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== JSON.stringify(pendingForm)) throw new Error("prepared draft changed");
    } catch {
      setSubmitError("등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도하세요.");
      setSubmitPhase("error");
      return;
    }

    /** 확정 실패는 이번 준비 기록만 풀고 같은 결속의 이전 불명은 남긴다. */
    function clearPreparedIfNew() {
      if (!alreadyTrackedLegacy) setForm({ ...pendingForm, priorUnknowns: form.priorUnknowns });
    }

    /** 불명 기록을 draft 목록에 보존한다 — 파기하지 않는다. */
    function recordLegacyUnknown() {
      postAttemptRef.current = buildSitePostAttempt(siteId, payloadInput, false);
      setForm({
        ...form,
        originFingerprint: origin,
        priorUnknowns: upsertPriorUnknown(form.priorUnknowns, {
          kind: "legacy",
          key: siteId,
          originFingerprint: origin,
          payloadDigest,
          name: payloadInput.name,
        }),
      });
    }

    function fail(message: string, detail: string | null = null, action: { label: string; href: string } | null = null) {
      setSubmitError(message);
      setSubmitDetail(detail);
      setSubmitAction(action);
      setSubmitPhase("error");
    }

    try {
      // POST를 **보내기 전에** 시도로 기록한다 — 네트워크 예외로 응답을 못 받아도
      // 서버는 등록했을 수 있다. 다만 그 "모른다"를 소유권 근거로 쓰지 않는다:
      // 다음 409가 타인의 ID를 가렸을 수도 있어 DUPLICATE 하나만으로는 확정할 수 없고,
      // 계정 일치도 확인할 수 없으므로 관측 성공 뒤의 409도 수동 확인으로만 푼다.
      const previousAttempt = postAttemptRef.current;
      postAttemptRef.current = buildSitePostAttempt(siteId, payloadInput, false);
      const dataResidency = buildDataResidencyInput(form.egressChoice, form.jurisdiction);
      const res = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...continuityHeader(origin) },
        // dataResidency 를 답하지 않았으면(unset) buildDataResidencyInput 이
        // undefined 를 돌려주고, JSON.stringify 가 undefined 값 키를 생략한다 —
        // 그래야 서버가 미선언을 fail-closed(반출 불가)로 해석한다(INV-050).
        body: JSON.stringify({
          siteId,
          name: form.name.trim(),
          siteFrame,
          aoi: { vertices: form.aoi },
          dataResidency,
          aiEgressAllowed: form.aiEgressAllowed,
        }),
      });
      if (res.ok) {
        // 2xx라도 보낸 원본과 결속되어야 성공이다. siteId만 같고 이름·좌표계·범위·
        // 반출 선언이 다르면(또는 본문이 깨졌으면) 서버가 무엇을 만들었는지 알 수
        // 없으므로 불명으로 둔다 — Core는 저장 필드를 정규화하지 않으므로 엄격 일치다.
        let responseSite: unknown;
        try {
          const successBody: unknown = await res.json();
          responseSite =
            successBody !== null && typeof successBody === "object" && "site" in successBody
              ? (successBody as { site?: unknown }).site
              : undefined;
        } catch {
          responseSite = undefined;
        }
        const expectation: SitePostEchoExpectation = {
          requestedSiteId: siteId,
          name: payloadInput.name,
          siteFrame: {
            crs: payloadInput.crs,
            verticalDatum: payloadInput.verticalDatum,
            unit: "meter",
            transformVersion: payloadInput.transformVersion,
          },
          aoiVertices: payloadInput.aoi,
          dataResidency: dataResidency ?? undefined,
          aiEgressAllowed: payloadInput.aiEgressAllowed,
        };
        const verified = verifySitePostEcho(responseSite, expectation);
        if (!verified.ok) {
          // 2xx인데 본문이 틀리다 — 만들었을지 모르므로 성공으로 올리지 않는다.
          // 목록에 없다는 이유만으로 미등록을 확정하지도 않는다.
          recordLegacyUnknown();
          fail(
            "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
              "같은 현장 ID로 바로 다시 보내지 마세요 — 현장 목록에서 입력한 ID가 있는지 먼저 확인하세요. " +
              "목록에 없으면 입력은 그대로 둔 채 다시 시도할 수 있습니다.",
          );
          return;
        }
        postAttemptRef.current = buildSitePostAttempt(siteId, payloadInput, true);
        // 응답 역전 가드 — mapped와 동일: 도착 시점 확인값이 보낸 신원과 다르면
        // 성공 화면을 내지 않고 불명으로 기록한다.
        if (effectiveRef.current === null || effectiveRef.current !== origin) {
          recordLegacyUnknown();
          fail(
            "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
              "화면의 계정 정보가 바뀌었을 수 있어 성공 화면을 표시하지 않았습니다. " +
              "현장 목록에서 입력한 ID가 있는지 먼저 확인하세요.",
          );
          return;
        }
        const completed: FormState = {
          ...pendingForm,
          priorUnknowns: removePriorUnknown(pendingForm.priorUnknowns, "legacy", siteId, origin, payloadDigest),
        };
        const saved = persistVerifiedSuccess(pendingForm, completed, {
          mode, siteId: verified.siteId, name: payloadInput.name, fingerprint: origin,
          draftBinding: receiptDraftBinding(completed),
        });
        const mapCleared = saved && clearMapAfterSuccess();
        setReceiptPersisted(saved && mapCleared);
        setSuccessStorageBlocked(!saved || !mapCleared);
        if (saved) setForm(completed);
        setSuccessOrigin(origin);
    setRegisteredSiteId(verified.siteId);
        setRegisteredSiteName(payloadInput.name);
        setSubmitPhase("success");
        setCurrentStep(2);
        // 성공 뒤 자동 새로고침을 하지 않는다 — 셸은 다음 화면 이동 때 반영되며,
        // 그 사이 완성 화면이 unmount될 일이 없다.
        return;
      }
      const body = await parseJsonSafe(res);
      if (res.status === 409 && body.code === "ACCOUNT_CONTINUITY_MISMATCH") {
        // 다른 계정 차단 — BFF가 Core POST 없이 끊은 상태다. legacy는 siteId가
        // 전역 유일이라 별도 현장이 생기지 않지만, 같은 이유로 재시도하지 않는다.
        postAttemptRef.current = previousAttempt;
        clearPreparedIfNew();
        setContinuityBlocked(true);
        fail(
          "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. " +
            "입력은 그대로 있습니다. 원래 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하거나, " +
            "현장 목록에서 입력한 ID가 있는지 먼저 확인하세요.",
          null,
          { label: "현장 목록에서 직접 확인하기", href: "/sites" },
        );
        return;
      }
      const outcome = classifyLegacySitePost({
        fetchThrew: false,
        status: res.status,
        bodyCode: body.code ?? null,
        responseSiteId: null,
        requestedSiteId: siteId,
        previous: previousAttempt,
        payloadDigest,
      });
      if (outcome.kind === "unknown") {
        recordLegacyUnknown();
        fail(
          "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
            "같은 현장 ID로 바로 다시 보내지 마세요 — 현장 목록에서 입력한 ID가 있는지 먼저 확인하세요. " +
            "목록에 없으면 입력은 그대로 둔 채 다시 시도할 수 있습니다.",
        );
        return;
      }
      if (outcome.kind === "duplicateUnverified") {
        // 409는 이 ID가 이미 있다는 뜻이지만 누구 것인지는 모른다. 첫 충돌이든
        // 관측 성공 뒤든, 계정 일치가 확인되지 않으므로 자동 성공·자동 이동하지
        // 않고 현장 목록·상세에서 직접 확인하게 한다.
        postAttemptRef.current = outcome.sameSiteAsPrevious
          ? (previousAttempt ?? buildSitePostAttempt(siteId, payloadInput, false))
          : null;
        clearPreparedIfNew();
        fail(
          "이미 등록된 현장 ID입니다. 이 ID가 방금 이 화면에서 등록한 것인지 알 수 없어 자동으로 들어가지 않았습니다.",
          "현장 목록·상세에서 ID·이름·좌표계가 입력과 같은지 직접 확인하세요. " +
            "다른 현장일 수 있습니다." +
            (outcome.payloadChanged ? " 그 사이 입력이 바뀌어, 바뀐 내용은 저장되지 않았습니다." : "") +
            (outcome.sameSiteAsPrevious
              ? " 이전 요청의 결과가 확인되지 않은 채 충돌했으므로, 목록에 없더라도 등록되지 않았다는 증명이 아닙니다."
              : ""),
          { label: "현장 목록에서 직접 확인하기", href: "/sites" },
        );
        return;
      }
      // 확정 실패(검증·권한·형식) — 이 요청은 만들지 않았다. 다만 같은 siteId의
      // 이전 시도가 미확인이면 그 기록은 살린다. 다음 409가 그 시도에서 왔을 수
      // 있어 확인 필요가 유지된다. remount로 in-memory 기록이 없어도 draft 목록의
      // 불명은 살린다(파기하지 않는다).
      postAttemptRef.current =
        previousAttempt?.siteId === siteId ? previousAttempt : null;
      clearPreparedIfNew();
      const draftUnknownSameSite = (form.priorUnknowns ?? []).some(
        (entry) => entry.kind === "legacy" && entry.key === siteId,
      );
      if (previousAttempt?.siteId === siteId || draftUnknownSameSite) {
        fail(
          body.message ?? "요청을 처리하지 못했습니다.",
          "이전 요청의 결과는 여전히 확인하지 못했습니다 — 목록에서 입력한 ID가 있는지 먼저 확인하세요.",
        );
        return;
      }
      fail(body.message ?? "요청을 처리하지 못했습니다.");
      return;
    } catch {
      // 응답 자체가 없다 — 만들었을지 모른다. 성공도 확정 실패도 아니다.
      // 입력·시도 기록은 그대로 두어 다음 409를 확인 필요로 안내한다.
      recordLegacyUnknown();
      fail(
        "등록 결과를 확인하지 못했습니다. 서버에 등록됐을 수도 있습니다. " +
          "같은 현장 ID로 바로 다시 보내지 마세요 — 현장 목록에서 입력한 ID가 있는지 먼저 확인하세요. " +
          "목록에 없으면 입력은 그대로 둔 채 다시 시도할 수 있습니다.",
      );
    }
  }

  // 성공해도 입력 초안과 확인 영수증은 남긴다 — 권한·조회 실패로 완성 화면이
  // unmount됐다가 같은 탭에서 다시 마운트되면 복원해야 한다. 정리는 브리핑으로
  // 떠날 때(handleNext 성공 이동) 한 번에 한다.
  const trimmedSiteId = form.siteId.trim();
  // 완성 화면·브리핑 이동의 기준 — 영수증 복원 뒤에도 초안 입력 없이 식별된다.
  const confirmedSiteId =
    registeredSiteId ?? (mode === "LEGACY_SITE_ID" ? trimmedSiteId : null);
  const confirmedSiteName = registeredSiteName ?? form.name.trim();
  // 확인되지 않은 이전 요청은 파기하지 않고 함께 안내한다. 상세(이름 등)는 각
  // 항목의 원래 신원과 현재 확인된 신원이 일치할 때만 보인다 — 둘 다 유효한
  // 지문이어야 하며, 한쪽이라도 없으면 비공개다.
  const remainingUnknowns = form.priorUnknowns ?? [];
  const quarantinedCount = form.quarantinedUnknowns?.length ?? 0;
  const hasUnknownRecords = remainingUnknowns.length > 0 || quarantinedCount > 0;
  /** 항목 상세를 보여도 되는가 — 원래 지문과 현재 지문을 각각 대조한다. */
  function unknownEntryDetailsAllowed(entry: PriorUnknownRequest): boolean {
    if (!entry.originFingerprint) return false;
    if (effectiveIdentity === null) return false;
    return entry.originFingerprint === effectiveIdentity;
  }

  /**
   * 계정 불일치 게이트 — 저장된 입력의 원래 신원이 있고, 현재 신원이 확인되지
   * 않거나 다르면 입력 표시·전송을 막는다. 원본은 파기하지 않는다.
   * "현재 계정"이라는 확정 표현은 쓰지 않는다 — prop·live 모두 스냅샷이라
   * 신선도가 확인되지 않으며, BFF 변이 가드가 최종 가드로 남는다.
   * 제출·복원은 지문 일치 때만 일어난다.
   */
  const storedOrigin = form.originFingerprint ?? (submitPhase === "success" ? successOrigin : null);
  // 주체 미상 구 초안은 어떤 계정에서도 표시·전송하지 않는다 — 빈 신규 초안과
  // 달리 원래 payload가 있어 추측 귀속하면 안 된다. B인지는 묻지 않는다.
  const hasUnverifiedLegacyDraft = form.originUnknown === true;
  const accountMismatch =
    hasUnverifiedLegacyDraft ||
    (storedOrigin !== null && (effectiveIdentity === null || storedOrigin !== effectiveIdentity));

  const mapConflict = !!mapRecord && (!supportedDraftShape(form) || mapReceiptConflict || mapRecord.mode !== mode || mapRecord.origin !== form.originFingerprint || mapRecord.draftId !== form.mapDraftId);
  function saveMapSnapshot(snapshot: AoiRawSnapshot) {
    // Do not replace a restored source with a mount-time emission.
    if (!mapMountedRef.current && mapRecord && JSON.stringify(snapshot) !== JSON.stringify(mapRecord.snapshot)) {
      mapFailedRef.current = true;
      setMapStorage("failed");
      return;
    }
    if (mapFailedRef.current || mapStorage !== "ready" || !effectiveRef.current || effectiveRef.current !== form.originFingerprint || !form.mapDraftId || mapConflict) {
      mapFailedRef.current = true;
      setMapStorage("failed");
      return;
    }
    const record: MapRecord = { version: 1, mode, origin: form.originFingerprint, draftId: form.mapDraftId, snapshot };
    try {
      const receiptExists = sessionStorage.getItem(SUCCESS_RECEIPT_KEY) !== null;
      const raw = writeMapRecord(record, mapRawRef.current);
      mapRawRef.current = raw;
      setMapRecord(record);
      if (receiptExists) setMapReceiptConflict(true);
    } catch {
      mapFailedRef.current = true;
      setMapStorage("failed");
    }
  }

  function clearMapAfterSuccess(): boolean {
    if (!mapRawRef.current) return true;
    try {
      if (sessionStorage.getItem(MAP_BACKUP_KEY) !== null || sessionStorage.getItem(MAP_STORAGE_KEY) !== mapRawRef.current) return false;
      const record = parseMapRecord(mapRawRef.current);
      if (record.origin !== form.originFingerprint || record.draftId !== form.mapDraftId || record.mode !== mode) return false;
      sessionStorage.removeItem(MAP_STORAGE_KEY);
      if (sessionStorage.getItem(MAP_STORAGE_KEY) !== null) return false;
      mapRawRef.current = null;
      setMapRecord(null);
      return true;
    } catch { return false; }
  }

  function persistVerifiedSuccess(pending: FormState, completed: FormState, receipt: RegistrationSuccessReceipt): boolean {
    try {
      const expected = JSON.stringify(pending);
      const original = sessionStorage.getItem(DRAFT_STORAGE_KEY);
      if (original !== expected || sessionStorage.getItem(SUCCESS_DRAFT_BACKUP_KEY) !== null) return false;
      // Keep the exact prepared request until both completed draft and receipt
      // are confirmed. A conflict must never be overwritten.
      sessionStorage.setItem(SUCCESS_DRAFT_BACKUP_KEY, original);
      if (sessionStorage.getItem(SUCCESS_DRAFT_BACKUP_KEY) !== original) return false;
      const next = JSON.stringify(completed);
      sessionStorage.setItem(DRAFT_STORAGE_KEY, next);
      if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== next) return false;
      if (!writeSuccessReceipt(receipt)) return false;
      sessionStorage.removeItem(SUCCESS_DRAFT_BACKUP_KEY);
      if (sessionStorage.getItem(SUCCESS_DRAFT_BACKUP_KEY) !== null) return false;
      return true;
    } catch { return false; }
  }

  // 불일치 화면의 새로 시작 버튼은 없앴다 — 타 계정·미확인 주체에게 원본
  // 입력을 지우게 할 수 없으므로, 복귀 안내와 목록 확인·새 탭만 둔다.
  // (미확인 기록의 지우기는 원래 신원이 확인된 항목에만 허용한다.)

  /** 확인되지 않은 이전 요청 목록 — 명시적 지우기에는 손실 고지가 따른다. */
  function renderUnknownRecordsList(entries: PriorUnknownRequest[]) {
    const quarantinedCount = form.quarantinedUnknowns?.length ?? 0;
    if (entries.length === 0 && quarantinedCount === 0) return null;
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-sunk p-4 text-sm sm:col-span-2">
        {entries.length > 0 && (
          <>
            <p className="font-semibold break-keep">
              확인되지 않은 이전 요청이 {entries.length}건 있습니다
            </p>
            <p className="text-[12px] break-keep text-ink-2">
              현장 목록에서 이름이 있는지 먼저 확인하세요. 기록을 지워도 서버의 등록
              상태는 바뀌지 않습니다. 실제로 등록됐던 요청의 기록을 지우면, 같은
              내용으로 다시 등록할 때 충돌 안내만 보고 헷갈릴 수 있습니다.
            </p>
          </>
        )}
        {quarantinedCount > 0 && (
          <p className="text-[12px] break-keep text-ink-2">
            {`읽을 수 없는 이전 기록이 ${quarantinedCount}건 보존되어 있습니다(형식이 달라 복원할 수 없음). 삭제하지 않으며, 어느 계정의 것으로도 표시·귀속하지 않습니다.`}
          </p>
        )}
        <ul className="flex flex-col gap-1.5">
          {entries.map((entry) => {
            const showDetails = unknownEntryDetailsAllowed(entry);
            // key에 원래 신원을 포함한다 — 같은 키의 A/B 항목이 React key로
            // 충돌하면 한쪽이 렌더링에서 사라져(또는 뒤바뀌어) 귀속을 헷갈리게 한다.
            return (
              <li
                key={JSON.stringify([entry.kind, entry.key, entry.originFingerprint, entry.payloadDigest])}
                className="flex flex-wrap items-center gap-2 text-[12.5px] break-keep"
              >
                <span className="font-medium">
                  {showDetails
                    ? entry.name || "(이름 없음)"
                    : "이름 비공개 — 원래 계정에서 확인하세요"}
                </span>
                {/* 지우기는 원래 신원이 확인된 항목에만 — 확인할 수 없는 기록을
                    타 계정에서 임의로 지우지 않는다. 미확인 항목에는 버튼을
                    내지 않는다(안전 잠금). */}
                {showDetails && entry.originFingerprint && !successStorageBlocked && (
                  <button
                    type="button"
                    onClick={() => dismissPriorUnknown(entry)}
                    className="tap-target rounded-md border border-line-strong bg-surface px-2 py-1 text-[12px]"
                  >
                    기록 지우기
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  function dismissPriorUnknown(entry: PriorUnknownRequest) {
    setInteracted(true);
    // 원본 지문이 없으면 지우지 않는다 — 미확인 기록은 잠금을 유지한다.
    // 호출부의 showDetails로 원래 신원이 확인된 항목만 넘어오며, 여기서
    // digest까지 대조해 같은 키의 다른 내용까지 지우지 않는다.
    if (!entry.originFingerprint || successStorageBlocked) return;
    setForm({
      ...form,
      priorUnknowns: removePriorUnknown(
        form.priorUnknowns,
        entry.kind,
        entry.key,
        entry.originFingerprint,
        entry.payloadDigest,
      ),
    });
  }

  /** 상한 도달로 신규 변이를 보내기 전에 차단한다 — 조용히 버리는 대신 막는다. */
  function failCapacityBlocked(kind: "mapped" | "legacy") {
    setSubmitError(
      `확인되지 않은 이전 요청이 ${MAX_PRIOR_UNKNOWNS}건 이상 있습니다. 새로 보내기 전에 현장 목록에서 ` +
        "먼저 확인하세요. 확인한 항목은 아래 목록에서 기록을 지울 수 있습니다. 형식이 손상된 기록은 지울 수 없습니다.",
    );
    setSubmitDetail(
      kind === "mapped"
        ? "목록에 없으면 입력은 그대로 둔 채 같은 요청 키로 다시 시도할 수 있습니다."
        : "목록에 없으면 입력은 그대로 둔 채 다시 시도할 수 있습니다.",
    );
    setSubmitPhase("error");
  }
  const jurisdictionRequired = form.egressChoice !== "unset";
  // MAP-AOI PENDING HOOK (연동됨: AoiPolygonMap.onPendingChange):
  // 지도 컴포넌트가 알리는 미반영·편집 중·삭제 중·잘못된 키보드 입력을
  // stepValid[1]과 제출 직전에서 모두 막는다. 커밋된 form.aoi와 다른 화면상
  // 임시값으로는 다음 단계에도, POST 본문에도 절대 나가지 않는다.
  // pending 자체는 transient라 초안·영수증에 남지 않는다.
  const stepValid: Record<number, boolean> = {
    0:
      (mode === "MAPPED_BOOTSTRAP" ||
        (trimmedSiteId.length > 0 && SITE_ID_PATTERN.test(trimmedSiteId))) &&
      form.name.trim().length > 0 &&
      (!jurisdictionRequired || form.jurisdiction.trim().length > 0),
    1:
      form.aoi.length >= 3 &&
      isConvexPolygon(form.aoi) &&
      form.crs.trim().length > 0 &&
      form.verticalDatum.trim().length > 0 &&
      form.transformVersion.trim().length > 0 &&
      !aoiPending.blocked && mapStorage === "ready" && storageStatus === "ready" && !mapConflict,
    2: submitPhase !== "pending",
  };

  function handleBack() {
    if (successStorageBlocked) return;
    setInteracted(true);
    // 미반영 지도 상태에서는 뒤로 가지 않는다 — 1단계 지도를 unmount하면
    // 완료·취소되지 않은 편집·입력(row)이 조용히 버려진다. 다음 버튼과 같은
    // 이유가 푸터에 이미 보이므로, 사용자는 지도에서 먼저 완료·취소한 뒤
    // 이동한다(머무르거나 명시적으로 폐기).
    if (currentStep === 1 && aoiPending.blocked) return;
    if (currentStep === 1) mapMountedRef.current = false;
    setCurrentStep((step) => {
      if (step === 1 || step === 2) {
        setSubmitPhase("idle");
        setSubmitError(null);
        setSubmitDetail(null);
        setSubmitAction(null);
        setContinuityBlocked(false);
      }
      return step - 1;
    });
    // 확인 화면을 떠나 다시 입력으로 돌아가면 이전 확인은 더 이상 현재 상태가 아니다.
    if (currentStep === 2 && submitPhase === "success") {
      clearSuccessReceipt(effectiveIdentity, mode, receiptDraftBinding(form));
      setRegisteredSiteId(null);
      setRegisteredSiteName(null);
    }
  }

  // adopt 버튼은 없앴다 — 오래된 prop을 "현재 계정"이라 확정해 부르거나 원래
  // 요청을 덮는 대신, BFF 차단 뒤에는 원래 계정 복귀(하단 다시 시도)·새로고침·
  // 목록 확인만 받는다. 화면 계정과 초안 계정이 엇갈리면 아래 게이트가 막는다.

  function handleNext() {
    setInteracted(true);
    if (currentStep === 2) {
      if (submitPhase === "success") {
        if (successStorageBlocked) return;
        // 확인된 등록으로 브리핑에 들어간다. 입력·영수증은 정리하되 확인되지
        // 않은 다른 키의 이전 요청 기록은 남긴다 — 성공 후 이동·remount 뒤에도
        // 미해결 항목이 유지되어야 한다. 삭제는 명시적 선택(기록 지우기)으로만.
        // 정리 저장이 실패하면 이동하지 않는다 — 미해결 기록을 잃은 채 떠나지
        // 않기 위해서다(무변이·경고).
        const siteId = registeredSiteId ?? trimmedSiteId;
        if (siteId) {
          const resetForm = { ...INITIAL_FORM, priorUnknowns: form.priorUnknowns, quarantinedUnknowns: form.quarantinedUnknowns };
          try {
            sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(resetForm));
          } catch {
            setSubmitError(
              "이동 전 정리를 브라우저에 저장하지 못했습니다. 미해결 기록을 잃을 수 있어 이동하지 않습니다. 저장 공간을 확인한 뒤 다시 시도하세요.",
            );
            setSubmitPhase("error");
            return;
          }
          clearSuccessReceipt(effectiveIdentity, mode, receiptDraftBinding(form));
          setForm(resetForm);
          void refreshShellSites(siteId);
          router.push(`/sites/${encodeURIComponent(siteId)}`);
        }
      } else {
        void runSubmission();
      }
      return;
    }
    if (currentStep === 0 && !form.mapDraftId) {
      if (storageStatus !== "ready" || mapStorage !== "ready" || mapRecord || !supportedDraftShape(form) || !effectiveIdentity || form.originUnknown || form.originFingerprint !== effectiveIdentity) return;
      const bound = { ...form, mapDraftId: createRegistrationUuid() };
      try {
        // Bind the snapshot to this particular draft before the map can emit.
        const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY);
        if (raw === null || JSON.stringify(migrateRegistrationDraft(JSON.parse(raw))) !== JSON.stringify(migrateRegistrationDraft(form))) throw new Error("draft changed before map binding");
        if (sessionStorage.getItem(DRAFT_BINDING_BACKUP_KEY) !== null) throw new Error("unresolved draft backup");
        sessionStorage.setItem(DRAFT_BINDING_BACKUP_KEY, raw);
        if (sessionStorage.getItem(DRAFT_BINDING_BACKUP_KEY) !== raw) throw new Error("draft backup not confirmed");
        const serialized = JSON.stringify(bound);
        sessionStorage.setItem(DRAFT_STORAGE_KEY, serialized);
        if (sessionStorage.getItem(DRAFT_STORAGE_KEY) !== serialized) throw new Error("draft write not confirmed");
        sessionStorage.removeItem(DRAFT_BINDING_BACKUP_KEY);
        if (sessionStorage.getItem(DRAFT_BINDING_BACKUP_KEY) !== null) throw new Error("draft backup cleanup not confirmed");
      } catch {
        mapFailedRef.current = true;
        setMapStorage("failed");
        return;
      }
      setForm(bound);
    }
    if (currentStep === 1) mapMountedRef.current = false;
    setCurrentStep((step) => step + 1);
  }

  const canGoBack = currentStep > 0 && !(currentStep === 2 && submitPhase === "pending");
  // 탭 닫기·새로고침 때 미반영 입력을 조용히 버리지 않는다 — 브라우저가 표준
  // 확인을 띄운다. 앱 내 이동(이전·다음·나가기)은 위에서 직접 막거나 허용한다.
  useEffect(() => {
    if (!aoiPending.blocked && mapStorage !== "failed" && storageStatus !== "write-failed" && !mapConflict && !successStorageBlocked) return undefined;
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [aoiPending.blocked, mapStorage, storageStatus, mapConflict, successStorageBlocked]);

  let nextLabel = "다음";
  if (currentStep === 2) {
    nextLabel =
      submitPhase === "success"
        ? "현장 브리핑으로 이동"
        : submitPhase === "error"
          ? "다시 시도"
          : "현장 등록";
  }

  const siteIdError =
    trimmedSiteId.length > 0 && !SITE_ID_PATTERN.test(trimmedSiteId)
      ? "영숫자로 시작하고 이후 영숫자·-·_·. 만 쓸 수 있습니다(공백·/ 금지)."
      : undefined;

  // 값이 비어 다음 버튼이 막혔을 때 그 이유를 말한다(F16) — 필드별 실시간 에러는
  // 여전히 값이 있고 형식이 틀렸을 때만 보인다(위 siteIdError 주석과 같은 원칙).
  const step0DisabledReason = stepValid[0]
    ? undefined
    : mode === "LEGACY_SITE_ID"
      ? !trimmedSiteId
        ? "현장 ID를 입력하세요."
        : siteIdError
          ? siteIdError
          : !form.name.trim()
            ? "현장 이름을 입력하세요."
            : jurisdictionRequired && !form.jurisdiction.trim()
              ? "관할을 입력하세요(예: KR)."
              : undefined
      : !form.name.trim()
        ? "현장 이름을 입력하세요."
        : jurisdictionRequired && !form.jurisdiction.trim()
          ? "관할을 입력하세요(예: KR)."
          : undefined;

  // 2단계도 같은 원칙이다(F16) — 2026-10-20 베타 참가자 드라이브에서, 경계만
  // 그리고 좌표계·높이 기준을 비우면 "다음"이 **이유 없이** 비활성이라서
  // 참가자가 무엇을 채워야 하는지 알 수 없었다. 비활성이면 무엇이 비었는지
  // 한 가지로 말한다.
  const step1DisabledReason = aoiPending.blocked
    ? (aoiPending.reason ??
      "지도 입력이 아직 반영되지 않았습니다. 완료·취소한 뒤 계속하세요.")
    : stepValid[1]
      ? undefined
      : form.aoi.length < 3
        ? "지도에서 조사 구역을 그리세요(최소 3개 꼭짓점)."
        : !isConvexPolygon(form.aoi)
          ? "현재 조사 경로는 오목한 외곽을 지원하지 않습니다. 볼록한 외곽으로 다시 그려 주세요."
          : !form.crs.trim()
            ? "현장 좌표계를 입력하세요(국내 중부 현장은 보통 EPSG:5186)."
            : !form.verticalDatum.trim()
              ? "높이 기준을 입력하세요(예: KNGeoid2018)."
              : !form.transformVersion.trim()
                ? "좌표 설정 버전을 입력하세요."
                : undefined;

  const nextDisabledReason =
    currentStep === 0 ? step0DisabledReason : currentStep === 1 ? step1DisabledReason : undefined;
  const nextBlockedByAccount = accountMismatch;
  // 잠긴 초안에서는 입력 필드에 접근할 수 없으므로, 누락 필드보다 먼저
  // 실제 차단 원인과 안전한 복귀 경로를 안내한다.
  const nextDisabledReasonWithGate = nextBlockedByAccount
    ? hasUnverifiedLegacyDraft
      ? "이 입력의 원래 계정을 확인할 수 없어 표시하지 않습니다. 현장 목록에서 먼저 확인하세요."
      : "저장된 입력의 계정과 이 화면의 계정 정보가 다릅니다. 원래 계정으로 돌아오세요."
    : nextDisabledReason;

  // exitHref는 미반영 중에는 내린다 — WizardShell의 목록 링크를 가로챌 수 없어
  // (공유 셸 변경 금지) 링크 자체를 내린다. 직접 URL 입력 이동은 막을 수 없으나,
  // 그 경우에도 초안 커밋값만 서버에 가며(미반영 값은 state에만 있음) BFF·echo
  // 결속이 POST를 검증한다.
  if (storageStatus === "loading" || storageStatus === "unreadable" || storageStatus === "unavailable") return <SiteRegistrationStorageGate status={storageStatus} />;
  if (mapStorage === "loading") return <SiteRegistrationStorageGate status="loading" />;
  if ((mapStorage === "failed" || mapConflict) && currentStep !== 1) return <section className="console-page flex flex-col gap-3" role="alert"><h2>지도 입력을 안전하게 복구할 수 없습니다</h2><p>저장된 지도 원문·초안·성공 영수증 또는 백업이 충돌하거나 형식이 다르거나 저장소를 확인하지 못했습니다. 어느 쪽도 추측해 복구하거나 제출하지 않습니다.</p><SiteRegistrationRecoveryGuidance /></section>;
  if (!draftReady || (mode === "LEGACY_SITE_ID" && effectiveIdentity && !accountMismatch && !legacyIdReady)) return <SiteRegistrationStorageGate status="loading" />;
  const identityUnconfirmed = liveChecking || liveFailed || !effectiveIdentity;
  // 지도 내부 편집은 부모 pending effect보다 먼저 시작될 수 있다. 지도 단계가
  // 열린 동안에는 알림 도착 여부와 무관하게 인스턴스를 보존한다.
  const preservePendingMap = currentStep === 1 && (identityUnconfirmed || accountMismatch);
  if (identityUnconfirmed && !preservePendingMap) return <div className="console-page" role={liveFailed ? "alert" : "status"}>{liveFailed ? "현재 계정을 확인할 수 없습니다. 이 탭을 유지하고 다시 열거나 계정을 확인해 주세요." : "현재 계정을 확인하고 있습니다."}</div>;

  return (
    <>
    {preservePendingMap && <section className="console-page !max-w-[960px]" role={liveFailed || accountMismatch && !identityUnconfirmed ? "alert" : "status"}>
      {identityUnconfirmed ? (
        <p className="rounded-lg border border-line bg-sunk p-4 text-sm text-ink-2">
          {liveFailed ? "현재 계정을 확인할 수 없습니다. 이 탭을 닫거나 새로고침하지 말고 계정을 확인한 뒤 이 탭으로 돌아와 주세요." : "현재 계정을 확인하고 있습니다. 지도 입력을 보존하는 동안 잠시 숨깁니다."}
        </p>
      ) : (
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-sunk p-4 text-sm text-ink-1">
          <h2 className="font-semibold break-keep">다른 계정의 입력입니다</h2>
          <p className="break-keep text-ink-2">지도 입력은 이 화면에 표시하거나 보내지 않습니다. 원래 계정으로 돌아온 뒤 이 탭에 다시 포커스하면 이어서 확인할 수 있습니다.</p>
          <p className="text-[12px] break-keep text-ink-2">미반영 지도 입력을 보존하려면 이 탭을 닫거나 새로고침하지 마세요.</p>
        </div>
      )}
      {(mapStorage === "failed" || mapConflict) && <SiteRegistrationRecoveryGuidance />}
    </section>}
    {storageStatus === "write-failed" && <p role="alert" className="console-page">초안 저장에 실패했습니다. 현재 화면을 벗어나면 최신 입력을 잃을 수 있어 제출을 막았습니다. 이 탭을 유지하고 입력을 별도로 보존하세요.</p>}
    {!supportedDraftShape(form) && <p role="alert" className="console-page">지원하지 않는 초안 필드가 있어 원문은 보존하고 편집과 제출을 막았습니다. 이 탭을 유지하고 이전 입력을 확인하세요.</p>}
    <div hidden={preservePendingMap} inert={preservePendingMap || !supportedDraftShape(form)}>
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {!accountMismatch && currentStep === 2 && submitPhase === "pending"
        ? "현장을 등록하는 중입니다."
        : !accountMismatch && currentStep === 2 && submitPhase === "success"
          ? receiptPersisted
            ? "현장이 등록되었습니다. 현장 브리핑으로 이동할 수 있습니다."
            : "등록은 확인됐지만 저장을 확인하지 못했습니다. 이 탭을 유지하고 현장 목록에서 확인하세요."
          : ""}
    </div>
    <WizardShell
      draftStatusText={storageStatus === "write-failed" ? "임시저장 실패 · 이 화면을 벗어나면 입력이 사라질 수 있습니다" : accountMismatch ? "저장된 입력을 표시하거나 변경하지 않습니다" : undefined}
      title="현장 등록"
      layout="steps"
      stepLabels={STEP_LABELS}
      currentStep={currentStep}
      onBack={canGoBack ? handleBack : undefined}
      onNext={handleNext}
      nextLabel={nextLabel}
      nextDisabled={!stepValid[currentStep] || nextBlockedByAccount || mapStorage !== "ready" || storageStatus !== "ready" || mapConflict || successStorageBlocked || !supportedDraftShape(form)}
      nextDisabledReason={nextDisabledReasonWithGate}
      nextPending={currentStep === 2 && submitPhase === "pending"}
      preservePendingFocus
      focusStepChanges={!(restoredSuccess && !interacted && submitPhase === "success")}
      error={
        currentStep === 2 && submitError ? (
          <div className="flex flex-col items-start gap-2">
            <ErrorState
              message={submitError}
              detail={submitDetail ?? undefined}
              action={submitAction ?? undefined}
            />
            {continuityBlocked && (
              <>
                <button
                  type="button"
                  onClick={() => router.refresh()}
                  className="btn tap-target bg-surface text-[13px]"
                >
                  계정 정보 새로고침
                </button>
                <p className="text-[12px] break-keep text-ink-2">
                  화면의 계정 정보가 최신이 아닐 수 있습니다. 새로고침 뒤에도 차단되면
                  원래 계정으로 돌아와 다시 시도하세요. BFF가 현재 세션을 매번
                  확인하므로 차단 상태에서는 Core에 보내지 않습니다.
                </p>
              </>
            )}
            {submitPhase === "error" && hasUnknownRecords && (
              renderUnknownRecordsList(remainingUnknowns)
            )}
          </div>
        ) : undefined
      }
      exitHref={aoiPending.blocked ? undefined : "/sites"}
    >
      {accountMismatch && !preservePendingMap ? (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-sunk p-4 text-sm sm:col-span-2">
          <h2 className="font-semibold break-keep">
            {hasUnverifiedLegacyDraft ? "주인을 확인할 수 없는 입력입니다" : "다른 계정의 입력입니다"}
          </h2>
          <p className="break-keep text-ink-2">
            {!hasUnverifiedLegacyDraft
              ? "이 입력은 원래 계정의 등록이 끝나지 않은 초안입니다. 삭제하지 않았고, " +
                "이 화면에서는 표시하지도 보내지도 않습니다. 원래 계정으로 돌아오면 " +
                "이어서 등록할 수 있습니다."
              : "이 입력이 어느 계정의 것인지 확인할 수 없어 표시하지도 보내지도 않습니다. " +
                "삭제하지 않았습니다. 원래 계정과 이전 요청을 먼저 확인하세요."}
          </p>
          <p className="text-[12px] break-keep text-ink-2">
            이 화면에서 입력을 지우는 방법은 없습니다 — 원본 삭제를 어느 계정에도
            허용하지 않기 때문입니다.
          </p>
          <SiteRegistrationRecoveryGuidance />
          {hasUnknownRecords && renderUnknownRecordsList(remainingUnknowns)}
        </section>
      ) : (
      <>
      {currentStep === 0 && (
        <>
          <p className="text-sm break-keep text-ink-2 sm:col-span-2">
            현장 이름과 범위를 등록한 뒤, 현장에서 관측 자료를 추가할 수 있습니다.
          </p>
          <Field label="현장 이름" required>
            <input
              type="text"
              value={form.name}
              onChange={(event) => update({ name: event.target.value })}
              placeholder="예: OO산업단지 3공구 신축공사 현장"
              className={inputClassName}
            />
          </Field>
          {mode === "LEGACY_SITE_ID" && (
            <Field
              label="현장 ID"
              helpText="자동으로 만들며, 필요하면 바꿀 수 있습니다. 영문·숫자로 시작하고 하이픈(-), 밑줄(_), 점(.)만 쓸 수 있습니다. 공백과 슬래시(/)는 쓸 수 없습니다."
              error={siteIdError}
              required
            >
              <input
                type="text"
                value={form.siteId}
                onChange={(event) => update({ siteId: event.target.value })}
                placeholder="SITE-2026-001"
                aria-invalid={Boolean(siteIdError)}
                className={inputClassName}
              />
            </Field>
          )}

          <fieldset className="flex flex-col gap-2 sm:col-span-2">
            <legend className="text-[12.5px] font-semibold break-keep text-ink-1">
              외부 클라우드 처리 동의
            </legend>
            <p className="text-[13px] leading-5 break-keep text-ink-2">
              등록 후 변경할 수 없습니다. 허용 또는 불허를 고르면 처리 기준 관할이 필요합니다.
            </p>
            {EGRESS_CHOICE_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`tap-target flex items-start gap-2 rounded-md border px-3 py-2 text-sm break-keep ${
                  form.egressChoice === opt.value
                    ? "border-accent bg-accent-tint"
                    : "border-line-strong bg-surface"
                }`}
              >
                <input
                  type="radio"
                  name="egress-choice-only"
                  value={opt.value}
                  checked={form.egressChoice === opt.value}
                  onChange={() => update({ egressChoice: opt.value })}
                  className="mt-0.5"
                />
                <span>
                  <span className="block font-medium">{opt.value === "unset" ? "미정 (기본값 — 등록 후 변경 불가)" : opt.value === "deny" ? "아니오 — 외부 클라우드 처리를 허용하지 않음" : opt.label}</span>
                  {opt.value === "unset" && <span className="mt-0.5 block text-[13px] leading-5 break-keep text-ink-2">벤더 클라우드 처리 작업을 발급할 수 없습니다.</span>}
                </span>
              </label>
            ))}
          </fieldset>

          <p className="text-[13px] leading-5 break-keep text-ink-2 sm:col-span-2">
            다음 단계의 OpenStreetMap 타일 요청은 보는 지도 범위와 접속 IP를 제공자에게 전달할 수 있습니다. 클라우드 처리 선택 및 AI 동의와 별개입니다.
          </p>

          {jurisdictionRequired && (
            <Field
              label="데이터 처리 기준 관할"
              helpText={
                form.egressChoice === "allow"
                  ? "외부 처리를 허용하는 관할을 입력하세요(예: KR). 등록 뒤에는 바꿀 수 없습니다."
                  : "사내 처리의 기준 관할을 입력하세요(예: KR). 등록 뒤에는 바꿀 수 없습니다."
              }
              required
            >
              <input
                type="text"
                value={form.jurisdiction}
                onChange={(event) => update({ jurisdiction: event.target.value })}
                placeholder="KR"
                className={inputClassName}
              />
            </Field>
          )}

          <fieldset className="flex flex-col gap-2 rounded-md border border-line-strong bg-surface px-3 py-3 sm:col-span-2">
            <legend className="text-[12.5px] font-semibold break-keep text-ink-1">
              KSI AI 활용 동의 (선택 사항)
            </legend>
            <p className="text-[13px] leading-5 break-keep text-ink-2">
              외부 클라우드 처리 선택과 별개이며 기본값은 허용하지 않음입니다. 허용된 현장 정보에 접근하려면 별도 설정과 권한이 필요하며, 동의만으로 AI가 실행되지는 않습니다. 이 등록 과정에서는 고객 원본 사진을 요청하지 않습니다.
            </p>
            <label className="tap-target flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.aiEgressAllowed}
                onChange={(event) => update({ aiEgressAllowed: event.target.checked })}
                className="mt-0.5"
              />
              <span className="block font-semibold">외부 AI의 현장 정보 접근을 허용</span>
            </label>
          </fieldset>
        </>
      )}

      {currentStep === 1 && (
        <>
          <div className="flex flex-col gap-3 sm:col-span-2">
            <p className="text-sm break-keep text-ink-2">
              지도에서 현장 범위를 그리세요. 최소 3개 꼭짓점의 볼록한 모양이어야 합니다.
            </p>
            <p className="text-sm text-ink-2">지도 입력은 이 탭의 sessionStorage에 단기 평문으로 저장되며 탭을 닫으면 사라집니다. 저장 실패 시 이동하면 최신 입력을 잃을 수 있습니다. 진행 중인 지도 포인터 그리기·편집은 복구되지 않으므로 이동 전에 완료하거나 취소하세요.</p>
            {(mapConflict || mapStorage === "failed") && <div role="alert" className="flex flex-col gap-2"><p>{mapConflict ? "지도 원문과 초안 또는 성공 영수증이 충돌합니다. 기록을 보존하고 제출을 막았습니다." : "지도 입력 저장을 확인하지 못했습니다. 현재 화면의 원문은 그대로 두었지만 이동하면 잃을 수 있어 제출을 막았습니다."}</p><SiteRegistrationRecoveryGuidance /></div>}
            <AoiPolygonMap
              value={form.aoi}
              onChange={(aoi) => update({ aoi })}
              onPendingChange={(pending) => { mapMountedRef.current = true; setAoiPending(pending); }}
              initialSnapshot={mapRecord && !mapConflict ? mapRecord.snapshot : undefined}
              onSnapshotChange={saveMapSnapshot}
            />
            {form.aoi.length >= 3 && !isConvexPolygon(form.aoi) && (
              <p className="text-sm break-keep text-high-ink">
                현재 조사 경로는 오목한 외곽을 지원하지 않습니다. 볼록한 외곽으로 다시 그려 주세요.
              </p>
            )}
          </div>
          <Field label="현장 좌표계" helpText="국내 중부 현장은 보통 EPSG:5186을 사용합니다." required>
            <input
              type="text"
              value={form.crs}
              onChange={(event) => update({ crs: event.target.value })}
              placeholder="EPSG:5186"
              className={inputClassName}
            />
          </Field>
          <Field label="높이 기준" helpText="예: KNGeoid2018" required>
            <input
              type="text"
              value={form.verticalDatum}
              onChange={(event) => update({ verticalDatum: event.target.value })}
              placeholder="KNGeoid2018"
              className={inputClassName}
            />
          </Field>
          <Field label="거리 단위" helpText="현재는 미터로 고정됩니다.">
            <input type="text" value="meter" disabled className={inputClassName} />
          </Field>
          <Field label="좌표 설정 버전" helpText="기본값을 유지해도 됩니다.">
            <input
              type="text"
              value={form.transformVersion}
              onChange={(event) => update({ transformVersion: event.target.value })}
              className={inputClassName}
            />
          </Field>
        </>
      )}

      {currentStep === 2 && (
        <>
          {submitPhase === "idle" && (
            <section className="flex flex-col gap-3 rounded-lg border border-line bg-sunk p-4 text-sm sm:col-span-2">
              <h2 className="font-semibold break-keep">등록 내용을 확인하세요</h2>
              <dl className="grid gap-2 sm:grid-cols-2">
                <div><dt className="text-[11.5px] text-ink-muted">현장</dt><dd className="font-medium">{form.name.trim()}</dd></div>
                {mode === "LEGACY_SITE_ID" && (
                  <div><dt className="text-[11.5px] text-ink-muted">현장 ID</dt><dd className="num break-token">{trimmedSiteId}</dd></div>
                )}
                <div><dt className="text-[11.5px] text-ink-muted">현장 범위</dt><dd>{form.aoi.length}개 꼭짓점</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">현장 좌표계</dt><dd className="num break-token">{form.crs.trim()}</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">외부 클라우드 처리</dt><dd>{form.egressChoice === "allow" ? "허용" : form.egressChoice === "deny" ? "허용하지 않음 — 벤더 클라우드 처리 작업 발급 불가" : "미정 — 벤더 클라우드 처리 작업 발급 불가, 등록 후 변경 불가"}</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">처리 기준 관할</dt><dd className="num break-token">{jurisdictionRequired ? form.jurisdiction.trim() : "—"}</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">외부 AI 접근 동의</dt><dd>{form.aiEgressAllowed ? "허용 — 실제 접근에는 별도 설정과 권한이 필요" : "허용하지 않음(기본값)"}</dd></div>
              </dl>
              <p className="text-[12px] break-keep text-ink-2">
                현장 등록과 자료 검사·분석은 별개입니다. 등록 후 작업구역과 관측 자료를 확인하세요.
              </p>
            </section>
          )}
          {submitPhase === "pending" && (
            <p className="text-sm break-keep text-ink-2 sm:col-span-2">현장을 등록하는 중입니다…</p>
          )}
          {submitPhase === "success" && (
            <div className="flex flex-col gap-3 rounded-lg border border-safe/30 bg-safe-bg p-4 text-sm sm:col-span-2">
              <p className="font-medium break-keep text-safe-ink">
                현장이 등록되었습니다.
              </p>
              {/* 확인된 등록의 식별자 — 새로고침 뒤 셸이 늦게 반영되거나 권한·조회
                  실패로 이 화면이 사라져도, 이 ID·이름이 다음 행동의 기준점이다. */}
              <dl className="grid gap-2 sm:grid-cols-2">
                <div>
                  <dt className="text-[11.5px] text-safe-ink/70">현장</dt>
                  <dd className="font-medium break-keep text-safe-ink">{confirmedSiteName || "이름 확인 안 됨"}</dd>
                </div>
                <div>
                  <dt className="text-[11.5px] text-safe-ink/70">현장 ID</dt>
                  <dd className="num font-medium break-token text-safe-ink">{confirmedSiteId || "ID 확인 안 됨"}</dd>
                </div>
              </dl>
              {/* 링크를 여기서 걸지 않는다 — 아래 "현장 상세로 이동" 버튼(다음 버튼)이
                  이미 같은 목적지로 보낸다. ADR-KSI-015 이후 이 흐름을 고른 사용자도
                  MISSIONS_ISSUE 를 갖고 있어(권한이 아니라 순서를 미룬 것뿐이다),
                  상세 화면에서 "베이스라인 조사 계획" 버튼이 곧바로 보인다. */}
              <p className="break-keep text-safe-ink/90">
                {mode === "MAPPED_BOOTSTRAP"
                  ? "현장에서 작업구역과 관측 자료를 확인하세요."
                  : "현장에서 작업구역을 확인하고 관측 자료 등록을 이어가세요."}
              </p>
              <p className="text-[12px] break-keep text-safe-ink/80">
                좌측 현장 목록·건수는 다음 화면으로 이동하면 서버 기준으로 반영됩니다.
                이 화면에서는 바로 바뀌지 않지만, 위 현장 ID로의 등록은 끝났습니다.
                아래에서 목록을 직접 열어 ID가 있는지 확인할 수 있습니다.
              </p>
              {!receiptPersisted && (
                <div className="text-[12px] break-keep text-safe-ink/80">
                  <p>
                  이 확인은 이 화면에서만 유지됩니다. 등록은 확인됐지만 초안 또는 영수증 저장·정리를 확인하지 못했습니다. 이전 요청 기록을 보존하고 자동 이동을 막았습니다. 이 탭을 유지하고 현장 ID를 목록에서 확인하세요.
                  </p>
                  <SiteRegistrationRecoveryGuidance confirmed />
                </div>
              )}
              {hasUnknownRecords && (
                renderUnknownRecordsList(remainingUnknowns)
              )}
              <Link
                href="/sites"
                target={!receiptPersisted ? "_blank" : undefined}
                rel={!receiptPersisted ? "noopener noreferrer" : undefined}
                className="tap-target self-start text-[13px] font-semibold break-keep text-safe-ink underline underline-offset-2"
              >
                현장 목록에서 직접 확인하기
              </Link>
            </div>
          )}
          {submitPhase === "error" && (
            <p className="text-sm break-keep text-ink-2 sm:col-span-2">
              처리 중 문제가 발생했습니다. 아래에서 원인을 확인하고 다시 시도하세요.
            </p>
          )}
          {submitPhase === "idle" && hasUnknownRecords && (
            renderUnknownRecordsList(remainingUnknowns)
          )}
        </>
      )}
      </>
      )}
    </WizardShell>
    </div>
    </>
  );
}
