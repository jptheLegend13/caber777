import type {
  AgentRole,
  Project,
  ProjectSummary,
  Scene,
  StreamEvent,
  ValidationReport,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail.slice(0, 300)}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () =>
    request<{
      status: string;
      agent_server: { reachable: boolean; version: string | null; url: string };
    }>("/health"),

  listProjects: () => request<{ items: ProjectSummary[] }>("/projects"),

  getProject: (id: string) => request<{ project: Project }>(`/projects/${id}`),

  createProject: (body: { request: string; name?: string; auto_start?: boolean; research?: boolean }) =>
    request<{ project: Project }>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  runProject: (id: string, research?: boolean) =>
    request<{ started: boolean }>(
      `/projects/${id}/run${research === undefined ? "" : `?research=${research}`}`,
      { method: "POST" },
    ),

  cancelProject: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/cancel`, { method: "POST" }),

  followUp: (id: string, message: string) =>
    request<{ sent: boolean; conversation_id: string }>(`/projects/${id}/follow-up`, {
      method: "POST",
      body: JSON.stringify({ message, run: true }),
    }),

  deleteProject: (id: string) =>
    request<{ deleted: boolean }>(`/projects/${id}`, { method: "DELETE" }),

  listFiles: (id: string, path = "") =>
    request<{
      type: string;
      path: string;
      entries?: { name: string; type: string; size: number }[];
      content?: string;
      size?: number;
    }>(`/projects/${id}/files${path ? `?path=${encodeURIComponent(path)}` : ""}`),

  report: (id: string) => request<{ report: string }>(`/projects/${id}/report`),

  agents: () =>
    request<{ count: number; disciplines: Record<string, AgentRole[]> }>("/agents"),

  solve: (problem: string, research = true) =>
    request<{ project_id: string; report: Record<string, unknown> }>("/solve", {
      method: "POST",
      body: JSON.stringify({ problem, research }),
    }),

  buildBuilding: (body: { request: string; name?: string; preferences?: string }) =>
    request<{
      project_id: string;
      title: string;
      validation: ValidationReport | null;
      scene_url: string;
      viewer_url: string;
    }>("/caber/buildings", { method: "POST", body: JSON.stringify(body) }),

  caberScene: (id: string) => request<Scene>(`/projects/${id}/caber/scene`),
  caberValidation: (id: string) => request<ValidationReport>(`/projects/${id}/caber/validation`),

  streamUrl: (id: string) => `${BASE}/projects/${id}/stream`,
};

export function subscribeToProject(
  projectId: string,
  onEvent: (event: StreamEvent) => void,
  onError?: (error: Event) => void,
): () => void {
  const source = new EventSource(api.streamUrl(projectId));
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as StreamEvent);
    } catch {
      /* ignore malformed frames */
    }
  };
  if (onError) source.onerror = onError;
  return () => source.close();
}
