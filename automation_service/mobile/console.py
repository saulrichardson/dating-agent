from __future__ import annotations

import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient, WebDriverElementRef
from .config import load_json_file, require_key
from .ui_xml_search import search_uiautomator_xml, suggest_locator


class MobileConsoleError(RuntimeError):
    pass


@dataclass
class MobileConsoleContext:
    client: AppiumHTTPClient
    artifacts_dir: Path
    last_page_source_xml: Optional[str] = None
    vars: dict[str, Any] = field(default_factory=dict)


def _timestamp() -> str:
    # High-resolution timestamp so repeated captures don't overwrite.
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    filename = f"{safe_stem}_{_timestamp()}.{ext.lstrip('.')}"
    return artifacts_dir / filename


def _require_int(token: str, *, name: str) -> int:
    try:
        return int(token)
    except Exception as e:
        raise MobileConsoleError(f"Expected integer for {name}, got: {token!r}") from e


def _resolve_element(
    ctx: MobileConsoleContext,
    *,
    using: str,
    value: str,
    index: int = 0,
) -> WebDriverElementRef:
    elements = ctx.client.find_elements(using=using, value=value)
    if not elements:
        raise MobileConsoleError(f"No elements found for locator using={using!r} value={value!r}")
    if index < 0:
        raise MobileConsoleError("index must be >= 0")
    if index >= len(elements):
        raise MobileConsoleError(
            f"Element index out of range: requested {index}, found {len(elements)} element(s)"
        )
    return elements[index]


def _print_help() -> None:
    print(
        "\n".join(
            [
                "",
                "Mobile console commands:",
                "  help",
                "  rect",
                "  screenshot [name]",
                "  source [name]",
                "  dump [limit]",
                "  search <query> [limit]",
                "  find <using> <value> [limit]",
                "  click <using> <value> [index]",
                "  type <using> <value> [index] <text...>",
                "  tap <x> <y>",
                "  swipe <x1> <y1> <x2> <y2> [duration_ms]",
                "  swipe_dir <up|down|left|right> [duration_ms]",
                "  sleep <seconds>",
                "  confirm <prompt...>",
                "  exit",
                "",
                "Notes:",
                "- If <using> contains spaces (e.g. accessibility id), quote it: \"accessibility id\"",
                "- If <value> contains spaces, quote it too.",
                "",
            ]
        )
    )


