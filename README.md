# Concierge

Dating app automation with persona extraction and context management services.

## Services

This project includes three microservices:

- **Context Service** (`http://localhost:8080`) - Manages conversation context per user/match
- **Persona Service** (`http://localhost:8081`) - Extracts messaging style and provides context to Automation Service
- **Automation Service** (`http://localhost:8082`) - Playwright + Appium automation with a mobile-first CLI workflow

### Quick Start (All Services)

```bash
make start
```

This will build and start both services. View logs with `make logs`.

### Individual Service Management

Each service can also be managed independently:

```bash
# Context Service
cd context_service && make start

# Persona Service  
cd persona_service && make start

# Automation Service
cd automation_service && make start
```

See `make help` for all available commands.

## Setup

1. Create a virtual environment:
```bash
python3 -m venv venv
```

2. Activate the virtual environment:
```bash
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Automation Service CLI

**Important:** Always activate the virtual environment before running:

```bash
source venv/bin/activate
python -m automation_service.cli
```

## Mobile Automation (Android + Appium)

For apps that do **not** have a website (native-only), Playwright won’t work. The repo now includes
a minimal Android/Appium path for local exploration and future native automation.

### What’s implemented today

- **Mobile smoke test**: create an Appium session, save a screenshot + UI XML (`/source`) to `./artifacts/`
- **Accessibility dump**: parse the UI XML and print the accessible strings (best-effort)

These are intentionally “fail fast”: you provide capabilities explicitly (no hidden defaults).

### Current status

- ✅ Verified on a local **Android 14 (API 34) Google Play emulator**: Appium + UiAutomator2 can create a session and produce `artifacts/mobile_screenshot.png` and `artifacts/mobile_page_source.xml`.
- ✅ Appium failures caused by missing `ANDROID_SDK_ROOT`/`ANDROID_HOME` are avoided by using `./scripts/start-appium-server.sh` and `./scripts/start-appium-mcp.sh` (they export these env vars).

### Next step (prototype goal)

- Install and sign into the target app (e.g. Hinge) in the emulator, then capture `/source` and use the CLI XML search to discover stable locators.
- Once we have locators, implement a first “interaction loop” for one app screen: open inbox → open a thread → extract last N messages → send a reply.

### Local prerequisites (Android)

- An Appium server running locally (default `http://127.0.0.1:4723`)
- An Android device or emulator available to Appium (ADB + SDK tooling)

### Bootstrap an emulator (recommended for prototyping)

This creates an Android 14 (API 34) **Google Play** emulator (needed to install apps like Hinge from Play Store).

```bash
brew install android-platform-tools
brew install --cask android-commandlinetools

yes | sdkmanager --sdk_root=/opt/homebrew/share/android-commandlinetools \
  "emulator" \
  "platform-tools" \
  "platforms;android-34" \
  "system-images;android-34;google_apis_playstore;arm64-v8a"

echo "no" | avdmanager create avd \
  -n concierge_api34_play \
  -k "system-images;android-34;google_apis_playstore;arm64-v8a" \
  -d pixel_7
```

Start the emulator:

```bash
./scripts/start-android-emulator.sh
```

> You’ll need to sign into the Play Store inside the emulator to install apps.

### Start Appium locally

Install the Android driver (once):

```bash
./scripts/install-appium-uiautomator2.sh
```

Start the server:

```bash
./scripts/start-appium-server.sh
```

### Start the Appium MCP server (optional, for locator exploration)

If you want to use MCP to inspect screens and generate locators:

```bash
./scripts/start-appium-mcp.sh
```

> Note: this script uses Node 20 via `fnm` because we saw module-resolution issues running `appium-mcp`
> under Node 24 on this machine.

### Run the mobile smoke test / accessibility dump

```bash
source venv/bin/activate
python -m automation_service.cli
```

