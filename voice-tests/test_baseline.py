import copy
from datetime import datetime, timezone
import unittest
from baseline import validate_observed_provenance, validate_fixture_assets


class BaselineTests(unittest.TestCase):
    def fixture(self):
        heads = {"workspace": "a" * 40, "cli": "b" * 40, "super-agents": "c" * 40}
        observed = {"vm": "prepared", "observed_at": datetime.now(timezone.utc).isoformat(),
            "vm_source": {guest: {"head": heads[name], "tracked_dirty": False,
                "tracked_patch_sha256": "empty"} for name, guest in
                (("workspace", "."), ("cli", "cli"), ("super-agents", "super-agents"))}}
        return {"revisions": heads}, observed

    def test_requested_revision_is_not_proof_of_installed_code(self):
        provenance, observed = self.fixture()
        validate_observed_provenance(provenance, observed, "prepared")
        wrong = copy.deepcopy(provenance)
        wrong["revisions"]["cli"] = "d" * 40
        with self.assertRaises(ValueError): validate_observed_provenance(wrong, observed, "prepared")
        with self.assertRaises(ValueError): validate_observed_provenance(provenance, observed, "another")

    def test_guest_patches_require_the_reviewed_actual_digest(self):
        provenance, observed = self.fixture()
        observed["vm_source"]["."]["tracked_dirty"] = True
        observed["vm_source"]["."]["tracked_patch_sha256"] = "fixture-overrides"
        with self.assertRaises(ValueError): validate_observed_provenance(provenance, observed, "prepared")
        provenance["allowed_tracked_patches"] = {".": "fixture-overrides"}
        validate_observed_provenance(provenance, observed, "prepared")

    def test_old_observation_cannot_seal_current_coverage(self):
        provenance, observed = self.fixture()
        observed["observed_at"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError): validate_observed_provenance(provenance, observed, "prepared")

    def test_clone_assets_must_exist_and_match_the_sealed_digest(self):
        expected = {"Desktop/orange/briefing.md": "reviewed"}
        with self.assertRaises(ValueError): validate_fixture_assets(expected, {})
        with self.assertRaises(ValueError):
            validate_fixture_assets(expected, {"Desktop/orange/briefing.md": {"exists": True, "sha256": "changed"}})
        validate_fixture_assets(expected, {"Desktop/orange/briefing.md": {"exists": True, "sha256": "reviewed"}})
