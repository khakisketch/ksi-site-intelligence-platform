/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WizardShell } from "@/components/wizard/WizardShell";

afterEach(() => cleanup());

describe("wizard draft status", () => {
  it("does not claim auto-save when the caller reports a write failure", () => {
    render(
      <WizardShell
        title="현장 등록"
        layout="steps"
        stepLabels={["기본정보", "범위", "확인"]}
        currentStep={0}
        onNext={() => {}}
        draftStatusText="입력을 자동 저장하지 못했습니다"
      >
        <p>입력</p>
      </WizardShell>,
    );
    expect(screen.getAllByText(/입력을 자동 저장하지 못했습니다/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/입력 내용은 자동 저장됩니다/)).toBeNull();
  });
});
