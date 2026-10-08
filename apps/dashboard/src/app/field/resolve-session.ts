import "server-only";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import type { WhoAmIResponse } from "@/lib/core-api/types";
import { classifyFieldSessionFailure, type FieldSessionFailure, type FieldSessionVerdict } from "./field-session";

export type FieldSession =
  | { kind: "ready"; principal: WhoAmIResponse }
  | { kind: "blocked"; verdict: FieldSessionVerdict };

function toFailure(error: unknown): FieldSessionFailure {
  if (error instanceof MissingSessionError) return { kind: "no-session" };
  if (error instanceof CoreApiError) return { kind: "api", status: error.status };
  return { kind: "unreachable" };
}

export async function resolveFieldSession(): Promise<FieldSession> {
  let principal: WhoAmIResponse;
  try {
    principal = await whoAmI();
  } catch (error) {
    return { kind: "blocked", verdict: classifyFieldSessionFailure(toFailure(error)) };
  }
  if (principal.kind !== "OPERATOR") {
    return {
      kind: "blocked",
      verdict: {
        kind: "login",
        notice: "사람 계정이 아닌 토큰으로 로그인돼 있습니다. 본인 토큰으로 다시 로그인하세요.",
      },
    };
  }
  return { kind: "ready", principal };
}
