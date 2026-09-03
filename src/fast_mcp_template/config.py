"""Settings, read from the environment.

Every field here is a name a deployer has to know about, so the
template ships the SEAM rather than a set of fields: add yours, and
`docs/reviews/check-settings-are-read.py` (carried, disabled) is the
gate that refuses a field nothing outside this module reads.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    The prefix is the ONE place the environment-variable namespace is
    written. Change it when you rename the project; nothing else
    should spell it out.
    """

    model_config = SettingsConfigDict(env_prefix="MCP_TEMPLATE_", extra="forbid")

    #: How the server greets a caller. A placeholder field so the
    #: settings seam is exercised by a real reader rather than being
    #: an empty class nothing can go wrong in.
    greeting: str = "hello"


def load_settings() -> Settings:
    """Read settings from the environment."""
    return Settings()
