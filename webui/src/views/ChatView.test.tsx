import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  activeRun: async () => null,
  cancelRun: async () => undefined,
  reattachRun: async () => undefined,
  streamMessage: async () => undefined,
}));

import { ChatView } from "./ChatView";

function renderEmpty() {
  const opened: string[] = [];
  const listener = (event: Event) => opened.push((event as CustomEvent<{ prompt: string }>).detail.prompt);
  window.addEventListener("magent:new-conversation", listener);
  render(
    <ChatView
      active={null}
      refresh={async () => undefined}
      setError={() => undefined}
      notify={() => undefined}
      context={[]}
      clearContext={() => undefined}
    />,
  );
  return { opened, stop: () => window.removeEventListener("magent:new-conversation", listener) };
}

describe("ChatView with no conversation", () => {
  afterEach(cleanup);

  it("opens the New conversation dialog with a starter prompt instead of filling a dead composer", () => {
    const { opened, stop } = renderEmpty();
    fireEvent.click(screen.getByRole("button", { name: "Summarize this project" }));
    expect(opened).toEqual(["Summarize this project"]);
    const composer = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    expect(composer.disabled).toBe(false);
    expect(composer.value).toBe("");
    stop();
  });

  it("typing and pressing Enter starts a conversation with that message", () => {
    const { opened, stop } = renderEmpty();
    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Plan the release" } });
    fireEvent.keyDown(composer, { key: "Enter" });
    expect(opened).toEqual(["Plan the release"]);
    expect((composer as HTMLTextAreaElement).value).toBe("");
    stop();
  });
});