Choose:
- **Option 4**: Mobile smoke test (writes `artifacts/mobile_screenshot.png` and `artifacts/mobile_page_source.xml`)
- **Option 5**: Mobile accessibility dump (prints accessible strings)
- **Option 6**: Search captured UI XML to discover locator candidates
- **Option 7**: Mobile interactive console (live Appium REPL: `find`/`click`/`type`/`swipe`/`search`)
- **Option 8**: Run a repeatable mobile script from JSON (`automation_service/mobile_examples/mobile_script.example.json`)
- **Option 9**: Run app-specific vertical inbox probe (`automation_service/mobile_examples/vertical_hinge_inbox_probe.example.json` or `automation_service/mobile_examples/vertical_tinder_inbox_probe.example.json`)
- **Option 10**: Run declarative app-agnostic mobile spec (`automation_service/mobile_examples/mobile_spec.example.json`)
- **Option 11**: Offline artifact extraction (convert captured XML/screenshot artifacts into JSONL for downstream scoring/analysis)
- **Option 12**: Live Hinge agent (single Appium session; natural-language directive + profile policy + optional LLM decision engine)
- **Option 13**: Full-fidelity Hinge capture (raw XML + PNG + node graph + normalized profile/message streams)
  - Hinge deterministic tab routine example: `automation_service/mobile_examples/hinge_deterministic_tabs.example.json`
  - Hinge matches-state probe example: `automation_service/mobile_examples/hinge_matches_state_probe.example.json`
  - Hinge offline extraction config: `automation_service/mobile_examples/offline_artifact_extract.hinge.example.json`
  - Live Hinge agent config: `automation_service/mobile_examples/live_hinge_agent.example.json`
  - Live Hinge agent LLM config: `automation_service/mobile_examples/live_hinge_agent.llm.example.json`
  - Live Hinge autonomous swipe + opener config: `automation_service/mobile_examples/live_hinge_agent.autonomous_swipe.llm.example.json`
  - Live Hinge stress suite config: `automation_service/mobile_examples/live_hinge_stress_suite.example.json`
  - Full-fidelity capture config: `automation_service/mobile_examples/hinge_full_fidelity_capture.example.json`
  - Hinge preference profile: `automation_service/mobile_examples/hinge_agent_profile.example.json`
  - Hinge profile (creative/playful): `automation_service/mobile_examples/hinge_agent_profile.creative_playful.example.json`
  - Hinge profile (direct/intentional): `automation_service/mobile_examples/hinge_agent_profile.direct_intentional.example.json`
  - Hinge tool catalog + NL examples: `automation_service/mobile_examples/hinge_agent_tools.md`

Capabilities are loaded from JSON. A starter template is included at:
`automation_service/mobile_examples/android_capabilities.example.json`

If you want Appium to launch a specific installed app, see:
`automation_service/mobile_examples/android_capabilities.launch_app.example.json`

### Two Prototype Tracks (Tinder/Hinge)

This repo now includes two explicit prototyping paths for native app automation:

1. **App-agnostic spec runner** (`Option 10`)
   - JSON-driven actions with retries, waits, assertions, variable extraction, and template interpolation.
   - Example: `automation_service/mobile_examples/mobile_spec.example.json`

2. **App-specific vertical probes** (`Option 9`)
   - Curated locator candidates for specific apps (`hinge`, `tinder`) to quickly test inbox/navigation viability.
   - Examples:
     - `automation_service/mobile_examples/vertical_hinge_inbox_probe.example.json`
     - `automation_service/mobile_examples/vertical_tinder_inbox_probe.example.json`

### Deterministic Hinge Routines (Read-Only)

These routines avoid sending likes/messages and are meant for reliability testing.

1. Run a full bottom-nav traversal (Discover, Matches, Likes You, Standouts, Profile Hub):

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.spec_runner import run_mobile_spec
run_mobile_spec(
    spec_json_path="automation_service/mobile_examples/hinge_deterministic_tabs.example.json"
)
PY
```

2. Probe the Matches tab state (handles both "no matches yet" and chat-ready surfaces):

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.spec_runner import run_mobile_spec
run_mobile_spec(
    spec_json_path="automation_service/mobile_examples/hinge_matches_state_probe.example.json"
)
PY
```

3. Benchmark deterministic stability over repeated runs:

