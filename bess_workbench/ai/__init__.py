"""AI adapter. The rules engine stays the source of truth for every number and status."""

from bess_workbench.ai.redact import install_redaction, scrub

__all__ = ["install_redaction", "scrub"]
