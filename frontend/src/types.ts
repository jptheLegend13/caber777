export type ProjectStatus =
  | "draft"
  | "planning"
  | "researching"
  | "executing"
  | "testing"
  | "reviewing"
  | "repairing"
  | "delivered"
  | "failed"
  | "cancelled";

export type TaskStatus =
  | "pending"
  | "blocked"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export interface Requirement {
  id: string;
  text: string;
  origin: "user" | "inferred";
  category: string;
  priority: "must" | "should" | "could";
  acceptance_criteria: string[];
}

export interface AcceptanceCriterion {
  id: string;
  statement: string;
  verification_method: string;
  satisfied: boolean;
  evidence: string | null;
}

export interface Constraint {
  id: string;
  text: string;
  kind: string;
  origin: "user" | "inferred";
}

export interface Specification {
  intent: string;
  deliverable: string;
  domain: string;
  caber_module: string;
  summary: string;
  requirements: Requirement[];
  constraints: Constraint[];
  acceptance_criteria: AcceptanceCriterion[];
  missing_information: string[];
  assumptions: string[];
  clarifications_needed: boolean;
  technology_choices: { area: string; choice: string; rationale: string }[];
  research_needed: boolean;
  research_questions: string[];
}

export interface Task {
  id: string;
  title: string;
  objective: string;
  agent_role: string;
  dependencies: string[];
  outputs: string[];
  tools: string[];
  acceptance_criteria: string[];
  status: TaskStatus;
  phase: string;
  evidence: string[];
  error: string | null;
  attempts: number;
  conversation_id: string | null;
}

export interface TaskGraph {
  tasks: Task[];
}

export interface Source {
  id: string;
  url: string;
  title: string;
  publisher: string;
  finding: string;
  kind: string;
  reliability: string;
  retrieved_at: string;
}

export interface ResearchReport {
  id: string;
  question: string;
  status: string;
  summary: string;
  findings: string[];
  sources: Source[];
  hypotheses: string[];
  gaps: string[];
  recommendations: string[];
  method: string;
}

export interface Artifact {
  id: string;
  name: string;
  kind: string;
  path: string;
  size_bytes: number;
  description: string;
}

export interface TestResult {
  id: string;
  suite: string;
  name: string;
  status: string;
  message: string;
}

export interface ProjectEvent {
  id: string;
  at: string;
  kind: string;
  message: string;
  data: Record<string, unknown>;
}

export interface VersionSnapshot {
  id: string;
  label: string;
  created_at: string;
  status: ProjectStatus;
  files: string[];
  note: string;
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  path: string;
  text_excerpt: string;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  original_request: string;
  status: ProjectStatus;
  specification: Specification;
  task_graph: TaskGraph;
  research: ResearchReport[];
  artifacts: Artifact[];
  tests: TestResult[];
  events: ProjectEvent[];
  versions: VersionSnapshot[];
  workspace_path: string;
  attachments: Attachment[];
  preview_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: ProjectStatus;
  domain: string;
  caber_module: string;
  created_at: string;
  updated_at: string;
}

export interface AgentRole {
  name: string;
  title: string;
  discipline: string;
  objective: string;
  tools: string[];
  permissions: string[];
  seniority: number;
  dynamic: boolean;
}

export interface ScenePrimitive {
  id: string;
  kind: string;
  name: string;
  position: [number, number, number];
  size: [number, number, number];
  rotation: [number, number, number];
  material: { color: string; roughness: number; metalness: number; opacity: number };
  room_id: string | null;
  object_id: string | null;
}

export interface SceneLight {
  id: string;
  kind: string;
  intensity: number;
  color: string;
  position: [number, number, number];
}

export interface Scene {
  title: string;
  units: string;
  primitives: ScenePrimitive[];
  lights: SceneLight[];
  bounds: { min: number[]; max: number[]; center: number[]; size: number[] };
  stats: Record<string, number>;
  metadata: Record<string, unknown>;
}

export interface ValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ValidationReport {
  passed: boolean;
  score: number;
  checks: ValidationCheck[];
  stats: Record<string, number>;
}

export interface StreamEvent {
  kind: string;
  message?: string;
  project?: Project;
  [key: string]: unknown;
}
