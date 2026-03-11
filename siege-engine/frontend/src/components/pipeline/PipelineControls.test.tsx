import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PipelineControls } from './PipelineControls';

const mockStartPipeline = vi.fn();
const mockCancelPipeline = vi.fn();

vi.mock('../../store/pipelineStore', () => ({
  usePipelineStore: vi.fn(() => ({
    isRunning: false,
    isPaused: false,
    startPipeline: mockStartPipeline,
    cancelPipeline: mockCancelPipeline,
  })),
}));

import { usePipelineStore } from '../../store/pipelineStore';

function mockStoreValues(values: Record<string, unknown>) {
  vi.mocked(usePipelineStore).mockReturnValue({
    isRunning: false,
    isPaused: false,
    startPipeline: mockStartPipeline,
    cancelPipeline: mockCancelPipeline,
    ...values,
  } as ReturnType<typeof usePipelineStore>);
}

describe('PipelineControls', () => {
  beforeEach(() => {
    mockStartPipeline.mockReset();
    mockCancelPipeline.mockReset();
    mockStoreValues({});
  });

  it('shows Start (Gated) and Start (Async) buttons when not running', () => {
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Start (Gated)')).toBeInTheDocument();
    expect(screen.getByText('Start (Async)')).toBeInTheDocument();
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument();
  });

  it('shows Cancel button when running', () => {
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.queryByText('Start (Gated)')).not.toBeInTheDocument();
    expect(screen.queryByText('Start (Async)')).not.toBeInTheDocument();
  });

  it('shows "Pipeline paused for review" when isPaused', () => {
    mockStoreValues({ isRunning: true, isPaused: true });
    render(<PipelineControls projectId="proj-1" />);

    expect(screen.getByText('Pipeline paused for review')).toBeInTheDocument();
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

  it('calls startPipeline with "gated" when Start (Gated) is clicked', async () => {
    const user = userEvent.setup();
    render(<PipelineControls projectId="proj-1" />);

    await user.click(screen.getByText('Start (Gated)'));

    expect(mockStartPipeline).toHaveBeenCalledWith('proj-1', 'gated');
  });

  it('calls startPipeline with "async" when Start (Async) is clicked', async () => {
    const user = userEvent.setup();
    render(<PipelineControls projectId="proj-1" />);

    await user.click(screen.getByText('Start (Async)'));

    expect(mockStartPipeline).toHaveBeenCalledWith('proj-1', 'async');
  });

  it('calls cancelPipeline when Cancel is clicked', async () => {
    const user = userEvent.setup();
    mockStoreValues({ isRunning: true });
    render(<PipelineControls projectId="proj-1" />);

    await user.click(screen.getByText('Cancel'));

    expect(mockCancelPipeline).toHaveBeenCalledWith('proj-1');
  });
});
