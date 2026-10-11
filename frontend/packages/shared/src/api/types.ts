/**
 * The backend API contract, mirrored here. Every field matches
 * `docs/tech-design-backend.md`; the backend owns this shape.
 */

export type Repo = {
  id: string;
  name: string;
  url: string;
  /** Relative to the repo root; "/" means the root itself. */
  path: string;
  composeFile: string;
  defaultBranch: string | null;
  cloned: boolean;
  lastDeployment: Deployment | null;
  createdAt: string;
};

export type Branch = { name: string; commit: string };

export type Commit = {
  sha: string;
  subject: string;
  author: string;
  committedAt: string;
};

export type DeployStep =
  | "clone"
  | "fetch"
  | "checkout"
  | "build"
  | "up"
  | "networks";

export type DeploymentStatus =
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "cancelled";

export type Deployment = {
  id: string;
  repoId: string;
  branch: string;
  commitSha: string | null;
  commitMessage: string | null;
  status: DeploymentStatus;
  step: DeployStep | null;
  error: string | null;
  startedAt: string;
  finishedAt: string | null;
};

export type DeploymentWithContainers = Deployment & { containers: Container[] };

export type ContainerState =
  | "running"
  | "exited"
  | "paused"
  | "restarting"
  | "created"
  | "dead";

export type Port = {
  containerPort: number;
  hostPort: number | null;
  hostIp: string | null;
  protocol: "tcp" | "udp";
};

export type Container = {
  id: string;
  fullId: string;
  name: string;
  image: string;
  state: ContainerState;
  /** Docker's own text, for example "Exited (137) 4 hours ago". */
  status: string;
  exitCode: number | null;
  ports: Port[];
  networks: string[];
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  /** Set when the portal deployed the container. */
  repoId: string | null;
  service: string | null;
};

export type Network = {
  id: string;
  name: string;
  driver: string;
  scope: "local" | "swarm" | "global";
  subnet: string | null;
  internal: boolean;
  builtin: boolean;
  composeManaged: boolean;
  containerCount: number;
};

export type LogLine = {
  time: string;
  stream: "stdout" | "stderr";
  msg: string;
};

export type Health = {
  status: "ok" | "degraded";
  docker: { reachable: boolean; serverVersion: string | null };
  git: { version: string | null };
};

/* Request and response payloads */

export type CreateRepoBody = {
  name: string;
  url: string;
  path?: string;
  composeFile?: string;
};

export type UpdateRepoBody = {
  name?: string;
  path?: string;
  composeFile?: string;
};

export type BranchList = { defaultBranch: string | null; branches: Branch[] };

export type StartDeploymentBody = { branch: string; commit?: string };

export type ConnectBody = {
  containerIds: string[];
  aliases?: string[];
};

export type ConnectResult = {
  connected: string[];
  failed: { containerId: string; error: string }[];
};

export type CreateNetworkBody = {
  name: string;
  driver?: "bridge";
  internal?: boolean;
};

/* SSE event payloads */

export type StepEvent = {
  step: DeployStep;
  status: "started" | "succeeded" | "failed";
};

export type LineEvent = { seq: number; text: string };

export type DoneEvent = {
  status: DeploymentStatus;
  commitSha: string | null;
  commitMessage: string | null;
  error: string | null;
};