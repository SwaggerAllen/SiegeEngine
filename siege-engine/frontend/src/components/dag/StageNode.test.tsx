import { render, screen } from '@testing-library/react';
import { StageNode } from './StageNode';
import type { DAGNodeData } from '../../types/dag';

// Stub @xyflow/react to avoid ReactFlow context dependency
vi.mock('@xyflow/react', () => ({
  Handle: ({ type }: { type: string }) => <div data-testid={`handle-${type}`} />,
  Position: { Top: 'top', Bottom: 'bottom' },
}));

vi.mock('../../store/dagStore', () => ({
  useDAGStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      selectedArtifactId: null,
      selectedStageKey: null,
    })
  ),
}));

const mockForceRestart = vi.fn();
const mockCancelStage = vi.fn();
vi.mock('../../hooks/mutations/usePipelineMutations', () => ({
  useForceRestartStage: () => ({ mutateAsync: mockForceRestart, mutate: mockForceRestart }),
  useCancelStage: () => ({ mutateAsync: mockCancelStage, mutate: mockCancelStage }),
}));

const baseData: DAGNodeData = {
  label: 'Architecture',
  artifact_type: 'system_architecture',
  status: 'pending',
  is_stale: false,
  component_key: null,
  version: 0,
  stage_key: 'system_architecture',
  is_active: false,
  has_artifact: false,
  prompt_info: null,
};

describe('StageNode', () => {
  beforeEach(() => {});

  it('renders the node label', () => {
    render(<StageNode id="test-node" data={baseData} />);
    expect(screen.getByText('Architecture')).toBeInTheDocument();
  });

  it('renders status label "Pending" for pending status', () => {
    render(<StageNode id="test-node" data={baseData} />);
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('renders status label "Awaiting Review" for awaiting_review', () => {
    render(<StageNode id="test-node" data={{ ...baseData, status: 'awaiting_review' }} />);
    expect(screen.getByText('Awaiting Review')).toBeInTheDocument();
  });

  it('renders status label "Approved" for approved status', () => {
    render(<StageNode id="test-node" data={{ ...baseData, status: 'approved' }} />);
    expect(screen.getByText('Approved')).toBeInTheDocument();
  });

  it('renders "Input" label for project_doc artifact type', () => {
    render(<StageNode id="test-node" data={{ ...baseData, artifact_type: 'project_doc' }} />);
    expect(screen.getByText('Input')).toBeInTheDocument();
  });

  it('renders "Branching" label for component_map with pending status', () => {
    render(<StageNode id="test-node" data={{ ...baseData, artifact_type: 'component_map', status: 'pending' }} />);
    expect(screen.getByText('Branching')).toBeInTheDocument();
  });

  it('renders component_key when provided', () => {
    render(<StageNode id="test-node" data={{ ...baseData, component_key: 'auth-module' }} />);
    expect(screen.getByText('auth-module')).toBeInTheDocument();
  });

  it('does not render component_key when null', () => {
    render(<StageNode id="test-node" data={baseData} />);
    expect(screen.queryByText('auth-module')).not.toBeInTheDocument();
  });

  it('renders version badge when has_artifact and version > 0', () => {
    render(<StageNode id="test-node" data={{ ...baseData, has_artifact: true, version: 3 }} />);
    expect(screen.getByText('v3')).toBeInTheDocument();
  });

  it('does not render version badge when version is 0', () => {
    render(<StageNode id="test-node" data={{ ...baseData, has_artifact: true, version: 0 }} />);
    expect(screen.queryByText('v0')).not.toBeInTheDocument();
  });

  it('shows spinner for running status', () => {
    const { container } = render(<StageNode id="test-node" data={{ ...baseData, status: 'running' }} />);
    expect(container.querySelector('.stage-spinner')).toBeInTheDocument();
  });

  it('shows spinner for ai_reviewing status', () => {
    const { container } = render(<StageNode id="test-node" data={{ ...baseData, status: 'ai_reviewing' }} />);
    const spinner = container.querySelector('.stage-spinner');
    expect(spinner).toBeInTheDocument();
    expect(spinner).toHaveClass('stage-spinner--purple');
  });

  it('does not show spinner for pending status', () => {
    const { container } = render(<StageNode id="test-node" data={baseData} />);
    expect(container.querySelector('.stage-spinner')).not.toBeInTheDocument();
  });

  it('renders prompt info with formatted model name', () => {
    render(
      <StageNode id="test-node"
        data={{
          ...baseData,
          prompt_info: {
            stage_key: 'system_architecture',
            model: 'claude-sonnet-4-20250514',
            has_custom_config: false,
            template_key: 'architecture',
          },
        }}
      />
    );
    expect(screen.getByText('sonnet-4')).toBeInTheDocument();
  });

  it('renders "default model" when prompt_info.model is null', () => {
    render(
      <StageNode id="test-node"
        data={{
          ...baseData,
          prompt_info: {
            stage_key: 'system_architecture',
            model: null,
            has_custom_config: false,
            template_key: 'architecture',
          },
        }}
      />
    );
    expect(screen.getByText('default model')).toBeInTheDocument();
  });

  it('renders handles for ReactFlow connections', () => {
    render(<StageNode id="test-node" data={baseData} />);
    expect(screen.getByTestId('handle-target')).toBeInTheDocument();
    expect(screen.getByTestId('handle-source')).toBeInTheDocument();
  });
});
