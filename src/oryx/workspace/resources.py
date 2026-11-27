"""Resolve logical links in customer records against the current Core installation."""

from pathlib import Path
import re
import subprocess

from oryx.release import archive

URI = re.compile(r"oryx://core/([A-Za-z0-9_./-]+)(?:#([A-Za-z0-9_-]+))?")


class CoreResources:
    def __init__(self, core):
        self.root = Path(core).resolve()
        self.files = None
        if (self.root / archive.MANIFEST).is_file():
            if self.root.name != "core" or self.root.parent.parent.name != "generations":
                raise ValueError("Resolve Core resources from a verified installation")
            self.root = archive.current(self.root.parent.parent.parent)
            self.files = archive.check_runtime(self.root)["files"]
        elif not (self.root / ".git").exists():
            raise ValueError("Cannot identify an installed Core or a development checkout")

    def resolve(self, uri, headings):
        match = URI.fullmatch(uri)
        if not match or not archive.valid_name(match[1]):
            raise ValueError("Use a canonical oryx://core/ path and optional heading anchor")
        name, anchor = match.groups()
        resource = self.root / name
        if resource.resolve() != resource or not resource.is_file():
            raise ValueError(f"Missing or redirected Core resource: {name}")
        if self.files is not None:
            if name not in self.files:
                raise ValueError(f"Unlisted Core resource: {name}")
        else:
            tracked = subprocess.run(["git", "-C", str(self.root), "ls-files", "--error-unmatch", "--", name],
                                     capture_output=True)
            if tracked.returncode:
                raise ValueError(f"Untracked development Core resource: {name}")
        if anchor and (resource.suffix != ".md" or anchor not in headings(resource.read_text(encoding="utf-8"))):
            raise ValueError(f"Missing Core resource anchor: {name}#{anchor}")
        return {"path": str(resource), **({"anchor": anchor} if anchor else {})}
