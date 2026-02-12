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
- Snapshot artifacts are stored under the config's `artifacts_dir` in `mcp_snapshots/`.
- `send_message` executes different UI sequences depending on `screen_type`:
  - `hinge_discover_card`: uses the Discover composer path (`Like -> Edit/Add comment -> Send like`) when configured.
  - `hinge_chat`: types into the thread composer and taps `Send`.
- If Hinge shows the "out of free likes" paywall, the agent may classify the screen as `hinge_like_paywall` and attempt to back out.
