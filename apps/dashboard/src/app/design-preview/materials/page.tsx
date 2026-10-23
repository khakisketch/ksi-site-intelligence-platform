import type { Metadata } from "next";
import { materialsDesignReturnHref } from "@/lib/design-preview-return";
import MaterialsDesignPreview from "./MaterialsDesignPreview";

export const metadata: Metadata = { title: "자료 화면 디자인 예시 · KSI" };

export default async function DesignPreviewMaterialsPage({
  searchParams,
}: { searchParams: Promise<{ returnTo?: string | string[] }> }) {
  const { returnTo } = await searchParams;
  return <MaterialsDesignPreview returnHref={materialsDesignReturnHref(returnTo)} />;
}
