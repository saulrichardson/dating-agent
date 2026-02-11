from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Optional

import requests


class AppiumHTTPError(RuntimeError):
    def __init__(
        self,
        *,
        message: str,
        method: str,
        url: str,
        status_code: Optional[int] = None,
        response_json: Optional[dict[str, Any]] = None,
        response_text: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.url = url
        self.status_code = status_code
        self.response_json = response_json
        self.response_text = response_text


@dataclass(frozen=True)
class WebDriverElementRef:
    element_id: str


def _extract_webdriver_value(payload: dict[str, Any]) -> Any:
    # W3C WebDriver typically wraps in {"value": ...}
    if "value" in payload:
        return payload["value"]
    return payload


def _extract_element_id(element_obj: Any) -> str:
    if not isinstance(element_obj, dict):
        raise ValueError(f"Unexpected element payload type: {type(element_obj)}")

    # W3C element key
    w3c_key = "element-6066-11e4-a52e-4f735466cecf"
    if w3c_key in element_obj and element_obj[w3c_key]:
        return str(element_obj[w3c_key])

    # Legacy JSONWire key
    if "ELEMENT" in element_obj and element_obj["ELEMENT"]:
        return str(element_obj["ELEMENT"])

    raise ValueError(f"Could not extract element id from payload keys: {list(element_obj.keys())}")


class AppiumHTTPClient:
    """
    Minimal Appium client using WebDriver HTTP endpoints.

    This avoids taking a dependency on the Appium Python client so we can keep
    local setup simple and compatible with the repo's existing dependencies.
    """

    def __init__(self, server_url: str, *, timeout_s: float = 30.0) -> None:
        if not server_url:
            raise ValueError("server_url is required")
        self.server_url = server_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session_id: Optional[str] = None
        self._session = requests.Session()

    def _request(self, method: str, path: str, *, json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.server_url}{path}"
        try:
            response = self._session.request(method, url, json=json, timeout=self.timeout_s)
        except Exception as e:
            raise AppiumHTTPError(
                message=f"Failed to call Appium server: {e}",
                method=method,
                url=url,
            ) from e

        response_text = None
        response_json: Optional[dict[str, Any]] = None
        try:
            response_json = response.json()
        except Exception:
            response_text = response.text

        if response.status_code >= 400:
            details = None
            if response_json is not None:
                value = _extract_webdriver_value(response_json)
                if isinstance(value, dict):
                    details = value.get("error") or value.get("message")
            raise AppiumHTTPError(
                message=f"Appium HTTP {response.status_code} for {method} {path}"
                + (f": {details}" if details else ""),
                method=method,
                url=url,
                status_code=response.status_code,
                response_json=response_json,
                response_text=response_text,
            )

        if response_json is None:
            raise AppiumHTTPError(
                message=f"Appium returned non-JSON response for {method} {path}",
                method=method,
                url=url,
                status_code=response.status_code,
                response_text=response_text,
            )

        return response_json

    def create_session(self, session_payload: dict[str, Any]) -> str:
        """
        Create an Appium session.

        `session_payload` must be a valid WebDriver session creation payload.
        Most commonly:
          {"capabilities": {"alwaysMatch": {...}, "firstMatch": [{}]}}

        This method does not guess defaults; it fails loudly if the payload is invalid.
        """
        if not isinstance(session_payload, dict) or not session_payload:
            raise ValueError("session_payload must be a non-empty dict")

        response = self._request("POST", "/session", json=session_payload)

        # Common shapes:
        # - {"value": {"sessionId": "...", "capabilities": {...}}}
        # - {"sessionId": "...", "value": {...}}
        value = _extract_webdriver_value(response)
        session_id = None
        if isinstance(value, dict):
            session_id = value.get("sessionId")
        session_id = session_id or response.get("sessionId")

        if not session_id:
            raise AppiumHTTPError(
                message="Appium did not return a sessionId in the create_session response",
                method="POST",
                url=f"{self.server_url}/session",
                response_json=response,
            )

        self.session_id = str(session_id)
        return self.session_id

    def delete_session(self) -> None:
        if not self.session_id:
            return
        session_id = self.session_id
        try:
            self._request("DELETE", f"/session/{session_id}")
        finally:
            self.session_id = None

    def get_page_source(self) -> str:
        self._require_session()
        response = self._request("GET", f"/session/{self.session_id}/source")
        value = _extract_webdriver_value(response)
        if not isinstance(value, str):
            raise AppiumHTTPError(
                message="Unexpected /source response shape (expected string)",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/source",
                response_json=response,
            )
        return value

    def get_screenshot_png_bytes(self) -> bytes:
        self._require_session()
        response = self._request("GET", f"/session/{self.session_id}/screenshot")
        value = _extract_webdriver_value(response)
        if not isinstance(value, str):
            raise AppiumHTTPError(
                message="Unexpected /screenshot response shape (expected base64 string)",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/screenshot",
                response_json=response,
            )
        try:
            return base64.b64decode(value)
        except Exception as e:
            raise AppiumHTTPError(
                message=f"Failed to decode screenshot base64: {e}",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/screenshot",
                response_json=response,
            ) from e

    def get_window_rect(self) -> dict[str, int]:
        self._require_session()
        response = self._request("GET", f"/session/{self.session_id}/window/rect")
        value = _extract_webdriver_value(response)
        if not isinstance(value, dict):
            raise AppiumHTTPError(
                message="Unexpected /window/rect response shape (expected object)",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/window/rect",
                response_json=response,
            )
        required = {"x", "y", "width", "height"}
        if not required.issubset(set(value.keys())):
            raise AppiumHTTPError(
                message=f"/window/rect missing keys (expected {sorted(required)})",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/window/rect",
                response_json=response,
            )
        return {k: int(value[k]) for k in required}

    def find_elements(self, *, using: str, value: str) -> list[WebDriverElementRef]:
        self._require_session()
        if not using or not value:
            raise ValueError("'using' and 'value' are required to find elements")
        response = self._request(
            "POST",
            f"/session/{self.session_id}/elements",
            json={"using": using, "value": value},
        )
        payload = _extract_webdriver_value(response)
        if not isinstance(payload, list):
            raise AppiumHTTPError(
                message="Unexpected /elements response shape (expected list)",
                method="POST",
                url=f"{self.server_url}/session/{self.session_id}/elements",
                response_json=response,
            )
        elements: list[WebDriverElementRef] = []
        for item in payload:
            elements.append(WebDriverElementRef(element_id=_extract_element_id(item)))
        return elements

    def perform_actions(self, actions: list[dict[str, Any]]) -> None:
        """
        Perform W3C input actions.

        This is the standard way to do coordinate-based touch input (tap/swipe)
        without relying on Appium-specific legacy endpoints.
        """
        self._require_session()
        if not actions or not isinstance(actions, list):
            raise ValueError("actions must be a non-empty list")

        self._request(
            "POST",
            f"/session/{self.session_id}/actions",
            json={"actions": actions},
        )

    def release_actions(self) -> None:
        """
        Release any active input actions (W3C).

        Not strictly required for single-shot interactions, but keeps the
        session clean when doing repeated actions.
        """
        self._require_session()
        self._request("DELETE", f"/session/{self.session_id}/actions")

    def tap(self, *, x: int, y: int) -> None:
        """
        Tap at viewport coordinates (x, y) using W3C touch actions.
        """
        self._require_session()
        if x is None or y is None:
            raise ValueError("x and y are required")

        actions = [
            {
                "type": "pointer",
                "id": "finger1",
                "parameters": {"pointerType": "touch"},
                "actions": [
                    {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y), "origin": "viewport"},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pause", "duration": 50},
                    {"type": "pointerUp", "button": 0},
                ],
            }
        ]

        try:
            self.perform_actions(actions)
        finally:
            # Some servers error on release if they consider it a no-op; ignore.
            try:
                self.release_actions()
            except Exception:
                pass

    def swipe(
        self,
        *,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 600,
    ) -> None:
        """
        Swipe from (x1, y1) to (x2, y2) over `duration_ms` milliseconds.
        """
        self._require_session()
        for name, v in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
            if v is None:
                raise ValueError(f"{name} is required")
        if duration_ms <= 0:
            raise ValueError("duration_ms must be > 0")

        actions = [
            {
                "type": "pointer",
                "id": "finger1",
                "parameters": {"pointerType": "touch"},
                "actions": [
                    {"type": "pointerMove", "duration": 0, "x": int(x1), "y": int(y1), "origin": "viewport"},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pause", "duration": 100},
                    {
                        "type": "pointerMove",
                        "duration": int(duration_ms),
                        "x": int(x2),
                        "y": int(y2),
                        "origin": "viewport",
                    },
                    {"type": "pointerUp", "button": 0},
                ],
            }
        ]

        try:
            self.perform_actions(actions)
        finally:
            try:
                self.release_actions()
            except Exception:
                pass

    def get_element_text(self, element: WebDriverElementRef) -> str:
        self._require_session()
        response = self._request("GET", f"/session/{self.session_id}/element/{element.element_id}/text")
        value = _extract_webdriver_value(response)
        if not isinstance(value, str):
            raise AppiumHTTPError(
                message="Unexpected element /text response shape (expected string)",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/element/{element.element_id}/text",
                response_json=response,
            )
        return value

    def get_element_rect(self, element: WebDriverElementRef) -> dict[str, int]:
        self._require_session()
        response = self._request("GET", f"/session/{self.session_id}/element/{element.element_id}/rect")
        value = _extract_webdriver_value(response)
        if not isinstance(value, dict):
            raise AppiumHTTPError(
                message="Unexpected element /rect response shape (expected object)",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/element/{element.element_id}/rect",
                response_json=response,
            )
        required = {"x", "y", "width", "height"}
        if not required.issubset(set(value.keys())):
            raise AppiumHTTPError(
                message=f"element /rect missing keys (expected {sorted(required)})",
                method="GET",
                url=f"{self.server_url}/session/{self.session_id}/element/{element.element_id}/rect",
                response_json=response,
            )
        return {k: int(value[k]) for k in required}

    def click(self, element: WebDriverElementRef) -> None:
        self._require_session()
        self._request("POST", f"/session/{self.session_id}/element/{element.element_id}/click", json={})

    def send_keys(self, element: WebDriverElementRef, *, text: str) -> None:
        self._require_session()
        if text is None:
            raise ValueError("text must not be None")
        # WebDriver spec accepts both `text` and `value`; many servers expect `value` as an array of chars.
        self._request(
            "POST",
            f"/session/{self.session_id}/element/{element.element_id}/value",
            json={"text": text, "value": list(text)},
        )

    def press_keycode(self, *, keycode: int, metastate: Optional[int] = None) -> None:
        """
        Press an Android keycode via Appium extension endpoint.

        Common values:
        - 4: Back
        - 3: Home
        - 66: Enter
        """
        self._require_session()
        if keycode is None:
            raise ValueError("keycode is required")
        payload: dict[str, Any] = {"keycode": int(keycode)}
        if metastate is not None:
            payload["metastate"] = int(metastate)
        self._request(
            "POST",
            f"/session/{self.session_id}/appium/device/press_keycode",
            json=payload,
        )

    def _require_session(self) -> None:
        if not self.session_id:
            raise RuntimeError("No active Appium session. Call create_session() first.")
