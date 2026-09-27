/**
 * MagAgent's stable machine API, without any VS Code dependency.
 *
 * A run is `magent ask --prompt-file <file> --json --events --approval-stdio`:
 * stdout carries AAIS NDJSON envelopes and then one result document; decisions
 * go back as `approval.decided` lines on stdin. Memory evidence comes from
 * `magent memory evidence <task|last> --json`.
 */
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export type Choice = { decision: "approve" | "deny" | "cancel"; scope: "once" | "session" | "persistent"; label: string };

export type ApprovalRequest = {
  aais: "1.0";
  type: "approval.requested";
  sequence: number;
  request: {
    id: string;
    action_digest: string;
    action: { name: string; summary: string; arguments?: Record<string, unknown> };
    risk: { level: string; reasons: string[] };
    choices: Choice[];
  };
};

export type MemoryNode = { id: string; type?: string; score?: number | null; matched?: string[]; source?: string };
export type MemoryTurn = { turn: number; status: string; nodes: MemoryNode[]; tokens: { injected?: number; budget?: number }; truncated?: boolean };

export type AskResult = {
  ok: boolean;
  response: string;
  session_id?: string;
  execution_task_id?: string;
  memory_evidence?: MemoryTurn[];
  audit?: Record<string, unknown>;
};

export type RunHandlers = {
  onApproval(request: ApprovalRequest): Promise<Choice | undefined>;
  onStatus?(line: string): void;
};

export type MagentOptions = { executable: string; cwd: string; permissionMode?: string };

export function decisionEnvelope(request: ApprovalRequest, choice: Choice, actorId: string, sequence: number): Record<string, unknown> {
  const now = new Date().toISOString();
  return {
    aais: "1.0",
    type: "approval.decided",
    id: `evt_${randomUUID().replaceAll("-", "")}`,
    occurred_at: now,
    sequence,
    decision: {
      id: `dec_${randomUUID().replaceAll("-", "")}`,
      request_id: request.request.id,
      action_digest: request.request.action_digest,
      decided_at: now,
      decision: choice.decision,
      scope: choice.scope,
      actor: { id: actorId, type: "human", authenticated_by: "vscode" },
    },
  };
}

/** Split a byte stream into complete lines. */
export class LineBuffer {
  private pending = "";
  push(chunk: string): string[] {
    this.pending += chunk;
    const lines = this.pending.split("\n");
    this.pending = lines.pop() ?? "";
    return lines.filter((line) => line.trim().length > 0);
  }
  flush(): string[] {
    const rest = this.pending.trim();
    this.pending = "";
    return rest ? [rest] : [];
  }
}

export class AskRun {
  private child?: ChildProcessWithoutNullStreams;
  private decisions = 0;
  private cancelled = false;

  constructor(private readonly options: MagentOptions) {}

