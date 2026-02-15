# Hinge Profile Bundle (Owned Contract)

This repo captures Hinge "Discover" profiles as an **owned artifact contract** so that:

- downstream systems can reconstruct what the agent saw (screenshots + UI XML)
- decision engines can select a **specific Like target** (photo vs prompt) via `target_id`
- offline pipelines can score, audit, and replay decisions without needing live Appium

The bundle represents the *UI representation* of a profile (what a human sees), not Hinge's internal model.

## Where It’s Written

When `profile_bundle_capture.enabled=true` and the agent is on `hinge_discover_card`, the live agent writes bundles under:

`<artifacts_dir>/profile_bundles/<run_tag>/profile_<iteration>/`

Each directory contains:

- `profile_bundle.json` (manifest)
- `view_00.png`, `view_00.xml`
- `view_01.png`, `view_01.xml`
- ...

The number of `view_*` pairs is controlled by `profile_bundle_capture.max_views` and early-stop heuristics.

MCP variant:
- the MCP tool `capture_profile_bundle(...)` writes under `<artifacts_dir>/profile_bundles/<tag>/`.

## Contract: `hinge_profile_bundle.v1`

Top-level shape (high level):

- `contract_version`: `"hinge_profile_bundle.v1"`
- `captured_at`: ISO timestamp
- `screen_type`: e.g. `"hinge_discover_card"`
- `expected_package`: e.g. `"co.hinge.app"` (optional validation)
- `bundle_dir`: absolute path to the bundle directory
- `window_rect`: `{x,y,width,height}` from Appium
- `capture_cfg`: the capture configuration used
- `swipes_executed`: how many swipe-up actions were performed during the sweep
- `profile_fingerprint`: SHA-256 over the merged `profile_summary`
- `profile_summary`: merged extraction from all views (prompts/flags/etc.)
- `like_candidates[]`: derived targets the decision engine cares about most
- `views[]`: per-viewport captures including screenshots, XML, and interaction targets

### `views[]`

Each `views[i]` contains:

- `view_index` (int): 0..N-1
- `ts` (ISO timestamp)
- `package_name` (string|null)
- `screen_type` (string)
- `xml_sha256` (string)
- `screenshot_sha256` (string)
- `screenshot_relpath` (string): e.g. `view_00.png` (portable)
- `xml_relpath` (string): e.g. `view_00.xml` (portable)
- `screenshot_path` (absolute path string)
- `xml_path` (absolute path string)
- `accessible_strings[]` (list[string]): Android accessibility strings extracted from XML
- `profile_snapshot` (object): conservative extraction of profile content
- `interaction_targets[]` (list[object]): clickable map (see below)

### `interaction_targets[]`

An `interaction_target` is a JSON-serializable description of a clickable element:

- `target_id` (string): stable-ish identifier **within this capture**
- `kind` (string): category of interaction
- `label` (string): best-effort label (content-desc preferred). May be empty for unlabeled tappable surfaces.
- `bounds` (list[int]): `[x1, y1, x2, y2]`
- `tap` (object): `{ "x": int, "y": int }` (center of bounds)
- `view_index` (int)
- `node_ordinal` (int): ordinal index in the parsed UI XML node list
- `class_name` (string|null)
- `resource_id` (string|null)
- `area_px` (int): approximate bounds area in pixels
- `context_text[]` (optional list[string]): only for `kind="like_button"`; nearby content text used to disambiguate which Like to press

Currently recognized `kind` values:

- `like_button`
- `pass_button`
- `more_menu`
- `undo`
- `send_like`
- `send_rose`
- `comment_input`
- `media_unmute`
- `close_overlay`
- `primary_surface` (large unlabeled tappable surface; best-effort, UI-dependent)
- `unlabeled_clickable` (capped; unlabeled but actionable by attribute)
- `clickable_other` (capped; used for drift/debug)

### `like_candidates[]`

The top-level `like_candidates` list is a reduced view of `interaction_targets` for Like selection:

- `target_id`
- `label`
- `view_index`
- `context_text[]`
- `tap` (x/y)

This list is what gets surfaced into the live agent packet so the LLM (or deterministic policy) can pick a specific Like target.

## How `target_id` Works

`target_id` is:

- stable-ish for the duration of a capture (it is derived from `kind`, `view_index`, and the node ordinal)
- **not** guaranteed to be stable across app versions, sessions, devices, or even different captures of the same profile

Use it as a short-lived pointer for “press this Like affordance now”, not as a long-term identifier.

## What This Is Not (Yet)

This capture is intentionally best-effort. It does **not** (yet):

- expand “More” sections explicitly
- click into photo viewers to capture multiple photos per prompt
- guarantee it starts from the top of the profile (it starts from the current viewport)

Those are explicit extension points for higher-fidelity capture, but the contract is designed so you can add those behaviors while still preserving: `screenshots + XML + targets`.
