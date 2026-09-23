#!/usr/bin/env python3
"""aisle_store - config + AisleRiot-style statistics persistence.

AisleRiot keeps PER-GAME statistics (not a score leaderboard): Wins, Total
games, win Percentage, and Best/Worst *winning time*. We persist the same set,
plus the player's chosen options per game, under XDG paths.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

import aisle_aisleriot as ar

APP_DIR_NAME = "aisle-cli"


def _xdg(env: str, default_rel: str) -> str:
    base = os.environ.get(env)
    if not base:
        base = os.path.join(os.path.expanduser("~"), default_rel)
    return base


def config_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), APP_DIR_NAME)


def data_dir() -> str:
    return os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def stats_path() -> str:
    return os.path.join(data_dir(), "stats.json")


DEFAULT_CONFIG = {
    "last_game": "klondike",
    "symbols": True,
    "options": {},          # per-game option overrides, keyed by game key
    # Share statistics with the installed GNOME AisleRiot. When on (and its
    # config dir exists) we read from and write to its keyfile, so games played
    # in either program are mirrored in both. Defaults on.
    "sync_aisleriot": True,
    # set to True once we've folded any pre-existing local stats into the
    # shared keyfile, so the one-time merge doesn't double-count.
    "merged_into_aisleriot": False,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["options"] = {}
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            if isinstance(data.get("last_game"), str):
                cfg["last_game"] = data["last_game"]
            cfg["symbols"] = bool(data.get("symbols", True))
            if isinstance(data.get("options"), dict):
                cfg["options"] = data["options"]
            cfg["sync_aisleriot"] = bool(data.get("sync_aisleriot", True))
            cfg["merged_into_aisleriot"] = bool(data.get("merged_into_aisleriot", False))
            # optional UI-preference keys, only present once set by the player:
            #   color      - colour on/off (the 'v' toggle)
            #   code_skin  - play wrapped in source (the 'c' toggle)
            #   camo_theme - boss-mode disguise theme
            #   view       - board view: "expanded" cards or "legacy" cells
            if "color" in data:
                cfg["color"] = bool(data["color"])
            if "code_skin" in data:
                cfg["code_skin"] = bool(data["code_skin"])
            if isinstance(data.get("camo_theme"), str):
                cfg["camo_theme"] = data["camo_theme"]
            if data.get("view") in ("expanded", "legacy"):
                cfg["view"] = data["view"]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> bool:
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        return True
    except OSError:
        return False


def game_options(cfg: dict, game_key: str) -> dict:
    opts = cfg.get("options", {})
    val = opts.get(game_key)
    return dict(val) if isinstance(val, dict) else {}


def set_game_options(cfg: dict, game_key: str, options: dict) -> None:
    cfg.setdefault("options", {})[game_key] = dict(options)


# --------------------------------------------------------------------------- #
# Statistics  (per game key: wins, total, best, worst — times in seconds)
# --------------------------------------------------------------------------- #

EMPTY_STAT = {"wins": 0, "total": 0, "best": 0, "worst": 0}


def _norm(s: Optional[dict]) -> dict:
    out = dict(EMPTY_STAT)
    if isinstance(s, dict):
        out.update({k: int(s.get(k, 0)) for k in EMPTY_STAT})
    return out


def syncing() -> bool:
    """True when we should mirror stats with the installed AisleRiot."""
    cfg = load_config()
    return bool(cfg.get("sync_aisleriot", True)) and ar.available()


def load_stats() -> dict:
    try:
        with open(stats_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_stats(stats: dict) -> bool:
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(stats_path(), "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)
        return True
    except OSError:
        return False


def get_stat(game_key: str) -> dict:
    """A game's stats. When syncing, AisleRiot's keyfile is the source of truth
    (so wins recorded by AisleRiot itself show up here); otherwise local JSON.
    """
    if syncing():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is not None:
            shared = ar.read_stat(sect)
            if shared is not None:
                return _norm(shared)
    return _norm(load_stats().get(game_key))


def record_result(game_key: str, won: bool, seconds: float) -> dict:
    """Update a game's statistics with a finished game. Returns the new stat.

    Best/Worst track WINNING times only (AisleRiot semantics): a loss bumps the
    total but never the best/worst time. When syncing, the update is applied to
    BOTH the shared AisleRiot keyfile and our local JSON, so a game played here
    shows up in AisleRiot and vice versa.
    """
    # Fold the one win/loss into a given baseline stat.
    def apply(base: dict) -> dict:
        s = _norm(base)
        s["total"] += 1
        if won:
            s["wins"] += 1
            secs = max(1, int(round(seconds)))
            if s["best"] == 0 or secs < s["best"]:
                s["best"] = secs
            if secs > s["worst"]:
                s["worst"] = secs
        return s

    if syncing():
        _merge_local_into_aisleriot_once()
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is not None:
            updated = apply(ar.read_stat(sect))   # build on the shared value
            ar.write_stat(sect, updated)
            # keep local JSON as a mirror/backup in lock-step with the keyfile
            stats = load_stats()
            stats[game_key] = updated
            save_stats(stats)
            return updated

    # not syncing: local JSON only
    stats = load_stats()
    updated = apply(stats.get(game_key))
    stats[game_key] = updated
    save_stats(stats)
    return updated


def _merge_local_into_aisleriot_once() -> None:
    """One-time additive merge of any pre-existing local stats into the keyfile.

    Before we shared storage, this game kept its own JSON stats. The first time
    we sync, fold those prior games into AisleRiot's totals so nothing is lost,
    then mark it done so we never double-count. Per game we add our local totals
    to AisleRiot's and keep the better (faster best / slower worst) times.
    """
    cfg = load_config()
    if cfg.get("merged_into_aisleriot"):
        return
    local = load_stats()
    for game_key, lstat in local.items():
        sect = ar.GAME_TO_SECTION.get(game_key)
        if sect is None:
            continue
        l = _norm(lstat)
        if l["total"] == 0:
            continue
        shared = _norm(ar.read_stat(sect))
        merged = {
            "wins": shared["wins"] + l["wins"],
            "total": shared["total"] + l["total"],
        }
        bests = [b for b in (shared["best"], l["best"]) if b > 0]
        merged["best"] = min(bests) if bests else 0
        merged["worst"] = max(shared["worst"], l["worst"])
        ar.write_stat(sect, merged)
    cfg["merged_into_aisleriot"] = True
    save_config(cfg)


def reset_stats() -> int:
    """Clear statistics for the games we manage. Returns how many were cleared.

    When syncing, each managed game's Statistic is zeroed in the shared keyfile
    too (other AisleRiot games and all non-Statistic keys are left untouched).
    Local JSON is always cleared. Returns the count of games that had a record.
    """
    import aisle  # local import to avoid a cycle at module load
    cleared = 0
    if syncing():
        for game_key in aisle.GAME_ORDER:
            sect = ar.GAME_TO_SECTION.get(game_key)
            if sect is None:
                continue
            cur = ar.read_stat(sect)
            if cur and cur.get("total", 0) > 0:
                cleared += 1
            if cur is not None:
                ar.write_stat(sect, dict(EMPTY_STAT))
    else:
        cleared = sum(1 for v in load_stats().values()
                      if isinstance(v, dict) and v.get("total", 0) > 0)
    save_stats({})
    return cleared


def percentage(stat: dict) -> Optional[float]:
    if stat["total"] <= 0:
        return None
    return 100.0 * stat["wins"] / stat["total"]


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"
