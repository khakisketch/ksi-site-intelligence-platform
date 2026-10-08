import { redirect } from "next/navigation";

export const metadata = { title: "현장 분석 · KSI" };

export default async function SiteChangesPage({ params }: { params: Promise<{ siteId: string }> }) {
  const { siteId } = await params;
  redirect(`/sites/${encodeURIComponent(siteId)}/analysis`);
}
