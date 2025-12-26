# Concierge

Dating app automation with persona extraction and context management services.

## Services

This project includes three microservices:

- **Context Service** (`http://localhost:8080`) - Manages conversation context per user/match
- **Persona Service** (`http://localhost:8081`) - Extracts messaging style and provides context to Automation Service
- **Automation Service** (`http://localhost:8082`) - Playwright-based UI automation with CLI

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

Capabilities are loaded from JSON. A starter template is included at:
`automation_service/mobile_examples/android_capabilities.example.json`

If you want Appium to launch a specific installed app, see:
`automation_service/mobile_examples/android_capabilities.launch_app.example.json`

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
