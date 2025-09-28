"""Configuration models and helpers for the Avtor24 auction bot."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

import yaml
from pydantic import BaseModel, Field, validator


class MessageTemplate(BaseModel):
    """Template for automatic messages."""

    name: str = Field(..., description="Human readable identifier")
    text: str = Field(..., description="Message body with placeholders")
    delay_seconds: int = Field(
        0,
        ge=0,
        description="Delay before sending the message once the bid succeeds",
    )


class OrderFilters(BaseModel):
    """Filters applied when fetching available orders."""

    categories: List[str] = Field(default_factory=list)
    types: List[str] = Field(default_factory=list)
    min_budget: Optional[int] = Field(
        None, ge=0, description="Minimum acceptable budget in roubles"
    )
    max_budget: Optional[int] = Field(
        None, ge=0, description="Maximum acceptable budget in roubles"
    )

    @validator("max_budget")
    def _validate_budget(cls, value: Optional[int], values: dict[str, object]) -> Optional[int]:
        min_budget = values.get("min_budget")
        if value is not None and min_budget is not None and value < min_budget:
            raise ValueError("max_budget must be greater than or equal to min_budget")
        return value


class AccountConfig(BaseModel):
    """Configuration for a single account."""

    name: str = Field(..., description="Short account nickname")
    login: str = Field(..., description="Account login/email")
    password: str = Field(..., description="Account password")
    min_seconds_between_bids: int = Field(
        3,
        ge=1,
        description="Lower bound for the interval between bids",
    )
    max_seconds_between_bids: int = Field(
        3,
        ge=1,
        description="Upper bound for jitter around bid intervals",
    )
    follow_up_delay_minutes: int = Field(
        5,
        ge=0,
        description="Default delay before sending a follow-up message",
    )
    filters: OrderFilters = Field(default_factory=OrderFilters)
    message_templates: List[MessageTemplate] = Field(default_factory=list)
    headless: bool = Field(
        False,
        description="Run the Playwright browser in headless mode (not recommended)",
    )
    storage_path: Optional[Path] = Field(
        None,
        description="Path for storing cookies/session data; defaults to config file directory",
    )

    @validator("max_seconds_between_bids")
    def _validate_interval(
        cls, value: int, values: dict[str, object]
    ) -> int:
        min_seconds = values.get("min_seconds_between_bids", 0)
        if value < min_seconds:
            raise ValueError("max_seconds_between_bids must be >= min_seconds_between_bids")
        return value


class BotConfig(BaseModel):
    """Top-level configuration."""

    accounts: List[AccountConfig]


def load_account_config(path: Path) -> AccountConfig:
    """Load a single account configuration from a YAML file."""

    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    account = AccountConfig.parse_obj(payload)
    if account.storage_path is None:
        account.storage_path = path.parent / f"{account.name}_storage"
    return account


def load_config_directory(config_dir: Path) -> List[AccountConfig]:
    """Load all account configs within a directory."""

    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory does not exist: {config_dir}")
    configs: List[AccountConfig] = []
    for path in sorted(config_dir.glob("*.yml")) + sorted(config_dir.glob("*.yaml")):
        configs.append(load_account_config(path))
    if not configs:
        raise ValueError("No account configuration files found")
    return configs


def iter_config_files(config_dir: Path) -> Iterable[Path]:
    """Iterate over configuration files in a directory."""

    return list(sorted(config_dir.glob("*.yml")) + sorted(config_dir.glob("*.yaml")))
