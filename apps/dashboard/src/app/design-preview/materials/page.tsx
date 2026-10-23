import type { Metadata } from "next";
import { materialsDesignReturnHref } from "@/lib/design-preview-return";
import MaterialsDesignPreview, { type ExampleMode } from "./MaterialsDesignPreview";

export const metadata: Metadata = { title: "자료 화면 디자인 예시 · KSI" };

function normalizeMode(value: unknown): ExampleMode {
  // 모드 없이 열면 지금의 나란히 보기를 둔다. 배열·모르는 값은 기본값이다.
  return value === "single" || value === "swipe" ? value : "compare";
}

export default async function DesignPreviewMaterialsPage({
  searchParams,
}: { searchParams: Promise<{ returnTo?: string | string[]; mode?: string | string[] }> }) {
  const { returnTo, mode } = await searchParams;
  return <MaterialsDesignPreview returnHref={materialsDesignReturnHref(returnTo)} initialMode={normalizeMode(mode)} />;
}
