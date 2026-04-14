# Catapult — Specification (v2)

## Vision

Catapult is a **design memory** system. It is not just a documentation tool and not just a code generator — it is the machine that holds the *why* behind every architectural decision, the *shape* of every component boundary, and the *history* of every revision. When an AI generates code, it does so informed by the full context of human decisions that preceded it. When a human reviews output, they see exactly where it sits in the design hierarchy and what upstream thinking produced it.

The core insight is that AI-generated code is only as good as the design thinking that guides it. A single massive prompt produces generic output. A structured graph of design entities — features feeding responsibilities feeding component architectures feeding plans feeding code — produces code that reflects genuine design intent. Catapult maintains this graph as a living artifact: event-sourced, reviewable, and always the authoritative source of truth for what the system is and why it was built that way.

This makes Catapult a *plan-before-you-code* machine. The design graph isn't scaffolding to be discarded after generation — it is the persistent design memory of the project. Changes flow through it: new features are routed to the right components, bug fixes propagate upward from affected code, refinements cascade through dependent nodes. The structured model evolves with the codebase because it *is* the codebase's design substrate.

For teams, this means onboarding becomes reading the graph. Architectural disputes become conversations anchored to specific nodes. Code review starts with design review. The system doesn't just generate — it remembers, and it holds teams accountable to their own design decisions.

---

Catapult is the industrial-strength successor to Siege Engine. It is an AI-powered design and code generation system that takes a project description and produces a complete structured model of the system and the code that implements it, through a reviewable pipeline.

The central design commitment: the **structured model is the source of truth**. Documents are *derived views* of the model. Users never edit document text directly — every write goes through the LLM via prose feedback, regeneration, and approval. The model is event-sourced; the current state is a projection of that event log; rebuilding the projection from the log must reproduce the same state byte-for-byte.

This specification is divided into two parts: **A. Requirements** (what the system does) and **B. Architecture** (what technologies are used and how). It describes the target design; it does not describe migration from any particular current state.

---

# Part A — Requirements

## A.1 Core concepts

*(to be filled in)*

## A.2 Flows

*(to be filled in)*

## A.3 Phases and generation order

*(to be filled in)*

## A.4 Projection sources, bootstrap nodes, and change plans

*(to be filled in)*

## A.5 Review and approval

*(to be filled in)*

## A.6 Flow lobby

*(to be filled in)*

## A.7 Concurrency and locking

*(to be filled in)*

## A.8 Resumability and recoverability

*(to be filled in)*

## A.9 Document storage model

*(to be filled in)*

## A.10 Git for code shipping

*(to be filled in)*

## A.11 Prompt and DAG configuration

*(to be filled in)*

## A.12 Credentials and token tracking

*(to be filled in)*

## A.13 Real-time updates and external integration

*(to be filled in)*

## A.14 Authentication and authorization

*(to be filled in)*

## A.15 Multi-project support

*(to be filled in)*

## A.16 Bootstrap flow

*(to be filled in)*

## A.17 AI coding assistant integration

*(to be filled in)*

## A.18 AI sandboxing

*(to be filled in)*

## A.19 AI chat interface — David

*(to be filled in)*

## A.20 Adoption and trust

*(to be filled in)*

## A.21 Operational invariants

*(to be filled in)*

---

# Part B — Architecture

*(to be filled in)*
