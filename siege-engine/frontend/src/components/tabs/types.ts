import type { StageExecution } from '../../types/pipeline';
import type { Artifact } from '../../types/project';

export interface DashboardContext {
  projectId: string;
  selectedArtifact: Artifact | null;
  selectedExecution: StageExecution | undefined;
}
