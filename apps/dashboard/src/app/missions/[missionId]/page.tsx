import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { getMission } from "@/lib/core-api/missions";
import { ErrorState } from "@/components/ui/ErrorState";

import { formatCoverageRatio, formatDateTime, formatNullable } from "../format";
import { ARTIFACT_KIND_LABEL, MISSION_TYPE_LABEL, ROUTE_PATTERN_LABEL } from "../mission-labels";

export default async function MissionDetailPage({
  params,
}: {
  params: Promise<{ missionId: string }>;
}) {
  const { missionId } = await params;

  let mission;
  try {
    mission = await getMission(missionId);
  } catch (error) {
    if (error instanceof CoreApiError) {
      if (error.status === 404) notFound();
      return (
        <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
          <BackLink />
          <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
        </div>
      );
    }
    throw error;
  }

  const fields: Array<{ label: string; value: ReactNode }> = [
    { label: "임무 ID", value: <span className="font-mono break-keep">{mission.missionId}</span> },
    {
      label: "현장",
      value: (
        <Link
          href={`/sites/${encodeURIComponent(mission.siteId)}`}
          className="break-keep underline decoration-foreground/30 underline-offset-2 hover:decoration-foreground"
        >
          {mission.siteId}
        </Link>
      ),
    },
    { label: "임무 유형", value: MISSION_TYPE_LABEL[mission.missionType] },
    { label: "산출물 종류", value: ARTIFACT_KIND_LABEL[mission.artifactKind] },
    {
      label: "KMZ SHA-256",
      value: mission.kmzSha256 ? (
        <span className="font-mono text-xs break-all">{mission.kmzSha256}</span>
      ) : (
        "—"
      ),
    },
    {
      label: "경로 패턴",
      value: mission.routePattern ? ROUTE_PATTERN_LABEL[mission.routePattern] : "—",
    },
    { label: "웨이포인트 수", value: formatNullable(mission.waypointCount) },
    { label: "커버리지", value: formatCoverageRatio(mission.coverageRatio) },
    { label: "발급 일시", value: formatDateTime(mission.issuedAt) },
    { label: "발급자", value: mission.issuedBy },
  ];

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
      <BackLink />
      <h1 className="text-lg font-semibold break-keep">임무 상세</h1>
      <dl className="divide-y divide-black/10 rounded-lg border border-black/10 dark:divide-white/10 dark:border-white/10">
        {fields.map((field) => (
          <div
            key={field.label}
            className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-baseline sm:gap-4"
          >
            <dt className="text-foreground/60 shrink-0 text-sm break-keep sm:w-40">
              {field.label}
            </dt>
            <dd className="text-sm break-keep">{field.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/missions"
      className="text-foreground/60 hover:text-foreground inline-flex min-h-11 items-center text-sm break-keep underline decoration-foreground/30 underline-offset-2"
    >
      ← 임무 목록으로
    </Link>
  );
}
