export type Json = any;

const BASE = "";

async function req(path: string, init?: RequestInit): Promise<Json> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const text = await r.text();
  let body: Json = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text };
  }
  if (!r.ok && r.status !== 409) {
    throw new Error(body?.detail || body?.message || `HTTP ${r.status}`);
  }
  return { ...body, __status: r.status };
}

export const api = {
  health: () => req("/api/health"),
  meta: () => req("/api/meta"),
  overview: () => req("/api/overview"),
  agents: () => req("/api/agents"),
  search: (q: string) => req(`/api/search?q=${encodeURIComponent(q)}`),
  seed: () => req("/api/seed", { method: "POST" }),
  entities: (q = "") => req(`/api/entities?q=${encodeURIComponent(q)}`),
  documents: (id: string) => req(`/api/entities/${encodeURIComponent(id)}/documents`),
  createRun: (body: Json, idem?: string) =>
    req("/api/runs", {
      method: "POST",
      body: JSON.stringify(body),
      headers: idem ? { "Idempotency-Key": idem } : {},
    }),
  run: (id: string) => req(`/api/runs/${encodeURIComponent(id)}`),
  reports: () => req("/api/reports"),
  versions: (id: string) => req(`/api/reports/${encodeURIComponent(id)}/versions`),
  version: (id: string, v: number) =>
    req(`/api/reports/${encodeURIComponent(id)}/versions/${v}`),
  provenance: (id: string, v: number) =>
    req(`/api/reports/${encodeURIComponent(id)}/versions/${v}/provenance`),
  evidence: (ref: string) => req(`/api/evidence/${ref}`),
  ask: (id: string, version_no: number, question: string, history: string[] = []) =>
    req(`/api/reports/${encodeURIComponent(id)}/questions`, {
      method: "POST",
      body: JSON.stringify({ version_no, question, history }),
    }),
  preview: (id: string, body: Json) =>
    req(`/api/reports/${encodeURIComponent(id)}/updates/preview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  commit: (id: string, draft: number, body: Json) =>
    req(`/api/reports/${encodeURIComponent(id)}/updates/${draft}/commit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  diff: (id: string, from: number, to: number) =>
    req(`/api/reports/${encodeURIComponent(id)}/diff?from=${from}&to=${to}`),
  document: (id: string) => req(`/api/documents/${encodeURIComponent(id)}`),
  eval: () => req("/api/eval"),
  industries: () => req("/api/industries"),
  industryMatrix: (year = 2025) => req(`/api/industry-matrix?year=${year}`),
  industry: (id: string, years = "2022,2023,2024,2025") =>
    req(`/api/industries/${encodeURIComponent(id)}?years=${years}`),
  chain: (id: string, year = 2025) =>
    req(`/api/industries/${encodeURIComponent(id)}/chain?year=${year}`),
  compare: (field = "revenue", year = 2025) =>
    req(`/api/compare?field=${encodeURIComponent(field)}&year=${year}`),
  llm: () => req("/api/llm"),
  suggest: (id: string, v: number) =>
    req(`/api/reports/${encodeURIComponent(id)}/versions/${v}/suggestions`),
  exportMd: (id: string, v: number) =>
    req(`/api/reports/${encodeURIComponent(id)}/versions/${v}/export`),
};

export function streamRun(
  runId: string,
  onEvent: (e: Json) => void,
  onDone: (e: Json) => void,
): () => void {
  const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  es.addEventListener("stage", (ev) => {
    try {
      onEvent(JSON.parse((ev as MessageEvent).data));
    } catch {}
  });
  es.addEventListener("done", (ev) => {
    try {
      onDone(JSON.parse((ev as MessageEvent).data));
    } catch {}
    es.close();
  });
  es.onerror = () => {
    /* 浏览器自动重连，靠 Last-Event-ID 续传 */
  };
  return () => es.close();
}
