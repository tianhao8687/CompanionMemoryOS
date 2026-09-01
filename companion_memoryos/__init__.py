"""Consent-first memory infrastructure for emotional companions."""

from companion_memoryos.config import CompanionConfig, load_config
from companion_memoryos.service import CompanionMemoryService

__all__ = ["CompanionConfig", "CompanionMemoryService", "load_config"]
__version__ = "0.6.0"
