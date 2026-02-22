"""Unit tests for backend/scraper/scraper.py"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

import pytest
from scraper import parse_pairings, parse_player_cell, Player


# ---------------------------------------------------------------------------
# parse_player_cell
# ---------------------------------------------------------------------------

class TestParsePlayerCell:
    def test_normal_cell(self):
        p = parse_player_cell("Alice Chen, 5-1-0, 15, MA")
        assert p is not None
        assert p.name == "Alice Chen"
        assert p.wins == 5
        assert p.losses == 1
        assert p.ties == 0
        assert p.points == 15
        assert p.division == "MA"

    def test_senior_division(self):
        p = parse_player_cell("Bob Kim, 3-2-0, 9, SR")
        assert p is not None
        assert p.division == "SR"

    def test_junior_division(self):
        p = parse_player_cell("Charlie Doe, 4-1-1, 13, JR")
        assert p is not None
        assert p.division == "JR"
        assert p.ties == 1
        assert p.points == 13

    def test_tie_record(self):
        p = parse_player_cell("Dana Lee, 4-1-1, 13, MA")
        assert p is not None
        assert p.wins == 4
        assert p.losses == 1
        assert p.ties == 1
        # computed: 4*3 + 1*1 = 13 matches reported
        assert p.points == 13

    def test_bye_skipped(self):
        assert parse_player_cell("BYE") is None
        assert parse_player_cell("bye") is None

    def test_empty_skipped(self):
        assert parse_player_cell("") is None
        assert parse_player_cell("   ") is None

    def test_unknown_division_skipped(self):
        assert parse_player_cell("Eve, 3-0-0, 9, XY") is None

    def test_malformed_record_skipped(self):
        assert parse_player_cell("Frank, 3-0, 9, MA") is None

    def test_too_few_parts_skipped(self):
        assert parse_player_cell("Grace, 3-0-0, 9") is None

    def test_lowercase_division_normalised(self):
        p = parse_player_cell("Hank, 1-0-0, 3, ma")
        assert p is not None
        assert p.division == "MA"

    def test_points_mismatch_uses_reported(self):
        # Reported 12 but computed should be 3*3 + 0 = 9 — uses reported value
        p = parse_player_cell("Iris, 3-0-0, 12, MA")
        assert p is not None
        assert p.points == 12


# ---------------------------------------------------------------------------
# parse_pairings
# ---------------------------------------------------------------------------

SIMPLE_TABLE = """
<html><body>
<table>
  <tr><th>Table</th><th>Name</th><th></th><th>Opponent</th></tr>
  <tr>
    <td>1</td>
    <td>Alice Chen, 5-1-0, 15, MA</td>
    <td></td>
    <td>Bob Martinez, 5-1-0, 15, MA</td>
  </tr>
  <tr>
    <td>2</td>
    <td>Carol Smith, 4-2-0, 12, MA</td>
    <td></td>
    <td>Dave Jones, 4-2-0, 12, MA</td>
  </tr>
</table>
</body></html>
"""

BYE_TABLE = """
<html><body>
<table>
  <tr><th>Table</th><th>Name</th><th></th><th>Opponent</th></tr>
  <tr>
    <td>1</td>
    <td>Alice Chen, 5-1-0, 15, MA</td>
    <td></td>
    <td>BYE</td>
  </tr>
</table>
</body></html>
"""

MULTI_DIVISION_TABLE = """
<html><body>
<table>
  <tr><th>Table</th><th>Name</th><th></th><th>Opponent</th></tr>
  <tr><td>1</td><td>Alice, 5-1-0, 15, MA</td><td></td><td>Bob, 5-1-0, 15, MA</td></tr>
  <tr><td>2</td><td>Charlie, 3-0-0, 9, SR</td><td></td><td>Diana, 3-0-0, 9, SR</td></tr>
  <tr><td>3</td><td>Eli, 2-0-0, 6, JR</td><td></td><td>Fay, 2-0-0, 6, JR</td></tr>
</table>
</body></html>
"""


class TestParsePairings:
    def test_parses_normal_rows(self):
        pairings = parse_pairings(SIMPLE_TABLE)
        assert len(pairings) == 2

    def test_table_numbers(self):
        pairings = parse_pairings(SIMPLE_TABLE)
        assert pairings[0].table_num == 1
        assert pairings[1].table_num == 2

    def test_player_fields(self):
        pairings = parse_pairings(SIMPLE_TABLE)
        p = pairings[0]
        assert p.name_player.name == "Alice Chen"
        assert p.opp_player.name == "Bob Martinez"

    def test_bye_row_skipped(self):
        pairings = parse_pairings(BYE_TABLE)
        assert len(pairings) == 0

    def test_multi_division(self):
        pairings = parse_pairings(MULTI_DIVISION_TABLE)
        divisions = {p.name_player.division for p in pairings}
        assert divisions == {"MA", "SR", "JR"}

    def test_empty_html(self):
        pairings = parse_pairings("<html><body></body></html>")
        assert pairings == []

    def test_header_row_skipped(self):
        # The header row contains "Name" — should not be parsed as a pairing
        pairings = parse_pairings(SIMPLE_TABLE)
        # Only 2 data rows, not 3 (header + 2 data)
        assert len(pairings) == 2
