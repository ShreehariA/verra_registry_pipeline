"""Where the pipeline reads and writes, how files are named, and how much bad input it tolerates.

No location is fixed in code. Every value comes from a JSON config file
(config/pipeline.json unless told otherwise); relative paths are resolved from
the config's own `root`, never from the current folder; and command-line flags
can override a value for a single run. Another environment, such as Google
Cloud later, is just another config file.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from verra_pipeline.errors import ConfigError
from verra_pipeline.json_formats import CONFIG_FORMAT, check_format, read_json

CONFIG_ENV_VAR = "VERRA_CONFIG"
DEFAULT_CONFIG_FILE = Path("config") / "pipeline.json"

_PLACEHOLDER = re.compile(r"\{([a-z_]*)\}")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True)
class SourceSystem:
    """A system that drops raw files, e.g. Verra: where they land and how they are named."""

    name: str
    landing: Path
    file_name: str

    def with_landing(self, landing: Path | None) -> SourceSystem:
        """A copy reading from another folder for one run; the folder is relative to the current one."""
        return self if landing is None else dataclasses.replace(self, landing=landing.resolve())


@dataclass(frozen=True)
class Paths:
    schema: Path
    lake: Path
    warehouse: Path


@dataclass(frozen=True)
class PipelineConfig:
    """One environment's settings, already checked. Templates use {placeholders}."""

    source_file: Path
    sources: Mapping[str, SourceSystem]
    paths: Paths
    lake_table_file: str
    lake_manifest_file: str
    current_view: str
    history_view: str
    max_rejected_share: float

    @classmethod
    def load(cls, file: Path) -> PipelineConfig:
        document = read_json(file, ConfigError)
        check_format(document, CONFIG_FORMAT, str(file), ConfigError)
        root = (file.parent / document["root"]).resolve()
        lake, views = document["lake"], document["warehouse"]
        return cls(
            source_file=file,
            sources=MappingProxyType(
                {name: _source(name, spec, root, file) for name, spec in document["sources"].items()}
            ),
            paths=Paths(**{name: _resolve(root, value, file) for name, value in document["paths"].items()}),
            lake_table_file=_template(
                lake["table_file"], "lake/table_file", {"layer", "table", "date"}, file
            ),
            lake_manifest_file=_template(
                lake["manifest_file"], "lake/manifest_file", {"stage", "date"}, file
            ),
            current_view=_template(views["current_view"], "warehouse/current_view", {"table"}, file),
            history_view=_template(views["history_view"], "warehouse/history_view", {"table"}, file),
            max_rejected_share=float(document["ingest"]["max_rejected_share"]),
        )

    def source(self, name: str | None) -> SourceSystem:
        """The named source system; with no name, the only one configured."""
        if name is None:
            if len(self.sources) != 1:
                raise ConfigError(
                    f"{self.source_file} has several sources; choose one of {sorted(self.sources)}"
                )
            return next(iter(self.sources.values()))
        if name not in self.sources:
            raise ConfigError(f"{self.source_file} has no source {name!r}; it has {sorted(self.sources)}")
        return self.sources[name]

    def overridden(
        self,
        *,
        schema: Path | None = None,
        lake: Path | None = None,
        warehouse: Path | None = None,
        max_rejected_share: float | None = None,
    ) -> PipelineConfig:
        """A copy with any given value replaced; paths given here are relative to the current folder."""
        given = {"schema": schema, "lake": lake, "warehouse": warehouse}
        paths = dataclasses.replace(
            self.paths, **{name: path.resolve() for name, path in given.items() if path is not None}
        )
        share = self.max_rejected_share if max_rejected_share is None else max_rejected_share
        return dataclasses.replace(self, paths=paths, max_rejected_share=share)


class ConfigLocator:
    """Finds the config file: --config, then $VERRA_CONFIG, then config/pipeline.json here or above."""

    def __init__(self, environment: Mapping[str, str], start: Path) -> None:
        self._environment = environment
        self._start = start

    def locate(self, explicit: Path | None = None) -> Path:
        if explicit is not None:
            return _existing(explicit, "--config")
        if CONFIG_ENV_VAR in self._environment:
            return _existing(Path(self._environment[CONFIG_ENV_VAR]), f"${CONFIG_ENV_VAR}")
        for folder in (self._start, *self._start.parents):
            candidate = folder / DEFAULT_CONFIG_FILE
            if candidate.is_file():
                return candidate
        raise ConfigError(
            f"no {DEFAULT_CONFIG_FILE} in {self._start} or any folder above it; "
            f"pass --config FILE or set {CONFIG_ENV_VAR}"
        )


def _existing(path: Path, named_by: str) -> Path:
    if not path.is_file():
        raise ConfigError(f"the config file {path} given by {named_by} does not exist")
    return path


def _source(name: str, spec: Mapping[str, str], root: Path, file: Path) -> SourceSystem:
    template = _template(spec["file_name"], f"sources/{name}/file_name", {"prefix", "date"}, file)
    return SourceSystem(name=name, landing=_resolve(root, spec["landing"], file), file_name=template)


def _resolve(root: Path, value: str, file: Path) -> Path:
    """An absolute path; storage URIs are refused until a cloud lake exists, instead of being mangled."""
    if _URI.match(value):
        raise ConfigError(
            f"{file}: {value!r} is a storage URI; cloud storage arrives with the deployment step"
        )
    path = Path(value)
    return path if path.is_absolute() else root / path


def _template(text: str, label: str, placeholders: Iterable[str], file: Path) -> str:
    """The template, checked to use exactly the expected {placeholders} and no stray braces."""
    expected = set(placeholders)
    leftover = _PLACEHOLDER.sub("", text)
    if set(_PLACEHOLDER.findall(text)) != expected or "{" in leftover or "}" in leftover:
        wanted = ", ".join(f"{{{name}}}" for name in sorted(expected))
        raise ConfigError(f"{file}: {label}: {text!r} must use exactly these placeholders: {wanted}")
    return text
