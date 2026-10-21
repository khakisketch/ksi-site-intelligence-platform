/**
 * 창 준비 요청 스케줄러(Console 측).
 *
 * 측정 증거(`docs/audit/GAP-06_SPATIAL_PREPARE_LOAD_EVIDENCE_2026-10-21.md`)가
 * 정한 레인 사실을 그대로 따른다 — 계약 §4의 자리수 N=4·대기 8칸 표현과
 * 다를 때에는 측정 사실을 따르고, 그 차이를 핸드오프에 밝힌다.
 *
 * - 레인은 동시에 최대 2개의 활성 PREPARE만 받는다. 3번째 동시 발행은
 *   빠르게 재시도 가능한 429 CONCURRENCY_LIMIT_EXCEEDED로 거부되며,
 *   주차되지 않는다. 큐 버퍼는 사실상 0이다 — 순서는 클라이언트가
 *   2개씩 발행하며 만든다.
 * - 같은 (assetRef, pixelWindow, purpose)는 같은 안정 키를 쓴다. 같은
 *   키·같은 본문의 재발행은 ~5ms에 같은 작업으로 돌아오므로(200),
 *   반복 제스처·캐시 적중은 새 PREPARE를 만들지 않는다. 다른 본문에
 *   같은 키를 쓰면 409이므로 키는 창 좌표를 정확히 포함한다.
 * - 한 512×512 창은 단독 약 5.4–5.9초(대부분 워커 수거 대기 약
 *   4.6–5.1초, 실행 약 0.77초). 1022×915 전체는 4창·2파동 ≈ 12초이며,
 *   상호작용 예산은 약 15초다 — 조용히 넘기지 않는다.
 *
 * 이 모듈은 Core의 작업을 대신 판단하지 않는다. 발행 순서·동시성·
 * 재시도만을 맡고, 권리·격자·영수증 검증은 Core가 그대로 소유한다.
 *
 * Invariants: INV-060·061(권한·이그레스 — 키에 권한을 섞지 않음).
 */

import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import type { SpatialDataBounds } from "./core-api/spatial-data-types";

/** 표시 준비의 용도 — Core 목적 값만 쓴다(새 목적 없음). */
export type DisplayPreparePurpose = "GENERAL_DATA_USE" | "EXTERNAL_AI";

/** 스케줄러가 발행하는 한 창의 요청 — 바이트가 아닌 요청 식별자다. */
export interface ScheduledDisplayWindow {
  /** `stablePrepareKey`의 결과 — 같은 창은 같은 키다. */
  key: string;
  assetRef: string;
  /** Core pixelWindow와 같은 half-open 순서 [c0, c1, r0, r1]. */
  pixelWindow: readonly [number, number, number, number];
  requestedBounds: SpatialDataBounds;
  observedCrsDigest: string;
  purpose: DisplayPreparePurpose;
}

export type DisplayWindowStatus =
  | "queued"
  | "active"
  | "retry-wait"
  | "done"
  | "failed"
  | "cancelled";

export interface DisplaySchedulerIssueResult {
  jobId: string;
  executionState: string;
}

/**
 * 발행 함수가 던지는 레인 오류 — fetch/Core 경계에서만 만든다.
 * 제품 자료를 만들지 않으며, 상태·코드·재시도 가능 여부만 옮긴다.
 */
export class DisplayPrepareIssueError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: { status?: number | null; code?: string | null; retryable?: boolean } = {},
  ) {
    super(message);
    this.name = "DisplayPrepareIssueError";
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.retryable = options.retryable ?? false;
  }
}

/** 429 또는 재시도 가능 표식이 있으면 back-off 후 재시도한다. */
export function isRetryableLaneError(error: unknown): boolean {
  if (error instanceof DisplayPrepareIssueError) {
    if (error.retryable) return true;
    return error.status === 429;
  }
  return false;
}

export type DisplayIssueFn = (
  window: ScheduledDisplayWindow,
  signal: AbortSignal,
) => Promise<DisplaySchedulerIssueResult>;

/**
 * 안정 준비 키 — (assetRef, pixelWindow, purpose)의 순수 함수다.
 * 같은 창·같은 용도의 반복 제스처는 같은 키가 되어 새 PREPARE를
 * 만들지 않고(200 재현), 다른 창에 같은 키를 쓰지 않으므로 409를
 * 만들지 않는다.
 */
export function stablePrepareKey(
  assetRef: string,
  pixelWindow: readonly [number, number, number, number],
  purpose: DisplayPreparePurpose,
): string {
  const canonical = `${assetRef}|${pixelWindow[0]},${pixelWindow[1]},${pixelWindow[2]},${pixelWindow[3]}|${purpose}`;
  return canonical;
}

/**
 * Idempotency-Key 헤더용 안정 키 — BFF 패턴(`[A-Za-z0-9._:-]{1,128}`)에
 * 맞춘다. 같은 입력에는 같은 키가 돌아와 재입장이 무료가 된다.
 */
