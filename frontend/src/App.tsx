import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, subscribeToProject } from "./api";
import Viewport from "./Viewport";
import { useVoiceInput } from "./useVoiceInput";
import type {
  AgentRole,
  Project,
  ProjectSummary,
  Scene,
  StreamEvent,
  ValidationReport,
} from "./types";

type Tab = "overview" | "research" | "activity" | "files" | "preview" | "tests" | "output";

const DOMAIN_LABEL: Record<string, string> = {
  web_app: "Web application",
  mobile_app: "Mobile application",
  desktop_app: "Desktop application",
  enterprise_software: "Enterprise software",
  backend_api: "Backend API",
  ai_application: "AI application",
  ai_agent: "AI agent",
  multi_agent_system: "Multi-agent system",
  data_system: "Data system",
  cloud_devops: "Cloud / DevOps",
  research: "Research",
  simulation: "Simulation",
  architecture_3d: "Building / 3D",
  design_system: "Design system",
  general: "General",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  planning: "Planning",
  researching: "Researching",
  executing: "Executing",
  testing: "Testing",
  reviewing: "Reviewing",
  repairing: "Repairing",
  delivered: "Delivered",
  failed: "Failed",
  cancelled: "Cancelled",
};

const MODE_HINT: Record<string, string> = {
  draft: "Describe what you want built and LEVEL 5 will plan, research, build and test it.",
  planning: "Central Intelligence is producing the specification and task graph.",
  researching: "Gathering cited evidence before committing to an implementation.",
  executing: "Specialist agents are writing and running real code in the workspace.",
  testing: "Running the project's tests and verifying acceptance criteria.",
  reviewing: "Independent review of the produced work.",
  repairing: "Diagnosing and fixing defects found during verification.",
  delivered: "Delivered. Inspect the files, preview and report below.",
  failed: "Some tasks failed. Review the error reports and re-run or refine.",
  cancelled: "Run cancelled.",
};

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [command, setCommand] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentServer, setAgentServer] = useState<{ reachable: boolean; version: string | null } | null>(null);
  const [activity, setActivity] = useState<StreamEvent[]>([]);
  const [roles, setRoles] = useState<AgentRole[]>([]);
  const [scene, setScene] = useState<Scene | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [selectedPrimitive, setSelectedPrimitive] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"solid" | "wireframe">("solid");
  const [filePath, setFilePath] = useState("");
  const [fileContent, setFileContent] = useState<{ type: string; entries?: any[]; content?: string } | null>(null);
  const [editInstruction, setEditInstruction] = useState("");
  const [preview, setPreview] = useState<{
    available: boolean;
    preview_url: string | null;
    package_dir: string | null;
    build: { status: string; name: string; message?: string } | null;
  } | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const projectIdRef = useRef<string | null>(null);

  useEffect(() => {
    projectIdRef.current = project?.id ?? null;
  }, [project]);

  const appendTranscript = useCallback((text: string) => {
    setCommand((current) => (current ? `${current} ${text}` : text));
  }, []);
  const voice = useVoiceInput(appendTranscript);

  // Initial load ----------------------------------------------------------- //
  useEffect(() => {
    api.health().then((h) => setAgentServer(h.agent_server)).catch(() => setAgentServer(null));
    api.listProjects().then((r) => setProjects(r.items)).catch(() => undefined);
    api
      .agents()
      .then((r) => setRoles(Object.values(r.disciplines).flat()))
      .catch(() => undefined);
  }, []);

  const openProject = useCallback(async (id: string) => {
    setError(null);
    const { project: loaded } = await api.getProject(id);
    setProject(loaded);
    setActivity(loaded.events as unknown as StreamEvent[]);
    setTab("overview");
    setScene(null);
    setValidation(null);
    setFilePath("");
    setFileContent(null);
    if (unsubRef.current) unsubRef.current();
    unsubRef.current = subscribeToProject(id, (event) => {
      setActivity((current) => [...current.slice(-300), event]);
      if (event.kind === "snapshot" && event.project) {
        setProject(event.project);
      } else {
        api
          .getProject(id)
          .then((r) => setProject(r.project))
          .catch(() => undefined);
      }
      // A build result changes whether a preview is available.
      if (event.kind === "build" || event.kind === "delivered" || event.kind === "failed") {
        api.previewStatus(id).then(setPreview).catch(() => undefined);
      }
    });
    // Load any existing 3D scene / validation for CABER projects.
    if (loaded.specification.caber_module === "C" || loaded.specification.domain === "architecture_3d") {
      api.caberScene(id).then(setScene).catch(() => setScene(null));
      api.caberValidation(id).then(setValidation).catch(() => setValidation(null));
    }
    // Load web-app build/preview state for application projects.
    api.previewStatus(id).then(setPreview).catch(() => setPreview(null));
  }, []);

  useEffect(() => () => unsubRef.current?.(), []);

  // Load scene/validation when a CABER project finishes -------------------- //
  useEffect(() => {
    if (!project) return;
    const isCab = project.specification.caber_module === "C" || project.specification.domain === "architecture_3d";
    if (!isCab) return;
    if (project.status === "delivered" || project.status === "reviewing") {
      if (!scene) api.caberScene(project.id).then(setScene).catch(() => undefined);
      if (!validation) api.caberValidation(project.id).then(setValidation).catch(() => undefined);
    }
  }, [project, scene, validation]);

  const refreshList = useCallback(() => {
    api.listProjects().then((r) => setProjects(r.items)).catch(() => undefined);
  }, []);

  const reloadProject = useCallback(() => {
    if (!projectIdRef.current) return;
    api
      .getProject(projectIdRef.current)
      .then((r) => setProject(r.project))
      .catch(() => undefined);
  }, []);

  const submit = useCallback(async () => {
    const text = command.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      // Attachments belong to a project, so a request that carries files is
      // created first, files are uploaded, and only then is execution started.
      const { project: created } = await api.createProject({
        request: text,
        auto_start: pendingFiles.length === 0,
      });
      setCommand("");
      if (pendingFiles.length > 0) {
        setUploading(true);
        for (const file of pendingFiles) {
          await api.uploadAttachment(created.id, file);
        }
        setPendingFiles([]);
        setUploading(false);
        await api.runProject(created.id);
      }
      refreshList();
      await openProject(created.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      setBusy(false);
    }
  }, [command, busy, pendingFiles, openProject, refreshList]);

  const runAgain = useCallback(async () => {
    if (!project) return;
    try {
      await api.runProject(project.id);
      setActivity([]);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [project]);

  const cancel = useCallback(async () => {
    if (!project) return;
    await api.cancelProject(project.id).catch(() => undefined);
  }, [project]);

  const sendEdit = useCallback(async () => {
    if (!project || !editInstruction.trim()) return;
    try {
      await api.followUp(project.id, editInstruction.trim());
      setEditInstruction("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, [project, editInstruction]);

  const loadFile = useCallback(
    async (path: string) => {
      if (!project) return;
      try {
        const result = await api.listFiles(project.id, path);
        setFilePath(result.path);
        setFileContent(result as any);
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [project],
  );

  const roleByTitle = useMemo(() => {
    const map = new Map<string, AgentRole>();
    roles.forEach((role) => map.set(role.name, role));
    return map;
  }, [roles]);

  const isCaber = project?.specification.caber_module === "C" || project?.specification.domain === "architecture_3d";
  const running = project ? ["planning", "researching", "executing", "testing", "reviewing", "repairing"].includes(project.status) : false;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">L5</span>
          <div>
            <div className="brand-title">LEVEL 5</div>
            <div className="brand-sub">Autonomous Engineering Intelligence</div>
          </div>
        </div>
        <div className="topbar-right">
          <span className={`pill ${agentServer?.reachable ? "ok" : "bad"}`}>
            Agent Server {agentServer?.reachable ? `v${agentServer.version}` : "offline"}
          </span>
          <span className="pill muted">{roles.length} specialist roles</span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <button className="new-project" onClick={() => { setProject(null); setActivity([]); setCommand(""); unsubRef.current?.(); }}>
            + New project
          </button>
          <div className="sidebar-heading">Projects</div>
          <ul className="project-list">
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  className={project?.id === p.id ? "active" : ""}
                  onClick={() => openProject(p.id)}
                >
                  <span className="project-name">{p.name}</span>
                  <span className={`dot status-${p.status}`} title={STATUS_LABEL[p.status]} />
                </button>
              </li>
            ))}
            {projects.length === 0 && <li className="empty-note">No projects yet.</li>}
          </ul>
        </aside>

        <main className="main">
          <section className="command-section">
            <div className="command-box">
              <textarea
                value={command}
                placeholder={
                  project
                    ? "Describe a change, or start a new project from the sidebar."
                    : "Build an enterprise task-management app with authentication, roles, analytics and tests.  /  Design a two-storey villa with a pool.  /  Investigate this technical problem…"
                }
                onChange={(event) => setCommand(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit();
                }}
                rows={3}
              />
              <div className="command-actions">
                {voice.supported && (
                  <button
                    className={`mic ${voice.listening ? "listening" : ""}`}
                    onClick={voice.toggle}
                    title={voice.listening ? "Stop dictation" : "Dictate"}
                  >
                    {voice.listening ? "◉ Listening" : "🎙 Voice"}
                  </button>
                )}
                <label className="attach" title="Attach files, images or reference documents">
                  📎 Attach
                  <input
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={(event) => {
                      const files = Array.from(event.target.files ?? []);
                      if (files.length) setPendingFiles((current) => [...current, ...files]);
                      event.target.value = "";
                    }}
                  />
                </label>
                <button className="primary" onClick={submit} disabled={busy || !command.trim()}>
                  {uploading ? "Uploading…" : busy ? "Starting…" : "Run"}
                </button>
              </div>
            </div>
            {pendingFiles.length > 0 && (
              <div className="pending-files">
                {pendingFiles.map((file, index) => (
                  <span className="chip" key={`${file.name}-${index}`}>
                    {file.name}
                    <button
                      onClick={() =>
                        setPendingFiles((current) => current.filter((_, i) => i !== index))
                      }
                      title="Remove"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            {voice.interim && <div className="interim">{voice.interim}</div>}
            {error && <div className="error-banner">{error}</div>}
          </section>

          {project ? (
            <>
              <section className="project-header">
                <div>
                  <h1>{project.name}</h1>
                  <p className="request-line">{project.original_request}</p>
                </div>
                <div className="project-controls">
                  <span className={`status status-${project.status}`}>{STATUS_LABEL[project.status]}</span>
                  {running ? (
                    <button onClick={cancel}>Cancel</button>
                  ) : (
                    <button onClick={runAgain}>Run / Re-run</button>
                  )}
                  <button onClick={() => { refreshList(); }}>Refresh</button>
                </div>
              </section>
              <div className="mode-hint">{MODE_HINT[project.status]}</div>

              <nav className="tabs">
                {(["overview", "research", "activity", "files", "preview", "tests", "output"] as Tab[]).map(
                  (name) => (
                    <button key={name} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>
                      {name}
                    </button>
                  ),
                )}
              </nav>

              {tab === "overview" && <OverviewTab project={project} roleByTitle={roleByTitle} />}
              {tab === "research" && <ResearchTab project={project} />}
              {tab === "activity" && <ActivityTab activity={activity} />}
              {tab === "files" && (
                <FilesTab
                  project={project}
                  filePath={filePath}
                  fileContent={fileContent}
                  onOpen={loadFile}
                />
              )}
              {tab === "preview" &&
                (isCaber ? (
                  <PreviewTab
                    scene={scene}
                    validation={validation}
                    selected={selectedPrimitive}
                    onSelect={(id) => setSelectedPrimitive(id)}
                    viewMode={viewMode}
                    onViewMode={setViewMode}
                    editInstruction={editInstruction}
                    onEditInstruction={setEditInstruction}
                    onSendEdit={sendEdit}
                    viewerUrl={project ? `/api/projects/${project.id}/caber/viewer` : "#"}
                  />
                ) : (
                  <DomainPreview
                    project={project}
                    status={preview}
                    onRefresh={() =>
                      api.previewStatus(project.id).then(setPreview).catch(() => undefined)
                    }
                  />
                ))}
              {tab === "tests" && <TestsTab project={project} />}
              {tab === "output" && <OutputTab project={project} onChanged={reloadProject} />}
            </>
          ) : (
            <section className="welcome">
              <h2>Describe the outcome. LEVEL 5 handles the engineering.</h2>
              <p>
                LEVEL 5 understands the request, researches it, produces a structured specification, plans a
                dependency-aware task graph, allocates specialist agents, writes and runs real code, tests it,
                reviews it, repairs defects and delivers working results.
              </p>
              <div className="examples">
                <ExampleCard
                  title="Application Creation"
                  text="Build an enterprise-grade task-management application with premium UI/UX, authentication, database, user roles, analytics, API docs and automated tests."
                  onUse={setCommand}
                />
                <ExampleCard
                  title="Problem Solving"
                  text="Investigate the trade-offs between exponential backoff and additive-increase multiplicative-decrease for congestion control, and simulate both."
                  onUse={setCommand}
                />
                <ExampleCard
                  title="Building Creation"
                  text="Design a modern two-storey villa with three bedrooms, open-plan living, a study, a terrace and a pool."
                  onUse={setCommand}
                />
                <ExampleCard
                  title="Innovation"
                  text="Investigate a novel self-tuning cache replacement policy that adapts its recency/frequency weighting online, research the prior art, and prototype it to test whether it beats LRU on skewed traces."
                  onUse={setCommand}
                />
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function ExampleCard({ title, text, onUse }: { title: string; text: string; onUse: (t: string) => void }) {
  return (
    <button className="example-card" onClick={() => onUse(text)}>
      <strong>{title}</strong>
      <span>{text}</span>
    </button>
  );
}

function OverviewTab({ project, roleByTitle }: { project: Project; roleByTitle: Map<string, AgentRole> }) {
  const spec = project.specification;
  return (
    <div className="grid two">
      <section className="panel">
        <h3>Specification</h3>
        <dl className="kv">
          <dt>Intent</dt>
          <dd>{spec.intent || "—"}</dd>
          <dt>Deliverable</dt>
          <dd>{spec.deliverable || "—"}</dd>
          <dt>Domain</dt>
          <dd>{spec.domain}</dd>
          <dt>CABER module</dt>
          <dd>{moduleLabel(spec.caber_module)}</dd>
        </dl>
        {spec.summary && <p className="summary">{spec.summary}</p>}

        <h4>Requirements</h4>
        <ul className="requirements">
          {spec.requirements.map((req) => (
            <li key={req.id}>
              <span className={`tag ${req.origin}`}>{req.origin}</span>
              <span className={`tag prio-${req.priority}`}>{req.priority}</span>
              <span>{req.text}</span>
            </li>
          ))}
        </ul>

        {spec.assumptions.length > 0 && (
          <>
            <h4>Assumptions (inferred)</h4>
            <ul className="plain">
              {spec.assumptions.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </>
        )}
        {spec.missing_information.length > 0 && (
          <>
            <h4>Missing information</h4>
            <ul className="plain warn">
              {spec.missing_information.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="panel">
        <h3>Task graph</h3>
        <ul className="task-list">
          {project.task_graph.tasks.map((task) => {
            const role = roleByTitle.get(task.agent_role);
            return (
              <li key={task.id} className={`task task-${task.status}`}>
                <div className="task-head">
                  <span className={`status-dot s-${task.status}`} />
                  <strong>{task.title}</strong>
                  <span className="role">{role?.title ?? task.agent_role}</span>
                </div>
                {task.objective && <p className="task-objective">{task.objective}</p>}
                {task.dependencies.length > 0 && (
                  <div className="task-meta">
                    depends on {task.dependencies.length} task(s) · phase {task.phase}
                  </div>
                )}
                {task.error && <div className="task-error">Error: {task.error}</div>}
                {task.evidence.length > 0 && (
                  <details>
                    <summary>Evidence ({task.evidence.length})</summary>
                    <ul className="plain">
                      {task.evidence.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            );
          })}
          {project.task_graph.tasks.length === 0 && <li className="empty-note">Planning has not started.</li>}
        </ul>

        <h4>Acceptance criteria</h4>
        <ul className="criteria">
          {spec.acceptance_criteria.map((crit) => (
            <li key={crit.id} className={crit.satisfied ? "satisfied" : ""}>
              <span className="check">{crit.satisfied ? "✓" : "○"}</span>
              {crit.statement}
              <em>{crit.verification_method}</em>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ResearchTab({ project }: { project: Project }) {
  if (project.research.length === 0) {
    return (
      <section className="panel">
        <h3>Research</h3>
        <p className="empty-note">
          No research performed for this project yet. Research runs when the specification requires external
          evidence.
        </p>
      </section>
    );
  }
  return (
    <div className="stack">
      {project.research.map((report) => (
        <section className="panel" key={report.id}>
          <h3>{report.question}</h3>
          <div className="research-meta">
            <span className={`tag ${report.status}`}>{report.status}</span>
            <span className="tag muted">{report.method}</span>
            <span className="tag muted">{report.sources.length} sources</span>
          </div>
          {report.summary && <p>{report.summary}</p>}
          {report.findings.length > 0 && (
            <>
              <h4>Findings</h4>
              <ul className="findings">
                {report.findings.map((finding, index) => (
                  <li key={index}>{finding}</li>
                ))}
              </ul>
            </>
          )}
          {report.sources.length > 0 && (
            <>
              <h4>Sources</h4>
              <ul className="sources">
                {report.sources.map((source) => (
                  <li key={source.id}>
                    <span className={`tag evidence-${source.kind}`}>{source.kind}</span>
                    <a href={source.url} target="_blank" rel="noreferrer noopener">
                      {source.title || source.url}
                    </a>
                    <span className="publisher">{source.publisher}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {report.hypotheses.length > 0 && (
            <>
              <h4>Hypotheses</h4>
              <ul className="plain">
                {report.hypotheses.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {report.gaps.length > 0 && (
            <>
              <h4>Gaps &amp; uncertainties</h4>
              <ul className="plain warn">
                {report.gaps.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {report.recommendations.length > 0 && (
            <>
              <h4>Recommendations</h4>
              <ul className="plain">
                {report.recommendations.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      ))}
    </div>
  );
}

function ActivityTab({ activity }: { activity: StreamEvent[] }) {
  const feed = useRef<HTMLDivElement>(null);
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [activity]);
  return (
    <section className="panel">
      <h3>Agent activity</h3>
      <div className="activity-feed" ref={feed}>
        {activity.map((event, index) => (
          <div className={`activity-row kind-${event.kind}`} key={`${event.kind}-${index}`}>
            <span className="activity-kind">{event.kind}</span>
            <span className="activity-message">{String(event.message ?? "")}</span>
            {typeof event.at === "string" && <span className="activity-time">{formatTime(event.at as string)}</span>}
          </div>
        ))}
        {activity.length === 0 && <p className="empty-note">No activity yet.</p>}
      </div>
    </section>
  );
}

function FilesTab({
  project,
  filePath,
  fileContent,
  onOpen,
}: {
  project: Project;
  filePath: string;
  fileContent: { type: string; entries?: any[]; content?: string } | null;
  onOpen: (path: string) => void;
}) {
  return (
    <div className="grid two">
      <section className="panel">
        <h3>Project files</h3>
        <div className="breadcrumb">
          <button onClick={() => onOpen("")}>workspace</button>
          {filePath && <span>/ {filePath}</span>}
        </div>
        {fileContent?.type === "directory" && (
          <ul className="file-list">
            {filePath && (
              <li>
                <button onClick={() => onOpen(filePath.split("/").slice(0, -1).join("/"))}>.. (up)</button>
              </li>
            )}
            {fileContent.entries?.map((entry) => (
              <li key={entry.name}>
                <button onClick={() => onOpen(filePath ? `${filePath}/${entry.name}` : entry.name)}>
                  <span className={`file-icon ${entry.type}`}>{entry.type === "directory" ? "📁" : "📄"}</span>
                  {entry.name}
                  {entry.type === "file" && <span className="file-size">{entry.size} B</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
        <h4>Generated deliverables</h4>
        <ul className="artifact-list">
          {project.artifacts.map((artifact) => (
            <li key={artifact.id}>
              <button onClick={() => onOpen(artifact.path)}>
                <span className="tag muted">{artifact.kind}</span>
                {artifact.path}
                <span className="file-size">{artifact.size_bytes} B</span>
              </button>
            </li>
          ))}
          {project.artifacts.length === 0 && <li className="empty-note">No artifacts recorded yet.</li>}
        </ul>
      </section>
      <section className="panel">
        <h3>File preview</h3>
        {fileContent?.type === "file" ? (
          <pre className="code-view">{fileContent.content}</pre>
        ) : (
          <p className="empty-note">Select a file to view its contents.</p>
        )}
      </section>
    </div>
  );
}

function DomainPreview({
  project,
  status,
  onRefresh,
}: {
  project: Project;
  status: {
    available: boolean;
    preview_url: string | null;
    package_dir: string | null;
    build: { status: string; name: string; message?: string } | null;
  } | null;
  onRefresh: () => void;
}) {
  const domain = project.specification.domain;
  const webDomains = ["web_app", "enterprise_software", "design_system"];
  const backendDomains = [
    "backend_api",
    "data_system",
    "cloud_devops",
    "ai_application",
    "ai_agent",
    "multi_agent_system",
  ];

  // A web application (or an app-like deliverable) gets the real browser preview.
  if (webDomains.includes(domain)) {
    return <WebPreviewTab project={project} status={status} onRefresh={onRefresh} />;
  }

  // Everything else gets a preview suited to its kind, backed by the real
  // workspace files and the honest build/run status — never a fake animation.
  const entryPoints = project.artifacts
    .map((a) => a.path)
    .filter(
      (p) =>
        /(^|\/)(main|app|index|server|cli)\.(py|js|ts|tsx|dart|go|rs|java|cs|kt|swift)$/i.test(p) ||
        /(^|\/)(README|readme)\.md$/.test(p),
    )
    .slice(0, 8);

  return (
    <div className="grid preview-grid">
      <section className="panel">
        <div className="panel-head">
          <h3>{DOMAIN_LABEL[domain] ?? "Deliverable"} preview</h3>
          <div className="view-controls">
            <button onClick={onRefresh}>Refresh</button>
            <a href={api.exportUrl(project.id)}>Export zip</a>
          </div>
        </div>
        <p className="hint-note">
          {domain === "mobile_app"
            ? "A mobile project. Open the generated project in its toolchain (Flutter / React Native / Android Studio) to run it on a device or emulator; the entry points below are the real sources."
            : domain === "desktop_app"
              ? "A desktop project. Run the generated entry point with its runtime (for example `python main.py`, `npm run tauri dev`, or the packaged binary)."
              : backendDomains.includes(domain)
                ? "A backend / service project. Start the generated server and exercise its API; the entry point and the run evidence are below."
                : "Inspect the generated deliverable: entry points, artifacts and the verification results."}
        </p>
        <h4>Entry points</h4>
        {entryPoints.length === 0 ? (
          <p className="empty-note">
            No entry points detected yet. The Files tab lists everything produced in the workspace.
          </p>
        ) : (
          <ul className="plain small">
            {entryPoints.map((path) => (
              <li key={path}>
                <code className="sha">{path}</code>
              </li>
            ))}
          </ul>
        )}
        <h4>Run evidence</h4>
        {project.tests.length === 0 ? (
          <p className="empty-note">No run or test evidence recorded yet.</p>
        ) : (
          <ul className="plain small">
            {project.tests.slice(-10).map((t) => (
              <li key={t.id} className={`test-${t.status}`}>
                <span className="activity-kind">{t.status}</span> {t.suite}: {t.name}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="panel">
        <h3>Build &amp; run status</h3>
        {status?.build ? (
          <dl className="kv">
            <dt>Status</dt>
            <dd className={status.build.status === "passed" ? "pass" : "fail"}>{status.build.status}</dd>
            <dt>Command</dt>
            <dd>{status.build.name}</dd>
            {status.package_dir && (
              <>
                <dt>Package</dt>
                <dd>{status.package_dir}</dd>
              </>
            )}
          </dl>
        ) : (
          <p className="empty-note">
            No build was attempted for this domain. That is expected for non-web projects; their
            verification runs through the test and review tasks instead.
          </p>
        )}
        {status?.build?.message && <pre className="log">{status.build.message}</pre>}
      </section>
    </div>
  );
}

function WebPreviewTab({
  project,
  status,
  onRefresh,
}: {
  project: Project;
  status: {
    available: boolean;
    preview_url: string | null;
    package_dir: string | null;
    build: { status: string; name: string; message?: string } | null;
  } | null;
  onRefresh: () => void;
}) {
  const [nonce, setNonce] = useState(0);
  const build = status?.build ?? null;
  return (
    <div className="grid preview-grid">
      <section className="panel viewport-panel">
        <div className="panel-head">
          <h3>Browser preview</h3>
          <div className="view-controls">
            <button
              onClick={() => {
                onRefresh();
                setNonce((n) => n + 1);
              }}
            >
              Reload
            </button>
            {status?.available && (
              <a href={`/api/projects/${project.id}/preview/`} target="_blank" rel="noreferrer noopener">
                Open in new tab
              </a>
            )}
          </div>
        </div>
        {status?.available ? (
          <iframe
            key={nonce}
            title="app preview"
            src={`/api/projects/${project.id}/preview/`}
            style={{ width: "100%", height: "70vh", border: "1px solid var(--border)", borderRadius: 8, background: "#fff" }}
          />
        ) : (
          <p className="empty-note">
            No built web app yet. The preview appears after the frontend build succeeds.
          </p>
        )}
      </section>
      <section className="panel">
        <h3>Build</h3>
        {build ? (
          <dl className="kv">
            <dt>Status</dt>
            <dd className={build.status === "passed" ? "pass" : "fail"}>{build.status}</dd>
            <dt>Command</dt>
            <dd>{build.name}</dd>
            <dt>Package</dt>
            <dd>{status?.package_dir ?? "—"}</dd>
          </dl>
        ) : (
          <p className="empty-note">No build has been run for this project.</p>
        )}
        {build?.message && (
          <>
            <h4>Build output</h4>
            <pre className="log">{build.message}</pre>
          </>
        )}
      </section>
    </div>
  );
}

function PreviewTab({
  scene,
  validation,
  selected,
  onSelect,
  viewMode,
  onViewMode,
  editInstruction,
  onEditInstruction,
  onSendEdit,
  viewerUrl,
}: {
  scene: Scene | null;
  validation: ValidationReport | null;
  selected: string | null;
  onSelect: (id: string | null) => void;
  viewMode: "solid" | "wireframe";
  onViewMode: (mode: "solid" | "wireframe") => void;
  editInstruction: string;
  onEditInstruction: (value: string) => void;
  onSendEdit: () => void;
  viewerUrl: string;
}) {
  const primitive = scene?.primitives.find((p) => p.id === selected) ?? null;
  return (
    <div className="grid preview-grid">
      <section className="panel viewport-panel">
        <div className="panel-head">
          <h3>3D viewport</h3>
          <div className="view-controls">
            <button className={viewMode === "solid" ? "active" : ""} onClick={() => onViewMode("solid")}>
              Solid
            </button>
            <button className={viewMode === "wireframe" ? "active" : ""} onClick={() => onViewMode("wireframe")}>
              Wireframe
            </button>
            <a href={viewerUrl} target="_blank" rel="noreferrer noopener">
              Open standalone
            </a>
          </div>
        </div>
        <Viewport scene={scene} selectedId={selected} onSelect={(id) => onSelect(id)} mode={viewMode} />
      </section>
      <section className="panel">
        <h3>Object inspector</h3>
        {primitive ? (
          <dl className="kv">
            <dt>Name</dt>
            <dd>{primitive.name}</dd>
            <dt>Kind</dt>
            <dd>{primitive.kind}</dd>
            <dt>Position (m)</dt>
            <dd>{primitive.position.map((v) => v.toFixed(2)).join(", ")}</dd>
            <dt>Size (m)</dt>
            <dd>{primitive.size.map((v) => v.toFixed(2)).join(", ")}</dd>
            <dt>Rotation (°)</dt>
            <dd>{primitive.rotation.map((v) => v.toFixed(1)).join(", ")}</dd>
            <dt>Material</dt>
            <dd>
              <span className="swatch" style={{ background: primitive.material.color }} /> {primitive.material.color}
            </dd>
          </dl>
        ) : (
          <p className="empty-note">Click an object in the viewport to inspect it.</p>
        )}

        <h4>Natural-language editing</h4>
        <textarea
          rows={3}
          value={editInstruction}
          onChange={(event) => onEditInstruction(event.target.value)}
          placeholder="e.g. Make the living room larger and add a second sofa against the north wall."
        />
        <button className="primary" onClick={onSendEdit} disabled={!editInstruction.trim()}>
          Send edit instruction
        </button>

        {validation && (
          <>
            <h4>
              Validation — {validation.score}% ({validation.checks.filter((c) => c.passed).length}/
              {validation.checks.length})
            </h4>
            <ul className="checks">
              {validation.checks.map((check) => (
                <li key={check.name} className={check.passed ? "pass" : "fail"}>
                  <span>{check.passed ? "✓" : "✕"}</span>
                  <strong>{check.name.replace(/_/g, " ")}</strong>
                  <em>{check.detail}</em>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}

function TestsTab({ project }: { project: Project }) {
  return (
    <section className="panel">
      <h3>Test &amp; verification results</h3>
      {project.tests.length === 0 ? (
        <p className="empty-note">No test results recorded yet.</p>
      ) : (
        <table className="tests">
          <thead>
            <tr>
              <th>Suite</th>
              <th>Test</th>
              <th>Status</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {project.tests.map((test) => (
              <tr key={test.id} className={`test-${test.status}`}>
                <td>{test.suite}</td>
                <td>{test.name}</td>
                <td>{test.status}</td>
                <td>{test.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h4>Acceptance criteria</h4>
      <ul className="criteria">
        {project.specification.acceptance_criteria.map((crit) => (
          <li key={crit.id} className={crit.satisfied ? "satisfied" : ""}>
            <span className="check">{crit.satisfied ? "✓" : "○"}</span>
            {crit.statement}
            {crit.evidence && <em>{crit.evidence}</em>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function OutputTab({ project, onChanged }: { project: Project; onChanged?: () => void }) {
  const [report, setReport] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [revisions, setRevisions] = useState<
    { sha: string; short: string; message: string; committed_at: string; files_changed: number }[]
  >([]);
  const [diff, setDiff] = useState<{ sha: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const loadRevisions = () => {
    api
      .revisions(project.id)
      .then((r) => setRevisions(r.items))
      .catch(() => setRevisions([]));
  };

  useEffect(() => {
    api
      .report(project.id)
      .then((r) => setReport(r.report))
      .catch(() => setReport(null));
    loadRevisions();
  }, [project.id, version]);

  const showDiff = async (sha: string) => {
    try {
      const r = await api.revisionDiff(project.id, sha);
      setDiff({ sha, text: r.diff });
    } catch (error) {
      setNote(`Could not load diff: ${(error as Error).message}`);
    }
  };

  const restore = async (sha: string) => {
    setBusy(true);
    setNote(null);
    try {
      await api.restoreRevision(project.id, sha, false);
      setNote(
        `Workspace restored to ${sha.slice(0, 8)}. A pre-restore revision was saved, so this can be undone.`,
      );
      setVersion((v) => v + 1);
      onChanged?.();
    } catch (error) {
      setNote(`Restore failed: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid two">
      <section className="panel">
        <div className="panel-head">
          <h3>Final output</h3>
          <div className="view-controls">
            <button onClick={() => setVersion((v) => v + 1)}>Reload report</button>
            <a href={api.exportUrl(project.id)}>Export zip</a>
          </div>
        </div>
        {report ? <pre className="report-view">{report}</pre> : <p className="empty-note">Report not generated yet.</p>}
        <h4>Event log</h4>
        <ul className="plain small">
          {project.events.slice(-40).map((event) => (
            <li key={event.id}>
              <span className="activity-kind">{event.kind}</span> {event.message}
            </li>
          ))}
        </ul>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h3>Version history</h3>
          <button onClick={loadRevisions}>Refresh</button>
        </div>
        {note && <div className="hint-note">{note}</div>}
        {revisions.length === 0 ? (
          <p className="empty-note">No revisions yet. Each pipeline step is committed automatically.</p>
        ) : (
          <ul className="version-list">
            {revisions.map((rev) => (
              <li key={rev.sha}>
                <strong>{rev.message}</strong>
                <code className="sha">{rev.short}</code>
                <span className="activity-time">{formatTime(rev.committed_at)}</span>
                <em>
                  {rev.files_changed} file{rev.files_changed === 1 ? "" : "s"} changed
                </em>
                <span className="rev-actions">
                  <button onClick={() => showDiff(rev.sha)}>Diff</button>
                  <button onClick={() => restore(rev.sha)} disabled={busy}>
                    Restore
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
        {diff && (
          <>
            <h4>
              Diff for <code className="sha">{diff.sha.slice(0, 8)}</code>
            </h4>
            <pre className="log">{diff.text}</pre>
          </>
        )}
        <h4>Labelled snapshots</h4>
        <ul className="version-list">
          {project.versions?.map((snap: any) => (
            <li key={snap.id}>
              <strong>{snap.label}</strong>
              <span className={`tag status-${snap.status}`}>{snap.status}</span>
              <span className="activity-time">{formatTime(snap.created_at)}</span>
              {snap.note && <em>{snap.note}</em>}
            </li>
          ))}
          {(!project.versions || project.versions.length === 0) && <li className="empty-note">No versions yet.</li>}
        </ul>
      </section>
    </div>
  );
}

function moduleLabel(module: string): string {
  switch (module) {
    case "A":
      return "A — Application Creation";
    case "B":
      return "B — Problem Solving";
    case "C":
      return "C — Building Creation";
    default:
      return "P — Shared platform";
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return "";
  }
}
