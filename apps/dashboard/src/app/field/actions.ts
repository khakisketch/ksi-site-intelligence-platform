"use server";

import { revalidatePath } from "next/cache";

import { CoreApiError } from "@/lib/core-api/client";
import { askCopilot } from "@/lib/core-api/copilot";
import { humanizeApiError } from "@/lib/core-api/labels";
import {
  approveObservationWorkOrder,
  approveReobservationDraft,
} from "@/lib/core-api/observation-work-orders";

import type { CopilotActionState, FieldActionState } from "./action-state";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

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
