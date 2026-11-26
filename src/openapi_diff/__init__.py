"""openapi-diff: OpenAPI 3.x breaking-change differ (stdlib only)."""

from .differ import Change, DiffResult, compare_specs

__version__ = "0.1.0"

__all__ = ["Change", "DiffResult", "compare_specs", "__version__"]
