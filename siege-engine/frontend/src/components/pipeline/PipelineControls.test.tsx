import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PipelineControls } from './PipelineControls';
import { TestQueryWrapper } from '../../test/queryWrapper';

async function expandControls(user: ReturnType<typeof userEvent.setup>) {
  const toggle = screen.queryByTitle('Show run controls');
  if (toggle) await user.click(toggle);
}

const mockCancelPipeline = vi.fn();
const mockResetAll = vi.fn();

// Mock TQ query hooks
let mockIsRunning = false;
let mockIsPaused = false;
let mockRuns: Array<{ id: string; run_number: number; status: string; run_id: string }> = [];
let mockBlockingPR: { blocking_pr_url: string | null; blocking_pr_number: number | null } | null = null;

vi.mock('../../hooks/queries/usePipelineQueries', () => ({
  usePipelineStatus: () => ({
    data: { snapshot: { is_running: mockIsRunning, is_paused: mockIsPaused } },
  }),
  usePipelineRuns: () => ({ data: mockRuns }),
  useBlockingPR: () => ({ data: mockBlockingPR }),
}));

vi.mock('../../hooks/mutations/usePipelineMutations', () => ({
  useCancelPipeline: () => ({ mutateAsync: mockCancelPipeline, mutate: mockCancelPipeline }),
  useResetAll: () => ({ mutateAsync: mockResetAll, mutate: mockResetAll }),
  useCheckBlockingPR: () => ({ mutateAsync: vi.fn().mockResolvedValue({ blocking: true }) }),
  useDismissBlockingPR: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
}));

function setMockState(values: {
  isRunning?: boolean;
  isPaused?: boolean;
  runs?: typeof mockRuns;
  blockingPR?: typeof mockBlockingPR;
}) {
  mockIsRunning = values.isRunning ?? false;
  mockIsPaused = values.isPaused ?? false;
  mockRuns = values.runs ?? [];
  mockBlockingPR = values.blockingPR ?? null;
}

describe('PipelineControls', () => {
  beforeEach(() => {
    mockCancelPipeline.mockReset();
    mockResetAll.mockReset();
    setMockState({});
  });

  it('does not show Start Run button (moved to node panels)', () => {
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    expect(screen.queryByText('Start Run')).not.toBeInTheDocument();
  });

  it('shows Cancel button when running', async () => {
    const user = userEvent.setup();
    setMockState({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('shows run number badge when running with a current run', async () => {
    const user = userEvent.setup();
    setMockState({
      isRunning: true,
      runs: [{ id: '1', run_number: 3, status: 'running', run_id: 'r-1' }],
    });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    expect(screen.getByText('Run #3')).toBeInTheDocument();
  });

  it('shows "Paused for review" when isPaused', async () => {
    const user = userEvent.setup();
    setMockState({ isRunning: true, isPaused: true });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    expect(screen.getByText('Paused for review')).toBeInTheDocument();
  });

  it('shows "Running..." when running but not paused', async () => {
    const user = userEvent.setup();
    setMockState({ isRunning: true, isPaused: false });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    expect(screen.getByText('Running...')).toBeInTheDocument();
  });

  it('does not show "Running..." when not running', () => {
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    expect(screen.queryByText('Running...')).not.toBeInTheDocument();
  });

  it('calls cancelPipeline when Cancel is clicked', async () => {
    const user = userEvent.setup();
    setMockState({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    // Click Cancel to open dialog
    await user.click(screen.getByText('Cancel'));
    // Click "Cancel Run" button in the dialog
    await user.click(screen.getByRole('button', { name: 'Cancel Run' }));

    expect(mockCancelPipeline).toHaveBeenCalledWith(undefined);
  });

  it('shows Reset All button when there is a completed run', async () => {
    const user = userEvent.setup();
    setMockState({
      runs: [{ id: '1', run_number: 1, status: 'completed', run_id: 'r-1' }],
    });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });
    await expandControls(user);

    expect(screen.getByText('Reset All')).toBeInTheDocument();
  });

  it('does not show Reset All when there are no completed runs', () => {
    setMockState({ runs: [] });
    render(<PipelineControls projectId="proj-1" />, { wrapper: TestQueryWrapper });

    expect(screen.queryByText('Reset All')).not.toBeInTheDocument();
  });
});
