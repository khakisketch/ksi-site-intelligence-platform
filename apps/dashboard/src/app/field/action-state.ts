import type { CopilotAnswerView } from "@/lib/core-api/types";

export interface FieldActionState {
  status: "idle" | "success" | "error";
  message: string;
}

export interface CopilotActionState extends FieldActionState {
  answer: CopilotAnswerView | null;
}

export const INITIAL_FIELD_ACTION_STATE: FieldActionState = { status: "idle", message: "" };
export const INITIAL_COPILOT_ACTION_STATE: CopilotActionState = {
  status: "idle",
  message: "",
  answer: null,
};
