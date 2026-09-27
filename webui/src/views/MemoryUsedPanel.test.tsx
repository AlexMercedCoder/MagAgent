import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryUsedPanel, evidenceSources } from "./MemoryUsedPanel";

const used = {
  schema: "magent.memory-evidence.v1",
  turn: 1,
  status: "used",
  query_preview: "Which test runner do I like?",
  nodes: [{ id: "prefers_pytest", type: "preference", score: 0.912, matched: ["body"], reason: "keyword" }],
  tokens: { recalled: 120, injected: 100, budget: 400, profile_reserve: 0 },
  truncated: true,
  truncation: ["recall_budget"],
};

describe("MemoryUsedPanel", () => {
  afterEach(cleanup);

  it("explains what to do when no run used memory", () => {
    render(<MemoryUsedPanel sources={[]} />);
    expect(screen.getByRole("heading", { name: "Memory used" })).toBeInTheDocument();
    expect(screen.getByText(/No run has recorded memory use yet/)).toBeInTheDocument();
  });

  it("shows nodes, scores, token cost and truncation for a run", () => {
    const sources = evidenceSources(
      [{ id: "run_abcdef1234567890", state: "succeeded", started_at: 1_790_000_000, memory_evidence: [used] }],
      [],
    );
    render(<MemoryUsedPanel sources={sources} />);
    expect(screen.getByText("prefers_pytest")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
    expect(screen.getByText(/truncated by memory budget/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "About 100 of 400 memory tokens used" })).toBeInTheDocument();
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
  });

  it("switches between runs and durable tasks", () => {
    const sources = evidenceSources(
      [{ id: "run_1", memory_evidence: [used] }],
      [
        { id: "task_1", title: "Nothing recalled", metadata: { memory_evidence: [{ turn: 1, status: "no_match", nodes: [], tokens: {} }] } },
        { id: "task_2", title: "No evidence", metadata: {} },
      ],
    );
    expect(sources.map((item) => item.label)).toEqual(["Chat run 1", "Nothing recalled"]);
    render(<MemoryUsedPanel sources={sources} />);
    fireEvent.change(screen.getByLabelText("Run"), { target: { value: "task:task_1" } });
    expect(screen.getByText("No memory matched")).toBeInTheDocument();
    expect(screen.queryByText("prefers_pytest")).toBeNull();
  });
});
