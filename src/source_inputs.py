"""Read directory, ZIP and single-section exports without changing their files."""

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

from bookmark_index import BookmarkIndex, _dump, _reject_constant, _unique_object


PROTOCOL_DIRS = ("永久栏目", "临时栏目")
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 10000


def hashes(files):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}


def fingerprint(file_hashes):
    return hashlib.sha256(_dump(file_hashes).encode("utf-8")).hexdigest()


def json_object(raw):
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("An export file must contain one JSON object")
    return value


def _safe_name(name):
    parts = PurePosixPath(name).parts
    if (not name or "\x00" in name or "\\" in name or name.startswith("/")
            or any(part in (".", "..") or ":" in part for part in name.rstrip("/").split("/"))):
        raise ValueError("Unsafe archive path: " + name[:200])
    return parts


def _section_name(name, raw, section_paths):
    obj = json_object(raw)
    prefix = "永久栏目" if obj.get("sectionType") == "permanent" else "临时栏目"
    relative = prefix + "/" + Path(name).name
    section_id, section = BookmarkIndex._section(relative, obj)
    BookmarkIndex._items(section_id, section, obj)
    # A card downloaded under a new filename still updates its known card.
    return section_paths.get(section_id, relative)


def _read_file(path, root):
    if path.is_symlink() or root not in path.resolve().parents:
        raise ValueError("Export contains an external symlink: " + str(path))
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Export file exceeds the 64 MiB limit: " + path.name)
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Export file exceeds the 64 MiB limit: " + path.name)
    return raw


def _directory(path):
    paths = list(path.glob("*.canvas"))
    for loose in path.glob("*.json"):
        raw = _read_file(loose, path)
        try:
            obj = json_object(raw)
        except ValueError:
            continue
        if obj.get("format") == "bookmark-canvas-section":
            raise ValueError("Loose section JSON at package root; import the card file directly or use protocol directories")
    for directory in PROTOCOL_DIRS:
        branch = path / directory
        if branch.is_symlink():
            raise ValueError("Export contains a symlinked protocol directory")
        for entry in branch.rglob("*"):
            if entry.is_symlink():
                raise ValueError("Export contains an external symlink: " + str(entry))
            if entry.is_file() and entry.suffix == ".json":
                paths.append(entry)
    if len(paths) > MAX_ENTRIES:
        raise ValueError("Export contains too many protocol files")
    files, total = {}, 0
    for entry in sorted(paths):
        raw = _read_file(entry, path)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Export exceeds the 256 MiB limit")
        files[entry.relative_to(path).as_posix()] = raw
    return files


def _zip(path, section_paths):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise ValueError("Archive contains too many entries")
            selected, roots, seen, loose = [], set(), set(), []
            total = 0
            for entry in entries:
                parts = _safe_name(entry.filename)
                normalized = "/".join(parts)
                if normalized in seen:
                    raise ValueError("Duplicate archive entry: " + normalized)
                seen.add(normalized)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise ValueError("Archive links and special files are unsupported")
                if entry.flag_bits & 1:
                    raise ValueError("Encrypted archives are unsupported")
                if entry.is_dir() or parts[0] == "__MACOSX" or parts[-1].startswith("."):
                    continue
                suffix = PurePosixPath(normalized).suffix
                root = None
                if suffix == ".canvas":
                    root = parts[:-1]
                elif suffix == ".json":
                    for position, part in enumerate(parts[:-1]):
                        if part in PROTOCOL_DIRS:
                            root = parts[:position]
                            break
                    if root is None:
                        loose.append(entry)
                if root is not None:
                    roots.add(root)
                    selected.append((entry, "/".join(parts[len(root):])))
                # Bound all decompressed sizes, including ignored files.
                total += entry.file_size
                if entry.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("Archive exceeds export size limits")
            if len(roots) > 1:
                raise ValueError("Archive contains multiple package roots; import each canvas as a separate source")
            if selected:
                for entry in loose:
                    try:
                        obj = json_object(archive.read(entry))
                    except ValueError:
                        continue
                    if obj.get("format") == "bookmark-canvas-section":
                        raise ValueError("Archive mixes a package with loose card JSON; import the inputs separately")
            if not selected and len(loose) == 1:
                raw = archive.read(loose[0])
                return {_section_name(loose[0].filename, raw, section_paths): raw}, True
            files = {name: archive.read(entry) for entry, name in selected}
            return files, False
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError("Cannot read ZIP export: " + str(exc)) from exc


def read_input(path, section_paths=None):
    path = Path(path).expanduser().resolve()
    section_paths = section_paths or {}
    single_section = False
    if path.is_dir():
        kind, files = "directory", _directory(path)
    elif path.is_file() and path.suffix.lower() == ".zip":
        kind = "zip"
        files, single_section = _zip(path, section_paths)
    elif path.is_file() and path.suffix.lower() == ".json":
        kind, single_section = "section", True
        raw = _read_file(path, path.parent)
        files = {_section_name(path.name, raw, section_paths): raw}
    else:
        raise ValueError("Input must be an existing package directory, ZIP, or section JSON: " + str(path))
    if not files:
        raise ValueError("No protocol JSON or .canvas files in export; the saved index was retained")
    if sum(name.endswith(".canvas") for name in files) > 1:
        raise ValueError("An export must have at most one .canvas entry")
    file_hashes = hashes(files)
    return {"path": str(path), "kind": kind, "single_section": single_section,
            "files": files, "hashes": file_hashes, "fingerprint": fingerprint(file_hashes)}


def git_directory(path):
    """Locate local Git metadata, including worktrees; never invoke Git or fetch."""
    path = Path(path)
    for parent in (path, *path.parents):
        marker = parent / ".git"
        if marker.is_dir():
            return marker
        if marker.is_file():
            if marker.stat().st_size > 4096:
                raise ValueError("Invalid Git worktree marker")
            text = marker.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir: "):
                raise ValueError("Invalid Git worktree marker")
            return (parent / text[8:]).resolve()
    return None


def git_busy(path):
    directory = git_directory(path)
    if directory is None:
        return False
    directories = [directory]
    common = directory / "commondir"
    if common.is_file() and common.stat().st_size <= 4096:
        directories.append((directory / common.read_text(encoding="utf-8").strip()).resolve())
    return any((root / name).exists() for root in directories
               for name in ("index.lock", "HEAD.lock", "packed-refs.lock", "shallow.lock"))