export function stableIdempotencyKey(
  assetRef: string,
  pixelWindow: readonly [number, number, number, number],
  purpose: DisplayPreparePurpose,
): string {
  const canonical = stablePrepareKey(assetRef, pixelWindow, purpose);
  const digest = bytesToHex(sha256(new TextEncoder().encode(canonical)));
  return `sdisp-v1-${digest.slice(0, 32)}`;
}

/** 레인 포화·재시도의 이름 있는 상태 문구 — 빈 화면·조용한 대체 금지. */
export function saturatedLaneCopy(active: number, queued: number): string {
  return `준비 중 ${active}개 · 기다리는 창 ${queued}개 · 순차 처리 중`;
}

export function retryWaitingCopy(attempt: number, maxAttempts: number): string {
  return `재시도 중(${attempt}/${maxAttempts}) · 순차 처리 중`;
}

export interface DisplaySchedulerOptions {
  /** 동시 발행 상한 — 측정된 레인 사실이므로 기본 2다. */
  maxConcurrent?: number;
  /** 재시도 가능 오류의 최대 재시도 횟수 — 무한 재시도 금지. */
  maxRetries?: number;
  /** 시도 횟수(1부터)에 대한 대기 ms — 측정 수거 주기(~5초)보다 짧게 두지 않는다. */
  backoffMs?: (attempt: number) => number;
  sleep?: (ms: number) => Promise<void>;
  /** 상태 전이 알림 — 화면의 이름 있는 대기·재시도 표시용이다. */
  listener?: (snapshot: DisplaySchedulerSnapshot) => void;
}

export interface DisplaySchedulerSnapshot {
  active: string[];
  queued: string[];
  retrying: string[];
  done: string[];
  failed: Record<string, string>;
  cancelled: string[];
  /** 조용히 예산을 넘기지 않기 위한 현재 자리수. */
  activeCount: number;
  queuedCount: number;
  maxConcurrent: number;
  laneCopy: string | null;
  retryCopy: string | null;
}

const DEFAULT_MAX_RETRIES = 3;

function defaultBackoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** (attempt - 1), 8000);
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * 최대 2개 동시 발행 스케줄러.
 *
 * 규칙:
 * - 같은 키의 진행 중 요청은 합류(join)한다 — 중복 발행하지 않는다.
 * - 이미 끝난 키는 다시 발행하지 않는다(호출자가 캐시 적중으로 취급).
 * - 뷰포트가 바뀌면 새 집합에 없는 대기열을 버리고(포기), 이미
 *   발행된 Fu행(active)은 끝까지 두어 기록·캐시에 남긴다 — 끝난
 *   기록은 다시 보기(pan-back) 적중이 된다.
 * - 재시도 가능 429는 bounded back-off 후 최대 maxRetries까지만
 *   재시도하고, 그 사이 "재시도 중"을 밝힌다.
 */
export class DisplayPrepareScheduler {
  private readonly issue: DisplayIssueFn;
  private readonly maxConcurrent: number;
  private readonly maxRetries: number;
  private readonly backoffMs: (attempt: number) => number;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly listener: ((snapshot: DisplaySchedulerSnapshot) => void) | null;

  private readonly order: string[] = [];
  private readonly queued = new Set<string>();
  private readonly active = new Set<string>();
  private readonly retrying = new Set<string>();
  private readonly done = new Set<string>();
  private readonly cancelled = new Set<string>();
  private readonly failed = new Map<string, string>();
  private readonly inflight = new Map<string, Promise<DisplaySchedulerIssueResult>>();
  private readonly windows = new Map<string, ScheduledDisplayWindow>();
  private readonly results = new Map<string, DisplaySchedulerIssueResult>();
  private readonly attempts = new Map<string, number>();
  private readonly controllers = new Map<string, AbortController>();
  private pumping = false;

  constructor(issue: DisplayIssueFn, options: DisplaySchedulerOptions = {}) {
    this.issue = issue;
    this.maxConcurrent = options.maxConcurrent ?? 2;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.backoffMs = options.backoffMs ?? defaultBackoffMs;
    this.sleep = options.sleep ?? defaultSleep;
    this.listener = options.listener ?? null;
  }

  private notify(): void {
    try {
      this.listener?.(this.snapshot());
    } catch {
      // 표시 알림 실패는 스케줄을 멈추지 않는다.
    }
  }

