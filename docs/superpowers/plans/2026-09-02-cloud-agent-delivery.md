# Cloud-agent delivery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` with test-first verification.

**Goal:** Reduce cloud-agent foreground tail latency through opt-in automatic durable async delivery and make HTTP queue/service tails attributable.

**Architecture:** A small pure delivery policy consumes caller mode, latency budget and telemetry p95. HTTP maps eligible synchronous endpoints to existing async jobs before execution. Generation results expose bounded phase metadata; the existing telemetry schema persists it.

## Tasks

- [ ] Add red tests for delivery mode selection and phase-metadata extraction; run them to observe the missing-feature failure.
- [ ] Add the pure delivery policy and bounded HTTP p95 estimator.
- [ ] Apply delivery policy at eligible HTTP endpoints and forward options through the MCP surface.
- [ ] Publish generation queue/service metadata and record it in HTTP telemetry.
- [ ] Document canonical cloud-agent request/delivery/retry contract and the already-present cache, breaker and A/B paths.
- [ ] Run focused tests, compilation, full suite, self-test, health/status; record reusable evidence and release leases.
