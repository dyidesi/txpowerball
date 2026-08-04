"""Powerball pick strategies inspired by PawnPower Number Selection Strategies."""

from strategies.base import Pick, PickResult
from strategies.due_numbers import DueNumbersStrategy
from strategies.patterns import PatternsStrategy
from strategies.bar_graph import BarGraphStrategy
from strategies.line_graph import LineGraphStrategy
from strategies.repeats_consecutive import RepeatsConsecutiveStrategy
from strategies.random_picks import RandomPicksStrategy
from strategies.pseudo_history import PseudoHistoryStrategy
from strategies.automated import AutomatedStrategy
from strategies.unpopular import UnpopularStrategy
from strategies.wheeling import WheelingStrategy

STRATEGY_REGISTRY = {
    "Unpopular (Anti-Share)": UnpopularStrategy,
    "Wheel ($10 Coverage)": WheelingStrategy,
    "Due Numbers": DueNumbersStrategy,
    "Patterns (5-Column)": PatternsStrategy,
    "Bar Graph Balance": BarGraphStrategy,
    "Line Graph Momentum": LineGraphStrategy,
    "Repeats & Consecutive Filter": RepeatsConsecutiveStrategy,
    "Random (Pattern-Constrained)": RandomPicksStrategy,
    "Pseudo History Validated": PseudoHistoryStrategy,
    "Automated (All Strategies)": AutomatedStrategy,
}

__all__ = [
    "Pick",
    "PickResult",
    "STRATEGY_REGISTRY",
    "UnpopularStrategy",
    "WheelingStrategy",
    "DueNumbersStrategy",
    "PatternsStrategy",
    "BarGraphStrategy",
    "LineGraphStrategy",
    "RepeatsConsecutiveStrategy",
    "RandomPicksStrategy",
    "PseudoHistoryStrategy",
    "AutomatedStrategy",
]
