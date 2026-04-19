// Cytoscape stylesheet for the Phase 10 FullDagView.
//
// Visual language mirrors the sidebar tree + the old DecompositionGraph
// where possible — blue for domain comps, purple for presentational,
// green for resps, amber for pending drafts, fuchsia for Phase 9
// staleness.
//
// Reachable-set highlight classes (`.reachable-down`, `.reachable-up`)
// are applied imperatively by FullDagView via `cy.batch()` on
// selection changes. The non-reachable case dims everything else.

import type { StylesheetCSS } from 'cytoscape';

export const fullDagStylesheet: StylesheetCSS[] = [
  {
    selector: 'node',
    css: {
      'background-color': '#374151',
      'border-width': 1,
      'border-color': '#4b5563',
      label: 'data(name)',
      color: '#e5e7eb',
      'font-size': 10,
      'text-valign': 'center',
      'text-halign': 'center',
      'text-wrap': 'wrap',
      'text-max-width': '140px',
      width: 70,
      height: 30,
      shape: 'round-rectangle',
    },
  },
  {
    selector: 'node[type = "feat"]',
    css: {
      'background-color': '#334155',
      'border-color': '#64748b',
      shape: 'round-rectangle',
      width: 120,
      height: 32,
    },
  },
  {
    selector: 'node[type = "resp-top"]',
    css: {
      'background-color': '#065f46',
      'border-color': '#10b981',
      width: 110,
      height: 30,
    },
  },
  {
    selector: 'node[type = "resp-sub"]',
    css: {
      'background-color': '#064e3b',
      'border-color': '#059669',
      width: 100,
      height: 26,
      'font-size': 9,
    },
  },
  {
    selector: 'node[type = "policy-top"]',
    css: {
      'background-color': '#78350f',
      'border-color': '#f59e0b',
      shape: 'pentagon',
      width: 100,
      height: 40,
    },
  },
  {
    selector: 'node[type = "policy-local"]',
    css: {
      'background-color': '#713f12',
      'border-color': '#d97706',
      shape: 'pentagon',
      width: 90,
      height: 34,
      'font-size': 9,
    },
  },
  {
    selector: 'node[type = "comp-top"]',
    css: {
      'background-color': '#1e3a8a',
      'border-color': '#3b82f6',
      'border-width': 2,
      width: 160,
      height: 56,
      'font-size': 12,
      'font-weight': 'bold',
    },
  },
  {
    selector: 'node[type = "comp-top"][kind = "presentational"]',
    css: {
      'background-color': '#581c87',
      'border-color': '#a855f7',
    },
  },
  {
    selector: 'node[type = "comp-sub"]',
    css: {
      'background-color': '#1f2937',
      'border-color': '#6b7280',
      width: 130,
      height: 44,
    },
  },
  {
    selector: 'node[type = "comp-sub"][kind = "presentational"]',
    css: {
      'background-color': '#3b0764',
      'border-color': '#7e22ce',
    },
  },
  {
    selector: 'node[type = "fanin"]',
    css: {
      'background-color': '#4c1d95',
      'border-color': '#c4b5fd',
      'border-width': 2,
      'border-style': 'dashed',
      shape: 'hexagon',
      width: 110,
      height: 44,
      color: '#ede9fe',
    },
  },
  {
    selector: 'node[type = "impl"]',
    css: {
      'background-color': '#1c1917',
      'border-color': '#a8a29e',
      shape: 'round-rectangle',
      width: 80,
      height: 22,
      'font-size': 8,
      color: '#e7e5e4',
    },
  },
  // External-context layer — dimmer than the primary layer so it
  // reads as context, not content.
  {
    selector:
      'node[type = "external-feat"], node[type = "external-resp"], node[type = "external-policy"]',
    css: {
      opacity: 0.7,
      'border-style': 'dashed',
    },
  },
  {
    selector: 'node[type = "external-feat"]',
    css: {
      'background-color': '#334155',
      'border-color': '#64748b',
    },
  },
  {
    selector: 'node[type = "external-resp"]',
    css: {
      'background-color': '#065f46',
      'border-color': '#10b981',
    },
  },
  {
    selector: 'node[type = "external-policy"]',
    css: {
      'background-color': '#78350f',
      'border-color': '#f59e0b',
      shape: 'pentagon',
    },
  },
  // Status badges. pendingDraft amber overlay, stale fuchsia overlay.
  // The two can stack — fuchsia wins for the border color so staleness
  // is the salient signal (pending is a subset of "something will
  // happen").
  {
    selector: 'node[pendingDraft]',
    css: {
      'border-color': '#f59e0b',
      'border-width': 4,
    },
  },
  {
    selector: 'node[isStale]',
    css: {
      'border-color': '#e879f9',
      'border-width': 4,
      'border-style': 'double',
    },
  },
  // Edges.
  {
    selector: 'edge',
    css: {
      width: 1.5,
      'line-color': '#6b7280',
      'target-arrow-color': '#6b7280',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge[edgeType = "decomposition"]',
    css: {
      'line-style': 'dashed',
      'line-color': '#10b981',
      'target-arrow-color': '#10b981',
      width: 1,
    },
  },
  {
    selector: 'edge[edgeType = "dependency"]',
    css: {
      'line-color': '#3b82f6',
      'target-arrow-color': '#3b82f6',
      width: 2,
    },
  },
  {
    selector: 'edge[edgeType = "domain_parent"]',
    css: {
      'line-style': 'dotted',
      'line-color': '#a855f7',
      'target-arrow-color': '#a855f7',
    },
  },
  {
    selector: 'edge[edgeType = "policy_application"]',
    css: {
      'line-color': '#f59e0b',
      'target-arrow-color': '#f59e0b',
      'line-style': 'dashed',
      width: 1.2,
    },
  },
  // Selection + reachable-set highlight.
  {
    selector: 'node:selected',
    css: {
      'border-color': '#fbbf24',
      'border-width': 4,
    },
  },
  {
    selector: '.reachable-down',
    css: {
      'line-color': '#fbbf24',
      'target-arrow-color': '#fbbf24',
      'border-color': '#fbbf24',
      width: 3,
    },
  },
  {
    selector: '.reachable-up',
    css: {
      'line-color': '#f472b6',
      'target-arrow-color': '#f472b6',
      'border-color': '#f472b6',
      width: 3,
    },
  },
  {
    selector: '.dimmed',
    css: {
      opacity: 0.25,
    },
  },
];
