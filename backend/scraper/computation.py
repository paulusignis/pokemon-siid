"""
ID (Intentional Draw) analysis for Pokemon TCG Swiss tournaments.

Top-cut thresholds by division size:
  - <= 8 players : compute P(top 1)
  - 9–20 players : compute P(top 4)
  - >  20 players: compute P(top 8)

For each pairing in a division, computes:
  - P(top cut | player IDs)  — player and opponent each get +1 point
  - P(top cut | player wins) — player gets +3 points, opponent gets +0

Other matches in the same division are simulated with equal probability
(1/3 each) for name_player win, draw, or opp_player win.

Simulation strategy:
  - n_other <= 10 → exhaustive enumeration of all 3^n outcomes
  - n_other >  10 → Monte Carlo with 10,000 samples

Ranking uses dense rank on points only (resistance tiebreaker not available
from pairings HTML alone — ties in points share the better rank).

Recommendation threshold: recommend "ID" only if prob_id - prob_win >= 0.02.
"""

from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

MONTE_CARLO_SAMPLES = 10_000
EXHAUSTIVE_THRESHOLD = 10
RECOMMENDATION_MARGIN = 0.02


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


def _top_cut_for_count(player_count: int) -> int:
    """
    Return the top-cut threshold to compute probabilities for, based on
    division size.
      <= 8 players : top 1
      9–20 players : top 4
      >  20 players: top 8
    """
    if player_count <= 8:
        return 1
    if player_count <= 20:
        return 4
    return 8


def _group_by_division(pairings: list) -> dict[str, list]:
    """Group pairings by the name_player's division."""
    groups: dict[str, list] = {}
    for p in pairings:
        div = p.name_player.division
        groups.setdefault(div, []).append(p)
    return groups


def _base_standings(div_pairings: list) -> dict[str, int]:
    """
    Build a dict of {player_name: current_points} for every player
    that appears in this division's pairings.
    """
    standings: dict[str, int] = {}
    for p in div_pairings:
        standings.setdefault(p.name_player.name, p.name_player.points)
        standings.setdefault(p.opp_player.name, p.opp_player.points)
    return standings


def _dense_rank(player_name: str, final_standings: dict[str, int]) -> int:
    """
    Dense rank: count players with strictly more points than this player,
    then add 1. Ties share the better rank.
    """
    my_points = final_standings[player_name]
    rank = 1 + sum(1 for pts in final_standings.values() if pts > my_points)
    return rank


def _apply_outcome(
    base: dict[str, int],
    target_pairing,
    target_result: str,  # "id" | "win"
    other_pairings: list,
    other_outcome: dict,  # {index: "name_wins" | "opp_wins"}
) -> dict[str, int]:
    """Return a new standings dict after applying all round results."""
    standings = dict(base)

    # Target pairing result
    if target_result == "id":
        standings[target_pairing.name_player.name] += 1
        standings[target_pairing.opp_player.name] += 1
    else:  # "win"
        standings[target_pairing.name_player.name] += 3
        # opponent gets +0

    # Other pairings results
    for idx, result in other_outcome.items():
        p = other_pairings[idx]
        if result == "name_wins":
            standings[p.name_player.name] += 3
        elif result == "draw":
            standings[p.name_player.name] += 1
            standings[p.opp_player.name] += 1
        else:  # opp_wins
            standings[p.opp_player.name] += 3

    return standings


_OUTCOME_CHOICES = ("name_wins", "draw", "opp_wins")


def _enumerate_outcomes(n: int) -> list[dict]:
    """Enumerate all 3^n win/draw/loss outcomes for n other matches."""
    outcomes = []
    for i in range(3 ** n):
        outcome = {}
        val = i
        for j in range(n):
            outcome[j] = _OUTCOME_CHOICES[val % 3]
            val //= 3
        outcomes.append(outcome)
    return outcomes


def _sample_outcomes(n: int, k: int) -> list[dict]:
    """Sample k random equal-probability win/draw/loss outcomes for n other matches."""
    outcomes = []
    for _ in range(k):
        outcomes.append({i: random.choice(_OUTCOME_CHOICES) for i in range(n)})
    return outcomes


def _analyze_pairing(target_pairing, other_pairings: list, base: dict[str, int], top_n: int) -> dict:
    """Compute ID analysis for a single pairing within its division."""
    n = len(other_pairings)

    if n <= EXHAUSTIVE_THRESHOLD:
        outcomes = _enumerate_outcomes(n)
        method = "exhaustive"
    else:
        outcomes = _sample_outcomes(n, MONTE_CARLO_SAMPLES)
        method = "monte_carlo"

    player_name = target_pairing.name_player.name
    count_id = 0
    count_win = 0

    for outcome in outcomes:
        standings_id = _apply_outcome(base, target_pairing, "id", other_pairings, outcome)
        if _dense_rank(player_name, standings_id) <= top_n:
            count_id += 1

        standings_win = _apply_outcome(base, target_pairing, "win", other_pairings, outcome)
        if _dense_rank(player_name, standings_win) <= top_n:
            count_win += 1

    total = len(outcomes)
    prob_id = count_id / total
    prob_win = count_win / total
    margin = prob_id - prob_win
    recommendation = "ID" if margin >= RECOMMENDATION_MARGIN else "WIN"

    return {
        "player": player_name,
        "top_cut": top_n,
        "current_points": target_pairing.name_player.points,
        "points_if_id": target_pairing.name_player.points + 1,
        "points_if_win": target_pairing.name_player.points + 3,
        "prob_top_cut_if_id": round(prob_id, 4),
        "prob_top_cut_if_win": round(prob_win, 4),
        "recommendation": recommendation,
        "id_beneficial": margin > 0,
        "margin": round(abs(margin), 4),
        "simulation_method": method,
        "other_matches_count": n,
    }


def compute_id_analysis(pairings: list) -> dict:
    """
    Run ID analysis for every pairing, grouped by division.

    Args:
        pairings: list of Pairing objects from scraper.parse_pairings()

    Returns:
        dict with key per division containing player count and pairing analyses.
    """
    if not pairings:
        logger.warning("No pairings provided; returning empty result")
        return {}

    divisions = _group_by_division(pairings)
    result = {}

    for division, div_pairings in divisions.items():
        base = _base_standings(div_pairings)
        # Count only players whose own division matches this group — opponents
        # from other divisions may appear in pairings but shouldn't inflate the count.
        player_count = len({
            player.name
            for p in div_pairings
            for player in (p.name_player, p.opp_player)
            if player.division.upper() == division
        })
        top_n = _top_cut_for_count(player_count)
        pairing_results = []

        for i, target in enumerate(div_pairings):
            other = [p for j, p in enumerate(div_pairings) if j != i]
            analysis = _analyze_pairing(target, other, base, top_n)

            pairing_results.append({
                "table": target.table_num,
                "name_player": asdict(target.name_player),
                "opp_player": asdict(target.opp_player),
                "id_analysis": analysis,
            })

        result[division] = {
            "player_count": player_count,
            "top_cut": top_n,
            "current_round_pairings": pairing_results,
        }

        logger.info(
            "Division %s: %d players, top_cut=%s, %d pairings analysed",
            division, player_count, top_n, len(div_pairings),
        )

    return result
