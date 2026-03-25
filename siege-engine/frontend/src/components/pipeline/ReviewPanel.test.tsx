import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReviewPanel } from './ReviewPanel';
import { TestQueryWrapper } from '../../test/queryWrapper';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';

const mockResumeStage = vi.fn();
const mockPruneArtifact = vi.fn();

// Mock TQ hooks
vi.mock('../../hooks/queries/usePipelineQueries', () => ({
  useIsRunning: () => false,
  usePipelineRuns: () => ({ data: [] }),
  usePipelineConfigData: () => ({
    stages: [{ stage_key: 'system_requirements', output_artifact_type: 'system_requirements' }],
  }),
  pipelineKeys: {
    status: (id: string) => ['pipeline', id, 'status'],
    runs: (id: string) => ['pipeline', id, 'runs'],
  },
}));

vi.mock('../../hooks/mutations/usePipelineMutations', () => ({
  useStartPipeline: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useResumeRun: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useRegenDownstream: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useResumeStage: () => ({ mutateAsync: mockResumeStage, mutate: mockResumeStage }),
  useResolveStale: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  useForceRestartStage: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
  usePruneArtifact: () => ({ mutateAsync: mockPruneArtifact, mutate: mockPruneArtifact }),
  useCancelStage: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
}));

vi.mock('../../hooks/queries/useDAGQueries', () => ({
  dagKeys: {
    workflow: (id: string) => ['dag', id, 'workflow'],
    documents: (id: string) => ['dag', id, 'documents'],
  },
}));

const mockAuthState = { user: { id: 'user-1', username: 'admin', role: 'admin' } };
vi.mock('../../store/authStore', () => ({
  useAuthStore: vi.fn((selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState
  ),
}));

vi.mock('../../api/comments', () => ({
  listComments: vi.fn().mockResolvedValue([]),
}));

const baseArtifact: Artifact = {
  id: 'art-1',
  project_id: 'proj-1',
  artifact_type: 'system_requirements',
  name: 'System Requirements',
  component_key: null,
  content: 'Some content',
  status: 'awaiting_review',
  version: 1,
  ai_review_feedback: null,
  human_review_notes: null,
  file_path: null,
  git_commit_sha: null,
  language: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
};

const awaitingExecution: StageExecution = {
  id: 'exec-1',
  stage_key: 'system_requirements',
  component_key: null,
  status: 'awaiting_review',
  artifact_id: 'art-1',
  started_at: null,
  completed_at: null,
  error_message: null,
  run_id: 'run-1',
};

describe('ReviewPanel', () => {
  beforeEach(() => {
    mockResumeStage.mockReset();
    mockPruneArtifact.mockReset();
  });

  it('renders prune button when execution is undefined and artifact is not awaiting review', () => {
    const approvedArtifact = { ...baseArtifact, status: 'approved' as const };
    render(
      <ReviewPanel projectId="proj-1" artifact={approvedArtifact} execution={undefined} />,
      { wrapper: TestQueryWrapper }
    );
    expect(screen.getByText('🗑 Prune Node')).toBeInTheDocument();
  });

  it('renders prune button when execution.status is approved and artifact is approved', () => {
    const approvedArtifact = { ...baseArtifact, status: 'approved' as const };
    const approvedExecution = { ...awaitingExecution, status: 'approved' as const };
    render(
      <ReviewPanel projectId="proj-1" artifact={approvedArtifact} execution={approvedExecution} />,
      { wrapper: TestQueryWrapper }
    );
    expect(screen.getByText('🗑 Prune')).toBeInTheDocument();
  });

  it('renders no action buttons for input doc artifacts', () => {
    const inputArtifact = { ...baseArtifact, artifact_type: 'project_doc' };
    render(
      <ReviewPanel projectId="proj-1" artifact={inputArtifact} execution={undefined} />,
      { wrapper: TestQueryWrapper }
    );
    expect(screen.queryByText('🗑 Prune Node')).not.toBeInTheDocument();
    expect(screen.queryByText('Start Run')).not.toBeInTheDocument();
    expect(screen.queryByText('Regen Downstream')).not.toBeInTheDocument();
  });

  it('renders Approve and Reject buttons in actions mode when awaiting_review', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="actions" />,
      { wrapper: TestQueryWrapper }
    );
    expect(screen.getByText('Approve')).toBeInTheDocument();
    expect(screen.getByText('Reject')).toBeInTheDocument();
    expect(screen.queryByText('Save Feedback')).not.toBeInTheDocument();
  });

  it('renders Save Feedback textarea in feedback mode when awaiting_review', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );
    expect(screen.getByText('Save Feedback')).toBeInTheDocument();
    expect(screen.queryByText('Approve')).not.toBeInTheDocument();
  });

  it('starts with empty notes textarea (no pre-population)', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );
    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    expect(textarea).toHaveValue('');
  });

  it('disables Save Feedback when notes are empty', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );
    const saveBtn = screen.getByText('Save Feedback');
    expect(saveBtn).toBeDisabled();
  });

  it('enables Save Feedback when user types notes', async () => {
    const user = userEvent.setup();
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );
    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    await user.type(textarea, 'Some feedback');

    const saveBtn = screen.getByText('Save Feedback');
    expect(saveBtn).not.toBeDisabled();
  });

  it('calls resumeStage with "approved" when Approve is clicked', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />,
      { wrapper: TestQueryWrapper }
    );
    await user.click(screen.getByText('Approve'));

    expect(mockResumeStage).toHaveBeenCalledWith({
      executionId: 'exec-1',
      action: 'approved',
      notes: undefined,
      editedContent: undefined,
    });
  });

  it('calls resumeStage with "rejected" when Reject is clicked', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />,
      { wrapper: TestQueryWrapper }
    );
    await user.click(screen.getByText('Reject'));

    expect(mockResumeStage).toHaveBeenCalledWith({
      executionId: 'exec-1',
      action: 'rejected',
      notes: undefined,
      editedContent: undefined,
    });
  });

  it('calls resumeStage with "save_feedback" when Save Feedback is clicked', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );

    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    await user.type(textarea, 'Some feedback');
    await user.click(screen.getByText('Save Feedback'));

    expect(mockResumeStage).toHaveBeenCalledWith({
      executionId: 'exec-1',
      action: 'save_feedback',
      notes: 'Some feedback',
      editedContent: undefined,
    });
  });

  it('shows "Feedback Saved" after save_feedback action', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} mode="feedback" />,
      { wrapper: TestQueryWrapper }
    );

    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    await user.type(textarea, 'Some feedback');
    await user.click(screen.getByText('Save Feedback'));

    await waitFor(() => {
      expect(screen.getByText('Feedback Saved')).toBeInTheDocument();
    });
  });
});
