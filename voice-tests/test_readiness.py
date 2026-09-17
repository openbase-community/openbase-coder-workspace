import unittest

from readiness import ios_ready, android_ready, valid_permit


class ReadinessTests(unittest.TestCase):
    def test_android_requires_connected_room_and_live_mic_in_viewport(self):
        nodes = ['<node bounds="[0,0][1080,2400]" displayed="true" enabled="true">']
        for text in ("Listening…", "connected", "active"):
            nodes.append(f'<node text="{text}" bounds="[100,300][300,400]" displayed="true" enabled="true"/>')
        for label in ("Mute", "End"):
            nodes.append(f'<node content-desc="{label}" bounds="[200,2100][300,2200]" displayed="true" enabled="true"/>')
        source = '<hierarchy>' + ''.join(nodes) + '</node></hierarchy>'
        self.assertTrue(android_ready(source))
        # UiAutomator2 emits Java class names as tags, unlike uiautomator dumps.
        self.assertTrue(android_ready(source.replace('<node', '<android.view.View').replace('</node>', '</android.view.View>')))
        self.assertFalse(android_ready(source.replace('content-desc="Mute"', 'content-desc="Unmute"')))
        self.assertFalse(android_ready(source.replace('text="connected"', 'text="disconnected"')))
        self.assertFalse(android_ready(source.replace('[200,2100][300,2200]', '[200,2500][300,2600]')))

    def test_listening_text_alone_does_not_allow_a_muted_phone(self):
        source = '<root><e type="XCUIElementTypeApplication" width="390" height="844"/><e width="40" height="40" visible="true" enabled="true" label="Listening..."/><e width="40" height="40" visible="true" enabled="true" type="XCUIElementTypeButton" label="Unmute"/></root>'
        self.assertFalse(ios_ready(source))
        connected = source.replace('label="Unmute"', 'label="Mute"').replace('</root>',
            '<e width="40" height="40" visible="true" enabled="true" type="XCUIElementTypeButton" label="End"/>'
            '<e width="40" height="40" visible="true" enabled="true" label="connected"/>'
            '<e width="40" height="40" visible="true" enabled="true" label="active"/></root>')
        self.assertTrue(ios_ready(connected))
        self.assertFalse(ios_ready(connected.replace('label="connected"', 'label="disconnected"')))
        self.assertFalse(ios_ready(connected.replace('label="End"', 'label="Start"')))
        self.assertFalse(ios_ready(source.replace('Listening...', 'Speaking...').replace('label="Unmute"', 'label="Mute"')))
        self.assertFalse(ios_ready(source.replace('label="Unmute"', 'label="Mute" y="900"')))

    def test_stale_or_reused_permit_never_triggers_speech(self):
        permit = {"nonce": "current", "allow": True, "observed_at_unix_ms": 1000,
            "microphone_enabled": True, "phone_state": "listening", "speaker_verified": True}
        self.assertTrue(valid_permit(permit, "current", 1200))
        self.assertFalse(valid_permit(permit, "previous", 1200))
        self.assertFalse(valid_permit(permit, "current", 2600))
        self.assertFalse(valid_permit(permit, "current", 900))
        permit["microphone_enabled"] = False
        self.assertFalse(valid_permit(permit, "current", 1200))


if __name__ == "__main__":
    unittest.main()
