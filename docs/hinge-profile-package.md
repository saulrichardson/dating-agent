# Hinge Profile Package (Owned Contract)

The **profile package** is the repo’s “complete folder object” for a single Hinge Discover profile.

It is designed to be:

- **faithful**: store raw UI evidence (screenshots + UIAutomator XML)
- **actionable**: store a derived interaction map and an explicit `action_space`
- **traceable**: store enough context so downstream pipelines can reproduce decisions offline

This is intentionally a *UI-level* contract (what the user saw), not a reconstruction of Hinge’s internal data model.

## Contract: `hinge_profile_package.v1`

Capture output directory contains:

- `profile_package.json` (manifest)
- `base_bundle/` (a `hinge_profile_bundle.v1` scroll-sweep)
- `surfaces/` (optional probe surfaces captured after tapping “reachable” affordances)

`profile_package.json` contains:

- `contract_version`: `"hinge_profile_package.v1"`
- `captured_at`: ISO timestamp
- `expected_package`: e.g. `co.hinge.app`
- `screen_type`: expected `hinge_discover_card` for now
- `package_dir`: absolute path to package directory
- `base_bundle_path`: absolute path to `base_bundle/profile_bundle.json`
- `profile_fingerprint`: SHA-256 fingerprint for deduping (best-effort)
- `surfaces[]`: list of captured probe surfaces (each is a `surface.json` record)
- `probe_errors[]`: list of probe failures (explicit; no silent fallback)
- `action_space[]`: explicit actions inferred from captured surfaces

## How It’s Captured (CLI)

This capture is intentionally **side-effect minimizing**:

- it scroll-sweeps the profile (no likes / no messages)
- probes attempt to open secondary surfaces (More menu, composer) but do **not** press “Send like”

Command:

```bash
./venv/bin/python scripts/capture-hinge-profile-package.py --tag deep_dive
```

Outputs under:

`artifacts/proofs/hinge_profile_package_<timestamp>_<tag>/`

## Relationship To Bundles

- `hinge_profile_bundle.v1` is a **scroll-sweep** of multiple viewports (evidence + interaction targets).
- `hinge_profile_package.v1` is a **wrapper** that includes the base bundle + additional probe surfaces + a derived action space.

