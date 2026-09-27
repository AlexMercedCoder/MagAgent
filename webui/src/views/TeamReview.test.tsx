import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls: { posts: unknown[]; inbox: Record<string, unknown> } = { posts: [], inbox: {} };

vi.mock("../api", () => ({
  request: async (path: string) => {
    if (path.startsWith("/api/memory/team/inbox")) return calls.inbox;
    return {
      ok: true,
      id: "p1",
      author: "alice",
      title: "Test runner convention",
      diff: "+Use pytest",
      checks: { ok: true, problems: [] },
    };
  },
  post: async (_path: string, body: unknown) => {
    calls.posts.push(body);
    return { ok: true };
  },
}));

import { TeamReview } from "./TeamReview";

describe("TeamReview", () => {
  afterEach(cleanup);

  it("explains how to set up team memory", async () => {
    calls.inbox = { ok: true, configured: false, proposals: [], note: "No team memory is set up." };
    render(<TeamReview setError={() => undefined} notify={() => undefined} />);
    expect(await screen.findByText("No team memory is set up.")).toBeInTheDocument();
  });

  it("reviews and accepts a teammate's proposal", async () => {
    calls.posts = [];
    calls.inbox = {
      ok: true,
      configured: true,
      user: "bob",
      proposals: [{ id: "p1", author: "alice", title: "Test runner convention", created_at: "", changes: [{ status: "A", path: "nodes/runner.md" }] }],
    };
    render(<TeamReview setError={() => undefined} notify={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: /Test runner convention/ }));
    expect(await screen.findByText(/Checks passed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept and merge" }));
    await vi.waitFor(() => expect(calls.posts).toEqual([{ id: "p1", decision: "accept", reason: "" }]));
  });

  it("does not let authors accept their own proposal", async () => {
    calls.inbox = {
      ok: true,
      configured: true,
      user: "alice",
      proposals: [{ id: "p1", author: "alice", title: "Test runner convention", created_at: "", changes: [] }],
    };
    render(<TeamReview setError={() => undefined} notify={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: /Test runner convention/ }));
    expect(await screen.findByRole("button", { name: "Accept and merge" })).toBeDisabled();
  });
});
