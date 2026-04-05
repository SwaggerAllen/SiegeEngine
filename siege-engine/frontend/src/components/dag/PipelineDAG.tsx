/**
 * PipelineDAG — public entry point for DAG visualization.
 *
 * Delegates to CytoscapeDAG (canvas-based, ELK layered layout) for
 * efficient rendering of large graphs with many edges.
 *
 * Re-exports SearchableNode and DAGSearchBar so existing consumers
 * (tabs, tests, DocumentTreeView) keep working without import changes.
 */

export { CytoscapeDAGView as PipelineDAG } from './CytoscapeDAG';
export type { SearchableNode } from './CytoscapeDAG';
export { DAGSearchBar } from './CytoscapeDAG';
