# Hinge MCP Tooling

The local MCP server at `automation_service/mobile/hinge_agent_mcp.py` exposes a live Hinge control plane.

## Startup

```bash
./scripts/start-hinge-agent-mcp.sh
```

Transport: `stdio`.

## Tool Set

- `start_session(config_json_path, session_name="default")`
- `list_sessions()`
- `observe(session_name="default", include_screenshot=true)`
- `get_page_source(session_name="default", persist_snapshot_artifact=true)`
- `capture_screenshot(session_name="default", persist_snapshot_artifact=true)`
- `find_elements(session_name="default", using="xpath", value="", limit=10, include_text=true, include_rect=true)`
- `click_element(session_name="default", using="xpath", value="", index=0)`
- `type_into_element(session_name="default", using="xpath", value="", text="", index=0)`
- `tap_point(session_name="default", x=0, y=0)`
- `swipe_points(session_name="default", x1=0, y1=0, x2=0, y2=0, duration_ms=600)`
- `press_keycode(session_name="default", keycode=4, metastate=null)`
- `decide(session_name="default", command_query=null, mode="llm", include_screenshot=true)`
- `execute(session_name="default", action="wait", message_text=null, dry_run=null)`
- `step(session_name="default", command_query=null, mode="llm", execute_action=true, dry_run=null, include_screenshot=true)`
- `dump_state(session_name="default")`
- `action_catalog()`
- `profile_summary(profile_json_path)`
- `stop_session(session_name="default")`
- `close_all_sessions()`

## Notes

- Session state is in-memory per MCP process.
- `dry_run` defaults to the value in the config used in `start_session`.
- `step` is the preferred autonomous primitive for agents.
- Low-level tools (`find_elements`, `click_element`, `type_into_element`, `tap_point`, `swipe_points`, `press_keycode`) are for direct operator control when UI variants break high-level routines.
- Snapshot artifacts are stored under the config's `artifacts_dir` in `mcp_snapshots/`.
- `send_message` executes different UI sequences depending on `screen_type`:
  - `hinge_discover_card`: uses the Discover composer path (`Like -> Edit/Add comment -> Send like`) when configured.
  - `hinge_chat`: types into the thread composer and taps `Send`.
- If Hinge shows the "out of free likes" paywall, the agent may classify the screen as `hinge_like_paywall` and attempt to back out.
