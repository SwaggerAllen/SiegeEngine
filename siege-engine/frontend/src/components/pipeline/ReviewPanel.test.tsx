import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReviewPanel } from './ReviewPanel';
import type { Artifact } from '../../types/project';
import type { StageExecution } from '../../types/pipeline';

const mockResumeStage = vi.fn();

vi.mock('../../store/pipelineStore', () => ({
  usePipelineStore: vi.fn(() => ({
    resumeStage: mockResumeStage,
  })),
}));

vi.mock('../../store/authStore', () => ({
  useAuthStore: vi.fn(() => ({
    user: { id: 'user-1', username: 'admin', role: 'admin' },
  })),
}));

vi.mock('../../api/comments', () => ({
  listComments: vi.fn().mockResolvedValue([]),
  createComment: vi.fn().mockResolvedValue({}),
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
  });

  it('renders Comments section when execution is undefined', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={undefined} />
    );
    expect(screen.getByText('Comments')).toBeInTheDocument();
  });

  it('renders Comments section when execution.status is not awaiting_review', () => {
    const approvedExecution = { ...awaitingExecution, status: 'approved' };
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={approvedExecution} />
    );
    expect(screen.getByText('Comments')).toBeInTheDocument();
  });

  it('renders Approve, Save Feedback, and Reject buttons when awaiting_review', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    expect(screen.getByText('Approve')).toBeInTheDocument();
    expect(screen.getByText('Save Feedback')).toBeInTheDocument();
    expect(screen.getByText('Reject & Re-generate')).toBeInTheDocument();
  });

  it('starts with empty notes textarea (no pre-population)', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    expect(textarea).toHaveValue('');
  });

  it('disables Save Feedback when notes are empty', () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    const saveBtn = screen.getByText('Save Feedback');
    expect(saveBtn).toBeDisabled();
  });

  it('enables Save Feedback when user types notes', async () => {
    const user = userEvent.setup();
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
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
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    await user.click(screen.getByText('Approve'));

    expect(mockResumeStage).toHaveBeenCalledWith(
      'proj-1', 'exec-1', 'approved', undefined, undefined
    );
  });

  it('calls resumeStage with "rejected" when Reject is clicked', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    await user.click(screen.getByText('Reject & Re-generate'));

    expect(mockResumeStage).toHaveBeenCalledWith(
      'proj-1', 'exec-1', 'rejected', undefined, undefined
    );
  });

  it('calls resumeStage with "save_feedback" when Save Feedback is clicked', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );

    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    await user.type(textarea, 'Some feedback');
    await user.click(screen.getByText('Save Feedback'));

    expect(mockResumeStage).toHaveBeenCalledWith(
      'proj-1', 'exec-1', 'save_feedback', 'Some feedback', undefined
    );
  });

  it('shows "Feedback Saved" after save_feedback action', async () => {
    const user = userEvent.setup();
    mockResumeStage.mockResolvedValue(undefined);

    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );

    const textarea = screen.getByPlaceholderText('Add feedback for re-generation...');
    await user.type(textarea, 'Some feedback');
    await user.click(screen.getByText('Save Feedback'));

    await waitFor(() => {
      expect(screen.getByText('Feedback Saved')).toBeInTheDocument();
    });
  });

  it('shows feedback controls and comments together when awaiting_review', async () => {
    render(
      <ReviewPanel projectId="proj-1" artifact={baseArtifact} execution={awaitingExecution} />
    );
    // Feedback textarea
    expect(screen.getByPlaceholderText('Add feedback for re-generation...')).toBeInTheDocument();
    // Comment input (from CommentsPanel) — wait for async load
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Add a comment...')).toBeInTheDocument();
    });
  });
});
