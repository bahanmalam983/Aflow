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
        )


# ---------------------------------------------------------------------------
# State load / save
# ---------------------------------------------------------------------------


def load_state(path: Path) -> AppState:
    if not path.exists():
        return AppState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppState.from_dict(data)
    except Exception as e:
        print(f"Warning: could not load state from {path}: {e}", file=sys.stderr)
        return AppState()


def save_state(state: AppState, path: Path) -> None:
    state.updated_at = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Destinations helpers
# ---------------------------------------------------------------------------


def get_destination_by_id(state: AppState, dest_id: str) -> Optional[Destination]:
    for d in state.destinations:
        if d.dest_id == dest_id:
            return d
    return None


def get_active_destinations(state: AppState) -> List[Destination]:
    return [d for d in state.destinations if d.active]


def get_destinations_by_region(state: AppState, region_code: int) -> List[Destination]:
    return [d for d in state.destinations if d.region_code == region_code and d.active]


def dest_id_from_name(name: str) -> str:
    safe = name.lower().replace(" ", "_").replace("-", "_")
    return bytes32_style(f"dest_{safe}")


# ---------------------------------------------------------------------------
# Itinerary helpers
# ---------------------------------------------------------------------------


def get_itinerary_by_id(state: AppState, itinerary_id: int) -> Optional[Itinerary]:
    for i in state.itineraries:
        if i.itinerary_id == itinerary_id:
            return i
    return None


def get_itineraries_by_creator(state: AppState, creator: str) -> List[Itinerary]:
    return [i for i in state.itineraries if i.creator == creator]


# ---------------------------------------------------------------------------
# Review helpers
# ---------------------------------------------------------------------------


def can_post_review(
    state: AppState,
    traveler: str,
    dest_id: str,
    current_block: int,
) -> Tuple[bool, str]:
    dest = get_destination_by_id(state, dest_id)
    if not dest or not dest.active:
        return False, "Destination not found or inactive"
    last = state.last_review_block_by_traveler.get(traveler, 0)
    if current_block < last + REVIEW_COOLDOWN_BLOCKS:
        return False, f"Cooldown: next review at block {last + REVIEW_COOLDOWN_BLOCKS}"
    counts = state.review_count_by_dest_traveler.get(dest_id, {})
    if counts.get(traveler, 0) >= MAX_REVIEWS_PER_DEST_PER_TRAVELER:
        return False, "Max reviews per destination reached"
    return True, ""


def get_reviews_for_destination(state: AppState, dest_id: str) -> List[ReviewRecord]:
    return [r for r in state.reviews if r.dest_id == dest_id]


def get_reviews_by_traveler(state: AppState, traveler: str) -> List[ReviewRecord]:
    return [r for r in state.reviews if r.traveler == traveler]


def average_rating_for_dest(state: AppState, dest_id: str) -> Tuple[float, int]:
    revs = get_reviews_for_destination(state, dest_id)
    if not revs:
        return 0.0, 0
    total = sum(r.rating for r in revs)
    return total / len(revs), len(revs)


# ---------------------------------------------------------------------------
# Guide helpers
# ---------------------------------------------------------------------------


def get_guide(state: AppState, address: str) -> Optional[Guide]:
    for g in state.guides:
        if g.address == address and g.listed:
            return g
    return None


def list_guides(state: AppState) -> List[Guide]:
    return [g for g in state.guides if g.listed]


# ---------------------------------------------------------------------------
# Seed initial data (mirror fusha constructor)
# ---------------------------------------------------------------------------


def seed_initial_destinations(state: AppState) -> None:
    initial = [
        ("tokyo_shibuya", 0, "Shibuya, Tokyo"),
        ("kyoto_fushimi", 0, "Fushimi Inari, Kyoto"),
        ("osaka_dotonbori", 0, "Dotonbori, Osaka"),
        ("seoul_myeongdong", 1, "Myeongdong, Seoul"),
        ("bangkok_khaosan", 2, "Khaosan Road, Bangkok"),
        ("taipei_101", 3, "Taipei 101"),
        ("hanoi_old_quarter", 4, "Old Quarter, Hanoi"),
        ("singapore_marina", 5, "Marina Bay, Singapore"),
        ("hong_kong_kowloon", 6, "Kowloon, Hong Kong"),
        ("shanghai_bund", 7, "The Bund, Shanghai"),
        ("bali_ubud", 8, "Ubud, Bali"),
        ("phuket_patong", 2, "Patong Beach, Phuket"),
        ("nara_todaiji", 0, "Todai-ji, Nara"),
        ("hiroshima_miyajima", 0, "Miyajima, Hiroshima"),
        ("busan_haeundae", 1, "Haeundae Beach, Busan"),
        ("chiang_mai_old_city", 2, "Old City, Chiang Mai"),
        ("ho_chi_minh_pham_ngu_lao", 4, "Pham Ngu Lao, Ho Chi Minh City"),
        ("kuala_lumpur_petronas", 9, "Petronas Towers, Kuala Lumpur"),
        ("beijing_forbidden", 7, "Forbidden City, Beijing"),
        ("nagoya_castle", 0, "Nagoya Castle"),
        ("sapporo_odori", 0, "Odori Park, Sapporo"),
        ("okinawa_churaumi", 0, "Churaumi Aquarium, Okinawa"),
    ]
    for slug, region, name in initial:
        dest_id = bytes32_style(f"dest_{slug}")
        if get_destination_by_id(state, dest_id) is not None:
            continue
        state.destinations.append(
            Destination(
                dest_id=dest_id,
                region_code=region,
                name=name,
                name_hash=bytes32_style(name + str(state.current_block)),
                listed_at_block=state.current_block,
                active=True,
            )
        )
        state.current_block += 1


