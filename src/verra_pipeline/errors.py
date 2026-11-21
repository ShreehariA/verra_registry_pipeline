"""Errors the pipeline raises on purpose.

Each one means "stop: the input cannot be trusted". They all derive from
PipelineError, so the command line can print one clear sentence instead of a
stack trace, and tests can assert on the exact kind of failure.
"""


class PipelineError(Exception):
    """A problem with the input or the run that should stop the pipeline."""


class ConfigError(PipelineError):
    """The config file is missing, malformed, or names something that does not exist."""


class SchemaDefinitionError(PipelineError):
    """A file in the schema folder is malformed or contradicts another one."""


class SnapshotNotFoundError(PipelineError):
    """No date in the landing folder has all three Verra files."""


class IncompleteSnapshotError(PipelineError):
    """The requested date is missing one or more of its three files."""


class UnreadableFileError(PipelineError):
    """A file is empty, has no header, or is not valid CSV at all."""


class SchemaMismatchError(PipelineError):
    """Data does not match the shape the schema declares, e.g. a required column is missing."""


class RejectBudgetExceededError(PipelineError):
    """Too much of one file could not be read to trust the rest of it."""
