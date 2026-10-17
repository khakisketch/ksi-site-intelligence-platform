import type { ResponsiveAction } from "@/components/responsive/responsive-actions";
import type { SiteView } from "@/lib/core-api/types";

export type OperatorNextActionKind = "MANAGE_WORK_AREAS" | "CREATE_OBSERVATION";

export interface OperatorNextAction {
  kind: OperatorNextActionKind;
  label: string;
  href: string;
  responsiveAction: ResponsiveAction;
  siteId: string;
}

interface SiteActionPermissions {
  canEditSite: boolean;
  canCreateWorkOrder: boolean;
}

/** Returns only actions backed by mounted site and observation-work-order routes. */
export function resolveSiteOperatorNextAction(
  site: SiteView,
  permissions: SiteActionPermissions,
  { includeRoutineSurvey = false }: { includeRoutineSurvey?: boolean } = {},
): OperatorNextAction | null {
  const siteHref = `/sites/${encodeURIComponent(site.siteId)}`;

  if (
    (site.status === "UNMAPPED" || site.status === "REMAP_REQUIRED" || site.status === "MODEL_STALE" || includeRoutineSurvey)
    && permissions.canCreateWorkOrder
  ) {
    return {
      kind: "CREATE_OBSERVATION",
      label: "관측 자료 등록",
      href: `${siteHref}/observations/new`,
      responsiveAction: "WORK_ORDERS_WRITE",
      siteId: site.siteId,
    };
  }

  if (permissions.canEditSite && site.status === "UNMAPPED") {
    return {
      kind: "MANAGE_WORK_AREAS",
      label: "작업구역 설정",
      href: `${siteHref}/work-areas`,
      responsiveAction: "SITE_DEVICE_TRANSITION",
      siteId: site.siteId,
    };
  }

  return null;
}
