import type { ChatEvent } from "./types";

/**
 * Client for the local Web UI API.
 *
 * The server mints a per-launch token, opens the browser at `/?token=...`, and
 * requires it on every request as both an identity header and a CSRF header.
 * That posture is unchanged by the TypeScript port; only the transport code
 * moved.
 */

const AUTH_STORAGE_KEY = "magent-ui-token";

let token = "";

/**
 * Capture the launch token once, then strip it from the address bar so it does
 * not survive in history, bookmarks, or a shared screenshot.
 */
export function captureLaunchToken(): string {
  if (typeof window === "undefined") return "";
  const url = new URL(window.location.href);
  const supplied = url.searchParams.get("token");
  if (supplied) {
    token = supplied;
    try {
      sessionStorage.setItem(AUTH_STORAGE_KEY, supplied);
    } catch {
      /* storage can be blocked; the in-memory copy still works */
    }
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    return token;
  }
  try {
    token = sessionStorage.getItem(AUTH_STORAGE_KEY) || "";
  } catch {
    token = "";
  }
  return token;
}

export function currentToken(): string {
  return token;
}

function headers(json = false): Record<string, string> {
  const result: Record<string, string> = {
    "X-Magent-Token": token,
    "X-Magent-CSRF": token,
  };
  if (json) result["Content-Type"] = "application/json";
  return result;
}

/**
 * Turn a failed response into something a person can act on.
 *
 * The body may only be read once, so it is taken as text and parsed after.
 */
async function responseError(response: Response): Promise<Error> {
  let body = "";
  try {
    body = await response.text();
  } catch {
    body = "";
  }

  let detail = body.trim();
  if (detail.startsWith("{")) {
    try {
      const parsed = JSON.parse(detail) as { error?: string; detail?: string };
      detail = String(parsed.error || parsed.detail || detail);
    } catch {
      /* not JSON after all */
    }
  }

  if (response.status === 403) {
    return new Error(
      "This workspace needs the launch token. Reopen the URL that `magent ui` printed, " +
        "or restart it to mint a new one.",
    );
  }
  if (response.status === 404) return new Error(detail || "That record no longer exists.");
  if (response.status === 405) return new Error(detail || "That action is not allowed here.");
  if (response.status === 409) {
    return new Error(detail || "Someone else changed this first. Reload and try again.");
  }
  if (response.status >= 500) {
    return new Error(detail || "MagAgent hit an internal error. Check the terminal running `magent ui`.");
  }
  return new Error(detail || `${response.status} ${response.statusText}`);
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { ...headers(Boolean(options.body)), ...(options.headers || {}) },
    credentials: "same-origin",
  });
  if (!response.ok) throw await responseError(response);
  const data = (await response.json()) as T & { ok?: boolean; error?: string };
  // The API reports domain failures in the body with ok:false and HTTP 200.
  if (data && data.ok === false) throw new Error(data.error || "Request failed");
  return data;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/**
 * Stream a chat turn. The server writes newline-delimited JSON onto the POST
 * response body; each complete line is one event.
 */
export async function streamMessage(
  conversationId: string,
  content: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/conversations/message", {
    method: "POST",
    headers: headers(true),
    credentials: "same-origin",
    body: JSON.stringify({ conversation_id: conversationId, content }),
    signal,
  });
  if (!response.ok) throw await responseError(response);

  const reader = response.body?.getReader();
  if (!reader) throw new Error("Streaming is unavailable in this browser.");
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    // The trailing element is an incomplete line; keep it for the next read.
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        onEvent(JSON.parse(line) as ChatEvent);
      } catch {
        /* a partial or malformed line is not worth failing the turn over */
      }
    }
    if (done) break;
  }
}
