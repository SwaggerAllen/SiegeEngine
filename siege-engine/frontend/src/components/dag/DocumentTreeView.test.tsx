import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentTreeView } from './DocumentTreeView';
import type { SearchableNode } from './PipelineDAG';
import type { DAGEdge } from './DocumentTreeView';

const mockSelectArtifact = vi.fn();
const mockSelectedArtifactId = vi.fn(() => null);

vi.mock('../../store/dagStore', () => ({
  useDAGStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      selectArtifact: mockSelectArtifact,
      selectedArtifactId: mockSelectedArtifactId(),
    })
  ),
}));

const sampleNodes: SearchableNode[] = [
  // System-level docs
  {
    id: 'art-1',
    label: 'Project Document',
    componentKey: null,
    status: 'approved',
    stageKey: 'project_doc',
    artifactType: 'project_doc',
    hasArtifact: true,
  },
  {
    id: 'art-2',
    label: 'System Requirements',
    componentKey: null,
    status: 'approved',
    stageKey: 'system_requirements',
    artifactType: 'system_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-3',
    label: 'System Architecture',
    componentKey: null,
    status: 'awaiting_review',
    stageKey: 'system_architecture',
    artifactType: 'system_architecture',
    hasArtifact: true,
  },
  {
    id: 'art-4',
    label: 'Component Map',
    componentKey: null,
    status: 'approved',
    stageKey: 'extract_components',
    artifactType: 'component_map',
    hasArtifact: true,
  },
  // Component-level docs
  {
    id: 'art-5',
    label: 'Auth Requirements',
    componentKey: 'auth',
    status: 'approved',
    stageKey: 'component_requirements',
    artifactType: 'component_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-6',
    label: 'Auth Architecture',
    componentKey: 'auth',
    status: 'approved',
    isStale: true,
    stageKey: 'component_architectures',
    artifactType: 'component_architecture',
    hasArtifact: true,
  },
  {
    id: 'art-7',
    label: 'API Requirements',
    componentKey: 'api',
    status: 'pending',
    stageKey: 'component_requirements',
    artifactType: 'component_requirements',
    hasArtifact: true,
  },
  // Sub-component map (fanout node)
  {
    id: 'art-10',
    label: 'Auth Sub-Component Map',
    componentKey: 'auth',
    status: 'approved',
    stageKey: 'extract_sub_components',
    artifactType: 'sub_component_map',
    hasArtifact: true,
  },
  // Sub-component docs
  {
    id: 'art-8',
    label: 'Auth Login Requirements',
    componentKey: 'auth.login',
    status: 'approved',
    stageKey: 'sub_component_requirements',
    artifactType: 'sub_component_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-9',
    label: 'Auth Login Architecture',
    componentKey: 'auth.login',
    status: 'generating',
    stageKey: 'sub_component_architectures',
    artifactType: 'sub_component_architecture',
    hasArtifact: true,
  },
];

const sampleEdges: DAGEdge[] = [
  // project_doc → system_requirements
  { id: 'e0', source: 'art-1', target: 'art-2', type: 'default', animated: false },
  // system_requirements → system_architecture
  { id: 'e1', source: 'art-2', target: 'art-3', type: 'default', animated: false },
  // system_requirements → component_map
  { id: 'e2', source: 'art-2', target: 'art-4', type: 'default', animated: false },
  // system_architecture → component_map
  { id: 'e3', source: 'art-3', target: 'art-4', type: 'default', animated: false },
  // component_map → auth requirements
  { id: 'e4', source: 'art-4', target: 'art-5', type: 'default', animated: false },
  // auth requirements → auth architecture
  { id: 'e5', source: 'art-5', target: 'art-6', type: 'default', animated: false },
  // component_map → api requirements
  { id: 'e6', source: 'art-4', target: 'art-7', type: 'default', animated: false },
  // auth architecture → auth sub-component map
  { id: 'e7', source: 'art-6', target: 'art-10', type: 'default', animated: false },
  // auth sub-component map → auth login requirements
  { id: 'e8', source: 'art-10', target: 'art-8', type: 'default', animated: false },
  // auth login requirements → auth login architecture
  { id: 'e9', source: 'art-8', target: 'art-9', type: 'default', animated: false },
];

