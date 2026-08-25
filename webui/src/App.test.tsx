import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const READY = { ok: true, ready: true, steps: [], blocking: [] };
const readiness = { current: READY as Record<string, unknown> };

vi.mock("./api", () => ({
  captureLaunchToken: () => "",
  currentToken: () => "",
  post: async () => ({}),
  streamMessage: async () => undefined,
  activeRun: async () => null,
  reattachRun: async () => undefined,
  cancelRun: async () => ({ ok: true }),
  request: async (path: string) => {
    if (path === "/api/onboarding/readiness") return readiness.current;
    if (path === "/api/onboarding/providers") return { providers: [] };
    if (path === "/api/bootstrap") {
      return {
        conversations: [],
        profiles: { profiles: [] },
        settings: { fields: [] },
        project: "/workspace",
      };
    }
    if (path === "/api/conversations") return { conversations: [] };
    return {};
  },
}));

describe("App", () => {
  beforeEach(() => {
    readiness.current = READY;
  });

  // Without this each render stacks in the same document, so a "not present"
  // assertion sees the previous test's markup.
  afterEach(cleanup);

  it("renders the workspace when the machine can run a turn", async () => {
    render(<App />);
    expect(await screen.findByLabelText("Primary navigation")).toBeInTheDocument();
  });

  it("shows setup instead of a composer when no provider works", async () => {
    readiness.current = {
      ok: true,
      ready: false,
      blocking: ["provider"],
      reason: "No provider is configured yet, so a message sent now would fail.",
      steps: [],
    };
    render(<App />);

    expect(await screen.findByText("Set up MagAgent")).toBeInTheDocument();
    // A composer that is guaranteed to fail is worse than saying so.
    expect(document.querySelector(".composer")).toBeNull();
  });

  it("does not hijack the workspace when readiness is unreadable", async () => {
    // Replacing the whole workspace is a strong intervention; an unexpected
    // answer must not trigger it. An earlier version treated any falsy `ready`
    // as a "no", so a malformed 200 sent every user to the setup panel.
    readiness.current = {};
    render(<App />);

    expect(await screen.findByLabelText("Primary navigation")).toBeInTheDocument();
    expect(screen.queryByText("Set up MagAgent")).not.toBeInTheDocument();
  });
});
