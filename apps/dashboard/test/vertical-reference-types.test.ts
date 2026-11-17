import { describe, expect, it } from "vitest";

import {
  isDeclarationRecord,
  isDeclarationState,
  parseDeclareBody,
  parseWithdrawBody,
} from "@/lib/core-api/vertical-reference-types";

const ASSET = `ksa-v1-${"a".repeat(64)}`;
const DIGEST = `sha256:${"b".repeat(64)}`;

const active = (overrides: Record<string, unknown> = {}) => ({
  declarationId: `vrd-${"1".repeat(32)}`, siteId: "site-1", workAreaId: "area-1", assetRef: ASSET, sequence: 1, status: "ACTIVE",
  datum: "orthometric_kngeoid2018", unit: "metre", basis: "Terra에서 내보냄", declaredBy: "operator-1",
  declaredAt: "2026-11-17T00:00:00Z", declarationDigest: DIGEST, ...overrides,
});
const withdrawn = (sequence = 2) => active({ declarationId: `vrd-${"2".repeat(32)}`, sequence, status: "WITHDRAWN", datum: null, basis: null });

describe("isDeclarationRecord", () => {
  it("선언과 철회를 각각 계약대로 받는다", () => {
    expect(isDeclarationRecord(active())).toBe(true);
    expect(isDeclarationRecord(withdrawn())).toBe(true);
  });

  it.each([
    ["선언인데 기준이 없다", active({ datum: null })],
    ["선언인데 근거가 없다", active({ basis: null })],
    ["선언인데 근거가 비었다", active({ basis: "" })],
    ["철회인데 기준이 남았다", { ...withdrawn(), datum: "ellipsoidal" }],
    ["철회인데 근거가 남았다", { ...withdrawn(), basis: "x" }],
    ["모르는 기준", active({ datum: "EGM96" })],
    ["단위가 미터가 아니다", active({ unit: "foot" })],
    ["모르는 상태", active({ status: "PENDING" })],
    ["식별자 형식", active({ declarationId: "x" })],
    ["자료 참조 형식", active({ assetRef: "x" })],
    ["digest 형식", active({ declarationDigest: "x" })],
    ["sequence 0", active({ sequence: 0 })],
    ["sequence 소수", active({ sequence: 1.5 })],
  ])("거부한다: %s", (_name, value) => {
    expect(isDeclarationRecord(value)).toBe(false);
  });
});

describe("isDeclarationState", () => {
  const state = (overrides: Record<string, unknown> = {}) => ({ assetRef: ASSET, observed: false, current: active(), history: [active()], ...overrides });

  it("선언 없음, 현재 선언, 철회 뒤를 받는다", () => {
    expect(isDeclarationState(state({ current: null, history: [] }))).toBe(true);
    expect(isDeclarationState(state())).toBe(true);
    expect(isDeclarationState(state({ current: null, history: [active(), withdrawn()] }))).toBe(true);
  });

  it.each([
    ["현재가 철회 기록", state({ current: withdrawn(), history: [active(), withdrawn()] })],
    ["현재가 이력의 마지막이 아니다", state({ history: [active(), active({ declarationId: `vrd-${"3".repeat(32)}`, sequence: 2 })] })],
    ["현재 없음인데 마지막이 선언이다", state({ current: null, history: [active()] })],
    ["observed가 불리언이 아니다", state({ observed: "no" })],
    ["이력에 깨진 기록", state({ history: [{ ...active(), datum: null }] })],
    ["자료 참조 형식", state({ assetRef: "x" })],
  ])("거부한다: %s", (_name, value) => {
    expect(isDeclarationState(value)).toBe(false);
  });
});

describe("parseDeclareBody", () => {
  const body = (overrides: Record<string, unknown> = {}) => ({ datum: "ellipsoidal", unit: "metre", basis: " RTK 타원체고 ", expectedSequence: 0, ...overrides });

  it("근거 앞뒤 공백을 지우고 받는다", () => {
    expect(parseDeclareBody(body())).toEqual({ datum: "ellipsoidal", unit: "metre", basis: "RTK 타원체고", expectedSequence: 0 });
  });

  it.each([
    ["본문이 객체가 아니다", null],
    ["모르는 필드(범위를 바꾸려는 시도)", body({ siteId: "other" })],
    ["모르는 기준", body({ datum: "EGM96" })],
    ["단위 미터 아님", body({ unit: "foot" })],
    ["단위 생략", { datum: "ellipsoidal", basis: "x", expectedSequence: 0 }],
    ["근거 없음", body({ basis: "   " })],
    ["근거가 문자열이 아니다", body({ basis: 5 })],
    ["근거가 너무 길다", body({ basis: "가".repeat(256) })],
    ["sequence 문자열", body({ expectedSequence: "0" })],
    ["sequence 음수", body({ expectedSequence: -1 })],
    ["sequence 상한 초과", body({ expectedSequence: 65 })],
  ])("거부한다: %s", (_name, value) => {
    expect(parseDeclareBody(value)).toBeNull();
  });

  it("근거 255자는 받는다", () => {
    expect(parseDeclareBody(body({ basis: "가".repeat(255) }))?.basis).toHaveLength(255);
  });
});

describe("parseWithdrawBody", () => {
  it("본 sequence만 받는다", () => {
    expect(parseWithdrawBody({ expectedSequence: 2 })).toEqual({ expectedSequence: 2 });
    expect(parseWithdrawBody({ expectedSequence: 0 })).toBeNull();
    expect(parseWithdrawBody({ expectedSequence: 2, siteId: "x" })).toBeNull();
    expect(parseWithdrawBody({})).toBeNull();
    expect(parseWithdrawBody("2")).toBeNull();
  });
});