  /** Start the run and resolve with the result document. */
  async start(prompt: string, handlers: RunHandlers, actorId = "vscode-user"): Promise<AskResult> {
    const folder = mkdtempSync(join(tmpdir(), "magagent-vscode-"));
    const promptFile = join(folder, "prompt.md");
    writeFileSync(promptFile, prompt, { encoding: "utf8", mode: 0o600 });
    const args = ["ask", "--prompt-file", promptFile, "--project", this.options.cwd, "--json", "--events", "--approval-stdio"];
    if (this.options.permissionMode) args.push("--permission-mode", this.options.permissionMode);
    const [command, ...prefix] = this.options.executable.split(" ");
    const child = spawn(command, [...prefix, ...args], { cwd: this.options.cwd, env: { ...process.env, NO_COLOR: "1" } });
    this.child = child;
    const stdout = new LineBuffer();
    let stderr = "";
    let result: AskResult | undefined;
    const approvals: Promise<void>[] = [];

    // `--json` prints the result on one line when stdout is not a terminal;
    // older MagAgent versions pretty-printed it, so collect those lines too.
    const unparsed: string[] = [];
    const handle = (line: string) => {
      let value: unknown;
      try {
        value = JSON.parse(line);
      } catch {
        unparsed.push(line);
        return;
      }
      if (!value || typeof value !== "object") return;
      const record = value as Record<string, unknown>;
      if (record.type === "approval.requested") {
        const request = record as unknown as ApprovalRequest;
        approvals.push(
          handlers.onApproval(request).then((choice) => {
            const picked = choice ?? request.request.choices.find((item) => item.decision !== "approve") ?? { decision: "deny", scope: "once", label: "Deny" };
            this.decisions += 1;
            child.stdin.write(JSON.stringify(decisionEnvelope(request, picked, actorId, this.decisions)) + "\n");
          }),
        );
      } else if (record.type === "approval.resolved") {
        handlers.onStatus?.(`Approval ${(record.resolution as { outcome?: string })?.outcome ?? "resolved"}`);
      } else if ("response" in record && "ok" in record) {
        result = record as unknown as AskResult;
      }
    };

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => stdout.push(chunk).forEach(handle));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
      for (const line of chunk.split("\n")) if (line.trim()) handlers.onStatus?.(line.trim());
    });

    const status = await new Promise<number | null>((resolve, reject) => {
      child.on("error", reject);
      child.on("close", resolve);
    }).finally(() => rmSync(folder, { recursive: true, force: true }));
    stdout.flush().forEach(handle);
    if (!result && unparsed.length) {
      const text = unparsed.join("\n");
      const start = text.indexOf("{");
      try {
        const value = JSON.parse(text.slice(start)) as Record<string, unknown>;
        if ("response" in value) result = value as unknown as AskResult;
      } catch {
        /* reported below */
      }
    }
    await Promise.allSettled(approvals);
    if (this.cancelled) throw new Error("The run was cancelled.");
    if (!result) {
      throw new Error(`magent exited with status ${status} and no result. ${stderr.trim().split("\n").slice(-3).join(" ")}`.trim());
    }
    return result;
  }

  cancel(): boolean {
    if (!this.child || this.child.exitCode !== null) return false;
    this.cancelled = true;
    this.child.stdin.end();
    this.child.kill("SIGTERM");
    return true;
  }
}

/** `magent memory evidence <task|last> --json` */
export async function memoryEvidence(options: MagentOptions, task = "last"): Promise<Record<string, unknown>> {
  const [command, ...prefix] = options.executable.split(" ");
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...prefix, "memory", "evidence", task, "--json"], { cwd: options.cwd, env: { ...process.env, NO_COLOR: "1" } });
    let out = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => (out += chunk));
    child.on("error", reject);
    child.on("close", () => {
      const start = out.indexOf("{");
      try {
        resolve(JSON.parse(out.slice(start)));
      } catch {
        reject(new Error("magent returned no memory evidence JSON."));
      }
    });
  });
}

/** Markdown for a memory-evidence payload (used by the "Memory used" view). */
export function renderEvidence(payload: Record<string, unknown>): string {
  if (!payload.ok) return `**No memory evidence.** ${String(payload.error ?? "")}\n\n${String(payload.hint ?? "")}`;
  const turns = (payload.turns as MemoryTurn[]) ?? [];
  const lines = [`# Memory used by ${String(payload.title || payload.task_id || "the last run")}`, ""];
  for (const turn of turns) {
    lines.push(`## Turn ${turn.turn}: ${turn.status === "used" ? "recalled memory" : turn.status.replaceAll("_", " ")}`);
    if (turn.status === "used") {
      lines.push(`~${turn.tokens.injected ?? 0} of ${turn.tokens.budget ?? 0} tokens${turn.truncated ? " (truncated)" : ""}`, "");
      lines.push("| Node | Source | Score | Matched |", "| --- | --- | --- | --- |");
      for (const node of turn.nodes) {
        lines.push(`| \`${node.id}\` | ${node.source ?? "personal"} | ${typeof node.score === "number" ? node.score.toFixed(2) : "–"} | ${(node.matched ?? []).join(", ")} |`);
      }
    }
    lines.push("");
  }
  return lines.join("\n");
}
