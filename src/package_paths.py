"""Bilingual protocol directory mapping and vault-relative reference resolution."""

from pathlib import Path, PurePosixPath

PERMANENT_DIRS = ("永久栏目", "Permanent")
TEMPORARY_DIRS = ("临时栏目", "Temporary")
PROTOCOL_DIRS = ("永久栏目", "临时栏目", "Permanent", "Temporary")

CHAIN_DIRS = ("常规链式", "General Chain")
SPECIAL_DIRS = ("特殊临时栏目", "Special temporary")

DIR_TO_SECTION_TYPE = {
    "永久栏目": "permanent",
    "Permanent": "permanent",
    "临时栏目": "temporary",
    "Temporary": "temporary",
}

SECTION_TYPE_TO_DIRS = {
    "permanent": PERMANENT_DIRS,
    "temporary": TEMPORARY_DIRS,
}


def section_type_for_dir(name):
    """Return 'permanent' or 'temporary' if name is a protocol directory, else None."""
    return DIR_TO_SECTION_TYPE.get(name)


def protocol_dirs_for_type(section_type):
    """Return the allowed directory names for a section type."""
    return SECTION_TYPE_TO_DIRS.get(section_type, ())


def dir_matches_section_type(file_path, section_type):
    """Check if the first component of a relative path matches the sectionType."""
    parts = PurePosixPath(file_path).parts
    if not parts:
        return False
    return parts[0] in protocol_dirs_for_type(section_type)


def is_valid_protocol_path(file_path):
    """Check if relative path matches the formal section layout structure."""
    parts = PurePosixPath(file_path).parts
    if not parts or not parts[-1].endswith(".json"):
        return False
    if parts[0] in PERMANENT_DIRS:
        return len(parts) == 2
    if parts[0] in TEMPORARY_DIRS:
        return len(parts) >= 2
    return False


def resolve_protocol_reference(reference, package_files=None):
    """Resolve the protocol directory suffix, not the referring file's parent.

    The vault root is external to an exported/moved package. Retaining the full
    protocol suffix accommodates its vault prefix without reading outside it.
    Supports both Chinese ('永久栏目', '临时栏目') and English ('Permanent', 'Temporary')
    protocol directories, and disambiguates using actual package file mappings.
    """
    if not isinstance(reference, str) or "\x00" in reference or not reference:
        raise ValueError("Expected vault-relative reference string")
    parts = PurePosixPath(reference).parts
    if reference.startswith(("/", "\\")) or "\\" in reference or ".." in parts:
        raise ValueError("Unsafe vault reference: " + reference)
    if parts and ":" in parts[0]:
        raise ValueError("Absolute/URI references are not package files")

    candidates = []
    for index, part in enumerate(parts):
        if part in PROTOCOL_DIRS:
            relative = PurePosixPath(*parts[index:])
            if relative.suffix == ".json":
                candidates.append(relative.as_posix())

    if not candidates:
        raise ValueError("Reference must name an internal section JSON: " + reference)

    # Disambiguate against actual package files when provided
    if package_files is not None:
        matched = [c for c in candidates if c in package_files]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            raise ValueError("Ambiguous reference matches multiple package files: " + reference)

    # Otherwise filter by valid package protocol layout
    valid = [c for c in candidates if is_valid_protocol_path(c)]
    if len(valid) == 1:
        return valid[0]
    if len(valid) > 1:
        # Prefer the innermost matching protocol directory (closest to the section JSON)
        return valid[-1]

    return candidates[-1]


def is_canvas_section_file(file_path):
    """Check if a file contains Bookmark Canvas section protocol signature."""
    try:
        path = Path(file_path)
        if not path.is_file() or path.is_symlink():
            return False
        with open(path, "rb") as stream:
            chunk = stream.read(4096)
        if b'"bookmark-canvas-section"' not in chunk:
            return False
        if b'"permanent"' not in chunk and b'"temporary"' not in chunk:
            return False
        return True
    except (OSError, PermissionError):
        return False


def is_package_dir(path):
    """Check if a path contains protocol directories or a canvas file."""
    p = Path(path)
    if not p.is_dir():
        return False
    if any(p.glob("*.canvas")):
        return True
    try:
        subdirs = {entry.name for entry in p.iterdir() if entry.is_dir()}
    except (OSError, PermissionError):
        return False
    for name in PROTOCOL_DIRS:
        if name in subdirs:
            branch = p / name
            try:
                for entry in branch.rglob("*.json"):
                    if is_canvas_section_file(entry):
                        return True
            except (OSError, PermissionError):
                pass
    return False
