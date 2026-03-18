# Siege Engine 2 — Project Input Document

## Overview

Siege Engine 2 is a pipeline application that takes software projects from an initial idea to enterprise-scale production code quickly and iteratively. It does this by expanding user intent into a structured document tree, then walking that tree to produce and maintain living documentation and working code. The system is built with Elixir and Postgres.

## Core Concepts

### Two DAGs

The system is organized around two directed acyclic graphs:

1. **The Pipeline DAG** — Represents the workflow: the sequence of processing stages a flow moves through, including fan-out points and dependency ordering. This is the "how work gets done" view.

2. **The Document DAG** — Represents the artifacts: the tree of documents and code that the pipeline produces and maintains. Each node is a versioned document. Parent-child relationships reflect the decomposition from system-level down to leaf-level. This is the "what exists" view.

### Flows

Every interaction with the system happens through a **flow**. A flow is a unit of work that enters the pipeline, traverses the document tree, and produces changes. There are four flow types:

1. **Project Scaffolding** — The initial flow for a new project. Creates the full document tree from scratch: system-level docs, component docs, sub-component docs, and generated code. Everything is new.

2. **Refactors** — Structural changes that may reorganize components, merge or split sub-components, or change architectural patterns. These flows may add, remove, or restructure nodes in the document tree.

3. **Feature Requests** — Additive changes that extend existing functionality. These flows traverse the existing tree, modifying documents where the feature touches them and potentially adding new component or sub-component nodes.

4. **Bug Fixes** — Targeted changes that correct incorrect behavior. These flows are typically narrow, touching only the documents and code relevant to the bug.

### Flow Lifecycle

Every flow follows the same high-level lifecycle regardless of type:

1. **Input** — The user provides an input document describing what they want. This can range from a rough idea to a detailed specification.

2. **Expansion** — The system expands the input document into a detailed, unambiguous description of the change. This expanded document becomes the authoritative reference for the rest of the flow.

3. **Top-Down Traversal** — Starting from the top of the document tree (system level), the flow visits each stage, evaluating what needs to change. At each stage, the system decides which nodes are affected and processes only those.

4. **Leaf Processing** — At the leaves of the tree, the system produces concrete implementation: code generation, tests, and review.

## Document Tree Structure

Every project maintains a document tree with five stages. Each stage can contain one or more document nodes with arbitrary internal relationships, but every stage always contains at least an **architecture node**. The architecture node is the basis for calculating fan-out at that stage.

### Stage 1: System Level

Documents that describe the project as a whole. This includes system-wide requirements, architecture, constraints, and cross-cutting concerns. There is exactly one set of system-level documents per project.

### Stage 2: Component Level (Conditional Fan-Out)

Documents that describe each major component of the system. The fan-out from Stage 1 to Stage 2 is conditional — the system examines the system-level architecture to determine which components exist and which are affected by the current flow. Only affected components are visited. New components can be created here during scaffolding or feature flows.

### Stage 3: Sub-Component Level (Conditional Fan-Out)

Documents that describe each sub-component within a component. The fan-out from Stage 2 to Stage 3 is also conditional. The system examines each component's architecture to determine which sub-components exist and which are affected. Only affected sub-components are visited.

### Stage 4: Leaf Processing

Each of the three prior stages (system, component, sub-component) can have leaf processing. Leaf processing takes the documents from a given node and produces actionable implementation artifacts — detailed plans, interface definitions, or other artifacts that directly inform code generation.

### Stage 5: Code Generation and Review

For each leaf, the system generates code and then reviews it. Code generation takes as input the leaf's documents, its parent context, and the expanded input document for the current flow. Review validates the generated code against the architecture and requirements.

## Document Modification, Not Regeneration

When a flow visits a document node that already exists, the system **modifies** the existing document rather than regenerating it from scratch. This preserves prior decisions, accumulated detail, and human edits. Only new nodes (created during scaffolding or when new components/sub-components are added) are generated from scratch.

## Dependency-Aware Generation

At the conditional fan-out stages (Stages 2 and 3), the system does more than just determine which nodes to visit. It also charts **dependencies** between sibling nodes. For example, Component A may depend on Component B's API, or Sub-Component X may depend on Sub-Component Y's data model.

Generation proceeds in **dependency order**. When processing a node, the system provides:

- The outputs of the previous stage (its parent context)
- The outputs of its immediate dependencies (sibling nodes it depends on that have already been processed)
- The expanded input document for the current flow

This ensures that each node has access to the decisions made by the nodes it depends on, producing coherent and consistent documentation and code across the project.

## Human-in-the-Loop

The pipeline is not fully autonomous. At key points, the system pauses for human review. Users can approve, reject, or edit any document before the pipeline continues. Rejected documents trigger re-generation or manual correction. The system should support configurable review gates — some teams may want to review every document, others may only want to review at stage boundaries.

## Staleness and Incremental Processing

When a document is modified (either by the pipeline or by a human), all downstream documents that depend on it become **stale**. The system tracks staleness and can selectively re-process only the stale portions of the tree, rather than re-running the entire pipeline. This is essential for the iterative workflow — users should be able to make a small change at the system level and have it propagate efficiently to only the affected leaves.

## Real-Time Visibility

Users need to see what the pipeline is doing as it works. This includes which nodes are being processed, which are queued, which are complete, and which are waiting for review. Both DAGs (pipeline and document) should be visible and navigable in real time.
