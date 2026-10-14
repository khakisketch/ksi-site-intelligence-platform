import { NextResponse } from "next/server";

import { downloadSpatialDataRequestFile } from "@/lib/core-api/spatial-data-requests";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const REQUEST_ID_PATTERN = /^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; requestId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId, workAreaId, requestId } = await params;
    if (!REQUEST_ID_PATTERN.test(requestId)) {
      return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    }

    const output = await downloadSpatialDataRequestFile(siteId, workAreaId, requestId);
    const coreMediaType = output.contentType.split(";", 1)[0]?.trim().toLowerCase();
    const mediaType = coreMediaType === "image/tiff" ? "image/tiff" : "application/octet-stream";
    const extension = mediaType === "image/tiff" ? "tif" : "bin";

    return new NextResponse(new Blob([output.body]), {
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Disposition": `attachment; filename="spatial-data-${requestId}.${extension}"`,
        "Content-Length": String(output.body.byteLength),
        "Content-Type": mediaType,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
