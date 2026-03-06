#!/usr/bin/env python3
"""
Aflow — fusha travel companion and Asia tour guide helper.

Local, file-backed companion for the fusha onchain travel ledger (Kansai-style):
- Manage destinations, itineraries, reviews, and guide roster.
- Simulate tips and treasury; export state for reporting.
- CLI to browse, add, and query travel data in the style of a Trip Advisor for Asia.

All data is stored in a JSON state file; no database required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "Aflow"
APP_VERSION = "2.1.0"
DEFAULT_STATE_FILE = "aflow_state.json"
DEFAULT_CONFIG_FILE = "aflow_config.json"

FUSHA_NAMESPACE = "fusha.travel.v3"
FUSHA_VERSION = 3
MAX_DESTINATIONS = 412
MAX_ITINERARY_STOPS = 28
MAX_ITINERARY_DAYS = 90
MIN_ITINERARY_DAYS = 1
REVIEW_COOLDOWN_BLOCKS = 217
MAX_REVIEWS_PER_DEST_PER_TRAVELER = 2
RATING_MIN = 1
RATING_MAX = 5
TIP_FEE_BP = 87
BP_DENOMINATOR = 10_000
MAX_REGION_CODE = 24
SEASON_BLOCKS = 604
MAX_TIP_WEI = 50 * 10**18

REGION_NAMES: Dict[int, str] = {
    0: "Japan (Kansai/Kanto)",
    1: "South Korea",
    2: "Thailand",
    3: "Taiwan",
    4: "Vietnam",
    5: "Singapore",
    6: "Hong Kong",
    7: "China (mainland)",
    8: "Indonesia",
    9: "Malaysia",
    10: "Philippines",
    11: "Cambodia",
    12: "Myanmar",
    13: "Laos",
    14: "Sri Lanka",
    15: "India",
    16: "Nepal",
    17: "Maldives",
    18: "Macau",
    19: "Brunei",
    20: "East Timor",
    21: "Bhutan",
    22: "Mongolia",
    23: "Russia (Far East)",
    24: "Other Asia",
}

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def dest_id_hash(name: str, salt: Optional[str] = None) -> str:
    raw = f"dest_{name}"
    if salt:
        raw += f"_{salt}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def bytes32_style(s: str) -> str:
    h = hashlib.sha256(s.encode()).hexdigest()
    return f"0x{h[:64]}" if len(h) >= 64 else f"0x{h.zfill(64)}"


def fmt_wei(wei: float) -> str:
    try:
        return f"{wei:.0f} wei"
    except Exception:
        return str(wei)


def fmt_eth(wei: float) -> str:
    try:
        return f"{wei / 1e18:.6f} ETH"
    except Exception:
        return str(wei)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rand_hex(n: int) -> str:
    alphabet = "0123456789abcdef"
    return "".join(random.choice(alphabet) for _ in range(n))


def truncate(addr: str, head: int = 6, tail: int = 4) -> str:
    if not addr or len(addr) <= head + tail + 2:
        return addr
    if addr.startswith("0x"):
        return f"{addr[: head + 2]}…{addr[-tail:]}"
    return f"{addr[:head]}…{addr[-tail:]}"


def wrap(text: str, width: int = 78, indent: str = "") -> str:
    return "\n".join(indent + line for line in textwrap.wrap(text, width))


def region_name(code: int) -> str:
    return REGION_NAMES.get(code, f"Region {code}")


def percent_bp(bp: int) -> str:
    return f"{bp / BP_DENOMINATOR * 100:.2f}%"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Destination:
    dest_id: str
    region_code: int
    name: str
    name_hash: str
    listed_at_block: int
    active: bool = True
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Destination":
        return cls(
            dest_id=d["dest_id"],
            region_code=int(d["region_code"]),
            name=d["name"],
            name_hash=d["name_hash"],
            listed_at_block=int(d["listed_at_block"]),
            active=bool(d.get("active", True)),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class Itinerary:
    itinerary_id: int
    dest_ids: List[str]
    duration_days: int
    creator: str
    created_at_block: int
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "itinerary_id": self.itinerary_id,
            "dest_ids": self.dest_ids,
            "duration_days": self.duration_days,
            "creator": self.creator,
            "created_at_block": self.created_at_block,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Itinerary":
        return cls(
            itinerary_id=int(d["itinerary_id"]),
            dest_ids=list(d["dest_ids"]),
            duration_days=int(d["duration_days"]),
            creator=d["creator"],
            created_at_block=int(d["created_at_block"]),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class ReviewRecord:
    dest_id: str
    traveler: str
    rating: int
    review_hash: str
    review_text: str
    at_block: int
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReviewRecord":
        return cls(
            dest_id=d["dest_id"],
            traveler=d["traveler"],
            rating=int(d["rating"]),
            review_hash=d["review_hash"],
            review_text=d.get("review_text", ""),
            at_block=int(d["at_block"]),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class Guide:
    address: str
    profile_hash: str
    display_name: str
    listed: bool = True
    registered_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Guide":
        return cls(
            address=d["address"],
            profile_hash=d["profile_hash"],
            display_name=d.get("display_name", truncate(d["address"])),
            listed=bool(d.get("listed", True)),
            registered_at=d.get("registered_at", now_iso()),
        )


@dataclass
class TipRecord:
    from_addr: str
    to_guide: str
    amount_wei: float
    fee_wei: float
    at_block: int
    created_at: str = field(default_factory=now_iso)
