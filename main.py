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

