import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DAGSearchBar } from './PipelineDAG';
import type { SearchableNode } from './PipelineDAG';

const mockSelectArtifact = vi.fn();
const mockSelectStage = vi.fn();
const mockSetCenter = vi.fn();
const mockGetNode = vi.fn(() => ({ position: { x: 0, y: 0 }, width: 220, height: 100 }));

// Stub @xyflow/react
vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    setCenter: mockSetCenter,
    getNode: mockGetNode,
  }),
}));

vi.mock('../../store/dagStore', () => ({
  useDAGStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      selectArtifact: mockSelectArtifact,
      selectStage: mockSelectStage,
    })
  ),
}));

const sampleNodes: SearchableNode[] = [
  {
    id: 'node-1',
    label: 'System Requirements',
    componentKey: null,
    status: 'approved',
    stageKey: 'system_requirements',
    artifactType: 'system_requirements',
    hasArtifact: true,
  },
  {
    id: 'node-2',
    label: 'Architecture',
    componentKey: 'auth-module',
    status: 'pending',
    stageKey: 'system_architecture',
    artifactType: 'system_architecture',
    hasArtifact: false,
  },
  {
    id: 'node-3',
    label: 'Code Generation',
    componentKey: 'auth-module',
    status: 'running',
    stageKey: 'code_generation',
    artifactType: 'code',
    hasArtifact: false,
  },
  {
    id: 'node-4',
    label: 'Test Plan',
    componentKey: null,
    status: 'awaiting_review',
    stageKey: 'test_plan',
    artifactType: 'high_level_plan',
    hasArtifact: true,
  },
];

describe('DAGSearchBar', () => {
  beforeEach(() => {
    mockSelectArtifact.mockReset();
    mockSelectStage.mockReset();
    mockSetCenter.mockReset();
    mockGetNode.mockReset();
    mockGetNode.mockReturnValue({ position: { x: 0, y: 0 }, width: 220, height: 100 });
  });

  it('renders with "Search nodes..." placeholder', () => {
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);
    expect(screen.getByPlaceholderText('Search nodes...')).toBeInTheDocument();
  });

  it('filters nodes by label', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'Architecture');

    expect(screen.getByText('Architecture')).toBeInTheDocument();
    expect(screen.queryByText('Test Plan')).not.toBeInTheDocument();
  });

  it('filters nodes by componentKey', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'auth-module');

    // Both Architecture and Code Generation have auth-module
    expect(screen.getByText('Architecture')).toBeInTheDocument();
    expect(screen.getByText('Code Generation')).toBeInTheDocument();
    expect(screen.queryByText('System Requirements')).not.toBeInTheDocument();
  });

  it('filters nodes by status', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'running');

    expect(screen.getByText('Code Generation')).toBeInTheDocument();
    expect(screen.queryByText('Architecture')).not.toBeInTheDocument();
  });

  it('filters nodes by stageKey (with underscores replaced by spaces)', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'code generation');

    expect(screen.getByText('Code Generation')).toBeInTheDocument();
    expect(screen.queryByText('Architecture')).not.toBeInTheDocument();
  });

  it('shows "No matches" when no nodes match the query', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'nonexistent');

    expect(screen.getByText('No matches')).toBeInTheDocument();
  });

  it('calls selectStage when a node is clicked in pipeline variant', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'Architecture');
    await user.click(screen.getByText('Architecture'));

    expect(mockSelectStage).toHaveBeenCalledWith('system_architecture');
  });

  it('calls selectArtifact when a node with artifact is clicked in documents variant', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="documents" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'System Requirements');
    await user.click(screen.getByText('System Requirements'));

    expect(mockSelectArtifact).toHaveBeenCalledWith('node-1');
  });

  it('clears search when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    const input = screen.getByPlaceholderText('Search nodes...');
    await user.type(input, 'Architecture');
    expect(screen.getByText('Architecture')).toBeInTheDocument();

    // Click the clear (✕) button
    const clearBtn = screen.getByText('✕');
    await user.click(clearBtn);

    // Dropdown should be closed and input cleared
    expect(screen.queryByText('Architecture')).not.toBeInTheDocument();
    expect(input).toHaveValue('');
  });

  it('navigates results with arrow keys and selects with Enter', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'auth-module');

    // Two results: Architecture and Code Generation
    // Press ArrowDown to move to second result, then Enter to select
    await user.keyboard('{ArrowDown}{Enter}');

    expect(mockSelectStage).toHaveBeenCalledWith('code_generation');
  });

  it('closes dropdown on Escape', async () => {
    const user = userEvent.setup();
    render(<DAGSearchBar nodes={sampleNodes} variant="pipeline" />);

    await user.type(screen.getByPlaceholderText('Search nodes...'), 'Architecture');
    expect(screen.getByText('Architecture')).toBeInTheDocument();

    await user.keyboard('{Escape}');

    // Dropdown should close (results hidden)
    expect(screen.queryByText('No matches')).not.toBeInTheDocument();
  });
});