```bash
source venv/bin/activate
python scripts/run-mobile-spec-benchmark.py \
  --spec automation_service/mobile_examples/hinge_deterministic_tabs.example.json \
  --iterations 3
```

The benchmark writes a JSON report to `artifacts/mobile_spec_benchmark_<timestamp>.json`.

### Offline Artifact Dataset Export

If you already captured Appium artifacts (`*.xml` + optional `*.png`), export them to JSONL for offline pipelines:

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.offline_artifacts import run_offline_artifact_extraction
result = run_offline_artifact_extraction(
    config_json_path="automation_service/mobile_examples/offline_artifact_extract.hinge.example.json"
)
print(result)
PY
```

Outputs are written under `artifacts/offline_exports/`:
- `<prefix>_screens_<timestamp>.jsonl`: one row per screen (paths, screen type, strings, quality features)
- `<prefix>_nodes_<timestamp>.jsonl`: optional flattened node rows (`resource-id`, `text`, `bounds`, etc.)
- `<prefix>_summary_<timestamp>.json`: run stats and errors

For tighter datasets, set `package_allowlist` in the extraction config (for Hinge: `["co.hinge.app"]`) to exclude non-app captures like Play Store screens.

Each screen row also includes deterministic ranking fields:
- `quality_score_v1` (0..100)
- `quality_reasons_v1` (why that score was assigned)

Build a downstream swipe queue from extracted screens:

```bash
source venv/bin/activate
python scripts/build-hinge-swipe-candidates.py \
  --screens-jsonl artifacts/offline_exports/hinge_dataset_screens_<timestamp>.jsonl \
  --like-threshold 75 \
  --review-threshold 50 \
  --exclude-skip
```

This emits:
- `hinge_swipe_candidates_<timestamp>.jsonl` (decision rows: `like` / `review` / `pass` / `skip`)
- `hinge_swipe_candidates_<timestamp>.summary.json` (counts by decision)

### Live Hinge Agent (Natural Language + Preference Profile + LLM)

This run mode keeps one continuous Appium session and chooses actions in-loop.

Run deterministic policy mode:

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.live_hinge_agent import run_live_hinge_agent
run_live_hinge_agent(
    config_json_path="automation_service/mobile_examples/live_hinge_agent.example.json"
)
PY
```

Run LLM decision mode (requires `OPENAI_API_KEY`):

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.live_hinge_agent import run_live_hinge_agent
run_live_hinge_agent(
    config_json_path="automation_service/mobile_examples/live_hinge_agent.llm.example.json"
)
PY
```

Run full autonomous swipe + personalized opener mode (LLM + screenshot packet + rich persona):

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.live_hinge_agent import run_live_hinge_agent
run_live_hinge_agent(
    config_json_path="automation_service/mobile_examples/live_hinge_agent.autonomous_swipe.llm.example.json"
)
PY
```

How decisions are made:
- Build a live packet from the current screen (`screen_type`, extracted signals, available actions).
- Optionally attach a decision screenshot from the same frame (`decision_engine.llm.include_screenshot=true`).
- Apply a natural-language directive from `command_query` (for example: caps, message/swipe goal, one-shot navigation).
- Evaluate action via `decision_engine.type`:
  - `deterministic`: rule + score policy.
  - `llm`: model chooses one action from available action set and writes a first message when needed.
- Execute action in the same session (no restart) and append to the action log JSON artifact.
  - On Discover cards, `send_message` follows the native sequence: `Like -> Add comment -> Send like`.
  - If Hinge shows the "out of free likes" paywall, the agent classifies it as `hinge_like_paywall` and will try to back out.
- Persist packet-level telemetry with optional screenshot/XML references (`persist_packet_log`, `packet_capture_screenshot`, `packet_capture_xml`).
- Validate autonomous actions with post-action checks:
  - configurable `validation.require_screen_change_for`
  - stop on repeated failed transitions via `validation.max_consecutive_failures`

`dry_run` note:
- In `dry_run=true`, no taps/typing are executed. You will see decision selection and logging, but screen state does not advance.

