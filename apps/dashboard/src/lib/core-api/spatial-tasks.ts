import "server-only";

import { coreFetch } from "./client";
import type { SpatialTaskOptions, SpatialTaskView } from "../spatial-task";

export function taskPath(siteId: string, taskId: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/spatial-tasks/${encodeURIComponent(taskId)}`;
}

export function getSpatialTask(siteId: string, taskId: string): Promise<SpatialTaskView> {
  return coreFetch(taskPath(siteId, taskId));
}

export function getSpatialTaskOptions(siteId: string, taskId: string, offset = 0): Promise<SpatialTaskOptions> {
  return coreFetch(`${taskPath(siteId, taskId)}/options`, { query: { offset } });
}

export function spatialTaskAction(siteId: string, taskId: string, action: "selection" | "readiness" | "run", body: unknown): Promise<SpatialTaskView> {
  return coreFetch(`${taskPath(siteId, taskId)}/${action}`, { method: "POST", body });
}