# ---------------------------------------------------------------------------
# CLI: list-destinations
# ---------------------------------------------------------------------------


def cmd_list_destinations(state: AppState, args: argparse.Namespace) -> None:
    region = getattr(args, "region", None)
    active_only = getattr(args, "active_only", True)
    limit = getattr(args, "limit", 50)
    dests = state.destinations
    if active_only:
        dests = [d for d in dests if d.active]
    if region is not None:
        dests = [d for d in dests if d.region_code == region]
    dests = dests[:limit]
    if not dests:
        print("No destinations found.")
        return
    print(f"Destinations ({len(dests)}):")
    for d in dests:
        reg = region_name(d.region_code)
        status = "active" if d.active else "retired"
        print(f"  {truncate(d.dest_id, 12, 8)}  region={d.region_code} ({reg})  {d.name}  [{status}]")


# ---------------------------------------------------------------------------
# CLI: add-destination
# ---------------------------------------------------------------------------


def cmd_add_destination(state: AppState, args: argparse.Namespace) -> None:
    name = getattr(args, "name", None)
    region = getattr(args, "region", 0)
    if not name:
        print("Error: --name required")
        return
    if len(state.destinations) >= MAX_DESTINATIONS:
        print(f"Error: max destinations ({MAX_DESTINATIONS}) reached")
        return
    if region > MAX_REGION_CODE:
        print(f"Error: region must be 0..{MAX_REGION_CODE}")
        return
    dest_id = dest_id_from_name(name)
    if get_destination_by_id(state, dest_id):
        print("Error: destination with same id already exists")
        return
    state.destinations.append(
        Destination(
            dest_id=dest_id,
            region_code=region,
            name=name,
            name_hash=bytes32_style(name + str(state.current_block)),
            listed_at_block=state.current_block,
            active=True,
        )
    )
    state.current_block += 1
    print(f"Added destination: {name} (id={truncate(dest_id, 12, 8)}, region={region})")


# ---------------------------------------------------------------------------
# CLI: create-itinerary
# ---------------------------------------------------------------------------


def cmd_create_itinerary(state: AppState, args: argparse.Namespace) -> None:
    dest_names = getattr(args, "dests", []) or getattr(args, "destinations", [])
    days = getattr(args, "days", 7)
    creator = getattr(args, "creator", "0x" + rand_hex(40))
    if not dest_names:
        print("Error: at least one destination required (--dests or --destinations)")
        return
    if len(dest_names) > MAX_ITINERARY_STOPS:
        print(f"Error: max {MAX_ITINERARY_STOPS} stops")
        return
    if days < MIN_ITINERARY_DAYS or days > MAX_ITINERARY_DAYS:
        print(f"Error: days must be {MIN_ITINERARY_DAYS}..{MAX_ITINERARY_DAYS}")
        return
    dest_ids = [dest_id_from_name(n) for n in dest_names]
    state.itinerary_counter += 1
    it = Itinerary(
        itinerary_id=state.itinerary_counter,
        dest_ids=dest_ids,
        duration_days=days,
        creator=creator,
        created_at_block=state.current_block,
    )
    state.itineraries.append(it)
    state.current_block += 1
    print(f"Created itinerary {it.itinerary_id}: {len(dest_ids)} stops, {days} days, creator={truncate(creator)}")


# ---------------------------------------------------------------------------
# CLI: post-review
# ---------------------------------------------------------------------------


