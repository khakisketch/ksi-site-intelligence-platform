"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { askCopilot } from "@/lib/core-api/copilot";
import { humanizeApiError } from "@/lib/core-api/labels";
import {
  approveObservationWorkOrder,
  approveReobservationDraft,
} from "@/lib/core-api/observation-work-orders";
import { clearSessionToken } from "@/lib/core-api/session";

import type { CopilotActionState, FieldActionState } from "./action-state";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

/**
 * 현장 화면 전용 로그아웃 — 세션만 버리고 **현장 화면 안에 남는다**.
 *
 * `login/actions.ts` 의 `logout()` 은 /login 으로 보낸다. 조종기에서는 그게 두 번
 * 나쁘다: ① 웹뷰가 리다이렉트를 삼키면 로그아웃 후 화면이 멈춘 것처럼 보이고,
 * ② 삼키지 않아도 다음 사람은 로그인한 뒤 /field 를 다시 찾아 들어와야 한다.
 * 조종기는 공용 장비라 "쓰고 넘기기"가 기본 동선이고, 그 동선이 화면 이동 두 번을
 * 요구하면 사람들은 그냥 로그아웃하지 않는다 — 그러면 다음 사람이 앞사람 계정으로
 * 임무를 다룬다.
 *
 * 임무 상세에서 눌러도 목록(/field)으로 보낸다. 로그아웃은 곧 장비를 넘긴다는 뜻이고,
 * 다음 사람이 이어서 볼 화면은 앞사람의 임무가 아니라 자기 임무 목록이다.
 * /field 는 세션이 없으면 인라인 로그인 폼을 그리므로(proxy.ts 의 PUBLIC_PATHS)
 * 그 한 번의 이동으로 "다음 사람 로그인 화면"이 완성된다.
 *
 * 세션 파기 자체는 `clearSessionToken` 하나뿐이다 — 쿠키 이름·속성을 여기서 다시
 * 적지 않는다.
 */
export async function fieldLogout(): Promise<void> {
  await clearSessionToken();
  redirect("/field");
}

export async function approveWorkOrderAction(
  _previous: FieldActionState,
  formData: FormData,
): Promise<FieldActionState> {
  const workOrderId = safeId(formData.get("workOrderId"));
  const expectedVersion = positiveInteger(formData.get("expectedVersion"));
  if (!workOrderId || expectedVersion === null) {
    return { status: "error", message: "작업 정보가 올바르지 않습니다. 화면을 새로 여세요." };
  }
  try {
    await approveObservationWorkOrder(workOrderId, expectedVersion);
    revalidatePath("/field");
    revalidatePath(`/field/work-orders/${workOrderId}`);
    return { status: "success", message: "승인했습니다. 자동 전달 준비 상태를 확인합니다." };
  } catch (error) {
    return actionFailure(error);
  }
}

export async function approveReobservationAction(
  _previous: FieldActionState,
  formData: FormData,
): Promise<FieldActionState> {
  const workOrderId = safeId(formData.get("workOrderId"));
  const draftId = safeId(formData.get("draftId"));
  const expectedVersion = positiveInteger(formData.get("expectedVersion"));
  if (!workOrderId || !draftId || expectedVersion === null) {
    return { status: "error", message: "재관측 초안 정보가 올바르지 않습니다." };
  }
  try {
    await approveReobservationDraft(draftId, expectedVersion);
    revalidatePath("/field");
    revalidatePath(`/field/work-orders/${workOrderId}`);
    return { status: "success", message: "재관측을 승인했습니다. 새 촬영 준비를 시작합니다." };
  } catch (error) {
    return actionFailure(error);
  }
}

export async function askCopilotAction(
  _previous: CopilotActionState,
  formData: FormData,
): Promise<CopilotActionState> {
  const siteId = safeId(formData.get("siteId"));
  const workOrderId = safeId(formData.get("workOrderId"));
  const question = formData.get("question");
  if (!siteId || !workOrderId || typeof question !== "string" || !question.trim()) {
    return { status: "error", message: "질문을 입력하세요.", answer: null };
  }
  if (question.length > 4000) {
    return { status: "error", message: "질문은 4,000자 이하여야 합니다.", answer: null };
  }
  try {
    const answer = await askCopilot({ siteId, workOrderId, question: question.trim() });
    return {
      status: answer.status === "ANSWERED" ? "success" : "error",
      message:
        answer.status === "ANSWERED"
          ? "검증된 현장 자료에서 답을 찾았습니다."
          : "현재 자료만으로는 답할 수 없습니다.",
      answer,
    };
  } catch (error) {
    return { ...actionFailure(error), answer: null };
  }
}

function safeId(value: FormDataEntryValue | null): string | null {
  return typeof value === "string" && SAFE_ID.test(value) ? value : null;
}

function positiveInteger(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : null;
}

function actionFailure(error: unknown): FieldActionState {
  if (error instanceof CoreApiError) {
    return {
      status: "error",
      message: humanizeApiError(error.code, error.status, error.serverMessage),
    };
  }
  return { status: "error", message: "요청을 완료하지 못했습니다. 연결을 확인해 다시 시도하세요." };
}
