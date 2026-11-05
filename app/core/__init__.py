"""
Core module exports for constants and configuration.
"""

from app.core.constants import (
    ANATEL_DDDS,
    ANATEL_DDDS_STR,
    DDD_REGION_MAP,
    DEFAULT_COUNTRY_CODE,
    CANONICAL_MOBILE_LENGTH,
    CANONICAL_LANDLINE_LENGTH,
    ContactStatus,
    SessionStatus,
    QueueState,
    RE_NON_DIGITS,
    RE_REPEATED_DIGITS,
    RE_SCIENTIFIC_NOTATION,
    RE_CARRIER_CSP,
    RE_PHONE_HEADER,
    RE_NAME_HEADER,
)
from app.core.config import settings, Settings

__all__ = [
    "ANATEL_DDDS",
    "ANATEL_DDDS_STR",
    "DDD_REGION_MAP",
    "DEFAULT_COUNTRY_CODE",
    "CANONICAL_MOBILE_LENGTH",
    "CANONICAL_LANDLINE_LENGTH",
    "ContactStatus",
    "SessionStatus",
    "QueueState",
    "RE_NON_DIGITS",
    "RE_REPEATED_DIGITS",
    "RE_SCIENTIFIC_NOTATION",
    "RE_CARRIER_CSP",
    "RE_PHONE_HEADER",
    "RE_NAME_HEADER",
    "settings",
    "Settings",
]