def cmd_post_review(state: AppState, args: argparse.Namespace) -> None:
    dest_id = getattr(args, "dest_id", None) or dest_id_from_name(getattr(args, "dest_name", ""))
    traveler = getattr(args, "traveler", "0x" + rand_hex(40))
    rating = getattr(args, "rating", 4)
    text = getattr(args, "text", "Great experience.")
    if not dest_id:
        print("Error: --dest_id or --dest_name required")
        return
    ok, err = can_post_review(state, traveler, dest_id, state.current_block)
    if not ok:
        print(f"Error: {err}")
        return
    if rating < RATING_MIN or rating > RATING_MAX:
        print(f"Error: rating must be {RATING_MIN}..{RATING_MAX}")
        return
    review_hash = bytes32_style(text + traveler + str(state.current_block))
    state.reviews.append(
        ReviewRecord(
            dest_id=dest_id,
            traveler=traveler,
            rating=rating,
            review_hash=review_hash,
            review_text=text,
            at_block=state.current_block,
        )
    )
    state.last_review_block_by_traveler[traveler] = state.current_block
    state.review_count_by_dest_traveler.setdefault(dest_id, {})
    state.review_count_by_dest_traveler[dest_id][traveler] = (
        state.review_count_by_dest_traveler[dest_id].get(traveler, 0) + 1
    )
    state.current_block += 1
    print(f"Posted review: dest={truncate(dest_id)}, rating={rating}, traveler={truncate(traveler)}")


# ---------------------------------------------------------------------------
# CLI: list-guides
# ---------------------------------------------------------------------------


def cmd_list_guides(state: AppState, args: argparse.Namespace) -> None:
    guides = list_guides(state)
    limit = getattr(args, "limit", 50)
    guides = guides[:limit]
    if not guides:
        print("No guides listed.")
        return
    print(f"Guides ({len(guides)}):")
    for g in guides:
        print(f"  {truncate(g.address)}  {g.display_name}  profile={truncate(g.profile_hash, 10, 6)}")


# ---------------------------------------------------------------------------
# CLI: register-guide
# ---------------------------------------------------------------------------


def cmd_register_guide(state: AppState, args: argparse.Namespace) -> None:
    address = getattr(args, "address", None)
    display_name = getattr(args, "name", "")
    if not address:
        print("Error: --address required")
        return
    if get_guide(state, address):
        print("Error: guide already registered")
        return
    profile_hash = bytes32_style(address + display_name + str(state.current_block))
    state.guides.append(
        Guide(
            address=address,
            profile_hash=profile_hash,
            display_name=display_name or truncate(address),
            listed=True,
        )
    )
    state.current_block += 1
    print(f"Registered guide: {truncate(address)} ({display_name or 'no name'})")


# ---------------------------------------------------------------------------
# CLI: send-tip (simulated)
# ---------------------------------------------------------------------------


def cmd_send_tip(state: AppState, args: argparse.Namespace) -> None:
    guide_addr = getattr(args, "guide", None)
    amount_wei = float(getattr(args, "amount_wei", 1e18))
    from_addr = getattr(args, "from_addr", "0x" + rand_hex(40))
    if not guide_addr:
        print("Error: --guide required")
        return
    if get_guide(state, guide_addr) is None:
        print("Error: guide not registered")
        return
    if amount_wei <= 0 or amount_wei > MAX_TIP_WEI:
        print(f"Error: amount must be in (0, {MAX_TIP_WEI}] wei")
        return
    fee_wei = (amount_wei * TIP_FEE_BP) / BP_DENOMINATOR
    to_guide = amount_wei - fee_wei
    state.tips.append(
        TipRecord(
            from_addr=from_addr,
            to_guide=guide_addr,
            amount_wei=amount_wei,
            fee_wei=fee_wei,
            at_block=state.current_block,
        )
    )
    state.total_tips_wei += amount_wei
    state.total_tips_fees_wei += fee_wei
    state.treasury_balance_wei += fee_wei
    state.current_block += 1
    print(f"Tip sent: {fmt_eth(amount_wei)} to {truncate(guide_addr)} (fee {fmt_eth(fee_wei)} to treasury)")


# ---------------------------------------------------------------------------
# CLI: stats
# ---------------------------------------------------------------------------


def cmd_stats(state: AppState, args: argparse.Namespace) -> None:
    active_dests = len(get_active_destinations(state))
    print(f"Destinations: {len(state.destinations)} total, {active_dests} active")
    print(f"Itineraries: {len(state.itineraries)} (counter={state.itinerary_counter})")
    print(f"Reviews: {len(state.reviews)}")
    print(f"Guides: {len(list_guides(state))}")
    print(f"Tips: {len(state.tips)}")
    print(f"Current block: {state.current_block}, season: {state.current_season}")
    print(f"Treasury: {fmt_eth(state.treasury_balance_wei)}")
    print(f"Total tips: {fmt_eth(state.total_tips_wei)}, fees: {fmt_eth(state.total_tips_fees_wei)}")
    print(f"Updated: {state.updated_at}")


