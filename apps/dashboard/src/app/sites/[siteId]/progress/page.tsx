import { redirect } from "next/navigation";

export const metadata = { title: "공간 자산 · KSI" };

export default async function SiteProgressPage({ params }: { params: Promise<{ siteId: string }> }) {
  const { siteId } = await params;
  redirect(`/sites/${encodeURIComponent(siteId)}/spatial-assets`);
}
