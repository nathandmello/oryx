"""Locate Studio customizations and move older installations without merging files."""

import os
from pathlib import Path

import layout_upgrade
import storage

RULES = "customizations/rules.json"
SETTINGS = "customizations/settings.json"
VIEWS = "customizations/views"
LEGACY = {RULES: ".hub-overrides.json", SETTINGS: ".hub-customizations.json", VIEWS: "workspace/.views"}


def location(private, name):
    """Use the existing home even before alignment, including on read-only requests."""
    current = private / name
    old = private / LEGACY[name]
    for path in (current, old):
        if path.resolve() != path:
            raise ValueError(f"Use a regular Studio path for {path.relative_to(private)}")
        if path.parent.exists() and not path.parent.is_dir():
            raise ValueError(f"Expected a directory at {path.parent.relative_to(private)}")
        if path.exists() and not (path.is_dir() if name == VIEWS else path.is_file()):
            raise ValueError(f"Unexpected file type at {path.relative_to(private)}")
    if old.exists() and current.exists():
        raise ValueError(f"Both {LEGACY[name]} and {name} exist. Review both copies before alignment")
    return old if old.exists() else current


def conflicts_with_destination(known, destination):
    """An index file, its descendants, and differently cased directories reserve their paths."""
    for existing, requested in zip(known.parts, destination.parts):
        if existing.casefold() != requested.casefold():
            return False
        if existing != requested:
            return True
    return True  # One path contains the other, or they name the same file.


def moves(private):
    pending = {legacy: name for name, legacy in LEGACY.items()
               if location(private, name) == private / legacy}
    if not pending:
        return {}
    occupied = layout_upgrade.reserved_paths(private)
    sources, destinations = [], []
    for legacy, name in pending.items():
        destination = Path(name)
        if any(conflicts_with_destination(known, destination) for known in occupied):
            raise ValueError(f"Review the occupied Studio destination {name} before alignment")
        names = [Path(legacy)]
        if name == VIEWS:
            for directory, children, files in os.walk(private / legacy):
                names.extend((Path(directory) / child).relative_to(private) for child in children + files)
        for source in names:
            path = private / source
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError(f"Use regular Studio files at {source}")
            dest = (Path(name) / source.relative_to(legacy)).as_posix()
            if layout_upgrade.ambiguous_component(private, dest):
                raise ValueError(f"Review the occupied Studio destination {dest} before alignment")
            sources.append(source.as_posix())
            destinations.append(dest)
    ignored = layout_upgrade.ignored_names(private, sources + destinations)
    if ignored:
        raise ValueError("Review private Git ignore rules before moving Studio files: " + ", ".join(sorted(ignored)))
    return pending


def relocate(private, pending):
    # Preflight the entire plan. Each complete rename is independently discoverable on retry.
    if pending != moves(private):
        raise ValueError("Studio paths changed. Inspect align --status and retry.")
    for old, new in pending.items():
        dest = private / new
        dest.parent.mkdir(parents=True, exist_ok=True)
        storage.rename_exclusive(private / old, dest)
