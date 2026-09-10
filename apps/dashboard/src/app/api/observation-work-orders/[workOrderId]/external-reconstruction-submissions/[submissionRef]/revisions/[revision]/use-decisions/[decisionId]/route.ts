import { NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { getExternalUseDecision } from "@/lib/core-api/external-reconstruction";
import { getSessionToken } from "@/lib/core-api/session";
const ref=/^ers-v1-[0-9a-f]{64}$/;
export async function GET(_request:Request,context:{params:Promise<{workOrderId:string;submissionRef:string;revision:string;decisionId:string}>}) {await getSessionToken();const p=await context.params,r=Number(p.revision);if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(p.workOrderId)||!ref.test(p.submissionRef)||!Number.isSafeInteger(r)||r<1||String(r)!==p.revision||!/^external-use-decision-[0-9a-f]{32}$/.test(p.decisionId))return NextResponse.json({code:"NOT_FOUND"},{status:404});try{return NextResponse.json(await getExternalUseDecision(p.workOrderId,p.submissionRef,r,p.decisionId));}catch(e){if(e instanceof CoreApiError)return NextResponse.json({code:e.code},{status:e.status});throw e;}}
