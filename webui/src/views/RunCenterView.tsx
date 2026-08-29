import { useEffect, useRef, useState } from "react";
import { post, request } from "../api";
import type { Schedule } from "../types";

type RunCenter = {
  chat_runs?: Record<string, unknown>[];
  graph_runs?: Record<string, unknown>[];
  schedules?: Schedule[];
};
type DurableTask = { id?: string; task_id?: string; title?: string; state?: string; status?: string; summary?: string };

export function RunCenterView({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [data, setData] = useState<RunCenter>({});
  const [path, setPath] = useState("");
  const [interval, setIntervalMinutes] = useState(60);
  const [notifications, setNotifications] = useState(() => localStorage.getItem("magent-notifications") === "on");
  const [tasks, setTasks] = useState<DurableTask[]>([]);
  const seenStates = useRef<Record<string, string>>({});

  async function load() {
    try {
      const [center, durable] = await Promise.all([
        request<RunCenter>("/api/run-center"),
        request<{ tasks?: DurableTask[] }>("/api/tasks"),
      ]);
      setData(center);
      setTasks(durable.tasks || []);
      if (notifications && "Notification" in window && Notification.permission === "granted") {
        const records = [...(center.chat_runs || []), ...(center.graph_runs || []), ...(durable.tasks || [])];
        for (const record of records) {
          const fields = record as Record<string, unknown>;
          const id = String(fields.id || fields.run_id || fields.job_id || fields.task_id || "");
          const state = String(fields.state || fields.status || "");
          const before = seenStates.current[id];
          if (id && before && before !== state && ["succeeded", "failed", "cancelled", "completed"].includes(state)) {
            new Notification(`MagAgent ${state}`, { body: String(fields.title || fields.summary || id) });
          }
          if (id) seenStates.current[id] = state;
        }
      }
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notifications]);

  async function schedule() {
    try {
      await post("/api/schedules", { path, interval_minutes: interval });
      setPath("");
      notify("Graph schedule created");
      await load();
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function action(id: string, command: string) {
    try {
      await post("/api/schedules/action", { id, action: command });
      await load();
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function taskAction(task: DurableTask, command: string) {
    const id = task.id || task.task_id || "";
    try {
      await post("/api/tasks/action", { task_id: id, action: command });
      notify(`Task ${command} requested`);
      await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  async function toggleNotifications() {
    if (!("Notification" in window)) {
      setError("This browser does not support desktop notifications.");
      return;
    }
    const enabled = !notifications && (await Notification.requestPermission()) === "granted";
    setNotifications(enabled);
    localStorage.setItem("magent-notifications", enabled ? "on" : "off");
  }

  return (
    <section className="view active page-view">
      <div className="page-head">
        <div><div className="eyebrow">BACKGROUND WORK</div><h1>Run center</h1><p>Monitor chat and graph execution, manage durable tasks, and schedule governed graphs.</p></div>
        <button className="ghost-button" type="button" onClick={() => void toggleNotifications()}>{notifications ? "Notifications on" : "Enable notifications"}</button>
      </div>
      <div className="ops-grid">
        <article className="ops-card"><h3>Chat runs</h3><pre>{JSON.stringify(data.chat_runs || [], null, 2)}</pre></article>
        <article className="ops-card"><h3>Graph runs</h3><pre>{JSON.stringify(data.graph_runs || [], null, 2)}</pre></article>
      </div>
      <article className="detail-card schedule-card">
        <h2>Durable tasks</h2>
        {!tasks.length && <p>No durable execution tasks yet.</p>}
        <div className="schedule-list">
          {tasks.map((task) => {
            const id = task.id || task.task_id || "";
            const state = task.state || task.status || "unknown";
            return <div className="schedule-row" key={id}>
              <div><b>{task.title || id}</b><small>{state}{task.summary ? ` · ${task.summary}` : ""}</small></div>
              <div className="toolbar-row">
                {state === "running" && <button type="button" onClick={() => void taskAction(task, "pause")}>Pause</button>}
                {state === "paused" && <button type="button" onClick={() => void taskAction(task, "resume")}>Resume</button>}
                {!['succeeded', 'cancelled'].includes(state) && <button type="button" onClick={() => void taskAction(task, "cancel")}>Cancel</button>}
                {['failed', 'cancelled'].includes(state) && <button type="button" onClick={() => void taskAction(task, "retry")}>Retry</button>}
              </div>
            </div>;
          })}
        </div>
      </article>
      <article className="detail-card schedule-card">
        <h2>Schedule a graph</h2>
        <p>Schedules run only while this local UI server is active and still pass graph validation and human-gate checks.</p>
        <div className="toolbar-row">
          <input aria-label="Graph path" value={path} onChange={(event) => setPath(event.target.value)} placeholder="workflows/review.agraph.yaml" />
          <input aria-label="Interval minutes" type="number" min={1} value={interval} onChange={(event) => setIntervalMinutes(Number(event.target.value))} />
          <button className="primary-button" type="button" disabled={!path} onClick={() => void schedule()}>Schedule</button>
        </div>
        <div className="schedule-list">
          {(data.schedules || []).map((item) => (
            <div className="schedule-row" key={item.id}>
              <div><b>{item.path}</b><small>Every {item.interval_minutes} min · {item.status}{item.last_error ? ` · ${item.last_error}` : ""}</small></div>
              <div className="toolbar-row">
                <button type="button" onClick={() => void action(item.id, "run")}>Run now</button>
                <button type="button" onClick={() => void action(item.id, item.status === "active" ? "pause" : "resume")}>{item.status === "active" ? "Pause" : "Resume"}</button>
                <button type="button" onClick={() => void action(item.id, "delete")}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
