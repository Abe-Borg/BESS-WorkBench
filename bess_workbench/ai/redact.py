"""Keep API keys out of logs."""

from __future__ import annotations

import logging
import re

_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_secrets: set[str] = set()
_INSTALLED = False
_ORIGINAL_FACTORY = logging.getLogRecordFactory()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 8:
        _secrets.add(value)


def scrub(text: str) -> str:
    cleaned = _KEY_RE.sub("[REDACTED]", text)
    for secret in list(_secrets):
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return cleaned


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(scrub(item) if isinstance(item, str) else item for item in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: scrub(value) if isinstance(value, str) else value for key, value in record.args.items()}
        return True


def _scrubbing_factory(*args, **kwargs):
    record = _ORIGINAL_FACTORY(*args, **kwargs)
    if isinstance(record.msg, str):
        record.msg = scrub(record.msg)
    if isinstance(record.args, tuple):
        record.args = tuple(scrub(item) if isinstance(item, str) else item for item in record.args)
    elif isinstance(record.args, dict):
        record.args = {key: scrub(value) if isinstance(value, str) else value for key, value in record.args.items()}
    return record


def install_redaction() -> None:
    global _INSTALLED
    logger = logging.getLogger("bess_workbench")
    if not any(isinstance(item, RedactingFilter) for item in logger.filters):
        logger.addFilter(RedactingFilter())
    if not _INSTALLED:
        logging.setLogRecordFactory(_scrubbing_factory)
        logger.setLevel(logging.INFO)
        _INSTALLED = True
