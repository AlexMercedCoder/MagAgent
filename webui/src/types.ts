export type Role = "user" | "assistant" | "system";

export type Message = {
  id: string;
  role: Role;
  content: string;
  speaker: string;
  status: "complete" | "streaming" | "error";
  created_at?: string;
  metadata?: Record<string, unknown>;
};

export type Conversation = {
  id: string;
  title: string;
  kind: "chat" | "bot" | "group";
  project: string;
  profiles: string[];
  coordinator?: string;
  permission_mode?: "paranoid" | "balanced" | "silent" | "yolo";
  messages: Message[];
  archived?: boolean;
  updated_at: string;
};

export type Profile = {
  name: string;
  description?: string;
  revision?: number;
  source?: string;
  trust?: string;
  encoding?: string;
  legacy?: boolean;
  spec_digest?: string;
  profile_digest?: string;
  resolution_digest?: string;
};

export type SettingField = {
  /** Dotted config path, e.g. "defaults.provider". */
  path: string;
  label: string;
  value: string | number | boolean | null;
  type?: string;
  scope?: string;
  category?: string;
  description?: string;
  choices?: string[];
};

export type GraphSummary = { path: string; name?: string };

export type GraphPlan = {
  ok?: boolean;
  graph?: string;
  title?: string;
  nodes?: GraphNode[];
  node_count?: number;
  max_parallel?: number;
  projected_cost_usd?: number;
  gates?: string[];
  error?: string;
};

export type GraphNode = {
  id: string;
  title: string;
  type: string;
  description?: string;
  depends_on?: string[];
  profile?: string;
  tools?: string[];
  /** pending | running | succeeded | failed | skipped | cancelled */
  state?: string;
  summary?: string;
  error?: string;
  error_code?: string;
  attempts?: Array<{
    attempt?: number;
    status?: string;
    error?: string;
    criteria?: Array<{ id?: string; passed?: boolean; evidence?: unknown }>;
  }>;
  files_changed?: number;
};

export type GraphRun = {
  status?: string;
  nodes?: GraphNode[];
  error?: string;
};

export type Bootstrap = {
  ok: boolean;
  csrf_token?: string;
  project?: string;
  project_path?: string;
  username?: string;
  permission_mode?: string;
  error?: string;
};

/** Streamed chat events, one JSON object per line. */
export type RunState = "running" | "succeeded" | "failed" | "cancelled";

export type RunSnapshot = {
  id: string;
  conversation_id: string;
  state: RunState;
  cursor: number;
  started_at?: number;
  finished_at?: number | null;
  error?: string;
};

export type ApprovalRequest = {
  id: string;
  action: {
    name: string;
    summary: string;
    arguments: Record<string, unknown>;
  };
  choices: Array<{ decision: "approve" | "deny" | "cancel"; scope: "once" | "session" | "persistent"; label: string }>;
};

export type ChatEvent =
  | ({ type: "run" } & RunSnapshot)
  | { type: "approval.requested"; aais: "1.0"; request: ApprovalRequest; sequence: number }
  | { type: "approval.resolved"; aais: "1.0"; resolution: { request_id: string; outcome: string; message: string }; sequence: number }
  | { type: "chunk"; speaker: string; content: string }
  | { type: "done"; conversation: Conversation }
  | { type: "conversation"; conversation: Conversation }
  | { type: "cancelled" }
  | { type: "error"; error: string; kind?: string; action?: string; detail?: string };

export type WorkspaceFile = {
  path: string;
  name: string;
  size: number;
  mime: string;
  artifact?: boolean;
};

export type Schedule = {
  id: string;
  path: string;
  interval_minutes: number;
  status: "active" | "paused";
  next_run_at?: number;
  last_run_at?: number | null;
  last_job_id?: string;
  last_error?: string;
};
