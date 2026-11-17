/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it } from "vitest";

import { loadExternalUploadDefaults, parseExternalUploadDefaults, saveExternalUploadDefaults } from "@/lib/external-upload-defaults";
import { installFakeLocalStorage } from "./storage-fakes";

const KEY = "ksi.external-upload-defaults.v1";

beforeEach(() => { installFakeLocalStorage(); });

describe("external upload defaults", () => {
  it("저장한 소프트웨어를 그대로 읽는다", () => {
    saveExternalUploadDefaults({ softwareName: "Metashape", softwareVersion: "2.1" });
    expect(loadExternalUploadDefaults()).toEqual({ softwareName: "Metashape", softwareVersion: "2.1" });
  });

  it("앞뒤 공백을 지우고 255자로 자른다", () => {
    saveExternalUploadDefaults({ softwareName: `  ${"a".repeat(300)}  `, softwareVersion: " 1 " });
    const loaded = loadExternalUploadDefaults();
    expect(loaded?.softwareName).toHaveLength(255);
    expect(loaded?.softwareVersion).toBe("1");
  });

  it("이름이 비면 저장하지 않고 기존 값을 지우지도 않는다", () => {
    saveExternalUploadDefaults({ softwareName: "ODM", softwareVersion: "3" });
    saveExternalUploadDefaults({ softwareName: "   ", softwareVersion: "9" });
    expect(loadExternalUploadDefaults()).toEqual({ softwareName: "ODM", softwareVersion: "3" });
  });

  it("깨진 값·다른 모양·배열은 기억 없음으로 본다", () => {
    for (const raw of [null, "", "not json", "[]", "7", '"x"', '{"softwareName":5}', '{"softwareName":"  "}']) {
      expect(parseExternalUploadDefaults(raw), String(raw)).toBeNull();
    }
  });

  it("저장하지 않은 필드(보관 위치 등)는 읽지 않는다", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ softwareName: "ODM", softwareVersion: "1", retentionLocus: "upstream_source", captureDate: "2026-01-01" }));
    expect(loadExternalUploadDefaults()).toEqual({ softwareName: "ODM", softwareVersion: "1" });
  });

  it("저장소를 못 쓰면 던지지 않고 기억 없이 동작한다", () => {
    const denied = () => { throw new DOMException("denied", "SecurityError"); };
    installFakeLocalStorage({ getItem: denied, setItem: denied });
    expect(() => saveExternalUploadDefaults({ softwareName: "ODM", softwareVersion: "1" })).not.toThrow();
    expect(loadExternalUploadDefaults()).toBeNull();
  });
});
