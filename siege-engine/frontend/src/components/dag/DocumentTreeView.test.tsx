import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentTreeView } from './DocumentTreeView';
import type { SearchableNode } from './PipelineDAG';

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
    hasArtifact: true,
  },
  {
    id: 'art-2',
    label: 'System Requirements',
    componentKey: null,
    status: 'approved',
    stageKey: 'system_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-3',
    label: 'System Architecture',
    componentKey: null,
    status: 'awaiting_review',
    stageKey: 'system_architecture',
    hasArtifact: true,
  },
  {
    id: 'art-4',
    label: 'Component Map',
    componentKey: null,
    status: 'approved',
    stageKey: 'component_map',
    hasArtifact: true,
  },
  // Component-level docs
  {
    id: 'art-5',
    label: 'Auth Requirements',
    componentKey: 'auth',
    status: 'approved',
    stageKey: 'component_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-6',
    label: 'Auth Architecture',
    componentKey: 'auth',
    status: 'stale',
    stageKey: 'component_architecture',
    hasArtifact: true,
  },
  {
    id: 'art-7',
    label: 'API Requirements',
    componentKey: 'api',
    status: 'pending',
    stageKey: 'component_requirements',
    hasArtifact: true,
  },
  // Sub-component docs
  {
    id: 'art-8',
    label: 'Auth Login Requirements',
    componentKey: 'auth.login',
    status: 'approved',
    stageKey: 'sub_component_requirements',
    hasArtifact: true,
  },
  {
    id: 'art-9',
    label: 'Auth Login Architecture',
    componentKey: 'auth.login',
    status: 'generating',
    stageKey: 'sub_component_architecture',
    hasArtifact: true,
  },
];

