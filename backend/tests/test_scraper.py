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
        p = parse_player_cell("Alice Chen\xa0(5/1/0 (15) - MA)")
        assert p is not None
        assert p.name == "Alice Chen"
        assert p.wins == 5
        assert p.losses == 1
        assert p.ties == 0
        assert p.points == 15
        assert p.division == "MA"

    def test_senior_division(self):
        p = parse_player_cell("Bob Kim\xa0(3/2/0 (9) - SR)")
        assert p is not None
        assert p.division == "SR"

    def test_junior_division(self):
        p = parse_player_cell("Charlie Doe\xa0(4/1/1 (13) - JR)")
        assert p is not None
        assert p.division == "JR"
        assert p.ties == 1
        assert p.points == 13

    def test_tie_record(self):
        p = parse_player_cell("Dana Lee\xa0(4/1/1 (13) - MA)")
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
        assert parse_player_cell("Eve\xa0(3/0/0 (9) - XY)") is None

    def test_malformed_record_skipped(self):
        assert parse_player_cell("Frank\xa0(3/0 (9) - MA)") is None

    def test_new_format_no_division(self):
        # New format omits division — should parse and default to MA
        p = parse_player_cell("Grace (3/0/0 (9))")
        assert p is not None
        assert p.name == "Grace"
        assert p.wins == 3
        assert p.losses == 0
        assert p.ties == 0
        assert p.points == 9
        assert p.division == "MA"

    def test_new_format_with_nbsp(self):
        p = parse_player_cell("Kevin Clemente\xa0(3/0/1 (10))")
        assert p is not None
        assert p.name == "Kevin Clemente"
        assert p.wins == 3
        assert p.ties == 1
        assert p.points == 10
        assert p.division == "MA"

    def test_truly_malformed_skipped(self):
        # Missing the inner (points) wrapper — neither format matches
        assert parse_player_cell("Grace\xa0(3/0/0 - MA)") is None

    def test_lowercase_division_normalised(self):
        p = parse_player_cell("Hank\xa0(1/0/0 (3) - ma)")
        assert p is not None
        assert p.division == "MA"

    def test_points_mismatch_uses_reported(self):
        # Reported 12 but computed should be 3*3 + 0 = 9 — uses reported value
        p = parse_player_cell("Iris\xa0(3/0/0 (12) - MA)")
        assert p is not None
        assert p.points == 12

    def test_space_around_parens(self):
        # Extra whitespace around the record block should still parse
        p = parse_player_cell("Kevin Clemente\xa0(3/0/1 (10) - MA)")
        assert p is not None
        assert p.name == "Kevin Clemente"
        assert p.wins == 3
        assert p.losses == 0
        assert p.ties == 1
        assert p.points == 10
        assert p.division == "MA"


# ---------------------------------------------------------------------------
# parse_pairings
# ---------------------------------------------------------------------------

SIMPLE_TABLE = """
<html><body>
<table>
  <tr><th>Table</th><th>Name</th><th></th><th>Opponent</th></tr>
  <tr>
    <td>1</td>
    <td>Alice Chen\xa0(5/1/0 (15) - MA)</td>
    <td></td>
    <td>Bob Martinez\xa0(5/1/0 (15) - MA)</td>
  </tr>
  <tr>
    <td>2</td>
    <td>Carol Smith\xa0(4/2/0 (12) - MA)</td>
    <td></td>
    <td>Dave Jones\xa0(4/2/0 (12) - MA)</td>
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
    <td>Alice Chen\xa0(5/1/0 (15) - MA)</td>
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
  <tr><td>1</td><td>Alice\xa0(5/1/0 (15) - MA)</td><td></td><td>Bob\xa0(5/1/0 (15) - MA)</td></tr>
  <tr><td>2</td><td>Charlie\xa0(3/0/0 (9) - SR)</td><td></td><td>Diana\xa0(3/0/0 (9) - SR)</td></tr>
  <tr><td>3</td><td>Eli\xa0(2/0/0 (6) - JR)</td><td></td><td>Fay\xa0(2/0/0 (6) - JR)</td></tr>
</table>
</body></html>
"""


NEW_FORMAT_TABLE = """
<html><body>
<table>
  <tr><th>Table</th><th>Name</th><th></th><th>Opponent</th></tr>
  <tr>
    <td>1</td>
    <td>Alice Chen (5/1/0 (15))</td>
    <td>vs.</td>
    <td>Bob Martinez (5/1/0 (15))</td>
  </tr>
  <tr>
    <td>2</td>
    <td>Carol Smith (4/2/0 (12))</td>
    <td>vs.</td>
    <td>Dave Jones (4/2/0 (12))</td>
  </tr>
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

    def test_new_format_parses(self):
        pairings = parse_pairings(NEW_FORMAT_TABLE)
        assert len(pairings) == 2
        assert pairings[0].name_player.name == "Alice Chen"
        assert pairings[0].name_player.division == "MA"
        assert pairings[1].opp_player.name == "Dave Jones"

    def test_empty_html(self):
        pairings = parse_pairings("<html><body></body></html>")
        assert pairings == []

    def test_header_row_skipped(self):
        # The header row contains "Name" — should not be parsed as a pairing
        pairings = parse_pairings(SIMPLE_TABLE)
        # Only 2 data rows, not 3 (header + 2 data)
        assert len(pairings) == 2
