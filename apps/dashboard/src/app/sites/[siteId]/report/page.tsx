import { redirect } from "next/navigation";

export const metadata = { title: "외부 관측 결과 · KSI" };

export default async function SiteReportPage({ params }: { params: Promise<{ siteId: string }> }) {
  const { siteId } = await params;
  redirect(`/sites/${encodeURIComponent(siteId)}`);
}
