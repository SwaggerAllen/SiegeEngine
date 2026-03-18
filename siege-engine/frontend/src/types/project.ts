export interface Project {
  id: string;
  name: string;
  description: string | null;
  git_repo_path: string;
  remote_url?: string | null;
  github_repo_slug?: string | null;
  created_at: string;
  updated_at: string;
  artifact_count: number;
  pipeline_status?: string;
}

export interface ProjectDetail extends Project {
  artifacts: ArtifactSummary[];
}

export type ArtifactStatus = 'generating' | 'awaiting_review' | 'approved' | 'stale' | 'ai_reviewing';

export interface ArtifactSummary {
  id: string;
  name: string;
  artifact_type: string;
  status: ArtifactStatus;
  component_key: string | null;
  version: number;
}

export interface Artifact {
  id: string;
  project_id: string;
  artifact_type: string;
  name: string;
  component_key: string | null;
  content: string | null;
  status: ArtifactStatus;
  version: number;
  ai_review_feedback: Record<string, unknown> | null;
  human_review_notes: string | null;
  file_path: string | null;
  git_commit_sha: string | null;
  language: string | null;
  created_at: string;
  updated_at: string;
}