# ---------------------------------------------------------------------------
# CLI: export
# ---------------------------------------------------------------------------


def cmd_export(state: AppState, args: argparse.Namespace) -> None:
    path = getattr(args, "output", None)
    fmt = getattr(args, "format", "json").lower()
    if not path:
        path = "aflow_export.json"
    out_path = Path(path)
    if fmt == "json":
        out_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Exported state to {out_path}")
    else:
        print("Only format=json supported for export.")


# ---------------------------------------------------------------------------
# CLI: seed
# ---------------------------------------------------------------------------


def cmd_seed(state: AppState, args: argparse.Namespace) -> None:
    seed_initial_destinations(state)
    print("Seeded initial destinations. Run list-destinations to see them.")


# ---------------------------------------------------------------------------
# CLI: advance-blocks / advance-season
# ---------------------------------------------------------------------------


def cmd_advance_blocks(state: AppState, args: argparse.Namespace) -> None:
    n = int(getattr(args, "blocks", 1))
    state.current_block += n
    new_season = state.current_block // SEASON_BLOCKS
    if new_season > state.current_season:
        state.current_season = new_season
    print(f"Advanced {n} blocks. Current block={state.current_block}, season={state.current_season}")


def cmd_advance_season(state: AppState, args: argparse.Namespace) -> None:
    state.current_season += 1
    print(f"Season advanced to {state.current_season}")


# ---------------------------------------------------------------------------
# CLI: top-destinations (by rating)
# ---------------------------------------------------------------------------


def cmd_top_destinations(state: AppState, args: argparse.Namespace) -> None:
    limit = int(getattr(args, "limit", 10))
    dest_ratings: List[Tuple[str, float, int]] = []
    seen: set = set()
    for d in get_active_destinations(state):
        if d.dest_id in seen:
            continue
        seen.add(d.dest_id)
        avg, count = average_rating_for_dest(state, d.dest_id)
        if count > 0:
            dest_ratings.append((d.dest_id, avg, count))
    dest_ratings.sort(key=lambda x: (x[1], x[2]), reverse=True)
    dest_ratings = dest_ratings[:limit]
    if not dest_ratings:
        print("No rated destinations yet.")
        return
    print("Top destinations by average rating:")
    for i, (dest_id, avg, count) in enumerate(dest_ratings, 1):
        dest = get_destination_by_id(state, dest_id)
        name = dest.name if dest else truncate(dest_id)
        print(f"  {i}. {name}  avg={avg:.2f}  reviews={count}")


# ---------------------------------------------------------------------------
# CLI: list-reviews
# ---------------------------------------------------------------------------


def cmd_list_reviews(state: AppState, args: argparse.Namespace) -> None:
    dest_id = getattr(args, "dest_id", None)
    traveler = getattr(args, "traveler", None)
    limit = int(getattr(args, "limit", 30))
    revs = state.reviews
    if dest_id:
        revs = [r for r in revs if r.dest_id == dest_id]
    if traveler:
        revs = [r for r in revs if r.traveler == traveler]
    revs = revs[-limit:] if len(revs) > limit else revs
    if not revs:
        print("No reviews found.")
        return
    print(f"Reviews ({len(revs)}):")
    for r in revs:
        dest = get_destination_by_id(state, r.dest_id)
        name = dest.name if dest else truncate(r.dest_id)
        print(f"  {truncate(r.dest_id)}  {name}  rating={r.rating}  by {truncate(r.traveler)}  block={r.at_block}")


# ---------------------------------------------------------------------------
# CLI: show-destination
# ---------------------------------------------------------------------------


def cmd_show_destination(state: AppState, args: argparse.Namespace) -> None:
    dest_id = getattr(args, "dest_id", None) or (dest_id_from_name(getattr(args, "name", "")) if getattr(args, "name", None) else None)
    if not dest_id:
        print("Error: --dest_id or --name required")
        return
    dest = get_destination_by_id(state, dest_id)
    if not dest:
        print("Destination not found.")
        return
    print(f"Destination: {dest.name}")
    print(f"  id: {dest.dest_id}")
    print(f"  region: {dest.region_code} ({region_name(dest.region_code)})")
    print(f"  name_hash: {truncate(dest.name_hash, 14, 10)}")
    print(f"  listed_at_block: {dest.listed_at_block}")
    print(f"  active: {dest.active}")
    avg, count = average_rating_for_dest(state, dest_id)
    print(f"  reviews: {count}, average rating: {avg:.2f}" if count else "  reviews: 0")
