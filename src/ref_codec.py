"""Process-local short reference registry.

Short refs reduce repeated addressing cost while the registry keeps the
authoritative source/version/object identity available to read and walk.
References are opaque handles; callers must resolve them through this module.
"""

import hashlib
import threading
from collections import OrderedDict


_MAX_REFS = 4096
_LOCK = threading.RLock()
_BY_REF = OrderedDict()
_BY_IDENTITY = {}


def _scope(kind, identity):
    digest = hashlib.sha256((kind + "\0" + "\0".join(str(v) for v in identity)).encode("utf-8")).hexdigest()
    return digest[:4]


def register(kind, identity):
    """Register an identity and return a collision-checked short ref."""
    if not isinstance(kind, str) or len(kind) != 1 or kind not in ("b", "w", "a"):
        raise ValueError("ref kind must be b, w or a")
    identity = tuple(str(value) for value in identity)
    key = (kind, identity)
    with _LOCK:
        existing = _BY_IDENTITY.get(key)
        if existing is not None:
            _BY_REF.move_to_end(existing)
            return existing
        scope = _scope(kind, identity)
        sequence = 1
        while True:
            ref = f"{kind}-{scope}-{sequence}"
            previous = _BY_REF.get(ref)
            if previous is None or previous == key:
                break
            sequence += 1
        _BY_REF[ref] = key
        _BY_IDENTITY[key] = ref
        _BY_REF.move_to_end(ref)
        while len(_BY_REF) > _MAX_REFS:
            old_ref, old_key = _BY_REF.popitem(last=False)
            if _BY_IDENTITY.get(old_key) == old_ref:
                del _BY_IDENTITY[old_key]
        return ref


def resolve(ref):
    """Resolve a short ref to its kind and bound identity, or return None."""
    if not isinstance(ref, str):
        return None
    with _LOCK:
        key = _BY_REF.get(ref)
        if key is None:
            return None
        _BY_REF.move_to_end(ref)
        kind, identity = key
        return {"kind": kind, "identity": list(identity)}


def clear():
    """Clear the process-local registry; intended for isolated tests."""
    with _LOCK:
        _BY_REF.clear()
        _BY_IDENTITY.clear()