def run_mobile_console_command(
    ctx: MobileConsoleContext,
    command_line: str,
    *,
    mode: str,
) -> bool:
    """
    Execute a single console command.

    Returns False if the caller should exit the loop, True otherwise.
    """
    if mode not in {"interactive", "script"}:
        raise ValueError("mode must be 'interactive' or 'script'")

    line = (command_line or "").strip()
    if not line:
        return True
    if line.startswith("#"):
        return True

    try:
        parts = shlex.split(line)
    except ValueError as e:
        raise MobileConsoleError(f"Failed to parse command: {e}") from e

    if not parts:
        return True

    cmd = parts[0].lower()

    if cmd in {"exit", "quit"}:
        return False

    if cmd == "help":
        _print_help()
        return True

    if cmd == "rect":
        rect = ctx.client.get_window_rect()
        print(rect)
        return True

    if cmd == "sleep":
        if len(parts) != 2:
            raise MobileConsoleError("Usage: sleep <seconds>")
        seconds = float(parts[1])
        if seconds < 0:
            raise MobileConsoleError("sleep seconds must be >= 0")
        time.sleep(seconds)
        return True

    if cmd == "confirm":
        if len(parts) < 2:
            raise MobileConsoleError("Usage: confirm <prompt...>")
        prompt = " ".join(parts[1:])
        answer = input(f"{prompt} [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if mode == "script":
            raise MobileConsoleError("Confirmation declined; stopping script.")
        print("Canceled.")
        return True

    if cmd == "screenshot":
        name = parts[1] if len(parts) >= 2 else "mobile_screenshot"
        _ensure_dir(ctx.artifacts_dir)
        path = _artifact_path(artifacts_dir=ctx.artifacts_dir, stem=name, ext="png")
        path.write_bytes(ctx.client.get_screenshot_png_bytes())
        print(f"Wrote screenshot: {path}")
        return True

    if cmd == "source":
        name = parts[1] if len(parts) >= 2 else "mobile_page_source"
        _ensure_dir(ctx.artifacts_dir)
        path = _artifact_path(artifacts_dir=ctx.artifacts_dir, stem=name, ext="xml")
        xml = ctx.client.get_page_source()
        ctx.last_page_source_xml = xml
        path.write_text(xml, encoding="utf-8")
        print(f"Wrote page source: {path}")
        return True

    if cmd == "dump":
        limit = 200
        if len(parts) >= 2:
            limit = _require_int(parts[1], name="limit")
        xml = ctx.client.get_page_source()
        ctx.last_page_source_xml = xml
        strings = extract_accessible_strings(xml, limit=5000)[:limit]
        if not strings:
            print("(no accessible strings found)")
            return True
        for i, s in enumerate(strings, 1):
            print(f"{i:>3}. {s}")
        return True

    if cmd == "search":
        if len(parts) < 2:
            raise MobileConsoleError("Usage: search <query> [limit]")
        query = parts[1]
        limit = 30
        if len(parts) >= 3:
            limit = _require_int(parts[2], name="limit")

        xml = ctx.client.get_page_source()
        ctx.last_page_source_xml = xml

        matches = search_uiautomator_xml(xml, query=query, limit=limit)
        if not matches:
            print("No matches found.")
            return True

        print(f"Found {len(matches)} match(es):")
        for i, m in enumerate(matches, 1):
            locator = suggest_locator(m)
            locator_str = f"{locator[0]} -> {locator[1]}" if locator else "(no suggestion)"
            bounds_str = f"{m.bounds}" if m.bounds else "(no bounds)"
            print(f"{i:>2}. {locator_str} | {bounds_str}")
            if m.text:
                print(f"    text: {m.text}")
            if m.content_desc:
                print(f"    content-desc: {m.content_desc}")
            if m.resource_id:
                print(f"    resource-id: {m.resource_id}")
            if m.class_name:
                print(f"    class: {m.class_name}")
        return True

    if cmd == "find":
        if len(parts) < 3:
            raise MobileConsoleError("Usage: find <using> <value> [limit]")
        using = parts[1]
        value = parts[2]
        limit = 10
        if len(parts) >= 4:
            limit = _require_int(parts[3], name="limit")

        elements = ctx.client.find_elements(using=using, value=value)
        print(f"Found {len(elements)} element(s).")
        for i, el in enumerate(elements[:limit]):
            try:
                text = ctx.client.get_element_text(el).strip()
            except Exception:
                text = ""
            try:
                rect = ctx.client.get_element_rect(el)
            except Exception:
                rect = None
            summary = []
            if text:
                summary.append(f"text={text!r}")
            if rect:
                summary.append(f"rect={rect}")
            suffix = (" " + " ".join(summary)) if summary else ""
            print(f"  [{i}] element_id={el.element_id}{suffix}")
        return True

    if cmd == "click":
        if len(parts) < 3:
            raise MobileConsoleError("Usage: click <using> <value> [index]")
        using = parts[1]
        value = parts[2]
        index = 0
        if len(parts) >= 4:
            index = _require_int(parts[3], name="index")
        el = _resolve_element(ctx, using=using, value=value, index=index)
        ctx.client.click(el)
        return True

    if cmd == "type":
        if len(parts) < 4:
            raise MobileConsoleError("Usage: type <using> <value> [index] <text...>")
        using = parts[1]
        value = parts[2]
        # Support both:
        # - type <using> <value> <index> <text...>
        # - type <using> <value> <text...>   (defaults index=0)
        index = 0
        text_start = 3
        try:
            index = _require_int(parts[3], name="index")
            text_start = 4
        except MobileConsoleError:
            index = 0
            text_start = 3

        if len(parts) <= text_start:
            raise MobileConsoleError("Usage: type <using> <value> [index] <text...>")

        text = " ".join(parts[text_start:])
        el = _resolve_element(ctx, using=using, value=value, index=index)
        ctx.client.send_keys(el, text=text)
        return True

    if cmd == "tap":
        if len(parts) != 3:
            raise MobileConsoleError("Usage: tap <x> <y>")
        x = _require_int(parts[1], name="x")
        y = _require_int(parts[2], name="y")
        ctx.client.tap(x=x, y=y)
        return True

    if cmd == "swipe":
        if len(parts) not in {5, 6}:
            raise MobileConsoleError("Usage: swipe <x1> <y1> <x2> <y2> [duration_ms]")
        x1 = _require_int(parts[1], name="x1")
        y1 = _require_int(parts[2], name="y1")
        x2 = _require_int(parts[3], name="x2")
        y2 = _require_int(parts[4], name="y2")
        duration_ms = 600
        if len(parts) == 6:
            duration_ms = _require_int(parts[5], name="duration_ms")
        ctx.client.swipe(x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms)
        return True

    if cmd == "swipe_dir":
        if len(parts) not in {2, 3}:
            raise MobileConsoleError("Usage: swipe_dir <up|down|left|right> [duration_ms]")
        direction = parts[1].lower()
        duration_ms = 600
        if len(parts) == 3:
            duration_ms = _require_int(parts[2], name="duration_ms")

        rect = ctx.client.get_window_rect()
        x = rect["x"]
        y = rect["y"]
        width = rect["width"]
        height = rect["height"]

        # Avoid edges (gesture areas) to reduce accidental OS navigation.
        margin_x = max(int(width * 0.15), 10)
        margin_y = max(int(height * 0.15), 10)

        mid_x = x + width // 2
        mid_y = y + height // 2

        if direction == "up":
            start = (mid_x, y + height - margin_y)
            end = (mid_x, y + margin_y)
        elif direction == "down":
            start = (mid_x, y + margin_y)
            end = (mid_x, y + height - margin_y)
        elif direction == "left":
            start = (x + width - margin_x, mid_y)
            end = (x + margin_x, mid_y)
        elif direction == "right":
            start = (x + margin_x, mid_y)
            end = (x + width - margin_x, mid_y)
        else:
            raise MobileConsoleError("Direction must be one of: up, down, left, right")

        ctx.client.swipe(x1=start[0], y1=start[1], x2=end[0], y2=end[1], duration_ms=duration_ms)
        return True

    raise MobileConsoleError(f"Unknown command: {cmd!r}. Type 'help' for available commands.")


def run_mobile_interactive_console(
    *,
    appium_server_url: str,
    capabilities_json_path: str,
    artifacts_dir: str = "artifacts",
) -> None:
    """
    Start an Appium session and open a small REPL for exploring native UI automation.

    This is intentionally low-level and explicit so you can iterate quickly on
    real devices/emulators, discover locators, and then script repeatable flows.
    """
    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    try:
        ctx = MobileConsoleContext(client=client, artifacts_dir=Path(artifacts_dir).resolve())
        print("\n=== Mobile Interactive Console ===")
        print(f"Session started: {session_id}")
        print("Type 'help' for commands. Type 'exit' to end the session.\n")

        while True:
            try:
                line = input("mobile> ")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            try:
                should_continue = run_mobile_console_command(ctx, line, mode="interactive")
            except MobileConsoleError as e:
                print(f"ERROR: {e}")
                continue

            if not should_continue:
                break
    finally:
        client.delete_session()


def run_mobile_script(
    *,
    script_json_path: str,
) -> None:
    """
    Run a scripted set of mobile console commands from a JSON file.

    Schema (explicit, fail-fast):
      {
        "appium_server_url": "http://127.0.0.1:4723",
        "capabilities_json_path": "automation_service/mobile_examples/android_capabilities.example.json",
        "artifacts_dir": "artifacts",
        "pause_before_start": true,
        "commands": [
          "screenshot start",
          "search \"messages\" 20",
          "click \"accessibility id\" \"Messages\" 0"
        ]
      }

    Notes:
    - Lines starting with '#' are treated as comments.
    - The `confirm` command stops the script if you answer "no".
    """
    config = load_json_file(script_json_path)
    appium_server_url = require_key(config, "appium_server_url", context=script_json_path)
    capabilities_json_path = require_key(config, "capabilities_json_path", context=script_json_path)
    commands = require_key(config, "commands", context=script_json_path)
    artifacts_dir = str(config.get("artifacts_dir") or "artifacts")
    pause_before_start = bool(config.get("pause_before_start") or False)

    if not isinstance(appium_server_url, str) or not appium_server_url.strip():
        raise ValueError("script config 'appium_server_url' must be a non-empty string")
    if not isinstance(capabilities_json_path, str) or not capabilities_json_path.strip():
        raise ValueError("script config 'capabilities_json_path' must be a non-empty string")
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        raise ValueError("script config 'commands' must be a list of strings")

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    try:
        ctx = MobileConsoleContext(client=client, artifacts_dir=Path(artifacts_dir).resolve())
        print("\n=== Mobile Script Runner ===")
        print(f"Script: {script_json_path}")
        print(f"Session started: {session_id}")
        if pause_before_start:
            input("Session started. Navigate/login in the emulator, then press Enter to run the script...")

        for i, cmd in enumerate(commands, 1):
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue
            print(f"\n[{i}/{len(commands)}] $ {cmd}")
            run_mobile_console_command(ctx, cmd, mode="script")
    finally:
        client.delete_session()
