# Hinge Profile Operating Model (Agent-Ready)

This doc defines the **operating model** for agent-driven control of a Hinge Discover profile:

- how we capture profile state faithfully (what the UI showed)
- how we represent “everything we can do next” as an explicit `action_space`
- how we keep decisions executable and traceable end-to-end

This is intentionally a **UI-level** model (screenshots + UI XML), not a reverse-engineered internal Hinge model.

## Terms

**Surface**
- A single UI state (e.g. Discover card, comment composer, paywall overlay).

**Observation**
- A snapshot of a surface at a point in time: screenshot + UIAutomator XML + derived targets + derived content.

**Interaction Target**
- A tappable/typable affordance represented as:
  - `kind` (semantic category)
  - `bounds` + `tap` point
  - optional `label`/`context_text`
  - a `target_id` that is stable-ish within the capture

**Action Space**
- An explicit set of actions that can be executed next, derived from captured surfaces and targets.

**Action Plan**
- The decision output of an agent/LLM:
  - `action_id`
  - optional `target_id`
  - optional `message_text`
  - `reason`

## Storage Contracts

### 1) `hinge_profile_bundle.v1` (Scroll-Sweep)

Documented in `docs/hinge-profile-bundle.md`.

Used when we want “full-ish profile content” without opening secondary menus:
- capture N viewports (`view_00..view_N`)
- store each viewport’s screenshot + XML
- extract interaction targets per viewport
- derive `like_candidates[]` (per-item Like targets)

### 2) `hinge_profile_package.v1` (Complete Folder Object)

Documented in `docs/hinge-profile-package.md`.

The package is the “complete object in a folder”:

- includes a base scroll-sweep bundle
- optionally probes reachable surfaces (e.g. More menu, composer)
- derives an explicit `action_space[]` from *captured* UI evidence
- records failures explicitly in `probe_errors[]` (no silent fallback)

## What “Faithful Capture” Means Here

We can be faithful about:

- **UI evidence** (PNG + UIAutomator XML for each surface)
- **interaction geometry** (bounds + tap points)

We cannot guarantee:

- the app’s internal profile fields
- that every profile expands “More” sections automatically
- that photo/video content is extractable from XML (often it isn’t)

For downstream ranking/analysis, the screenshot is the source of truth. XML provides structure and targets.

## Extraction Methods (What We Actually Use)

### A) UIAutomator XML (structure + targets)

Pros:
- contains bounds and content-desc/text
- stable enough to create an interaction map

Cons:
- `clickable=\"false\"` does not mean “not actionable” (buttons are sometimes marked non-clickable)
- many tappable surfaces (photos/videos) may be unlabeled

Our extraction therefore:
- treats known action labels as actionable even if `clickable=false`
- includes a capped set of unlabeled tappable surfaces (`unlabeled_clickable`)

### B) Accessibility Strings (fast, brittle, good for classification)

Used for:
- screen classification (Discover vs chat vs overlay)
- cheap signal extraction (“Selfie Verified”, “Active today”, etc.)

### C) Screenshots (ground truth)

Used for:
- offline audits
- optional LLM vision conditioning
- OCR and richer extraction when accessibility strings are missing

## Interaction Target Kinds (Current)

These come from `automation_service/mobile/hinge_observation.py`:

- `like_button`: “Like photo/prompt/video prompt/…”
- `pass_button`: “Skip …”
- `comment_input`: “Add/Edit comment”
- `send_like`: “Send like”
- `send_rose`: “Send a Rose”
- `more_menu`: “More”
- `undo`: “Undo …”
- `media_unmute`: “Unmute …”
- `close_overlay`: “Close / Close sheet”
- `primary_surface`: large unlabeled tappable surface (best-effort; UI-dependent)
- `unlabeled_clickable`: capped unlabeled tappable surfaces
- `clickable_other`: capped drift/debug targets

This list is expected to grow as we capture more surfaces (photo viewer, report menu, etc.).

## Action Space (How We Make Decisions Executable)

The key principle:

> If the agent says “like”, it must also say *which Like* (via `target_id`) when multiple Like affordances exist.

We encode that as:

- `like` requires `target_id` on Discover when `like_candidates[]` is present
- `comment_like` requires `message_text` and a composer surface with `comment_input` + `send_like`

`hinge_profile_package.v1` includes a conservative `action_space[]` that only claims actions we can prove
are represented in the captured UI evidence.

## How This Enables Autonomous Control

1. Capture a package/bundle for the current profile.
2. Provide the decision engine:
   - `profile_summary` (cheap extraction)
   - `like_candidates[]` (explicit targets)
   - screenshots (ground truth)
3. Decision engine returns an Action Plan:
   - `{action, reason, message_text, target_id}`
4. Executor:
   - scrolls to the correct viewport if needed
   - taps the selected target
   - validates post-action state
   - writes artifacts (pre/post evidence + logs)

