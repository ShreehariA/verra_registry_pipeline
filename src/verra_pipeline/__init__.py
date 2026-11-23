"""Verra registry pipeline: the daily Verra exports in, a clean and tested data model out."""


class PipelineError(Exception):
    """The input or the settings can't be trusted: stop the run with one clear sentence."""
