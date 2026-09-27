import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AskRun } from "../src/client";

// Runs against a real MagAgent when MAGENT_REAL_EXECUTABLE is set (for example
// "python -m magent") with a disposable HOME and the offline mock provider in
// scripted mode (MAGENT_MOCK_SCRIPT). Skipped otherwise.
const executable = process.env.MAGENT_REAL_EXECUTABLE;

describe.skipIf(!executable)("real magent", () => {
  it("approves a shell action through the machine API", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "magagent-vscode-real-"));
    const approvals: string[] = [];
    const result = await new AskRun({ executable: `${executable}`, cwd, permissionMode: "balanced" }).start(
      "make the directory",
      {
        onApproval: async (request) => {
          approvals.push(request.request.action.summary);
          return request.request.choices.find((choice) => choice.scope === "once" && choice.decision === "approve");
        },
      },
    );
    expect(approvals.length).toBe(1);
    expect(result.response).toContain("Made the directory");
    expect(existsSync(join(cwd, "from-vscode"))).toBe(true);
  }, 180000);
});
