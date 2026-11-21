"""Read JSON files and check them against the formats shipped with the code.

This is the only module that uses the jsonschema library. The formats live in
verra_pipeline/formats/, so they are always found, whichever config file or
schema folder a run uses.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

from verra_pipeline.errors import PipelineError

TABLE_FORMAT = "table.schema.json"
COLUMN_SET_FORMAT = "column_set.schema.json"
CONFIG_FORMAT = "pipeline.schema.json"
_FORMATS = (TABLE_FORMAT, COLUMN_SET_FORMAT, CONFIG_FORMAT)


def read_json(path: Path, error: type[PipelineError]) -> Any:
    """The parsed file; a missing file or a syntax mistake raises `error` naming the file and line."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as missing:
        raise error(f"{path} does not exist") from missing
    except json.JSONDecodeError as mistake:
        raise error(
            f"{path} is not valid JSON: {mistake.msg} at line {mistake.lineno}, column {mistake.colno}"
        ) from mistake


def check_format(document: Any, format_name: str, where: str, error: type[PipelineError]) -> None:
    """Raise `error` describing the first place `document` breaks the format, if it does."""
    problem = best_match(_validator(format_name).iter_errors(document))
    if problem is not None:
        location = "/".join(str(part) for part in problem.absolute_path) or "top level"
        raise error(f"{where}: {location}: {problem.message}")


def format_document(format_name: str) -> Any:
    """The format itself, e.g. to read the values an enum allows."""
    return _documents()[format_name]


@cache
def _documents() -> dict[str, Any]:
    folder = resources.files("verra_pipeline.formats")
    return {name: json.loads(folder.joinpath(name).read_text(encoding="utf-8")) for name in _FORMATS}


@cache
def _validator(format_name: str) -> jsonschema.Draft202012Validator:
    """A validator that also resolves references between the formats, e.g. a column set's columns."""
    documents = _documents()
    registry: Registry[Any] = Registry().with_resources(
        (name, Resource.from_contents(document)) for name, document in documents.items()
    )
    return jsonschema.Draft202012Validator(documents[format_name], registry=registry)
