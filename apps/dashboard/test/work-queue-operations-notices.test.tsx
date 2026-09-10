/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { WorkQueueOperationsNotices } from "@/app/field/WorkQueueOperationsNotices";

it("renders linked deadline and my-work notices without another principal name", () => {
  render(<WorkQueueOperationsNotices notices={[{
    workOrder: { workOrderId: "work-1", name: "동측 절성토 확인" },
    operations: { dueAt: "2026-09-10T02:00:00Z" },
    overdue: true,
    dueSoon: false,
    assignedToMe: true,
  }]} />);

  expect(screen.getByRole("link", { name: /동측 절성토 확인/ }).getAttribute("href")).toBe("/field/work-orders/work-1");
  expect(screen.getByText("마감 지남")).toBeTruthy();
  expect(screen.getByText("내 작업")).toBeTruthy();
  expect(screen.getByText(/마감 · 2026/)).toBeTruthy();
  expect(screen.queryByText("operator-1")).toBeNull();
});
