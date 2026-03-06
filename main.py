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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TipRecord":
        return cls(
            from_addr=d["from_addr"],
            to_guide=d["to_guide"],
            amount_wei=float(d["amount_wei"]),
            fee_wei=float(d["fee_wei"]),
            at_block=int(d["at_block"]),
            created_at=d.get("created_at", now_iso()),
        )


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    destinations: List[Destination] = field(default_factory=list)
    itineraries: List[Itinerary] = field(default_factory=list)
    reviews: List[ReviewRecord] = field(default_factory=list)
    guides: List[Guide] = field(default_factory=list)
    tips: List[TipRecord] = field(default_factory=list)
    current_block: int = 0
    current_season: int = 0
    treasury_balance_wei: float = 0.0
    total_tips_wei: float = 0.0
    total_tips_fees_wei: float = 0.0
    itinerary_counter: int = 0
    last_review_block_by_traveler: Dict[str, int] = field(default_factory=dict)
    review_count_by_dest_traveler: Dict[str, Dict[str, int]] = field(default_factory=dict)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destinations": [d.to_dict() for d in self.destinations],
            "itineraries": [i.to_dict() for i in self.itineraries],
            "reviews": [r.to_dict() for r in self.reviews],
            "guides": [g.to_dict() for g in self.guides],
            "tips": [t.to_dict() for t in self.tips],
            "current_block": self.current_block,
            "current_season": self.current_season,
            "treasury_balance_wei": self.treasury_balance_wei,
            "total_tips_wei": self.total_tips_wei,
            "total_tips_fees_wei": self.total_tips_fees_wei,
            "itinerary_counter": self.itinerary_counter,
            "last_review_block_by_traveler": self.last_review_block_by_traveler,
            "review_count_by_dest_traveler": self._serialize_review_counts(),
            "updated_at": self.updated_at,
        }

    def _serialize_review_counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for dest_key, traveler_counts in self.review_count_by_dest_traveler.items():
            out[dest_key] = dict(traveler_counts)
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppState":
        dests = [Destination.from_dict(x) for x in d.get("destinations", [])]
        itins = [Itinerary.from_dict(x) for x in d.get("itineraries", [])]
        revs = [ReviewRecord.from_dict(x) for x in d.get("reviews", [])]
        guids = [Guide.from_dict(x) for x in d.get("guides", [])]
        tip_recs = [TipRecord.from_dict(x) for x in d.get("tips", [])]
        rc: Dict[str, Dict[str, int]] = {}
        for k, v in d.get("review_count_by_dest_traveler", {}).items():
            rc[k] = {k2: int(v2) for k2, v2 in v.items()}
        return cls(
            destinations=dests,
            itineraries=itins,
            reviews=revs,
            guides=guids,
            tips=tip_recs,
            current_block=int(d.get("current_block", 0)),
            current_season=int(d.get("current_season", 0)),
            treasury_balance_wei=float(d.get("treasury_balance_wei", 0)),
            total_tips_wei=float(d.get("total_tips_wei", 0)),
            total_tips_fees_wei=float(d.get("total_tips_fees_wei", 0)),
            itinerary_counter=int(d.get("itinerary_counter", 0)),
            last_review_block_by_traveler=dict(d.get("last_review_block_by_traveler", {})),
            review_count_by_dest_traveler=rc,
            updated_at=d.get("updated_at", now_iso()),
