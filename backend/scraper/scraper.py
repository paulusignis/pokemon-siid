"""
Fetches and parses a Pokemon TCG tournament pairings page.

Expected HTML table format:
  Column 0: Table number (ignored)
  Column 1: Name player  — "Alice Chen, 5-1-0, 15, MA"
  Column 2: blank (ignored)
  Column 3: Opponent player — same format

Player cell format: "Name, W-L-T, points, division"
  - Division: MA (Masters), SR (Seniors), JR (Juniors)
  - Points: wins*3 + ties*1 (validated against reported value)
"""

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

VALID_DIVISIONS = {"MA", "SR", "JR"}
REQUEST_TIMEOUT = 15  # seconds


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

    Expected format: "Alice Chen, 5-1-0, 15, MA"
    """
    text = cell_text.strip()
    if not text or text.upper() == "BYE":
        return None

    # Split on comma — name may contain spaces but not commas
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 4:
        logger.warning("Cell has fewer than 4 comma-parts, skipping: %r", text)
        return None

    try:
        name = parts[0]
        if not name:
            return None

        # Parse W-L-T record
        record_match = re.fullmatch(r"(\d+)-(\d+)-(\d+)", parts[1])
        if not record_match:
            logger.warning("Cannot parse record %r for cell %r", parts[1], text)
            return None
        wins, losses, ties = int(record_match[1]), int(record_match[2]), int(record_match[3])

        # Parse reported points
        points = int(parts[2])

        # Validate computed vs reported points
        expected_points = wins * 3 + ties * 1
        if expected_points != points:
            logger.warning(
                "Points mismatch for %r: computed %d (W=%d L=%d T=%d), reported %d — using reported",
                name, expected_points, wins, losses, ties, points,
            )

        division = parts[3].upper()
        if division not in VALID_DIVISIONS:
            logger.warning("Unknown division %r for player %r, skipping", division, name)
            return None

        return Player(
            name=name,
            wins=wins,
            losses=losses,
            ties=ties,
            points=points,
            division=division,
        )

    except (ValueError, IndexError) as exc:
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
