import { NextRequest, NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { sealExternalEvidence } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getSessionToken } from "@/lib/core-api/session";
const ref=/^ers-v1-[0-9a-f]{64}$/;
const evidenceRef=/^eev-v1-[0-9a-f]{64}$/;
export async function POST(request: NextRequest, context:{params:Promise<{workOrderId:string;submissionRef:string;revision:string;evidenceRef:string}>}) { if(isCrossSiteMutation(request))return NextResponse.json({code:"CROSS_SITE_REQUEST"},{status:403});await getSessionToken();const p=await context.params,r=Number(p.revision),k=request.headers.get("idempotency-key")?.trim();if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(p.workOrderId)||!ref.test(p.submissionRef)||!Number.isSafeInteger(r)||r<1||String(r)!==p.revision||!evidenceRef.test(p.evidenceRef)||!k||k.length>255)return NextResponse.json({code:"NOT_FOUND"},{status:404});try{return NextResponse.json(await sealExternalEvidence(p.workOrderId,p.submissionRef,r,p.evidenceRef,k));}catch(e){if(e instanceof CoreApiError)return NextResponse.json({code:e.code},{status:e.status});throw e;} }
