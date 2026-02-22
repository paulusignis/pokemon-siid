"""Unit tests for backend/scraper/computation.py"""
import sys
import os
import random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

import pytest
from computation import (
    Player, Pairing, compute_id_analysis,
    _dense_rank, _analyze_pairing, _base_standings,
    RECOMMENDATION_MARGIN,
)


def make_player(name, wins, losses, ties, division="MA"):
    points = wins * 3 + ties
    return Player(name=name, wins=wins, losses=losses, ties=ties,
                  points=points, division=division)


def make_pairing(table, name_player, opp_player):
    return Pairing(table_num=table, name_player=name_player, opp_player=opp_player)


# ---------------------------------------------------------------------------
# _dense_rank
# ---------------------------------------------------------------------------

class TestDenseRank:
    def test_sole_leader(self):
        standings = {"A": 15, "B": 12, "C": 9}
        assert _dense_rank("A", standings) == 1

    def test_tied_for_first(self):
        standings = {"A": 15, "B": 15, "C": 9}
        assert _dense_rank("A", standings) == 1
        assert _dense_rank("B", standings) == 1

    def test_tied_for_third(self):
        standings = {"A": 15, "B": 15, "C": 12, "D": 12}
        assert _dense_rank("C", standings) == 3
        assert _dense_rank("D", standings) == 3

    def test_last_place(self):
        standings = {"A": 9, "B": 6, "C": 3}
        assert _dense_rank("C", standings) == 3


# ---------------------------------------------------------------------------
# _analyze_pairing — two-player division (no other matches)
# ---------------------------------------------------------------------------

class TestAnalyzePairing:
    def _two_player_setup(self):
        """Return (target_pairing, other_pairings=[], base_standings)."""
        a = make_player("Alice", 5, 1, 0)   # 15 pts
        b = make_player("Bob",   5, 1, 0)   # 15 pts
        target = make_pairing(1, a, b)
        base = _base_standings([target])
        return target, [], base

    def test_two_player_both_always_top8(self):
        target, others, base = self._two_player_setup()
        result = _analyze_pairing(target, others, base)
        # With only 2 players in the division, both are always top 8
        assert result["prob_top8_if_id"] == 1.0
        assert result["prob_top8_if_win"] == 1.0

    def test_fields_present(self):
        target, others, base = self._two_player_setup()
        result = _analyze_pairing(target, others, base)
        required = {
            "player", "current_points", "points_if_id", "points_if_win",
            "prob_top8_if_id", "prob_top8_if_win", "recommendation",
            "id_beneficial", "margin", "simulation_method", "other_matches_count",
        }
        assert required.issubset(result.keys())

    def test_points_computed_correctly(self):
        target, others, base = self._two_player_setup()
        result = _analyze_pairing(target, others, base)
        assert result["current_points"] == 15
        assert result["points_if_id"] == 16
        assert result["points_if_win"] == 18

    def test_uses_exhaustive_for_small_n(self):
        target, others, base = self._two_player_setup()
        result = _analyze_pairing(target, others, base)
        assert result["simulation_method"] == "exhaustive"
        assert result["other_matches_count"] == 0

    def test_guaranteed_top8_if_id(self):
        """Player with overwhelming point lead: ID should give prob 1.0."""
        # 8 players total: Alice at 30 pts, others at 0-3 pts each
        a = make_player("Alice", 10, 0, 0)  # 30 pts
        b = make_player("Bob", 0, 10, 0)   # 0 pts
        others_players = [make_player(f"P{i}", 0, 9, 0) for i in range(6)]  # 0 pts

        target = make_pairing(1, a, b)
        other_pairings = [
            make_pairing(i + 2, others_players[2*i], others_players[2*i+1])
            for i in range(3)
        ]
        all_pairings = [target] + other_pairings
        base = _base_standings(all_pairings)

        result = _analyze_pairing(target, other_pairings, base)
        # Alice has 30 pts; even with +1 (ID), she's far ahead of everyone
        assert result["prob_top8_if_id"] == 1.0

    def test_recommendation_win_when_margin_below_threshold(self):
        """When ID margin is tiny, recommendation should be WIN."""
        a = make_player("Alice", 5, 1, 0)
        b = make_player("Bob", 4, 2, 0)
        target = make_pairing(1, a, b)
        base = _base_standings([target])
        result = _analyze_pairing(target, [], base)
        # With only 2 players, both probs are 1.0 → margin is 0 → WIN
        assert result["recommendation"] == "WIN"
        assert result["margin"] == 0.0

    def test_exhaustive_vs_monte_carlo_convergence(self):
        """With 10 other matches, exhaustive and MC should be within 3%."""
        a = make_player("Alice", 5, 1, 0)  # 15 pts
        b = make_player("Bob", 5, 1, 0)    # 15 pts
        target = make_pairing(1, a, b)

        # Create 10 other MA pairings (20 more players)
        other_pairings = []
        for i in range(10):
            p1 = make_player(f"P{2*i}", 4, 2, 0)
            p2 = make_player(f"P{2*i+1}", 4, 2, 0)
            other_pairings.append(make_pairing(i + 2, p1, p2))

        all_pairings = [target] + other_pairings
        base = _base_standings(all_pairings)

        random.seed(42)
        result_exhaustive = _analyze_pairing(target, other_pairings, base)
        assert result_exhaustive["simulation_method"] == "exhaustive"

        # Force Monte Carlo by temporarily monkey-patching the threshold
        import computation as comp
        original = comp.EXHAUSTIVE_THRESHOLD
        comp.EXHAUSTIVE_THRESHOLD = -1  # force MC
        random.seed(42)
        result_mc = _analyze_pairing(target, other_pairings, base)
        comp.EXHAUSTIVE_THRESHOLD = original  # restore

        assert result_mc["simulation_method"] == "monte_carlo"
        assert abs(result_exhaustive["prob_top8_if_id"] - result_mc["prob_top8_if_id"]) < 0.05


# ---------------------------------------------------------------------------
# compute_id_analysis — integration
# ---------------------------------------------------------------------------

class TestComputeIdAnalysis:
    def test_empty_input(self):
        assert compute_id_analysis([]) == {}

    def test_groups_by_division(self):
        pairings = [
            make_pairing(1, make_player("A", 3, 0, 0, "MA"), make_player("B", 3, 0, 0, "MA")),
            make_pairing(2, make_player("C", 2, 0, 0, "SR"), make_player("D", 2, 0, 0, "SR")),
        ]
        result = compute_id_analysis(pairings)
        assert "MA" in result
        assert "SR" in result
        assert "JR" not in result

    def test_player_count(self):
        pairings = [
            make_pairing(1, make_player("A", 3, 0, 0, "MA"), make_player("B", 3, 0, 0, "MA")),
            make_pairing(2, make_player("C", 2, 0, 0, "MA"), make_player("D", 2, 0, 0, "MA")),
        ]
        result = compute_id_analysis(pairings)
        assert result["MA"]["player_count"] == 4

    def test_output_structure(self):
        pairings = [
            make_pairing(1, make_player("A", 3, 0, 0, "MA"), make_player("B", 3, 0, 0, "MA")),
        ]
        result = compute_id_analysis(pairings)
        ma = result["MA"]
        assert "player_count" in ma
        assert "current_round_pairings" in ma
        assert len(ma["current_round_pairings"]) == 1
        first = ma["current_round_pairings"][0]
        assert "table" in first
        assert "name_player" in first
        assert "opp_player" in first
        assert "id_analysis" in first