  /**
   * 새 집합을 스케줄한다. 새 집합에 없는 대기열은 버리고(포기),
   * 진행(active)·재시도 대기는 끝까지 둔다. 같은 키 중복은 합류한다.
   *
   * S1 — 핀 고정 히스테리시스: `retainKeys`에 든 대기열 키는 새 집합에
   * 없어도 유지한다. 호출자가 `selectHysteresisRetainedKeys`로 다음 커버
   * 근처의 대기열만 골라 넘긴다 — 1픽셀 팬 같은 미세 이동이 진행 중인
   * 대기열을 버리고 다시 발행하게 두지 않는다. 생략 시 기존 동작(버리기)
   * 그대로다.
   */
  ensure(
    windows: readonly ScheduledDisplayWindow[],
    options: { retainKeys?: readonly string[] } = {},
  ): DisplaySchedulerSnapshot {
    const keep = new Set(windows.map((item) => item.key));
    for (const retained of options.retainKeys ?? []) {
      if (this.queued.has(retained)) keep.add(retained);
    }
    for (const key of [...this.queued]) {
      if (!keep.has(key)) {
        this.queued.delete(key);
        this.cancelled.add(key);
        const index = this.order.indexOf(key);
        if (index >= 0) this.order.splice(index, 1);
      }
    }
    for (const item of windows) {
      this.windows.set(item.key, item);
      if (
        this.done.has(item.key) ||
        this.active.has(item.key) ||
        this.retrying.has(item.key) ||
        this.queued.has(item.key) ||
        this.inflight.has(item.key)
      ) {
        continue;
      }
      this.failed.delete(item.key);
      this.cancelled.delete(item.key);
      this.queued.add(item.key);
      this.order.push(item.key);
    }
    void this.pump();
    this.notify();
    return this.snapshot();
  }

  /** 진행을 기다리는 결합 — 같은 키는 같은 약속을 공유한다. */
  join(key: string): Promise<DisplaySchedulerIssueResult> | null {
    return this.inflight.get(key) ?? null;
  }

  /** 이미 끝난 키의 준비 기록 — 반복 제스처의 재입장용이다. */
  completedResult(key: string): DisplaySchedulerIssueResult | null {
    return this.results.get(key) ?? null;
  }

  snapshot(): DisplaySchedulerSnapshot {
    const active = [...this.active];
    const queued = this.order.filter((key) => this.queued.has(key));
    const retrying = [...this.retrying];
    const failed: Record<string, string> = {};
    for (const [key, message] of this.failed) failed[key] = message;
    const activeCount = this.active.size;
    const queuedCount = queued.length;
    return {
      active,
      queued,
      retrying,
      done: [...this.done],
      failed,
      cancelled: [...this.cancelled],
      activeCount,
      queuedCount,
      maxConcurrent: this.maxConcurrent,
      laneCopy: queuedCount > 0 ? saturatedLaneCopy(activeCount, queuedCount) : null,
      retryCopy:
        retrying.length > 0
          ? retryWaitingCopy(this.attempts.get(retrying[0] as string) ?? 1, this.maxRetries)
          : null,
    };
  }

  private async pump(): Promise<void> {
    if (this.pumping) return;
    this.pumping = true;
    try {
      while (this.active.size < this.maxConcurrent) {
        const next = this.order.find((key) => this.queued.has(key));
        if (!next) return;
        this.queued.delete(next);
        const index = this.order.indexOf(next);
        if (index >= 0) this.order.splice(index, 1);
        const request = this.windows.get(next);
        if (!request) continue;
        this.active.add(next);
        const attempt = (this.attempts.get(next) ?? 0) + 1;
        this.attempts.set(next, attempt);
        const controller = new AbortController();
        this.controllers.set(next, controller);
        const pending = this.runOne(request, controller.signal);
        this.inflight.set(next, pending);
        void pending.then(
          (result) => {
            this.inflight.delete(next);
            this.controllers.delete(next);
            this.active.delete(next);
            this.done.add(next);
            this.results.set(next, result);
            this.notify();
            void this.pump();
          },
          (error: unknown) => {
            this.inflight.delete(next);
            this.controllers.delete(next);
            this.active.delete(next);
            if (isRetryableLaneError(error) && attempt <= this.maxRetries) {
              this.retrying.add(next);
              this.notify();
              void this.sleep(this.backoffMs(attempt))
                .then(() => {
                  this.retrying.delete(next);
                  if (!this.done.has(next)) {
                    this.queued.add(next);
                    this.order.unshift(next);
                  }
                  this.notify();
                  void this.pump();
                })
                .catch(() => {
                  this.retrying.delete(next);
                  this.failed.set(next, "재시도 대기를 마치 못했습니다. 다시 시도하세요.");
                  this.notify();
                });
            } else {
              this.failed.set(
                next,
                error instanceof DisplayPrepareIssueError
                  ? error.message
                  : "창 준비 요청을 만들지 못했습니다. 현재 상태를 다시 확인하세요.",
              );
              this.notify();
            }
            void this.pump();
          },
        );
      }
    } finally {
      this.pumping = false;
    }
  }

  private runOne(
    request: ScheduledDisplayWindow,
    signal: AbortSignal,
  ): Promise<DisplaySchedulerIssueResult> {
    return this.issue(request, signal);
  }
}
