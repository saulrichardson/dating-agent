from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient, WebDriverElementRef
from .config import load_json_file, require_key


class MobileSpecError(RuntimeError):
    pass


@dataclass(frozen=True)
class Locator:
    using: str
    value: str


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int
    sleep_s: float


@dataclass(frozen=True)
class MobileSpecRunResult:
    session_id: str
    executed_steps: int
    artifacts: list[Path]
    vars: dict[str, str]


@dataclass
class _RunContext:
    client: AppiumHTTPClient
    artifacts_dir: Path
    vars: dict[str, str] = field(default_factory=dict)
    artifacts: list[Path] = field(default_factory=list)


_VAR_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _as_non_empty_str(value: Any, *, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MobileSpecError(f"{context}: '{field}' must be a non-empty string")
    return value.strip()


def _as_positive_int(value: Any, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except Exception as e:
        raise MobileSpecError(f"{context}: '{field}' must be an integer") from e
    if parsed <= 0:
        raise MobileSpecError(f"{context}: '{field}' must be > 0")
    return parsed


def _as_non_negative_float(value: Any, *, field: str, context: str) -> float:
    try:
        parsed = float(value)
    except Exception as e:
        raise MobileSpecError(f"{context}: '{field}' must be a number") from e
    if parsed < 0:
        raise MobileSpecError(f"{context}: '{field}' must be >= 0")
    return parsed


def _parse_locator(raw: Any, *, context: str) -> Locator:
    if not isinstance(raw, dict):
        raise MobileSpecError(f"{context}: locator must be an object")
    using = _as_non_empty_str(raw.get("using"), field="using", context=context)
    value = _as_non_empty_str(raw.get("value"), field="value", context=context)
    return Locator(using=using, value=value)


def _parse_locators(raw: Any, *, context: str) -> list[Locator]:
    if not isinstance(raw, list) or not raw:
        raise MobileSpecError(f"{context}: locators must be a non-empty list")
    out: list[Locator] = []
    for idx, item in enumerate(raw, 1):
        out.append(_parse_locator(item, context=f"{context}: locators[{idx}]"))
    return out


def _parse_retry(raw: Any, *, context: str) -> RetryPolicy:
    if raw is None:
        return RetryPolicy(attempts=1, sleep_s=0.0)
    if not isinstance(raw, dict):
        raise MobileSpecError(f"{context}: retry must be an object")

    attempts = raw.get("attempts", 1)
    sleep_s = raw.get("sleep_s", 0.0)
    return RetryPolicy(
        attempts=_as_positive_int(attempts, field="attempts", context=f"{context}: retry"),
        sleep_s=_as_non_negative_float(sleep_s, field="sleep_s", context=f"{context}: retry"),
    )


def _template(raw: str, *, vars_map: dict[str, str], context: str) -> str:
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in vars_map:
            missing.append(key)
            return ""
        return str(vars_map[key])

    rendered = _VAR_PATTERN.sub(_replace, raw)
    if missing:
        missing_keys = ", ".join(sorted(set(missing)))
        raise MobileSpecError(f"{context}: missing template variable(s): {missing_keys}")
    return rendered


def _artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    filename = f"{safe_stem}_{_timestamp()}.{ext.lstrip('.')}"
    return artifacts_dir / filename


def _first_element(
    ctx: _RunContext,
    *,
    locator: Locator,
    index: int = 0,
) -> WebDriverElementRef:
    elements = ctx.client.find_elements(using=locator.using, value=locator.value)
    if not elements:
        raise MobileSpecError(
            f"No elements found for locator using={locator.using!r} value={locator.value!r}"
        )
    if index < 0:
        raise MobileSpecError("index must be >= 0")
    if index >= len(elements):
        raise MobileSpecError(
            f"Element index out of range for locator using={locator.using!r} value={locator.value!r}: "
            f"requested {index}, found {len(elements)} element(s)"
        )
    return elements[index]


def _first_element_any(
    ctx: _RunContext,
    *,
    locators: list[Locator],
    index: int = 0,
) -> tuple[Locator, WebDriverElementRef]:
    for locator in locators:
        elements = ctx.client.find_elements(using=locator.using, value=locator.value)
        if elements and index < len(elements):
            return locator, elements[index]
    locator_debug = "; ".join(f"{l.using}:{l.value}" for l in locators)
    raise MobileSpecError(f"No elements found for any locator candidate: {locator_debug}")


def _wait_for_locator(
    ctx: _RunContext,
    *,
    locator: Locator,
    timeout_s: float,
    poll_s: float,
    min_count: int,
) -> int:
    deadline = time.time() + timeout_s
    while time.time() <= deadline:
        elements = ctx.client.find_elements(using=locator.using, value=locator.value)
        if len(elements) >= min_count:
            return len(elements)
        time.sleep(poll_s)
    return 0


def _wait_for_any_locator(
    ctx: _RunContext,
    *,
    locators: list[Locator],
    timeout_s: float,
    poll_s: float,
    min_count: int,
) -> Optional[Locator]:
    deadline = time.time() + timeout_s
    while time.time() <= deadline:
        for locator in locators:
            elements = ctx.client.find_elements(using=locator.using, value=locator.value)
            if len(elements) >= min_count:
                return locator
        time.sleep(poll_s)
    return None


def _run_step_once(
    ctx: _RunContext,
    *,
    step: dict[str, Any],
    context: str,
) -> None:
    action = _as_non_empty_str(step.get("action"), field="action", context=context).lower()

    if action == "set_var":
        name = _as_non_empty_str(step.get("var"), field="var", context=context)
        raw_value = _as_non_empty_str(step.get("value"), field="value", context=context)
        ctx.vars[name] = _template(raw_value, vars_map=ctx.vars, context=context)
        print(f"  set_var: {name}={ctx.vars[name]!r}")
        return

    if action == "sleep":
        seconds = _as_non_negative_float(step.get("seconds"), field="seconds", context=context)
        time.sleep(seconds)
        return

    if action == "confirm":
        prompt = _as_non_empty_str(step.get("prompt"), field="prompt", context=context)
        answer = input(f"{prompt} [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            raise MobileSpecError(f"{context}: confirmation declined")
        return

    if action == "screenshot":
        name = _as_non_empty_str(step.get("name") or "mobile_spec_screenshot", field="name", context=context)
        _ensure_dir(ctx.artifacts_dir)
        path = _artifact_path(artifacts_dir=ctx.artifacts_dir, stem=name, ext="png")
        path.write_bytes(ctx.client.get_screenshot_png_bytes())
        ctx.artifacts.append(path)
        print(f"  screenshot: {path}")
        return

    if action == "source":
        name = _as_non_empty_str(step.get("name") or "mobile_spec_source", field="name", context=context)
        _ensure_dir(ctx.artifacts_dir)
        path = _artifact_path(artifacts_dir=ctx.artifacts_dir, stem=name, ext="xml")
        xml = ctx.client.get_page_source()
        path.write_text(xml, encoding="utf-8")
        ctx.artifacts.append(path)
        print(f"  source: {path}")

        save_to_var = step.get("save_to_var")
        if save_to_var is not None:
            key = _as_non_empty_str(save_to_var, field="save_to_var", context=context)
            ctx.vars[key] = xml
        return

    if action == "dump_strings":
        limit = _as_positive_int(step.get("limit", 120), field="limit", context=context)
        xml = ctx.client.get_page_source()
        strings = extract_accessible_strings(xml, limit=5000)[:limit]
        print(f"  dump_strings: {len(strings)} string(s)")
        for i, s in enumerate(strings, 1):
            print(f"    {i:>3}. {s}")
        save_to_var = step.get("save_to_var")
        if save_to_var is not None:
            key = _as_non_empty_str(save_to_var, field="save_to_var", context=context)
            ctx.vars[key] = "\n".join(strings)
        return

    if action == "wait_for":
        locator = _parse_locator(require_key(step, "locator", context=context), context=f"{context}: locator")
        timeout_s = _as_non_negative_float(step.get("timeout_s", 15), field="timeout_s", context=context)
        poll_s = _as_non_negative_float(step.get("poll_s", 0.5), field="poll_s", context=context)
        min_count = _as_positive_int(step.get("min_count", 1), field="min_count", context=context)
        count = _wait_for_locator(
            ctx,
            locator=locator,
            timeout_s=timeout_s,
            poll_s=max(poll_s, 0.05),
            min_count=min_count,
        )
        if count < min_count:
            raise MobileSpecError(
                f"{context}: wait_for timed out for locator using={locator.using!r} value={locator.value!r}"
            )
        print(f"  wait_for: matched {count} element(s)")
        return

    if action == "wait_for_any":
        locators = _parse_locators(require_key(step, "locators", context=context), context=f"{context}")
        timeout_s = _as_non_negative_float(step.get("timeout_s", 15), field="timeout_s", context=context)
        poll_s = _as_non_negative_float(step.get("poll_s", 0.5), field="poll_s", context=context)
        min_count = _as_positive_int(step.get("min_count", 1), field="min_count", context=context)
        matched_locator = _wait_for_any_locator(
            ctx,
            locators=locators,
            timeout_s=timeout_s,
            poll_s=max(poll_s, 0.05),
            min_count=min_count,
        )
        if matched_locator is None:
            raise MobileSpecError(f"{context}: wait_for_any timed out")
        print(
            "  wait_for_any: matched locator "
            f"using={matched_locator.using!r} value={matched_locator.value!r}"
        )
        return

    if action in {"click", "type", "extract_text", "assert_text_contains"}:
        locator = _parse_locator(require_key(step, "locator", context=context), context=f"{context}: locator")
        index = int(step.get("index", 0))
        if index < 0:
            raise MobileSpecError(f"{context}: index must be >= 0")
        element = _first_element(ctx, locator=locator, index=index)

        if action == "click":
            ctx.client.click(element)
            return

        if action == "type":
            raw_text = _as_non_empty_str(step.get("text"), field="text", context=context)
            resolved_text = _template(raw_text, vars_map=ctx.vars, context=context)
            ctx.client.send_keys(element, text=resolved_text)
            return

        text = ctx.client.get_element_text(element).strip()
        if action == "extract_text":
            var_name = _as_non_empty_str(step.get("var"), field="var", context=context)
            ctx.vars[var_name] = text
            print(f"  extract_text: {var_name}={text!r}")
            return

        expected = _as_non_empty_str(step.get("contains"), field="contains", context=context)
        expected_value = _template(expected, vars_map=ctx.vars, context=context)
        if expected_value not in text:
            raise MobileSpecError(
                f"{context}: assert_text_contains failed. expected substring={expected_value!r}, got={text!r}"
            )
        return

    if action in {"click_any", "extract_text_any"}:
        locators = _parse_locators(require_key(step, "locators", context=context), context=context)
        index = int(step.get("index", 0))
        if index < 0:
            raise MobileSpecError(f"{context}: index must be >= 0")
        used_locator, element = _first_element_any(ctx, locators=locators, index=index)
        print(f"  using locator: {used_locator.using!r} => {used_locator.value!r}")
        if action == "click_any":
            ctx.client.click(element)
            return
        var_name = _as_non_empty_str(step.get("var"), field="var", context=context)
        ctx.vars[var_name] = ctx.client.get_element_text(element).strip()
        print(f"  extract_text_any: {var_name}={ctx.vars[var_name]!r}")
        return

    if action == "assert_exists":
        locator = _parse_locator(require_key(step, "locator", context=context), context=f"{context}: locator")
        min_count = _as_positive_int(step.get("min_count", 1), field="min_count", context=context)
        count = len(ctx.client.find_elements(using=locator.using, value=locator.value))
        if count < min_count:
            raise MobileSpecError(
                f"{context}: assert_exists failed for locator using={locator.using!r} "
                f"value={locator.value!r}. found={count}, expected>={min_count}"
            )
        return

    if action == "tap":
        x = _as_positive_int(step.get("x"), field="x", context=context)
        y = _as_positive_int(step.get("y"), field="y", context=context)
        ctx.client.tap(x=x, y=y)
        return

    if action == "swipe_dir":
        direction = _as_non_empty_str(step.get("direction"), field="direction", context=context).lower()
        duration_ms = _as_positive_int(step.get("duration_ms", 600), field="duration_ms", context=context)

        rect = ctx.client.get_window_rect()
        x = rect["x"]
        y = rect["y"]
        width = rect["width"]
        height = rect["height"]
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
            raise MobileSpecError(f"{context}: direction must be one of up/down/left/right")

        ctx.client.swipe(
            x1=start[0],
            y1=start[1],
            x2=end[0],
            y2=end[1],
            duration_ms=duration_ms,
        )
        return

    raise MobileSpecError(f"{context}: unknown action {action!r}")


def _run_step_with_retry(
    ctx: _RunContext,
    *,
    step: dict[str, Any],
    context: str,
    default_retry: RetryPolicy,
) -> None:
    step_retry = _parse_retry(step.get("retry"), context=context)
    attempts = step_retry.attempts if step.get("retry") is not None else default_retry.attempts
    sleep_s = step_retry.sleep_s if step.get("retry") is not None else default_retry.sleep_s

    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            _run_step_once(ctx, step=step, context=context)
            return
        except Exception as e:
            last_error = e
            if attempt >= attempts:
                break
            print(f"  retrying step ({attempt}/{attempts}) after error: {e}")
            if sleep_s > 0:
                time.sleep(sleep_s)

    raise MobileSpecError(f"{context}: failed after {attempts} attempt(s): {last_error}")


def run_mobile_spec(
    *,
    spec_json_path: str,
) -> MobileSpecRunResult:
    """
    Run a declarative mobile automation spec from JSON.

    Schema (fail-fast):
      {
        "appium_server_url": "http://127.0.0.1:4723",
        "capabilities_json_path": "automation_service/mobile_examples/android_capabilities.example.json",
        "artifacts_dir": "artifacts",
        "pause_before_start": true,
        "vars": {"reply_text": "hey"},
        "default_retry": {"attempts": 2, "sleep_s": 0.4},
        "steps": [
          {"name": "Capture baseline", "action": "screenshot", "name": "baseline"},
          {"action": "click_any", "locators": [{"using": "accessibility id", "value": "Messages"}]},
          {"action": "wait_for_any", "locators": [{"using": "-android uiautomator", "value": "new UiSelector().textContains(\"Send\")"}], "timeout_s": 12}
        ]
      }
    """
    config = load_json_file(spec_json_path)

    appium_server_url = _as_non_empty_str(
        require_key(config, "appium_server_url", context=spec_json_path),
        field="appium_server_url",
        context=spec_json_path,
    )
    capabilities_json_path = _as_non_empty_str(
        require_key(config, "capabilities_json_path", context=spec_json_path),
        field="capabilities_json_path",
        context=spec_json_path,
    )
    steps_raw = require_key(config, "steps", context=spec_json_path)
    if not isinstance(steps_raw, list) or not steps_raw:
        raise MobileSpecError(f"{spec_json_path}: 'steps' must be a non-empty list")

    default_retry = _parse_retry(config.get("default_retry"), context=spec_json_path)
    pause_before_start = bool(config.get("pause_before_start") or False)
    artifacts_dir = Path(str(config.get("artifacts_dir") or "artifacts")).resolve()
    initial_vars_raw = config.get("vars", {})
    if not isinstance(initial_vars_raw, dict):
        raise MobileSpecError(f"{spec_json_path}: 'vars' must be an object when provided")
    initial_vars = {str(k): str(v) for k, v in initial_vars_raw.items()}

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    try:
        ctx = _RunContext(client=client, artifacts_dir=artifacts_dir, vars=initial_vars)
        _ensure_dir(ctx.artifacts_dir)

        print("\n=== Mobile Spec Runner ===")
        print(f"Spec: {Path(spec_json_path).resolve()}")
        print(f"Session started: {session_id}")
        if pause_before_start:
            input("Session started. Navigate/login in the emulator, then press Enter to run steps...")

        for idx, step in enumerate(steps_raw, 1):
            if not isinstance(step, dict):
                raise MobileSpecError(f"{spec_json_path}: steps[{idx}] must be an object")
            display_name = str(step.get("name") or f"step_{idx}")
            context = f"{spec_json_path}: steps[{idx}] ({display_name})"
            print(f"\n[{idx}/{len(steps_raw)}] {display_name}")
            _run_step_with_retry(ctx, step=step, context=context, default_retry=default_retry)

        return MobileSpecRunResult(
            session_id=session_id,
            executed_steps=len(steps_raw),
            artifacts=ctx.artifacts,
            vars=ctx.vars.copy(),
        )
    finally:
        client.delete_session()
