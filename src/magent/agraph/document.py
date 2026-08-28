"""Secure loading and canonical identity for AGS documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from ags import canonical_json as _canonical_json
from ags import graph_digest


class GraphDocumentError(ValueError):
    """Raised when a graph document cannot be parsed safely."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


_UniqueKeyLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _first in "yYnNoO":
    _UniqueKeyLoader.yaml_implicit_resolvers.pop(_first, None)


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise GraphDocumentError("AGS mappings require string keys")
        if key in result:
            raise GraphDocumentError(f"AG005 duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@dataclass(frozen=True)
class GraphDocument:
    path: Path | None
    data: dict[str, Any]
    digest: str

    @property
    def graph_id(self) -> str:
        return str(self.data.get("id", ""))

    def canonical_json(self) -> str:
        return canonical_json(self.data)


def canonical_json(document: dict[str, Any]) -> str:
    return _canonical_json(document).decode("utf-8")


def load_graph(source: str | Path | dict[str, Any]) -> GraphDocument:
    if isinstance(source, dict):
        data = source
        path = None
    else:
        path = Path(source).expanduser().resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GraphDocumentError(f"Cannot read graph: {exc}") from exc
        try:
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.load(text, Loader=_UniqueKeyLoader)
            else:
                data = json.loads(text)
        except GraphDocumentError:
            raise
        except Exception as exc:
            raise GraphDocumentError(
                f"AG001 parse error: {str(exc).replace(chr(10), ' ')}"
            ) from exc
    if not isinstance(data, dict):
        raise GraphDocumentError("AG001 document root must be an object")
    return GraphDocument(path=path, data=data, digest=graph_digest(data))


def write_graph(document: dict[str, Any], path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".json":
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    else:
        text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    target.write_text(text, encoding="utf-8")
    return target
