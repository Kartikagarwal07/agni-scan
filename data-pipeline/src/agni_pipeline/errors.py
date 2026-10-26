"""Exception types raised by the pipeline.

Every error carries a message that is meant to be shown to the operator as-is,
so messages name the file, row or field that caused the problem.
"""


class PipelineError(Exception):
    """Base class for all expected, user-facing pipeline failures."""


class InputValidationError(PipelineError):
    """An input file (CSV, GeoJSON, config) is malformed or inconsistent."""


class BoundaryError(InputValidationError):
    """A boundary GeoJSON has an unsupported CRS, invalid geometry or bad extent."""


class ConfigError(InputValidationError):
    """The scoring configuration is invalid."""


class ContractViolationError(PipelineError):
    """Generated output does not conform to docs/DATA_CONTRACT.md."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        shown = "\n  - ".join(self.errors[:20])
        more = f"\n  ... and {len(self.errors) - 20} more" if len(self.errors) > 20 else ""
        super().__init__(f"Output violates DATA_CONTRACT.md:\n  - {shown}{more}")
