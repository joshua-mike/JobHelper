"""Read/write config YAMLs for the Settings UI, preserving comments.

The three config files are heavily commented and those comments carry real
operational knowledge (case-sensitive slugs, board-move notes, placeholder
warnings), so UI saves round-trip through ruamel.yaml: only the keys the UI
actually sends are updated, everything else — comments, key order, unknown
keys, quoting, flow style — survives. The pipeline's read path
(jobhelper.config) stays on PyYAML.

Writes are atomic (temp file + os.replace) and preceded by a timestamped
backup under data/backups/ (data/ is gitignored). A missing profile.yaml is
seeded from profile.example.yaml so a fresh clone gets the example file's
comment scaffolding on first save.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    FoldedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

from ..util import CONFIG_DIR as _DEFAULT_CONFIG_DIR
from ..util import DATA_DIR

# Module-level so tests can point the store at a scratch directory.
CONFIG_DIR: Path = _DEFAULT_CONFIG_DIR
BACKUP_DIR: Path = DATA_DIR / "backups"

FILES = {
    "profile": "profile.yaml",
    "sources": "sources.yaml",
    "criteria": "criteria.yaml",
}


def config_path(name: str) -> Path:
    return CONFIG_DIR / FILES[name]


def example_profile_path() -> Path:
    return CONFIG_DIR / "profile.example.yaml"


def _yaml() -> YAML:
    y = YAML()  # round-trip mode
    y.preserve_quotes = True
    y.width = 4096  # never re-wrap long lines (inline comments would drift)
    y.indent(mapping=2, sequence=4, offset=2)  # matches the existing files
    # The files write explicit `null` (e.g. gpa: null); ruamel defaults to empty.
    y.representer.add_representer(
        type(None),
        lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return y


def _dump_text(doc: CommentedMap) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def _load_path(path: Path) -> CommentedMap | None:
    if not path.exists():
        return None
    doc = _yaml().load(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, CommentedMap) else CommentedMap()


def load_doc(name: str) -> CommentedMap | None:
    return _load_path(config_path(name))


def to_plain(node: Any) -> Any:
    """ruamel node -> JSON-safe plain dict/list/scalars."""
    return json.loads(json.dumps(node, default=str))


def load_data(name: str) -> dict[str, Any] | None:
    doc = load_doc(name)
    return None if doc is None else to_plain(doc)


def load_example_profile() -> dict[str, Any] | None:
    doc = _load_path(example_profile_path())
    return None if doc is None else to_plain(doc)


# ---- Merge (the comment-preserving part) ---------------------------------------
def _ident(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _equal(old: Any, new: Any) -> bool:
    """Value equality that won't conflate bools with 0/1."""
    if isinstance(old, bool) != isinstance(new, bool):
        return False
    return to_plain(old) == to_plain(new)


def _style_str(value: str, template: Any) -> str:
    """Present a NEW string the way its neighbors/predecessor are presented."""
    if isinstance(template, DoubleQuotedScalarString):
        return DoubleQuotedScalarString(value)
    if isinstance(template, SingleQuotedScalarString):
        return SingleQuotedScalarString(value)
    if isinstance(template, FoldedScalarString):
        return FoldedScalarString(value)
    if isinstance(template, LiteralScalarString):
        return LiteralScalarString(value)
    if "\n" in value:  # no template: keep multi-line text readable as a block
        return LiteralScalarString(value)
    return value


def _to_node(value: Any, flow_maps: bool = False, str_template: Any = None) -> Any:
    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = _to_node(v, flow_maps, str_template)
        if flow_maps:
            m.fa.set_flow_style()
        return m
    if isinstance(value, list):
        return CommentedSeq(_to_node(v, flow_maps, str_template) for v in value)
    if isinstance(value, str):
        return _style_str(value, str_template)
    return value


def _seq_str_template(old: CommentedSeq) -> Any:
    """First styled string anywhere in the old items (covers {..} row values)."""
    for item in old:
        candidates = item.values() if isinstance(item, dict) else [item]
        for v in candidates:
            if isinstance(v, (DoubleQuotedScalarString, SingleQuotedScalarString)):
                return v
    return None


def _rebuild_seq(old: CommentedSeq, new_list: list) -> CommentedSeq:
    """Replace a sequence's contents, carrying each surviving item's comment.

    Items are matched by value, so unchanged entries keep their inline notes
    even after add/remove/reorder; an edited entry loses its note (the note
    described the old value). New items copy the old items' presentation:
    quote style and, for dict rows, flow style ({...}).
    """
    comments: dict[str, deque] = {}
    for idx, item in enumerate(old):
        if idx in old.ca.items:
            comments.setdefault(_ident(to_plain(item)), deque()).append(
                old.ca.items[idx])
    dict_items = [x for x in old if isinstance(x, dict)]
    flow = bool(dict_items) and all(
        isinstance(x, CommentedMap) and x.fa.flow_style() for x in dict_items)
    template = _seq_str_template(old)

    # Reuse the old node for value-identical items (keeps quoting exactly);
    # build styled nodes for new/edited ones.
    old_by_ident: dict[str, deque] = {}
    for item in old:
        old_by_ident.setdefault(_ident(to_plain(item)), deque()).append(item)

    seq = CommentedSeq()
    for item in new_list:
        reusable = old_by_ident.get(_ident(item))
        if reusable:
            seq.append(reusable.popleft())
        else:
            seq.append(_to_node(item, flow_maps=flow, str_template=template))
    for idx, item in enumerate(new_list):
        queue = comments.get(_ident(item))
        if queue:
            seq.ca.items[idx] = queue.popleft()
    return seq


def merge_into(node: CommentedMap, new: dict[str, Any]) -> None:
    """Deep-merge `new` into the ruamel doc. Keys absent from `new` are kept,
    and unchanged values keep their original nodes (quoting, folded style)."""
    for key, val in new.items():
        if key not in node:
            node[key] = _to_node(val)
            continue
        old = node[key]
        if isinstance(val, dict) and isinstance(old, CommentedMap):
            merge_into(old, val)
        elif isinstance(val, list) and isinstance(old, CommentedSeq):
            if not _equal(old, val):
                node[key] = _rebuild_seq(old, val)
        elif not _equal(old, val):
            node[key] = _to_node(val, str_template=old)


# ---- Write path ----------------------------------------------------------------
def backup(name: str) -> Path | None:
    """Copy the current file to data/backups/<stem>-<timestamp>.yaml."""
    path = config_path(name)
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}"
    n = 1
    while dest.exists():
        dest = BACKUP_DIR / f"{path.stem}-{stamp}-{n}{path.suffix}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(name: str, data: dict[str, Any]) -> tuple[Path | None, bool]:
    """Merge `data` into the file (backing it up first) and write atomically.

    Returns (backup_path, changed). A no-op save (merged output identical to
    the file) writes and backs up nothing. A missing profile is seeded from
    profile.example.yaml so its comment scaffolding is kept.
    """
    path = config_path(name)
    doc = load_doc(name)
    if doc is None:
        doc = (_load_path(example_profile_path()) if name == "profile" else None) \
            or CommentedMap()
    merge_into(doc, data)
    text = _dump_text(doc)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return None, False
    backup_path = backup(name)
    _atomic_write(path, text)
    return backup_path, True
