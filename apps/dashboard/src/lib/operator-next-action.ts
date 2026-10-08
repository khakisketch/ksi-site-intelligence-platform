import type { ResponsiveAction } from "@/components/responsive/responsive-actions";
import type { SiteView } from "@/lib/core-api/types";

export type OperatorNextActionKind = "SET_SITE_AOI" | "CREATE_OBSERVATION";

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

  if (site.status === "UNMAPPED" && site.aoi === null) {
    if (!permissions.canEditSite) return null;
    return {
      kind: "SET_SITE_AOI",
      label: "현장 범위 설정",
      href: `${siteHref}#site-aoi`,
      responsiveAction: "SITE_DEVICE_TRANSITION",
      siteId: site.siteId,
    };
  }

  if (
    site.aoi !== null &&
    (site.status === "UNMAPPED" || site.status === "REMAP_REQUIRED" || site.status === "MODEL_STALE" || includeRoutineSurvey)
  ) {
    if (!permissions.canCreateWorkOrder) return null;
    return {
      kind: "CREATE_OBSERVATION",
      label: "새 관측 시작",
      href: `${siteHref}/observations/new`,
      responsiveAction: "WORK_ORDERS_WRITE",
      siteId: site.siteId,
    };
  }

  return null;
}
