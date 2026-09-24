"""Spiderette: Spider on one deck and seven columns, dealt like Klondike."""

from __future__ import annotations

from .spider import Spider


class Spiderette(Spider):
    key = "spiderette"
    name = "Spiderette"
    blurb = "One-deck Spider on seven columns, dealt like Klondike."
    short_blurb = "One-deck Spider, dealt like Klondike."
    columns = (1, 2, 3, 4, 5, 6, 7)
    decks = 1

    @classmethod
    def default_options(cls):
        return {}  # four suits only, as AisleRiot has it

    @classmethod
    def option_spec(cls):
        return []

    def _lay_out(self, g):
        """The stock top left with the foundations beside it, then the columns."""
        self.stock = g.add_slot("stock")
        self.foundations = [g.add_slot("foundation") for _ in range(4)]
        g.carriage_return()
        self.tableau = [g.add_slot("tableau", "down") for _ in self.columns]
