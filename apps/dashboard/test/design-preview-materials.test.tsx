import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));

import MaterialsDesignPreview from "@/app/design-preview/materials/MaterialsDesignPreview";
import DesignPreviewMaterialsPage from "@/app/design-preview/materials/page";
import { materialsDesignReturnHref } from "@/lib/design-preview-return";

const REAL_MATERIALS_HREF =
  "/sites/prod-sample-floreat-01/spatial-assets?workAreaId=wa-prod-sample-floreat-01-0001";

// 실제 등록 바인딩·조회 흔적 — 예시 파일에 절대 두지 않는다. 디자인 예시는
// 등록 자료의 fallback이 아니며, Core를 호출하지 않는다.
const BANNED_SOURCE_TOKENS = [
  "core-api",
  "ksa-v1-",
  "jobId",
  "submissionRef",
  "visualAAssetRef",
  "getSpatialAsset",
  "listSpatialAssets",
  "external-reconstruction",
  "spatial-data-requests",
  "fetch(",
];

function designPreviewSourceFiles(): string[] {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "app", "design-preview");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (full.endsWith(".tsx") || full.endsWith(".ts")) files.push(full);
    }
  };
  walk(root);
  // 겹쳐 보기 원시 요소도 예시 전용 호출(등록 바인딩 없음)을 지킨다.
  files.push(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "components", "site", "SpatialSwipeCompare.tsx"));
  files.push(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "lib", "spatial-swipe.ts"));
  return files;
}

describe("design preview materials boundary", () => {
  it("never imports Core bindings or fabricates record identities", () => {
    const files = designPreviewSourceFiles();
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const token of BANNED_SOURCE_TOKENS) {
        expect(text, `${file} must not contain ${token}`).not.toContain(token);
      }
    }
  });
});

describe("design preview materials page", () => {
  it("returns to the caller's scoped materials selection rather than another site", async () => {
    const target = "/sites/site-return/spatial-assets?workAreaId=area-return&cursor=page-2&info=1";
    const page = await DesignPreviewMaterialsPage({ searchParams: Promise.resolve({ returnTo: target }) });
    const html = renderToStaticMarkup(page);
    expect(html).toContain(`href="${target.replaceAll("&", "&amp;")}"`);
    expect(html).not.toContain(`href="${REAL_MATERIALS_HREF}"`);
  });

  it("refuses external, malformed and non-material return destinations", () => {
    for (const target of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/sites/a/../spatial-assets", "/account", " /sites/a/spatial-assets", "/sites/a/spatial-assets#fragment", ["/sites/a/spatial-assets"], "x".repeat(2049)]) {
      expect(materialsDesignReturnHref(target)).toBe(REAL_MATERIALS_HREF);
    }
  });

  it("opens with two photographic sides, a persistent banner and a return path", () => {
    const html = renderToStaticMarkup(<MaterialsDesignPreview />);
    // 지속 배너 — 현재 등록 자료가 아님을 한 줄로 먼저 밝힌다.
    expect(html).toContain("디자인 예시 · 현재 등록 자료 아님");
    expect(html).toContain(`href="${REAL_MATERIALS_HREF}"`);
    expect(html).toContain("실제 등록 자료로 돌아가기");
    // 처음부터 양쪽 사진(2021/2022 정사영상)이 보인다.
    expect(html).toContain("/design-preview/spatial/ortho-2021.webp");
    expect(html).toContain("/design-preview/spatial/ortho-2022.webp");
    expect(html).toContain("2021-08-17");
    expect(html).toContain("2022-08-24");
    // 보기 방식과 각 칸의 층 선택이 있다.
    expect(html).toContain("나란히");
    expect(html).toContain("한 장");
    expect(html).toContain("층 선택");
    // 날짜 선택은 각 이미지 바로 위에서 한다.
    expect(html).toContain('id="example-observation-A"');
    expect(html).toContain('id="example-observation-B"');
    // 출처 표시는 항상 보인다.
    expect(html).toContain("Cambridge Coastcare / DataWA · CC BY 4.0 · 보기용 크롭");
    expect(html).toContain("https://creativecommons.org/licenses/by/4.0/");
    // 수치·정합·분석 결과 주장이 없다.
    expect(html).not.toContain("ksa-v1-");
    expect(html).not.toContain("/api/sites");
    expect(html).not.toContain("정확도");
  });

  it("keeps the detailed provenance on demand and explains registration limits", () => {
    const html = renderToStaticMarkup(<MaterialsDesignPreview />);
    // 상세 근거는 정보 펼침에서만 본다 — 기본 화면은 사진이 먼저다.
    // 서랍 틀은 마운트 유지하되 숨긴다.
    expect(html).toContain("정보");
    expect(html).toContain('id="design-example-info"');
    expect(html).toContain("display:none");
    expect(html).not.toContain("이 예시에서는 등록·준비·검사를 만들 수 없습니다");
    // 등록은 실제 현장 맥락으로만 연결한다.
    expect(html).toContain("실제 현장에서 등록");
    expect(html).toContain('href="/sites"');
  });
});

describe("design preview swipe mode", () => {
  it("stays on side-by-side without a mode and validates the mode parameter", async () => {
    const plain = renderToStaticMarkup(<MaterialsDesignPreview />);
    expect(plain).not.toContain("비교 경계");
    expect(plain).toContain("독립 보기 · 정량 비교 아님");

    const swiped = renderToStaticMarkup(<MaterialsDesignPreview initialMode="swipe" />);
    expect(swiped).toContain("비교 경계");
    expect(swiped).toContain("표시용 겹쳐 보기 · 정량 비교 아님");
    expect(swiped).not.toContain("독립 보기 · 정량 비교 아님");
  });

  it("opens ?mode=swipe directly and falls back to side-by-side otherwise", async () => {
    const swiped = renderToStaticMarkup(
      await DesignPreviewMaterialsPage({ searchParams: Promise.resolve({ mode: "swipe" }) }),
    );
    expect(swiped).toContain("비교 경계");
    for (const mode of ["zoom", "", "COMPARE", ["swipe", "compare"]]) {
      const fallback = renderToStaticMarkup(
        await DesignPreviewMaterialsPage({ searchParams: Promise.resolve({ mode: mode as string }) }),
      );
      expect(fallback).not.toContain("비교 경계");
      expect(fallback).toContain("나란히");
    }
  });

  it("keeps the scoped return destination with the swipe entry", async () => {
    const target = "/sites/site-return/spatial-assets?workAreaId=area-return&visualAAssetRef=ksa-v1-x";
    const swiped = renderToStaticMarkup(
      await DesignPreviewMaterialsPage({ searchParams: Promise.resolve({ mode: "swipe", returnTo: target }) }),
    );
    expect(swiped).toContain("비교 경계");
    expect(swiped).toContain(`href="${target.replaceAll("&", "&amp;")}"`);
  });
});