Stress-test multiple paths:

```bash
source venv/bin/activate
python scripts/stress-test-live-hinge-agent.py \
  --base-config automation_service/mobile_examples/live_hinge_agent.example.json \
  --suite-config automation_service/mobile_examples/live_hinge_stress_suite.example.json
```

This writes a stress report under `artifacts/live_hinge_stress/` with:
- pass/fail split by `execution_failed` vs `assertion_failed`
- action execution coverage (`aggregate_covered_actions`, `aggregate_missing_actions`)
- action availability coverage (`aggregate_available_actions`, `aggregate_unavailable_actions`)
- validation metrics (`total_validation_failed`, `worst_repeat_action_streak`)

`live_hinge_stress_suite.example.json` supports per-scenario assertions:
- `max_validation_failed`
- `min_unique_actions`
- `max_repeat_action_streak`
- `expect_actions_any`, `expect_actions_all`
- `expect_screens_any`, `expect_screens_all`

### Hinge Agent MCP Server (Free-Form Agent Control)

For coding agents that need free-form control over a live Hinge session, run:

```bash
./scripts/start-hinge-agent-mcp.sh
```

This server keeps one Appium session alive and exposes tools:
- `start_session`: start from a `live_hinge_agent` config
- `observe`: capture current packet (screen type, score, available actions)
- `decide`: choose next action with deterministic or LLM mode
- `execute`: execute a concrete action
- `step`: one autonomous tick (`observe -> decide -> execute`)
- `stop_session`: close session cleanly

MCP entrypoint module:
- `automation_service/mobile/hinge_agent_mcp.py`

Reference docs:
- `docs/hinge-mcp-tools.md`
- `skills/hinge-autonomous-control/SKILL.md`

### Hinge Full-Fidelity Capture (Profile + Message Artifacts)

This mode captures high-fidelity records per frame so you can feed downstream profile scoring
and message tracking pipelines without losing raw context.

Run:

```bash
source venv/bin/activate
python - <<'PY'
from automation_service.mobile.full_fidelity_hinge import run_hinge_full_fidelity_capture
run_hinge_full_fidelity_capture(
    config_json_path="automation_service/mobile_examples/hinge_full_fidelity_capture.example.json"
)
PY
```

Outputs are written to a session folder under `artifacts/full_fidelity_hinge/`:
- `frames.jsonl`: one row per loop iteration (screen type, package, strings, hashes, capture paths)
- `profiles.jsonl`: normalized profile snapshots (name candidates, prompt/answer pairs, flags, fidelity score)
- `messages.jsonl`: normalized thread snapshots and deltas (new messages when chat surfaces change)
- `nodes.jsonl`: flattened node graph (`resource_id`, `text`, `content_desc`, `bounds`, etc.)
- `summary.json`: run counts and distribution metrics

Navigation behavior is explicit in config:
- `navigation.mode="observe"`: capture only (no taps)
- `navigation.mode="matches_poll"` with `navigation.execute=true`: attempt periodic routing to Matches and thread-open checks

### Credential Bootstrap (Manual Sign-In)

For Option 10 (declarative spec runner), you need a signed-in app state in the emulator first.

1. Start emulator:
   - `./scripts/start-android-emulator.sh`
2. Start Appium:
   - `./scripts/start-appium-server.sh`
3. In emulator Play Store, install target app and finish app login manually.
4. Run Option 10 with:
   - `automation_service/mobile_examples/mobile_spec.example.json`

To figure out the foreground app package/activity (for capabilities), run:

```bash
./scripts/android-current-activity.sh
```

### Configuration

- `CONTEXT_SERVICE_URL` (optional): Base URL for the Context Service used by chat history extraction.
  - Default: `http://localhost:8080` (Docker Compose)
  - If running Context Service locally (Option 3 in `context_service/README.md`): set `CONTEXT_SERVICE_URL=http://localhost:5000`

Or use the service directly:
```bash
cd automation_service && make start
```

## Deactivate

When you're done, deactivate the virtual environment:
```bash
deactivate
```
