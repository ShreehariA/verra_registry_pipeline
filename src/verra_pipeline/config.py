"""Read pipeline.toml: where the files are, how they are named, and what each export must contain."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from verra_pipeline import PipelineError


@dataclass(frozen=True)
class Source:
    """One daily export and the columns the model needs from it."""

    table: str
    prefix: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    aliases: Mapping[str, str]


@dataclass(frozen=True)
class Config:
    landing: Path
    lake: Path
    sql: Path
    file_name: str
    max_rejected_share: float
    sources: tuple[Source, ...]


def load(path: Path) -> Config:
    """The settings in `path`, with relative paths resolved from the file's own folder."""
    try:
        settings = tomllib.loads(path.read_text(encoding="utf-8"))
        root, paths, ingest = path.resolve().parent, settings["paths"], settings["ingest"]
        return Config(
            landing=root / paths["landing"],
            lake=root / paths["lake"],
            sql=root / paths["sql"],
            file_name=ingest["file_name"],
            max_rejected_share=float(ingest["max_rejected_share"]),
            sources=tuple(
                Source(
                    table,
                    source["prefix"],
                    tuple(source["required"]),
                    tuple(source.get("optional", ())),
                    source.get("aliases", {}),
                )
                for table, source in settings["sources"].items()
            ),
        )
    except OSError as error:
        raise PipelineError(f"cannot read the config {path}: {error.strerror}") from error
    except tomllib.TOMLDecodeError as error:
        raise PipelineError(f"{path} is not valid TOML: {error}") from error
    except KeyError as error:
        raise PipelineError(f"{path} is missing the setting {error}") from error
    except (TypeError, ValueError) as error:
        raise PipelineError(f"{path} has a setting of the wrong type: {error}") from error
