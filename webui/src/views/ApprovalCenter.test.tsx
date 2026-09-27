import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pushed: { emit?: (items: unknown[]) => void; snapshots: number } = { snapshots: 0 };

vi.mock("../api", () => ({
  request: async () => {
    pushed.snapshots += 1;
    return { snapshot: { pending: [] } };
  },
  post: async () => ({ ok: true }),
  followApprovals: (onSnapshot: (items: unknown[]) => void) => {
    pushed.emit = onSnapshot;
    return new Promise(() => undefined);
  },
}));

import { ApprovalCenter } from "./ApprovalCenter";

const approval = {
  id: "apr_1",
  created_at: "2026-09-27T00:00:00Z",
  origin: { harness: "magagent", session_id: "s1" },
  action: { kind: "tool.call", name: "shell.exec", summary: "Run: npm test", arguments: { command: "npm test" } },
  action_digest: "sha256:abc",
  risk: { level: "medium", reasons: ["Executes a local process"] },
  choices: [
    { decision: "approve", scope: "once", label: "Allow once" },
    { decision: "deny", scope: "once", label: "Deny" },
  ],
};

describe("ApprovalCenter", () => {
  afterEach(cleanup);

  it("shows an approval as soon as the server pushes it, without polling", async () => {
    render(<ApprovalCenter setError={() => undefined} notify={() => undefined} />);
    await vi.waitFor(() => expect(pushed.emit).toBeTypeOf("function"));
    pushed.emit?.([approval]);
    expect(await screen.findByText("Run: npm test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deny" })).toBeInTheDocument();
    // One initial fetch; everything after arrives on the push stream.
    expect(pushed.snapshots).toBe(1);
    pushed.emit?.([]);
    await vi.waitFor(() => expect(screen.queryByText("Run: npm test")).toBeNull());
  });
});
