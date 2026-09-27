#!/usr/bin/env node
// A stand-in for `magent` that follows the machine API contract.
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";

const args = process.argv.slice(2);
if (args[0] === "memory") {
  console.log(JSON.stringify({ ok: true, title: "fix tests", turns: [{ turn: 1, status: "used", nodes: [{ id: "prefers_pytest", score: 0.9, matched: ["body"], source: "team" }], tokens: { injected: 120, budget: 4000 } }] }));
  process.exit(0);
}
const prompt = readFileSync(args[args.indexOf("--prompt-file") + 1], "utf8");
if (prompt.includes("slow")) {
  setTimeout(() => {}, 60000);
} else {
  console.error("📚 Loaded 3 skills");
  const request = { aais: "1.0", type: "approval.requested", sequence: 1, request: { id: "apr_1", action_digest: "sha256:abc", action: { name: "shell.exec", summary: "Run: npm test", arguments: { command: "npm test" } }, risk: { level: "medium", reasons: ["Executes a process"] }, choices: [{ decision: "approve", scope: "once", label: "Allow once" }, { decision: "deny", scope: "once", label: "Deny" }] } };
  console.log(JSON.stringify(request));
  const lines = createInterface({ input: process.stdin });
  lines.on("line", (line) => {
    const decided = JSON.parse(line);
    const answer = decided.decision.decision;
    console.log(JSON.stringify({ aais: "1.0", type: "approval.resolved", sequence: 2, resolution: { request_id: "apr_1", outcome: answer === "approve" ? "approved" : "denied" } }));
    console.log(JSON.stringify({ ok: true, response: `You said ${prompt.length} chars; decision ${answer}; actor ${decided.decision.actor.authenticated_by}`, memory_evidence: [] }, null, 2));
    process.exit(0);
  });
}
