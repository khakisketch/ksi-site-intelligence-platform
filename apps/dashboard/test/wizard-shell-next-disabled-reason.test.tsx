// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WizardShell } from "@/components/wizard/WizardShell";

afterEach(cleanup);

describe("WizardShell next-disabled reason (F16)", () => {
  it("names what blocks the disabled next button when a reason is given", () => {
    render(
      <WizardShell
        title="테스트 위저드"
        stepLabels={["1단계"]}
        currentStep={0}
        onNext={() => {}}
        nextDisabled
        nextDisabledReason="현장 이름을 입력하세요."
      >
        <p>내용</p>
      </WizardShell>,
    );
    expect(screen.getByText("현장 이름을 입력하세요.")).toBeTruthy();
  });

  it("shows no reason text when the next button is enabled", () => {
    render(
      <WizardShell
        title="테스트 위저드"
        stepLabels={["1단계"]}
        currentStep={0}
        onNext={() => {}}
        nextDisabledReason="현장 이름을 입력하세요."
      >
        <p>내용</p>
      </WizardShell>,
    );
    expect(screen.queryByText("현장 이름을 입력하세요.")).toBeNull();
  });
});
