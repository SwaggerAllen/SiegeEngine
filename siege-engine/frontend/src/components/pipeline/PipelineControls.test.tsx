import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PipelineControls } from './PipelineControls';

const mockStartPipeline = vi.fn();
const mockResumePipeline = vi.fn();
const mockCancelPipeline = vi.fn();

vi.mock('../../store/pipelineStore', () => ({
  usePipelineStore: vi.fn(() => ({
    isRunning: false,
    isPaused: false,
    currentRunNumber: null,
    runs: [],
    startPipeline: mockStartPipeline,
    resumeRun: mockResumePipeline,
    cancelPipeline: mockCancelPipeline,
  })),
}));

import { usePipelineStore } from '../../store/pipelineStore';

function mockStoreValues(values: Record<string, unknown>) {
  vi.mocked(usePipelineStore).mockReturnValue({
    isRunning: false,
    isPaused: false,
    currentRunNumber: null,
    runs: [],
    startPipeline: mockStartPipeline,
    resumeRun: mockResumePipeline,
    cancelPipeline: mockCancelPipeline,
    ...values,
  } as ReturnType<typeof usePipelineStore>);
}

describe('PipelineControls', () => {
  beforeEach(() => {
    mockStartPipeline.mockReset();
    mockResumePipeline.mockReset();
    mockCancelPipeline.mockReset();
    mockStoreValues({});
  });

  it('shows Start Run button when not running', () => {
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Start Run')).toBeInTheDocument();
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
  });

  it('shows Cancel button when running', () => {
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.queryByText('Start Run')).not.toBeInTheDocument();
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

  it('opens config panel when Start Run is clicked', async () => {
    const user = userEvent.setup();
    render(<PipelineControls projectId="proj-1" />);

    await user.click(screen.getByText('Start Run'));

    expect(screen.getByText('Run Configuration')).toBeInTheDocument();
    expect(screen.getByText('Include human review')).toBeInTheDocument();
    expect(screen.getByText('AI self-improvement loops')).toBeInTheDocument();
    expect(screen.getByText('Pause at')).toBeInTheDocument();
  });

  it('calls startPipeline with default options when Start is clicked', async () => {
    const user = userEvent.setup();
    render(<PipelineControls projectId="proj-1" />);

    // Open config panel
    await user.click(screen.getByText('Start Run'));
    // Click Start button in panel
    await user.click(screen.getByRole('button', { name: 'Start' }));

    expect(mockStartPipeline).toHaveBeenCalledWith('proj-1', {
      human_review: true,
      ai_loops: 1,
      stop_point: 'after_all',
    });
  });

  it('calls cancelPipeline when Cancel is clicked', async () => {
    const user = userEvent.setup();
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    await user.click(screen.getByText('Cancel'));

    expect(mockCancelPipeline).toHaveBeenCalledWith('proj-1');
  });

  it('shows Resume button when there is a completed run', () => {
    mockStoreValues({
      runs: [{ id: '1', run_number: 1, status: 'completed', run_id: 'r-1' }],
    });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Resume')).toBeInTheDocument();
  });

  it('does not show Resume button when there are no completed runs', () => {
    mockStoreValues({ runs: [] });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.queryByText('Resume')).not.toBeInTheDocument();
  });

  it('calls resumeRun when Resume config panel is used', async () => {
    const user = userEvent.setup();
    mockStoreValues({
      runs: [{ id: '1', run_number: 1, status: 'completed', run_id: 'r-1' }],
    });
    render(<PipelineControls projectId="proj-1" />);

    // Click Resume button to open config panel
    await user.click(screen.getByText('Resume'));

    // Should show resume-specific header
    expect(screen.getByText('Resume Run')).toBeInTheDocument();

    // Click the Resume confirm button inside the panel (second one — the first is the trigger)
    const resumeBtns = screen.getAllByRole('button', { name: 'Resume' });
    await user.click(resumeBtns[resumeBtns.length - 1]);

    expect(mockResumePipeline).toHaveBeenCalledWith('proj-1', {
      human_review: true,
      ai_loops: 1,
      stop_point: 'after_all',
    });
  });
});
