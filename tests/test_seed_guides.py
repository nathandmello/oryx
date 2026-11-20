"""Keep historical private guides recognizable after public branding and template changes."""

import hashlib
import json
import subprocess
import unittest

import test_pm
import pm
import records
import upgrades


GUIDES = ("README.md", "context/README.md", "workspace/README.md")
RELEASES = (
    "c4122dea5ad5a9e4e65ec7e3c35d066f4b851bca",  # First purpose-based layout
    "1ecf2b97e2929d5a7cda9bf896eacb72bf9763c8",  # Later 0.3 guides
    "34483926be5d29b3163e53cdf17124abe51a2d02",  # 0.4.0
    "a3f09f76eb158e5f9637f4afb056be22f361d043",  # 0.10.0
    "0068527ea599c5eb3d10466e242d255d77bb51e6",  # 0.11.0
)


class SeedGuideTests(unittest.TestCase):
    def setUp(self):
        test_pm.HubTests.setUp(self)
        ledger = self.work / upgrades.LEDGER
        state = json.loads(ledger.read_text())
        del state[upgrades.STUDIO_GUIDES]
        ledger.write_text(upgrades.encode(state))

    def release_guides(self, release):
        seed = self.root / "tools/workspace-seed"
        destinations = {seed / name: self.work / name for name in GUIDES}
        guides = {}
        for name in GUIDES:
            path = f"tools/workspace-seed/{name}"
            text = subprocess.check_output(["git", "-C", str(pm.ROOT), "show", f"{release}:{path}"], text=True)
            guides[name] = records.retarget_links(text, seed / name, self.work / name, self.root, destinations)
        return guides

    def test_current_and_historical_guides_in_both_checkout_line_endings(self):
        current = {name: (self.work / name).read_text() for name in GUIDES}
        versions = {"current": current, **{release: self.release_guides(release) for release in RELEASES}}
        # The pre-rename Studio already used the protected launcher and customization home.
        earlier = dict(versions[RELEASES[-2]])
        earlier["README.md"] = earlier["README.md"].replace("# Private PM repository", "# PM Studio").replace(
            "Open the containing Hub in Codex or Claude.", "Start a [protected PM session](../playbook/overrides.md)."
        ).replace("Keep your background", "Use [Studio customizations](../playbook/overrides.md) to change "
                  "how the Hub works for you.\n\nKeep your background")
        versions["pre-rename Studio"] = earlier
        for version, guides in versions.items():
            for newline in ("\n", "\r\n"):
                with self.subTest(version=version, newline=newline):
                    originals = {name: text.replace("\n", newline).encode() for name, text in guides.items()}
                    for name, data in originals.items():
                        (self.work / name).write_bytes(data)
                    self.assertEqual(pm.alignment(self.root)["outstanding"], [])
                    self.assertEqual({name: (self.work / name).read_bytes() for name in GUIDES}, originals)

    def test_edited_guides_and_copies_at_another_path_stay_visible(self):
        original = self.release_guides(RELEASES[-1])
        edited = {name: (text.rstrip() + "\n\nUse the signed Friday notes.\n").encode() for name, text in original.items()}
        # Even a byte-identical installed guide can be the PM's own document elsewhere.
        edited["field-notes.md"] = original["workspace/README.md"].encode()
        for name, content in edited.items():
            (self.work / name).write_bytes(content)
        for apply in (False, True, True):
            reviews = pm.alignment(self.root, prepare=apply)["outstanding"]
            self.assertEqual({row["path"]: row["digest"] for row in reviews},
                             {name: hashlib.sha256(content).hexdigest() for name, content in edited.items()})
            self.assertEqual({name: (self.work / name).read_bytes() for name in edited}, edited)
