import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GraphsView } from "./GraphsView";

vi.mock("../api", () => ({
  humanizeError: (value: string) => value,
  post: vi.fn(),
  request: async (path: string) => {
    if (path === "/api/graphs") return { graphs: [] };
    if (path === "/api/extensions") return { skills: [], mcp_servers: [] };
    if (path.startsWith("/api/graphs/status")) return {
      state: "running",
      run_id: "run-7",
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
  });

  it("reattaches to the active graph after navigating back", async () => {
    render(<GraphsView profiles={[]} setError={vi.fn()} notify={vi.fn()} />);

    expect(await screen.findByText("Build it")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("Events").parentElement).toHaveTextContent("Events1");
    expect(screen.getByText("job-7")).toBeInTheDocument();
  });
});
