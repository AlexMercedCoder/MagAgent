/**
 * MagAgent for VS Code: a thin bridge over MagAgent's machine API (see client.ts).
 *
 * - "MagAgent: Ask" runs a task in the workspace folder and streams status to
 *   the MagAgent output channel; the reply opens as a Markdown document.
 * - Approvals the run asks for appear as modal prompts with the exact action.
 * - "MagAgent: Show Memory Used by Last Run" shows which memories it recalled.
 */
import * as vscode from "vscode";
import { AskRun, type ApprovalRequest, type Choice, memoryEvidence, renderEvidence } from "./client";

let active: AskRun | undefined;

function options(): { executable: string; cwd: string; permissionMode: string } | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    void vscode.window.showErrorMessage("Open a folder first: MagAgent runs in a project directory.");
    return undefined;
  }
  const config = vscode.workspace.getConfiguration("magagent");
  return {
    executable: config.get<string>("executable", "magent"),
    cwd: folder.uri.fsPath,
    permissionMode: config.get<string>("permissionMode", "balanced"),
  };
}

async function askApproval(request: ApprovalRequest): Promise<Choice | undefined> {
  const { action, risk, choices } = request.request;
  const detail = [
    action.summary,
    `Risk: ${risk.level}. ${risk.reasons.join(" ")}`,
    action.arguments ? `Arguments: ${JSON.stringify(action.arguments)}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
  const labels = choices.map((choice) => choice.label);
  // Escape (undefined) leaves the answer to the fallback: deny, never approve.
  const picked = await vscode.window.showWarningMessage(`MagAgent wants to run ${action.name}`, { modal: true, detail }, ...labels);
  return choices.find((choice) => choice.label === picked);
}

async function run(prompt: string, output: vscode.OutputChannel): Promise<void> {
  const settings = options();
  if (!settings || !prompt.trim()) return;
  if (active) {
    void vscode.window.showWarningMessage("A MagAgent run is already in progress. Cancel it first.");
    return;
  }
  const current = new AskRun(settings);
  active = current;
  output.show(true);
  output.appendLine(`> ${prompt.split("\n")[0]}`);
  try {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "MagAgent is working", cancellable: true },
      (_progress, token) => {
        token.onCancellationRequested(() => current.cancel());
        return current.start(prompt, { onApproval: askApproval, onStatus: (line) => output.appendLine(line) });
      },
    );
    const used = (result.memory_evidence ?? []).filter((turn) => turn.status === "used").flatMap((turn) => turn.nodes.map((node) => node.id));
    output.appendLine(used.length ? `Memory used: ${used.join(", ")}` : "No memory was recalled.");
    const document = await vscode.workspace.openTextDocument({ language: "markdown", content: result.response });
    await vscode.window.showTextDocument(document, { preview: true });
  } catch (error) {
    void vscode.window.showErrorMessage(`MagAgent: ${(error as Error).message}`);
  } finally {
    active = undefined;
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("MagAgent");
  context.subscriptions.push(
    output,
    vscode.commands.registerCommand("magagent.ask", async () => {
      const prompt = await vscode.window.showInputBox({ prompt: "Ask MagAgent", placeHolder: "Fix the failing test in parser.py" });
      if (prompt) await run(prompt, output);
    }),
    vscode.commands.registerCommand("magagent.askAboutSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      const selection = editor?.document.getText(editor.selection) ?? "";
      if (!selection) {
        void vscode.window.showInformationMessage("Select some code first.");
        return;
      }
      const question = await vscode.window.showInputBox({ prompt: "What should MagAgent do with the selection?" });
      if (!question) return;
      const where = editor ? vscode.workspace.asRelativePath(editor.document.uri) : "the selection";
      await run(`${question}\n\nFrom ${where}:\n\n\`\`\`\n${selection}\n\`\`\``, output);
    }),
    vscode.commands.registerCommand("magagent.cancel", () => {
      if (!active?.cancel()) void vscode.window.showInformationMessage("No MagAgent run is in progress.");
    }),
    vscode.commands.registerCommand("magagent.memoryUsed", async () => {
      const settings = options();
      if (!settings) return;
      try {
        const payload = await memoryEvidence(settings);
        const document = await vscode.workspace.openTextDocument({ language: "markdown", content: renderEvidence(payload) });
        await vscode.window.showTextDocument(document, { preview: true });
      } catch (error) {
        void vscode.window.showErrorMessage(`MagAgent: ${(error as Error).message}`);
      }
    }),
  );
}

export function deactivate(): void {
  active?.cancel();
}