describe('DocumentTreeView', () => {
  beforeEach(() => {
    mockSelectArtifact.mockReset();
    mockSelectedArtifactId.mockReturnValue(null);
  });

  it('renders system-level docs at root level', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    expect(screen.getByText('Project Document')).toBeInTheDocument();
    expect(screen.getByText('System Requirements')).toBeInTheDocument();
    expect(screen.getByText('System Architecture')).toBeInTheDocument();
    expect(screen.getByText('Component Map')).toBeInTheDocument();
  });

  it('renders Components folder', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    expect(screen.getByText('Components')).toBeInTheDocument();
  });

  it('expands Components folder to show component folders', async () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Components folder starts expanded by default
    expect(screen.getByText('auth')).toBeInTheDocument();
    expect(screen.getByText('api')).toBeInTheDocument();
  });

  it('expands a component folder to show its docs', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Click the auth component folder to expand
    await user.click(screen.getByText('auth'));

    expect(screen.getByText('Auth Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
  });

  it('shows Sub-components folder inside a component', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Expand auth component
    await user.click(screen.getByText('auth'));

    expect(screen.getByText('Sub-components')).toBeInTheDocument();
  });

  it('shows sub_component_map fanout node inside a component folder', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Expand auth component
    await user.click(screen.getByText('auth'));

    expect(screen.getByText('Auth Sub-Component Map')).toBeInTheDocument();
  });

  it('shows component_map fanout node at system level', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    expect(screen.getByText('Component Map')).toBeInTheDocument();
  });

  it('expands Sub-components folder to show sub-component folders', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.click(screen.getByText('auth'));
    await user.click(screen.getByText('Sub-components'));

    expect(screen.getByText('login')).toBeInTheDocument();
  });

  it('shows sub-component docs when sub-component folder is expanded', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.click(screen.getByText('auth'));
    await user.click(screen.getByText('Sub-components'));
    await user.click(screen.getByText('login'));

    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();
  });

  it('calls selectArtifact when a document is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.click(screen.getByText('System Requirements'));

    expect(mockSelectArtifact).toHaveBeenCalledWith('art-2');
  });

  it('calls selectArtifact when a component doc is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.click(screen.getByText('auth'));
    await user.click(screen.getByText('Auth Requirements'));

    expect(mockSelectArtifact).toHaveBeenCalledWith('art-5');
  });

  it('collapses a folder when clicked twice', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    expect(screen.getByText('auth')).toBeInTheDocument();

    await user.click(screen.getByText('Components'));
    expect(screen.queryByText('auth')).not.toBeInTheDocument();

    await user.click(screen.getByText('Components'));
    expect(screen.getByText('auth')).toBeInTheDocument();
  });

  it('shows "No documents yet" when nodes array is empty', () => {
    render(<DocumentTreeView nodes={[]} edges={[]} />);
    expect(screen.getByText('No documents yet')).toBeInTheDocument();
  });

  it('shows status dots with correct colors', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    const sysReqRow = screen.getByText('System Requirements').closest('button');
    const dot = sysReqRow?.querySelector('.bg-green-500');
    expect(dot).toBeInTheDocument();
  });

  // ── Search tests ────────────────────────────────────────────────────

  it('renders the search input', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    expect(screen.getByPlaceholderText('Filter documents...')).toBeInTheDocument();
  });

  it('filters documents by label', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Auth');

    expect(screen.getByText('Auth Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();

    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();
    expect(screen.queryByText('System Requirements')).not.toBeInTheDocument();
    expect(screen.queryByText('API Requirements')).not.toBeInTheDocument();
  });

  it('auto-expands ancestor folders for search matches', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Login');

    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();
    expect(screen.getByText('Components')).toBeInTheDocument();
    expect(screen.getByText('auth')).toBeInTheDocument();
    expect(screen.getByText('Sub-components')).toBeInTheDocument();
    expect(screen.getByText('login')).toBeInTheDocument();
  });

  it('shows match count badge', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Requirements');

    expect(screen.getByText('4 matches')).toBeInTheDocument();
  });

  it('shows singular "match" for single result', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Project Document');

    expect(screen.getByText('1 match')).toBeInTheDocument();
  });

  it('shows "No matching documents" when search has no results', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'xyznonexistent');

    expect(screen.getByText('No matching documents')).toBeInTheDocument();
  });

  it('clears search and restores tree when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    const input = screen.getByPlaceholderText('Filter documents...');
    await user.type(input, 'Auth');

    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();

    await user.click(screen.getByText('✕'));

    expect(screen.getByText('Project Document')).toBeInTheDocument();
    expect(input).toHaveValue('');
  });

  it('filters by component key', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'api');

    expect(screen.getByText('API Requirements')).toBeInTheDocument();
    expect(screen.queryByText('Auth Requirements')).not.toBeInTheDocument();
  });

  it('filters by status', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'approved');

    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
  });

  it('clears search on Escape key', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    const input = screen.getByPlaceholderText('Filter documents...');
    await user.type(input, 'Auth');
    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(input).toHaveValue('');
    expect(screen.getByText('Project Document')).toBeInTheDocument();
  });

  // ── Dependency / Dependents tests ───────────────────────────────────

  it('shows Dependencies label on nodes that have dependencies', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    // System Requirements depends on Project Document
    const depLabels = screen.getAllByText(/Dependencies \(\d+\)/);
    expect(depLabels.length).toBeGreaterThan(0);
  });

  it('shows Dependents label on nodes that have dependents', () => {
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);
    // Project Document has dependents (System Requirements)
    const depLabels = screen.getAllByText(/Dependents \(\d+\)/);
    expect(depLabels.length).toBeGreaterThan(0);
  });

  it('expands Dependencies to show dependency list', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // System Requirements has dependency on Project Document
    // Find the Dependencies label for System Requirements
    const depButtons = screen.getAllByText(/Dependencies \(1\)/);
    await user.click(depButtons[0]);

    // Should show "Project Document" as a dependency link
    // (it already appears at the top level, so check the dep list has it)
    const projDocButtons = screen.getAllByText('Project Document');
    // One at the top level, one in the dep list
    expect(projDocButtons.length).toBe(2);
  });

  it('expands Dependents to show dependent list', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Project Document has dependents: System Requirements
    const depButtons = screen.getAllByText(/Dependents \(1\)/);
    await user.click(depButtons[0]);

    // System Requirements should appear in the dependents list
    const sysReqButtons = screen.getAllByText('System Requirements');
    expect(sysReqButtons.length).toBe(2);
  });

  it('clicking a dependency link calls selectArtifact', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} edges={sampleEdges} />);

    // Expand Dependencies on System Requirements (depends on Project Document)
    const depButtons = screen.getAllByText(/Dependencies \(1\)/);
    await user.click(depButtons[0]);

    // Click the dependency link
    const projDocButtons = screen.getAllByText('Project Document');
    // The second one is in the dep list (smaller button)
    const depLink = projDocButtons.find((el) => el.closest('.text-xs'));
    expect(depLink).toBeTruthy();
    await user.click(depLink!);

    expect(mockSelectArtifact).toHaveBeenCalledWith('art-1');
  });

  it('works without edges (backward compatible)', () => {
    render(<DocumentTreeView nodes={sampleNodes} />);
    expect(screen.getByText('Project Document')).toBeInTheDocument();
    expect(screen.getByText('Components')).toBeInTheDocument();
    // No Dependencies/Dependents labels when no edges
    expect(screen.queryByText(/Dependencies/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Dependents/)).not.toBeInTheDocument();
  });
});
