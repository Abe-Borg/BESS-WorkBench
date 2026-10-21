"""API key in the OS credential store, with ANTHROPIC_API_KEY as the fallback."""

from __future__ import annotations

import os

from bess_workbench.ai.redact import register_secret

SERVICE = "BESS-WorkBench"
ACCOUNT = "anthropic-api-key"


class MemoryKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, password: str) -> None:
        self.store[(service, user)] = password

    def delete_password(self, service: str, user: str) -> None:
        self.store.pop((service, user), None)


class Keystore:
    def __init__(self, backend=None) -> None:
        self.backend = backend

    def _backend(self):
        if self.backend is not None:
            return self.backend
        import keyring

        return keyring

    def resolve(self) -> tuple[str | None, str]:
        stored = None
        try:
            stored = self._backend().get_password(SERVICE, ACCOUNT)
        except Exception:
            stored = None
        if stored:
            register_secret(stored)
            return stored, "keyring"
        env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if env:
            register_secret(env)
            return env, "environment"
        return None, "none"

    def status(self) -> dict:
        key, source = self.resolve()
        if not key:
            return {
                "present": False,
                "source": "none",
                "hint": "No API key. AI features are off. The rules engine still runs offline.",
            }
        where = "the OS credential store (keyring)" if source == "keyring" else "the ANTHROPIC_API_KEY environment variable"
        return {
            "present": True,
            "source": source,
            "hint": f"A key is available from {where} (ending {key[-4:]}). The full key is not shown.",
        }

    def save(self, key: str) -> None:
        cleaned = key.strip()
        if not cleaned:
            raise ValueError("API key is empty.")
        register_secret(cleaned)
        self._backend().set_password(SERVICE, ACCOUNT, cleaned)

    def clear(self) -> None:
        try:
            self._backend().delete_password(SERVICE, ACCOUNT)
        except Exception:
            return
