# Batch workflow implementation plan
> Execute inline using executing-plans, then independent UI and code review.

Goal: AI-first script review, decomposed generation packages, and unified image conversation workspace.
Architecture: retain SQLite records/versions, add project-scoped workflow routes and immutable task snapshots; frontend consumes same boundary for simulated and future model services.
Tech: existing FastAPI / React / Konva stack; no additional dependencies.
Spec: docs/superpowers/specs/2026-11-02-batch-workflow-redesign.md (approved by user 开始).

## Global constraints
No real API calls. No lost data. Selected script modification never changes identity/order or neighbors. Discussion never starts generation. New results require explicit adoption. Image comments bind exact versions.

## Review focus
Range crossing batch boundaries; duplicate/missing episode mapping; repeated task submission; conversation changes after generation; historical image and annotations retained.

### Task 1: workflow persistence and tasks
Files: backend/workflow.py, app.py, store.py, tests/test_workflow.py.
Interfaces: GET/PUT outline-index/{id}; POST production-jobs; GET/POST conversations; POST candidates/{id}/adopt. Existing records/tasks GET remain authoritative.
- [x] Write failing tests for mapping validation, selective rewrite, discussion without tasks, immutable snapshots, adoption and idempotence.
- [x] Implement validated workflow routes and queued worker using existing task table.
- [x] Run backend tests and commit.

### Task 2: script review and package detail
Files: frontend/src/Production.tsx, Workflow.tsx, production.css, workflow.test.ts.
Interfaces: consume Task 1 endpoints; maintain ProductionProps and Scripts export.
- [x] Test outline parsing/selection and prompt composition.
- [x] Implement source-range generation dialog, correctable episode index, full11-column review, selected rewrite and candidate adoption.
- [x] Implement asset/version display, decomposed prompts, explicit override and discussion edits.
- [x] Run tests/build and commit.

### Task 3: image conversation workspace
Files: Images.tsx, AnnotationCanvas.tsx, Conversation.tsx, App.tsx, production.css.
Interfaces: conversations keyed by selected image/version refs, production-jobs receives exact conversation version and explicit plan.
- [x] Test zoom normalization and task snapshot with multiple image instructions.
- [x] Integrate thumbnail rail, large canvas, regional annotation composer, multi-image discussion and explicit generate action.
- [x] Add smooth pointer zoom, pan gestures, comparison/adoption, version context and persisted drafts.
- [x] Run tests/build and commit.

### Task 4: verification and independent review
- [x] Seed isolated representative data, use real browser to verify workflows and failures at1440/1280.
- [ ] Independent reviewer tests primary paths; fix material findings.
- [ ] Update docs with actual coverage and limitations, preserve local data, commit.
