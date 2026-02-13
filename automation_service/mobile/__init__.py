"""
Native mobile automation helpers (Android/iOS) built around Appium.

This package is intentionally small and "fail-fast":
- Capabilities are provided explicitly via JSON (no hidden defaults).
- App-specific locators are expected to be supplied by the user.
"""

from .appium_http_client import AppiumHTTPClient, AppiumHTTPError, WebDriverElementRef
from .flows import (
    run_mobile_smoke_test,
    run_mobile_accessibility_dump,
)
from .console import run_mobile_interactive_console, run_mobile_script
from .spec_runner import run_mobile_spec, MobileSpecRunResult, MobileSpecError
from .vertical_slices import run_vertical_inbox_probe, VerticalSliceResult, VerticalSliceError
from .offline_artifacts import (
    run_offline_artifact_extraction,
    OfflineArtifactExtractionResult,
    OfflineArtifactExtractionError,
)
from .live_hinge_agent import (
    run_live_hinge_agent,
    get_hinge_action_catalog,
    HingePersonaSpec,
    LiveHingeAgentResult,
    LiveHingeAgentError,
)
from .full_fidelity_hinge import (
    run_hinge_full_fidelity_capture,
    FullFidelityHingeResult,
    FullFidelityHingeError,
)

__all__ = [
    "AppiumHTTPClient",
    "AppiumHTTPError",
    "WebDriverElementRef",
    "run_mobile_smoke_test",
    "run_mobile_accessibility_dump",
    "run_mobile_interactive_console",
    "run_mobile_script",
    "run_mobile_spec",
    "MobileSpecRunResult",
    "MobileSpecError",
    "run_vertical_inbox_probe",
    "VerticalSliceResult",
    "VerticalSliceError",
    "run_offline_artifact_extraction",
    "OfflineArtifactExtractionResult",
    "OfflineArtifactExtractionError",
    "run_live_hinge_agent",
    "get_hinge_action_catalog",
    "HingePersonaSpec",
    "LiveHingeAgentResult",
    "LiveHingeAgentError",
    "run_hinge_full_fidelity_capture",
    "FullFidelityHingeResult",
    "FullFidelityHingeError",
]
