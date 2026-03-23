import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PipelineControls } from './PipelineControls';

const mockCancelPipeline = vi.fn();
const mockResetAll = vi.fn();

// Mock usePipelineStore to support both selector and no-arg calls.
// When called with a selector function, apply it to the mock state.
let mockState: Record<string, unknown> = {};

vi.mock('../../store/pipelineStore', () => ({
  usePipelineStore: vi.fn((selector?: (s: Record<string, unknown>) => unknown) => {
    return selector ? selector(mockState) : mockState;
  }),
}));

import { usePipelineStore } from '../../store/pipelineStore';

function mockStoreValues(values: Record<string, unknown>) {
  mockState = {
    isRunning: false,
    isPaused: false,
    currentRunNumber: null,
    runs: [],
    blockingPR: null,
    cancelPipeline: mockCancelPipeline,
    resetAll: mockResetAll,
    checkBlockingPR: vi.fn(),
    dismissBlockingPR: vi.fn(),
    ...values,
  };
  // Also update the mock implementation for re-renders
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(usePipelineStore).mockImplementation(((selector?: (s: any) => any) =>
    selector ? selector(mockState) : mockState) as any,
  );
}

describe('PipelineControls', () => {
  beforeEach(() => {
    mockCancelPipeline.mockReset();
    mockResetAll.mockReset();
    mockStoreValues({});
  });

  it('does not show Start Run button (moved to node panels)', () => {
    render(<PipelineControls projectId="proj-1" />);
    expect(screen.queryByText('Start Run')).not.toBeInTheDocument();
  });

  it('shows Cancel button when running', () => {
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('shows run number badge when running with a current run', () => {
    mockStoreValues({ isRunning: true, currentRunNumber: 3 });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Run #3')).toBeInTheDocument();
  });

  it('shows "Paused for review" when isPaused', () => {
    mockStoreValues({ isRunning: true, isPaused: true });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Paused for review')).toBeInTheDocument();
  });

  it('shows "Running..." when running but not paused', () => {
    mockStoreValues({ isRunning: true, isPaused: false });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Running...')).toBeInTheDocument();
  });

  it('does not show "Running..." when not running', () => {
    render(<PipelineControls projectId="proj-1" />);
    expect(screen.queryByText('Running...')).not.toBeInTheDocument();
  });

  it('calls cancelPipeline when Cancel is clicked', async () => {
    const user = userEvent.setup();
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    // Click Cancel to open dialog
    await user.click(screen.getByText('Cancel'));
    // Click "Cancel Run" button in the dialog
    await user.click(screen.getByRole('button', { name: 'Cancel Run' }));

    expect(mockCancelPipeline).toHaveBeenCalledWith('proj-1', undefined);
  });

  it('shows Reset All button when there is a completed run', () => {
    mockStoreValues({
      runs: [{ id: '1', run_number: 1, status: 'completed', run_id: 'r-1' }],
    });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Reset All')).toBeInTheDocument();
  });

  it('does not show Reset All when there are no completed runs', () => {
    mockStoreValues({ runs: [] });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.queryByText('Reset All')).not.toBeInTheDocument();
  });
});
