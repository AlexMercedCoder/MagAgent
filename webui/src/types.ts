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
  depends_on?: string[];
  profile?: string;
  /** pending | running | succeeded | failed | skipped | cancelled */
  state?: string;
  summary?: string;
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
  request_id: string;
  description: string;
  tier: number;
};

export type ChatEvent =
  | ({ type: "run" } & RunSnapshot)
  | ({ type: "approval.requested" } & ApprovalRequest)
  | { type: "approval.resolved"; request_id: string; approved: boolean; reason?: string }
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
