import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { post } from "../api";
import { GraphsView } from "./GraphsView";

vi.mock("../api", () => ({
  humanizeError: (value: string) => value,
  post: vi.fn(),
  request: async (path: string) => {
    if (path === "/api/graphs") return { graphs: [] };
    if (path === "/api/extensions") return { skills: [], mcp_servers: [] };
    if (path.includes("job_id=job-failed")) return {
      state: "failed",
      run_id: "run-failed",
      activity: "Graph execution finished with status failed.",
      events: [{ type: "graph.completed" }],
      nodes: [{
        id: "inspect",
        title: "Research authoritative sources",
        state: "failed",
        dependencies: [],
        summary: "I have the facts. Now emitting the declared output.",
        error_code: "GRAPH_NODE_FAILED",
        error: "missing required outputs: findings",
        attempts: [{
          attempt: 2,
          status: "criteria_failed",
          error: "missing required outputs: findings",
          criteria: [{ id: "findings_present", passed: false, evidence: "null" }],
        }],
      }],
    };
    if (path.includes("job_id=job-approval")) return {
      state: "running",
      run_id: "run-approval",
      activity: "Waiting for permission: Run npm test",
      events: [{ type: "approval.requested" }],
      nodes: [{ id: "build", title: "Build it", state: "running", dependencies: [] }],
      awaiting_approvals: [{
        request_id: "ask-1",
        description: "Run: `npm test`",
        tier: 2,
        choices: ["once", "session", "always", "deny"],
        node_id: "build",
      }],
    };
    if (path.startsWith("/api/graphs/status")) return {
      state: "running",
      run_id: "run-7",
      activity: "Build it requested the declared tool web_fetch.",
      events: [{ type: "node.started" }],
      nodes: [{ id: "build", title: "Build it", state: "running", dependencies: [] }],
    };
    return {};
  },
}));

describe("GraphsView", () => {
  beforeEach(() => {
    sessionStorage.setItem(
      "magent:last-graph-run",
      JSON.stringify({ job_id: "job-7", run_id: "run-7", path: "work.agraph.yaml" }),
    );
  });
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.mocked(post).mockReset();
  });

  it("reattaches to the active graph after navigating back", async () => {
    render(<GraphsView profiles={[]} setError={vi.fn()} notify={vi.fn()} />);

    expect(await screen.findByText("Build it")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("Events").parentElement).toHaveTextContent("Events1");
    expect(screen.getByText("job-7")).toBeInTheDocument();
    expect(screen.getByText("Most recent activity").parentElement).toHaveTextContent("web_fetch");
    expect(screen.getByText("Run audit log · 1 event")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Run audit log · 1 event"));
    expect(screen.getByText("node.started")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
  });

  it("shows the runtime error and failed criterion instead of only the agent summary", async () => {
    sessionStorage.setItem(
      "magent:last-graph-run",
      JSON.stringify({ job_id: "job-failed", run_id: "run-failed", path: "work.agraph.yaml" }),
    );

    render(<GraphsView profiles={[]} setError={vi.fn()} notify={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "missing required outputs: findings",
    );
    expect(screen.getByText("1 attempt")).toBeInTheDocument();
    expect(screen.getByText(/I have the facts/)).toBeInTheDocument();
  });

  it("answers a graph tool permission without returning to the terminal", async () => {
    sessionStorage.setItem(
      "magent:last-graph-run",
      JSON.stringify({ job_id: "job-approval", run_id: "run-approval", path: "work.agraph.yaml" }),
    );
    vi.mocked(post).mockResolvedValue({ ok: true });

    render(<GraphsView profiles={[]} setError={vi.fn()} notify={vi.fn()} />);

    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Graph card needs your approval");
    expect(screen.getByText("Run: `npm test`")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "For this session" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/graphs/approve", {
      job_id: "job-approval",
      request_id: "ask-1",
      decision: "session",
    }));
  });
});