describe('DocumentTreeView', () => {
  beforeEach(() => {
    mockSelectArtifact.mockReset();
    mockSelectedArtifactId.mockReturnValue(null);
  });

  it('renders system-level docs at root level', () => {
    render(<DocumentTreeView nodes={sampleNodes} />);
    expect(screen.getByText('Project Document')).toBeInTheDocument();
    expect(screen.getByText('System Requirements')).toBeInTheDocument();
    expect(screen.getByText('System Architecture')).toBeInTheDocument();
    expect(screen.getByText('Component Map')).toBeInTheDocument();
  });

  it('renders Components folder', () => {
    render(<DocumentTreeView nodes={sampleNodes} />);
    expect(screen.getByText('Components')).toBeInTheDocument();
  });

  it('expands Components folder to show component folders', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Components folder starts expanded by default
    expect(screen.getByText('auth')).toBeInTheDocument();
    expect(screen.getByText('api')).toBeInTheDocument();
  });

  it('expands a component folder to show its docs', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Click the auth component folder to expand
    await user.click(screen.getByText('auth'));

    expect(screen.getByText('Auth Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
  });

  it('shows Sub-components folder inside a component', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Expand auth component
    await user.click(screen.getByText('auth'));

    expect(screen.getByText('Sub-components')).toBeInTheDocument();
  });

  it('expands Sub-components folder to show sub-component folders', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Expand auth
    await user.click(screen.getByText('auth'));
    // Expand Sub-components
    await user.click(screen.getByText('Sub-components'));

    expect(screen.getByText('login')).toBeInTheDocument();
  });

  it('shows sub-component docs when sub-component folder is expanded', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.click(screen.getByText('auth'));
    await user.click(screen.getByText('Sub-components'));
    await user.click(screen.getByText('login'));

    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();
  });

  it('calls selectArtifact when a document is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.click(screen.getByText('System Requirements'));

    expect(mockSelectArtifact).toHaveBeenCalledWith('art-2');
  });

  it('calls selectArtifact when a component doc is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Expand auth component
    await user.click(screen.getByText('auth'));
    await user.click(screen.getByText('Auth Requirements'));

    expect(mockSelectArtifact).toHaveBeenCalledWith('art-5');
  });

  it('collapses a folder when clicked twice', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Components folder starts expanded
    expect(screen.getByText('auth')).toBeInTheDocument();

    // Click to collapse
    await user.click(screen.getByText('Components'));
    expect(screen.queryByText('auth')).not.toBeInTheDocument();

    // Click to expand again
    await user.click(screen.getByText('Components'));
    expect(screen.getByText('auth')).toBeInTheDocument();
  });

  it('shows "No documents yet" when nodes array is empty', () => {
    render(<DocumentTreeView nodes={[]} />);
    expect(screen.getByText('No documents yet')).toBeInTheDocument();
  });

  it('shows status dots with correct colors', () => {
    render(<DocumentTreeView nodes={sampleNodes} />);
    // System Requirements has status 'approved' - check it has the green dot
    const sysReqRow = screen.getByText('System Requirements').closest('button');
    const dot = sysReqRow?.querySelector('.bg-green-500');
    expect(dot).toBeInTheDocument();
  });

  it('renders the search input', () => {
    render(<DocumentTreeView nodes={sampleNodes} />);
    expect(screen.getByPlaceholderText('Filter documents...')).toBeInTheDocument();
  });

  it('filters documents by label', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Auth');

    // Auth-related docs should be visible
    expect(screen.getByText('Auth Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();

    // Non-matching docs should be gone
    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();
    expect(screen.queryByText('System Requirements')).not.toBeInTheDocument();
    expect(screen.queryByText('API Requirements')).not.toBeInTheDocument();
  });

  it('auto-expands ancestor folders for search matches', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    // Search for a sub-component doc — should auto-expand all parent folders
    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Login');

    // The sub-component docs are visible without manual folder clicks
    expect(screen.getByText('Auth Login Requirements')).toBeInTheDocument();
    expect(screen.getByText('Auth Login Architecture')).toBeInTheDocument();

    // Ancestor folders should be visible too
    expect(screen.getByText('Components')).toBeInTheDocument();
    expect(screen.getByText('auth')).toBeInTheDocument();
    expect(screen.getByText('Sub-components')).toBeInTheDocument();
    expect(screen.getByText('login')).toBeInTheDocument();
  });

  it('shows match count badge', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Requirements');

    // Should match: System Requirements, Auth Requirements, API Requirements, Auth Login Requirements
    expect(screen.getByText('4 matches')).toBeInTheDocument();
  });

  it('shows singular "match" for single result', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'Project Document');

    expect(screen.getByText('1 match')).toBeInTheDocument();
  });

  it('shows "No matching documents" when search has no results', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'xyznonexistent');

    expect(screen.getByText('No matching documents')).toBeInTheDocument();
  });

  it('clears search and restores tree when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    const input = screen.getByPlaceholderText('Filter documents...');
    await user.type(input, 'Auth');

    // Non-matching doc hidden
    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();

    // Click clear button
    await user.click(screen.getByText('✕'));

    // All docs restored
    expect(screen.getByText('Project Document')).toBeInTheDocument();
    expect(input).toHaveValue('');
  });

  it('filters by component key', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'api');

    expect(screen.getByText('API Requirements')).toBeInTheDocument();
    expect(screen.queryByText('Auth Requirements')).not.toBeInTheDocument();
  });

  it('filters by status', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    await user.type(screen.getByPlaceholderText('Filter documents...'), 'stale');

    // Auth Architecture has status 'stale'
    expect(screen.getByText('Auth Architecture')).toBeInTheDocument();
    expect(screen.getByText('1 match')).toBeInTheDocument();
  });

  it('clears search on Escape key', async () => {
    const user = userEvent.setup();
    render(<DocumentTreeView nodes={sampleNodes} />);

    const input = screen.getByPlaceholderText('Filter documents...');
    await user.type(input, 'Auth');
    expect(screen.queryByText('Project Document')).not.toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(input).toHaveValue('');
    expect(screen.getByText('Project Document')).toBeInTheDocument();
  });
});
