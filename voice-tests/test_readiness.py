import unittest

from readiness import ios_ready, valid_permit


class ReadinessTests(unittest.TestCase):
    def test_listening_text_alone_does_not_allow_a_muted_phone(self):
        source = '<root><e type="XCUIElementTypeApplication" width="390" height="844"/><e width="40" height="40" visible="true" enabled="true" label="Listening..."/><e width="40" height="40" visible="true" enabled="true" type="XCUIElementTypeButton" label="Unmute"/></root>'
        self.assertFalse(ios_ready(source))
        self.assertTrue(ios_ready(source.replace('label="Unmute"', 'label="Mute"')))
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
