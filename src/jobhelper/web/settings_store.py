"""Read/write config YAMLs for the Settings UI, preserving comments.

The three config files are heavily commented and those comments carry real
operational knowledge (case-sensitive slugs, board-move notes, placeholder
warnings), so UI saves round-trip through ruamel.yaml: only the keys the UI
actually sends are updated, everything else — comments, key order, unknown
keys, quoting, flow style — survives. The pipeline's read path
(jobhelper.config) stays on PyYAML.

Two ruamel comment-attachment quirks get special handling: comments AFTER a
list ride on its last item, so replacing/emptying the list would drop the next
section's header (_pop_section_tail / _append_section_tail); and comments
between flow-style rows are discarded at parse time, so they're re-attached
from the raw text (_rescue_dropped_comments). Flow-map interior padding
(aligned columns) is NOT preserved — ruamel re-emits canonical spacing.

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
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    FoldedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)
from ruamel.yaml.tokens import CommentToken

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


def _seq_dash_col(old: CommentedSeq) -> int:
    """Column of the items' `-` markers (item value column minus 2)."""
    data = getattr(getattr(old, "lc", None), "data", None) or {}
    cols = [col for _, col in data.values()]
    return (min(cols) - 2) if cols else 0


def _pop_section_tail(old: CommentedSeq) -> str:
    """Detach the section trailer from the last item's comment token.

    ruamel attaches everything between a list's last item and the next key to
    that item's comment token, so "trailing" comments that describe the NEXT
    section (dedented left of the `-` markers) die with the item on a rebuild.
    Returns those dedented lines (plus adjacent blank lines, '' if none) and
    truncates the token to the part that really belongs to the item — its
    inline comment and any continuation lines at or right of the markers.
    """
    entry = old.ca.items.get(len(old) - 1) if len(old) else None
    tok = entry[0] if entry else None
    if tok is None:
        return ""
    first_nl = tok.value.find("\n")
    if first_nl < 0:
        return ""
    head, rest = tok.value[:first_nl + 1], tok.value[first_nl + 1:]
    dash_col = _seq_dash_col(old)
    lines = rest.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.strip():
            continue  # blank lines side with the next comment line
        if len(line) - len(line.lstrip(" ")) < dash_col:
            while i > 0 and not lines[i - 1].strip():
                i -= 1
            tok.value = head + "".join(lines[:i])
            if not tok.value.strip():  # nothing left but the item's newline
                del old.ca.items[len(old) - 1]
            return "".join(lines[i:])
    return ""


def _append_section_tail(seq: CommentedSeq, parent: CommentedMap, key: Any,
                         tail: str) -> None:
    """Re-attach a section trailer after a rebuilt list: onto its new last
    item, or — when the list was emptied to `[]` — onto the parent key so the
    comments still emit below `key: []`."""
    if len(seq):
        entry = seq.ca.items.get(len(seq) - 1)
        if entry and entry[0] is not None:
            entry[0].value += tail
        else:
            seq.ca.items[len(seq) - 1] = [
                CommentToken("\n" + tail, CommentMark(0), None),
                None, None, None]
    else:
        entry = parent.ca.items.setdefault(key, [None, None, None, None])
        if entry[2] is not None:
            entry[2].value += tail
        else:
            entry[2] = CommentToken("\n" + tail, CommentMark(0), None)


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
                tail = _pop_section_tail(old)
                node[key] = _rebuild_seq(old, val)
                if tail:
                    _append_section_tail(node[key], node, key, tail)
        elif not _equal(old, val):
            node[key] = _to_node(val, str_template=old)


def _rescue_dropped_comments(doc: CommentedMap, text: str) -> None:
    """Re-attach comment blocks that ruamel discards at PARSE time.

    ruamel 0.19 drops a full-line comment block sitting between two flow-style
    sequence items when the earlier item has no inline comment (with one, the
    block glues onto that token and survives) — e.g. the workday section
    headers. Walk every sequence; where the raw file shows only comments and
    blanks between a flow-style item and the next but the parsed seq holds no
    comment token for it, rebuild the token from the raw lines verbatim.
    """
    lines = text.splitlines()

    def walk(node: Any) -> None:
        if isinstance(node, CommentedMap):
            for v in node.values():
                walk(v)
            return
        if not isinstance(node, CommentedSeq):
            return
        data = getattr(getattr(node, "lc", None), "data", None) or {}
        for idx in range(len(node) - 1):
            prev = node[idx]
            if idx in node.ca.items or not (
                    isinstance(prev, (CommentedMap, CommentedSeq))
                    and prev.fa.flow_style()):
                continue  # a token, had one existed, would have caught the gap
            pos, nxt = data.get(idx), data.get(idx + 1)
            if not pos or not nxt:
                continue
            gap = lines[pos[0] + 1: nxt[0]]
            if (any(ln.strip() for ln in gap) and all(
                    not ln.strip() or ln.lstrip().startswith("#") for ln in gap)):
                node.ca.items[idx] = [
                    CommentToken("\n" + "".join(ln + "\n" for ln in gap),
                                 CommentMark(0), None),
                    None, None, None]
        for item in node:
            walk(item)

    walk(doc)


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
    else:
        _rescue_dropped_comments(doc, path.read_text(encoding="utf-8"))
    merge_into(doc, data)
    text = _dump_text(doc)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return None, False
    backup_path = backup(name)
    _atomic_write(path, text)
    return backup_path, True
