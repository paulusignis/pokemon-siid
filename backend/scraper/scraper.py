"""
Fetches and parses a Pokemon TCG tournament pairings page.

Expected HTML table format:
  Column 0: Table number
  Column 1: Name player
  Column 2: blank ("vs.")
  Column 3: Opponent player

Two supported player cell formats:

  Old: "Kevin Clemente\xa0(3/0/1 (10) - MA)"
    - Non-breaking space (\xa0) separates name from the record block
    - Division suffix: MA (Masters), SR (Seniors), JR (Juniors)

  New: "Kevin Clemente (3/0/1 (10))"
    - No division suffix; division defaults to "MA"

Points: wins*3 + ties*1 (validated against reported value)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

VALID_DIVISIONS = {"MA", "SR", "JR"}
REQUEST_TIMEOUT = 15  # seconds
DEFAULT_DIVISION = "MA"  # used when the page omits the division suffix

# Old format: "Name (W/L/T (points) - DIVISION)"
_RE_WITH_DIVISION = re.compile(
    r"^(.+?)\s*\((\d+)/(\d+)/(\d+)\s*\((\d+)\)\s*-\s*(MA|SR|JR)\s*\)$",
    re.IGNORECASE,
)
# New format: "Name (W/L/T (points))"
_RE_NO_DIVISION = re.compile(
    r"^(.+?)\s*\((\d+)/(\d+)/(\d+)\s*\((\d+)\)\s*\)$",
)


@dataclass
class Player:
    name: str
    wins: int
    losses: int
    ties: int
    points: int
    division: str


@dataclass
class Pairing:
    table_num: int
    name_player: Player
    opp_player: Player


def fetch_pairings(url: str) -> str:
    """Fetch the pairings page HTML. Raises on network/HTTP errors."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_player_cell(cell_text: str) -> Player | None:
    """
    Parse a single player cell string into a Player.
    Returns None for BYE, empty cells, or cells that cannot be parsed.

    Supports two formats:
      Old: "Kevin Clemente\xa0(3/0/1 (10) - MA)"  — division explicit
      New: "Kevin Clemente (3/0/1 (10))"           — division defaults to MA
    """
    # Normalise: replace non-breaking spaces with regular spaces, then strip
    text = cell_text.replace("\xa0", " ").strip()
    if not text or text.upper() == "BYE":
        return None

    # Try old format first (includes division), then new format (no division)
    m = _RE_WITH_DIVISION.match(text)
    if m:
        division = m.group(6).upper()
        groups = m.group(1, 2, 3, 4, 5)
    else:
        m = _RE_NO_DIVISION.match(text)
        if not m:
            logger.warning("Cannot parse player cell, skipping: %r", text)
            return None
        division = DEFAULT_DIVISION
        logger.debug("No division in cell %r; defaulting to %s", text, DEFAULT_DIVISION)
        groups = m.group(1, 2, 3, 4, 5)

    try:
        name = groups[0].strip()
        if not name:
            return None

        wins   = int(groups[1])
        losses = int(groups[2])
        ties   = int(groups[3])
        points = int(groups[4])

        # Validate computed vs reported points
        expected_points = wins * 3 + ties
        if expected_points != points:
            logger.warning(
                "Points mismatch for %r: computed %d (W=%d L=%d T=%d), reported %d — using reported",
                name, expected_points, wins, losses, ties, points,
            )

        return Player(
            name=name,
            wins=wins,
            losses=losses,
            ties=ties,
            points=points,
            division=division,
        )

    except (ValueError, AttributeError) as exc:
        logger.warning("Failed to parse player cell %r: %s", text, exc)
        return None


def parse_pairings(html: str) -> list[Pairing]:
    """
    Parse all pairings from the page HTML.
    Returns a list of Pairing objects (one per valid table row across all tables).
    Rows where either player cannot be parsed are skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    pairings: list[Pairing] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            # Skip header rows (any cell contains "Name" or "Opponent")
            cell_texts = [c.get_text(strip=True) for c in cells]
            if any(t.lower() in ("name", "opponent", "table") for t in cell_texts):
                continue

            table_num_text = cell_texts[0]
            name_cell_text = cell_texts[1]
            opp_cell_text = cell_texts[3]

            # Parse table number (default 0 if unparseable)
            try:
                table_num = int(table_num_text)
            except ValueError:
                table_num = 0

            name_player = parse_player_cell(name_cell_text)
            opp_player = parse_player_cell(opp_cell_text)

            if name_player is None or opp_player is None:
                logger.debug(
                    "Skipping row %d: name=%r opp=%r",
                    table_num, name_cell_text, opp_cell_text,
                )
                continue

            pairings.append(Pairing(
                table_num=table_num,
                name_player=name_player,
                opp_player=opp_player,
            ))

    logger.info("Parsed %d pairings from HTML", len(pairings))
    return pairings
