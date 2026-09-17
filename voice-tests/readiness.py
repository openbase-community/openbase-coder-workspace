"""Expiring, request-specific permits for ordinary acoustic stimuli."""
import time
import xml.etree.ElementTree as ET


def ios_ready(source: str) -> bool:
    tree = ET.fromstring(source)
    application = next((e for e in tree.iter() if e.get("type") == "XCUIElementTypeApplication"), None)
    if application is None:
        return False
    width, height = float(application.get("width", 0)), float(application.get("height", 0))
    def in_view(element):
        x, y = float(element.get("x", 0)), float(element.get("y", 0))
        w, h = float(element.get("width", 0)), float(element.get("height", 0))
        return w > 0 and h > 0 and 0 <= x + w / 2 < width and 0 <= y + h / 2 < height
    visible = [e for e in tree.iter() if e.get("visible") == "true"
        and e.get("enabled") == "true" and in_view(e)]
    listening = any("Listening" in e.get("label", "") for e in visible)
    mute = any(e.get("type") == "XCUIElementTypeButton" and e.get("label") == "Mute" for e in visible)
    unmute = any(e.get("type") == "XCUIElementTypeButton" and e.get("label") == "Unmute" for e in visible)
    return listening and mute and not unmute


def valid_permit(permit: dict, nonce: str, now_ms: float | None = None) -> bool:
    now = time.time_ns() / 1e6 if now_ms is None else now_ms
    age = now - permit.get("observed_at_unix_ms", 0)
    return (permit.get("nonce") == nonce and permit.get("allow") is True
        and permit.get("microphone_enabled") is True and permit.get("phone_state") == "listening"
        and permit.get("speaker_verified") is True and 0 <= age <= 1500)
