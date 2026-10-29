import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { getSpatialTask, getSpatialTaskOptions } from "@/lib/core-api/spatial-tasks";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { isTaskView, selectorKey, spatialTaskError } from "@/lib/spatial-task";
import { SpatialTaskPanel } from "./SpatialTaskPanel";

export const metadata = { title: "작업 범위 선택 · KSI" };

export default async function SpatialTaskPage({ params }: { params: Promise<{ siteId: string; taskId: string }> }) {
  const { siteId, taskId } = await params;
  const next = `/sites/${encodeURIComponent(siteId)}/spatial-tasks/${encodeURIComponent(taskId)}`;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={next} />;
  let loaded: { view: Awaited<ReturnType<typeof getSpatialTask>>; options: Awaited<ReturnType<typeof getSpatialTaskOptions>>; site: Awaited<ReturnType<typeof getSite>>; areas: Awaited<ReturnType<typeof listWorkAreas>> } | null = null;
  let failure: unknown;
  try {
    const view = await getSpatialTask(siteId, taskId);
    if (!isTaskView(view, siteId, taskId)) throw new Error("Invalid task response");
    const [site, firstOptions, areas] = await Promise.all([
      getSite(siteId), getSpatialTaskOptions(siteId, taskId), listWorkAreas(siteId),
    ]);
    let options = firstOptions;
    const inputs = view.task.selection.inputs;
    // Restore the saved exact pair even when it is outside the first candidate page.
    for (let page = 0; inputs && options.nextOffset !== null && page < 16; page += 1) {
      const keys = new Set(options.observations.map((item) => selectorKey(item.selector)));
      if (keys.has(selectorKey(inputs.baseline)) && keys.has(selectorKey(inputs.current))) break;
      const nextPage = await getSpatialTaskOptions(siteId, taskId, options.nextOffset);
      options = { ...nextPage, observations: [...options.observations, ...nextPage.observations] };
    }
    loaded = { view, options, site, areas };
  } catch (error) { failure = error; }
  if (!loaded) {
    const message = failure instanceof CoreApiError ? spatialTaskError(failure.code, failure.status) : "작업을 불러오지 못했습니다. 연결을 확인하고 새로고침하세요.";
    return <div className="mx-auto max-w-5xl p-5"><h1 className="mb-4 text-xl font-bold">작업 범위 선택</h1><ErrorState message={message} retryable={!(failure instanceof CoreApiError) || failure.status >= 500} action={{ label: "현장으로 돌아가기", href: `/sites/${encodeURIComponent(siteId)}` }} /></div>;
  }
  const { view, options, site, areas } = loaded;
  const allowedIds = new Set(options.areas.map((area) => area.workAreaId));
  return <SpatialTaskPanel initialView={view} initialOptions={options}
    siteName={site.name} areas={areas.workAreas.filter((area) => allowedIds.has(area.workAreaId))}
    canWrite={session.principal.permissions.includes("SITES_WRITE")} />;
}
