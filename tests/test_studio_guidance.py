"""Keep shipped examples and installed navigation aligned with the Studio layout."""

import re
import unittest
from urllib.parse import unquote, urlsplit

import test_pm
import pm
import storage
import studio_layout


# These directories ship instructions or configuration for agents, CI, or the PM.
GUIDANCE = {"playbook", "templates", ".agents", ".claude", ".codex", ".github"}
TEXT = {".md", ".json", ".yml", ".yaml", ".toml", ".sh", ".ps1"}
OLD_HOMES = set(storage.PRIVATE_ROOTS) - {storage.STUDIO}
OLD_FILES = "|".join(re.escape(path) for path in studio_layout.LEGACY.values())
RETIRED = re.compile(
    rf"(?<![\w.-])(?:{OLD_FILES})(?![\w.-])"
    r"|(?<![\w.-])private/|/private(?=$|[\s`'\")])"
    r"|(?<![\w.-])workspace/(?:context|workspace|customizations|settings\.json|\.git)(?=/|$|[\s`'\")])"
    r"|(?:\bcd\s+|\bpushd\s+|\bgit\s+-C\s+"
    r"|\b(?:working-directory|cwd|workspace_root)[\"']?\s*[:=]\s*)"
    r"[\"']?(?:\./)?(?:private|workspace)/?(?=$|[\s`'\";,}])",
    re.IGNORECASE,
)


def stale_path(relative, line):
    stripped = line.strip()
    if relative == ".gitignore" and stripped in {f"/{old}/" for old in OLD_HOMES}:
        return None
    if relative == "playbook/updates.md":
        # The migration table names an old root only as the source of a move.
        cells = [cell.strip() for cell in stripped.split("|")]
        if any(cells == ["", f"`{old}/`", f"`{storage.STUDIO}/`", ""] for old in OLD_HOMES):
            return None
    local = re.sub(r"https?://[^\s`)>]+", "", line).replace("\\", "/")
    return RETIRED.search(local)


def local_links(document):
    for label, reference in pm.LINK.findall(document.read_text(encoding="utf-8")):
        uri = urlsplit(reference.strip("<>"))
        if uri.path and not uri.scheme and not uri.netloc:
            yield label, (document.parent / unquote(uri.path)).resolve()


class StudioGuidanceTests(unittest.TestCase):
    def test_shipped_guidance_uses_current_paths(self):
        errors = []
        for path in storage.inventory(pm.ROOT):
            relative = path.relative_to(pm.ROOT)
            shipped = (len(relative.parts) == 1 or relative.parts[0] in GUIDANCE
                       or relative.parts[:2] == ("tools", "workspace-seed"))
            if not shipped or (path.suffix not in TEXT and path.name != ".gitignore"):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = stale_path(relative.as_posix(), line)
                if match:
                    errors.append(f"{relative}:{number}: {match.group()}")
        self.assertEqual(errors, [])

    def test_checks_commands_links_and_config_even_in_migration_guidance(self):
        for example in ("cd private", 'git -C "workspace" status', "working-directory: ./private",
                        '{"cwd": "workspace/"}', 'workspace_root=private',
                        'Open `private/context/`', "[rules](../../private/settings.json)",
                        r"Read private\context\sources", "work=workspace/context",
                        "Use .hub-overrides.json", "Read workspace/.views/week.html"):
            with self.subTest(example=example):
                self.assertIsNotNone(stale_path("playbook/updates.md", example))
        for example in ("git workspace status", "pm.py new goal workspace/goals/new.md",
                        "Keep this repository private.", "https://example.org/private/api"):
            self.assertIsNone(stale_path("README.md", example))


class StudioSeedLinksTests(unittest.TestCase):
    setUp = test_pm.HubTests.setUp

    def test_installed_navigation_preserves_each_seed_link_destination(self):
        seed = self.root / "tools/workspace-seed"
        for source in seed.rglob("*.md"):
            installed = self.work / source.relative_to(seed)
            expected = []
            for label, before in local_links(source):
                target = self.work / before.relative_to(seed) if before.is_relative_to(seed) else before
                self.assertTrue(target.exists(), (source, target))
                expected.append((label, target))
            self.assertEqual(list(local_links(installed)), expected, str(installed))
