import type {
  AgentRole,
  Attachment,
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
      intelligence?: {
        internal_inference_ready: boolean;
        external_models_enabled: boolean;
        dev_gateway_enabled: boolean;
        production_target: string;
      };
    }>("/health"),

  intelligence: () =>
    request<{
      gateway: {
        independence: {
          external_models_enabled: boolean;
          dev_gateway_enabled: boolean;
          production_backend_class: string;
          external_fallback_on_internal_failure: boolean;
        };
        permitted_order: string[];
        backends: {
          name: string;
          class: string;
          model: string;
          permitted: boolean;
          key_policy: string;
        }[];
      };
      self_hosted_runtime: {
        engine_installed: boolean;
        serving: boolean;
        models_registered: number;
        note: string;
      };
      memory: { backend: string; model_required: boolean };
      model_free_fallbacks: { understanding: boolean; planning: boolean };
    }>("/intelligence"),

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

  revisions: (id: string) =>
    request<{
      items: {
        sha: string;
        short: string;
        message: string;
        committed_at: string;
        files_changed: number;
      }[];
      count: number;
    }>(`/projects/${id}/revisions`),

  revisionDiff: (id: string, sha: string) =>
    request<{ sha: string; diff: string }>(`/projects/${id}/revisions/${sha}/diff`),

  restoreRevision: (id: string, sha: string, run = false) =>
    request<{ restored: boolean; sha: string; rerunning: boolean }>(
      `/projects/${id}/restore`,
      { method: "POST", body: JSON.stringify({ sha, run }) },
    ),

  exportUrl: (id: string) => `${BASE}/projects/${id}/export`,

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

  previewStatus: (id: string) =>
    request<{
      available: boolean;
      preview_url: string | null;
      package_dir: string | null;
      build: { status: string; name: string; message?: string } | null;
    }>(`/projects/${id}/preview/status`),

  listAttachments: (id: string) =>
    request<{ items: Attachment[] }>(`/projects/${id}/attachments`),

  uploadAttachment: async (id: string, file: File): Promise<{ attachment: Attachment }> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${BASE}/projects/${id}/attachments`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`${response.status}: ${detail.slice(0, 300)}`);
    }
    return (await response.json()) as { attachment: Attachment };
  },

  deleteAttachment: (id: string, attachmentId: string) =>
    request<{ deleted: boolean }>(`/projects/${id}/attachments/${attachmentId}`, {
      method: "DELETE",
    }),

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
