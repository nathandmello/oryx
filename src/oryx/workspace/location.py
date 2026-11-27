"""Select one external Workspace and verify its filesystem and logical identity."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

IDENTITY = Path(".oryx/workspace.json")


def workspace_marker(folder):
    marker = folder / IDENTITY
    if marker.resolve() != marker or not marker.is_file() or marker.stat().st_size > 1024:
        raise ValueError("The selected Workspace needs a regular .oryx/workspace.json identity")
    record = json.loads(marker.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or set(record) not in ({"id"}, {"id", "layout"})
            or "layout" in record and record["layout"] != "purpose-v1"):
        raise ValueError("Invalid Workspace identity")
    value = record["id"]
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid Workspace identity")
    expected = os.environ.get("ORYX_WORKSPACE_ID")
    if expected is not None and value != expected:
        raise ValueError("The selected Workspace identity changed")
    return record


def workspace_id(folder):
    return workspace_marker(folder)["id"]


def purpose_layout(folder=None):
    if folder is None:
        supplied = os.environ.get("ORYX_WORKSPACE")
        if not supplied:
            return False
        folder = Path(supplied)
    marker = folder / IDENTITY
    if not os.path.lexists(marker):
        return False
    return workspace_marker(folder).get("layout") == "purpose-v1"


def selected_path(core, *, explicit=None):
    """Validate explicit location even when the caller only wants to read a file."""
    value = os.environ.get("ORYX_WORKSPACE")
    if explicit is not None:
        if value is not None and Path(value) != explicit:
            raise ValueError("The explicit location differs from the selected Workspace")
        value = os.fspath(explicit)
    if value is None:
        if "ORYX_WORKSPACE_ID" in os.environ:
            raise ValueError("ORYX_WORKSPACE_ID needs an explicit ORYX_WORKSPACE")
        return None
    if "PM_HUB_PROTECTED_ROOT" in os.environ:
        raise ValueError("Use the PM terminal for an external Workspace until protected host support is qualified")
    git_overrides = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES")
    if any(key in os.environ for key in git_overrides):
        raise ValueError("Clear Git directory overrides before using the selected Workspace")
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("ORYX_WORKSPACE must be an absolute path without links or parent traversal")
    core = core.resolve()
    protected = core
    if (core / "oryx-release-manifest.json").is_file() and core.parent.parent.name == "generations":
        # The installer owns every generation, its archives, and the active pointer.
        protected = core.parent.parent.parent
    if path.is_relative_to(protected) or protected.is_relative_to(path):
        raise ValueError("Core installation and the selected Workspace require separate locations")
    # A personal Workspace gets one independent Git repository. Do not place new
    # customer data inside a different checkout or accept redirected Git metadata.
    inside_git = any(
        (parent / ".git/HEAD").is_file() or (parent / ".git").is_file() or (parent / ".git").is_symlink()
        for parent in path.parents
    )
    if not path.parent.is_dir() or inside_git:
        raise ValueError("Select a Workspace in an existing directory outside other Git repositories")
    if os.path.lexists(path):
        git = path / ".git"
        if not git.is_dir() or git.is_symlink() or not (git / "HEAD").is_file() or (git / "HEAD").is_symlink():
            raise ValueError("The selected Workspace needs its own local Git repository")
        workspace_id(path)
    elif "ORYX_WORKSPACE_ID" in os.environ:
        raise ValueError("The previously selected Workspace is missing")
    return path


def create_identity(folder):
    marker = folder / IDENTITY
    marker.parent.mkdir(mode=0o700)
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"id": str(uuid4()), "layout": "purpose-v1"}, stream)
        stream.write("\n")
