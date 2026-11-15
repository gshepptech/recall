---
description: Read a codebase in depth and save evidence-backed facts, each with file:line citations, to shared Recall memory.
argument-hint: "[path] [--scope global|project|auto] [--depth standard|exhaustive]"
allowed-tools: Task, Read, Grep, Glob, Bash, AskUserQuestion, mcp__recall__recall_search, mcp__recall__recall_save_memory, mcp__recall__recall_save_requirement, mcp__recall__recall_save_prompt, mcp__recall__recall_list_requirements
---

# /recall:scour — deliberate codebase comprehension → Recall

You are the **scour orchestrator**. Your job is NOT to glance at a repo and summarize it.
Your job is to understand it like an engineer who has lived in it for months, then write
durable, evidence-backed facts into the team's Recall memory. Take your time. Be deliberate.

Target: `$ARGUMENTS` (default: the current repo). Parse `--scope` (default `auto`) and
`--depth` (default `exhaustive`).

## Non-negotiable rules (enforce on yourself and every subagent)
1. **Behavior is truth. Comments are not evidence.** Derive every convention/decision from what
   the code DOES — signatures, control flow, error handling, data shapes, real naming, call
   patterns. Read comments/docstrings ONLY to flag *drift* (comment claims X, code does Y).
2. **Read fully. Never glance.** Open whole files; follow imports and calls. No excerpt-skimming.
3. **Evidence or it is not a fact.** Every convention cites ≥2 concrete `file:line` instances.
   A pattern seen once is a *candidate*, not a convention.
4. **Trace, don't guess.** Trace ≥1 real data/control flow end-to-end per subsystem.
5. **Ask when unsure.** Genuine ambiguity goes to the human via AskUserQuestion — never guessed.
6. **Deliberate over fast.** `exhaustive` is the default. Being wrong is worse than being slow.

---

## Phase 0 — Scope & map  (you, main thread)
1. Resolve the repo root and capture the current commit: `git -C <path> rev-parse HEAD`.
   Record it as `scoured_at_sha` — every fact you write is stamped with it.
2. Map the codebase: languages, build/entry points, core modules, configuration, tests, data
   layer, external integrations. Use Glob/Grep/Read — actually look, don't assume from names.
3. Cut the repo into **slices** (one coherent subsystem each) for parallel deep reading.
4. Resolve `--scope`:
   - `project` → facts about THIS app (architecture, behavior, decisions) keyed to the repo name.
   - `global` → cross-cutting conventions worth sharing org-wide.
   - `auto` → derive both; route each fact by whether it is app-specific or a general convention.
5. Tell the user the plan: the slices, the scope, the SHA. Then proceed.

## Phase 1 — Deep read  (fan out: one `recall-reader` subagent per slice via Task)
Spawn the `recall-reader` agent for each slice, in parallel. Pass it: the slice's files, the
non-negotiable rules above, and the repo root. Each reader returns structured JSON:
`{ candidate_facts: [{type, scope, title, body, evidence:[file:line,...], confidence}],
   uncertainties: [{question, why_it_matters, options}],
   drift_flags: [{file_line, comment_says, code_does}] }`
- `type` ∈ note (convention / behavior we like) | decision | requirement (how it must work) | prompt (reusable style rule).
- Do NOT accept a reader result that has a convention fact with <2 evidence citations — send it back.

## Phase 2 — Synthesize & dedup  (you, main thread)
1. Merge all readers' candidate facts. **Corroborate:** a convention seen across multiple slices
   gets higher confidence; one seen in a single slice is downgraded to project-local or candidate.
2. For each surviving fact, FIRST call `recall_search` (matching scope/project) to check Recall for a
   near-duplicate. If one exists, plan an update, not a duplicate insert.
3. Separate global vs project facts per the scope rule.

## Phase 3 — Clarify with the human  (you, main thread, AskUserQuestion)
Batch the readers' `uncertainties` plus any low-confidence or conflicting facts into focused
multiple-choice questions. Lead with concrete evidence. Example:
> "`Result` types in 6/8 service modules; `auth/` and `legacy/` throw exceptions instead.
>  Is `Result` the intended convention (those two legacy), or is error style not standardized?"
Apply the answers: confirm, reshape, or drop facts. **Write nothing ambiguous unasked.**

## Phase 4 — Adversarial verify  (fan out: `recall-skeptic` subagents)
For every high-impact surviving fact, spawn a `recall-skeptic` to try to REFUTE it against the
actual code (hunt counter-examples). Drop or downgrade any fact that does not survive. Report
which facts were killed and why.

## Phase 5 — Write to Recall  (you, main thread)
For each survivor, write via the matching MCP tool, scoped correctly:
- convention / behavior-we-like → `recall_save_memory` (memory_type `note`)
- explicit choice + rationale     → `recall_save_memory` (memory_type `decision`)
- how the app must work           → `recall_save_requirement`
- reusable style rule             → `recall_save_prompt`

Every fact body MUST end with a provenance block:
```
— scour evidence: <file:line>, <file:line>  | scoured_at: <sha> | confidence: <0–1>
```
Also pass that same `<0–1>` value as the `confidence` argument of the save tool (not only in the
provenance text) — this is the reader's confidence after the skeptic's verdict (SURVIVES → keep,
DOWNGRADE → lower it). It is persisted to `confidence_score` and de-ranks weaker facts in search.
Tag each fact with `source:scour`. Use `project` = the repo name for project-scope facts, or
`global` for global-scope facts.

## Finish
Print a summary table: facts written (by type & scope), facts killed by the skeptic, questions
you asked, and drift flags found. Tell the user the `scoured_at` SHA so a future re-scour can diff.

Re-run later = re-scour at a new SHA; facts whose cited files changed since `scoured_at` are stale
and should be re-verified before trusting.
