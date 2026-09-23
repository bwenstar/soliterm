"""soliterm.migrate - bring the settings and stats over from aisle-cli.

Soliterm used to be called aisle-cli and kept its config.json and stats.json
in aisle-cli folders. The first time it runs under the new name, ensure()
copies them into the soliterm folders. They are copied, never moved, so an
old copy of the program still finds its own files.

The one-time AisleRiot merge must not run again on the copy: an old
version that was sharing kept stats.json in step with the keyfile, so
merging it now would count every shared game twice.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import List, Optional, Tuple

from . import aisleriot as ar
from . import store

OLD_APP_DIR_NAME = "aisle-cli"


def _old_paths() -> Tuple[str, str]:
    """aisle-cli's config.json and stats.json, found the way the store
    finds ours (XDG dirs, else the home folder)."""
    return (os.path.join(store._xdg("XDG_CONFIG_HOME", ".config"),
                         OLD_APP_DIR_NAME, "config.json"),
            os.path.join(store._xdg("XDG_DATA_HOME", ".local/share"),
                         OLD_APP_DIR_NAME, "stats.json"))


def _say(msg: str) -> None:
    print(f"soliterm: {msg}", file=sys.stderr)


def _read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _object(raw: Optional[bytes]) -> Optional[dict]:
    """The JSON object in `raw`, or None if there isn't one."""
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: str, raw: bytes) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{os.path.basename(path)}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, indent=2).encode("utf-8")


def _merged(config: Optional[dict], stats: dict) -> Optional[bool]:
    """Whether the old stats are already in the keyfile, or None if there is
    nothing to say (no game on record)."""
    if config is not None and config.get("merged_into_aisleriot") is True:
        return True
    if not any(k in ar.GAME_TO_SECTION for k in stats):
        return None
    # Old versions shared whenever the keyfile was there, so stats beside a
    # keyfile are a copy of what it holds. Their merge flag in config.json
    # can't be trusted to say so (a stale save could turn it back off). With
    # sharing turned off they may not be, but leaving them out of AisleRiot's
    # totals beats counting them twice. With no keyfile they are nowhere
    # else yet, and go in once AisleRiot turns up.
    return os.path.exists(ar.keyfile_path())


def ensure() -> None:
    """Copy aisle-cli's files into the soliterm folders if neither soliterm
    folder is there yet, and say so on stderr. Does nothing on later runs.

    A damaged old file is copied as it is, for the store to set aside as it
    does any damaged file. If an old file can't be read, nothing is copied
    and it is tried again next time.
    """
    if os.path.exists(store.config_dir()) or os.path.exists(store.data_dir()):
        return
    old_config, old_stats = _old_paths()
    try:
        config_raw, stats_raw = _read(old_config), _read(old_stats)
    except OSError as exc:
        _say(f"couldn't read {exc.filename or 'the aisle-cli files'} "
             f"({exc.strerror or exc}), so the aisle-cli settings and "
             "statistics were not copied over; they will be tried again next time")
        return
    if config_raw is None and stats_raw is None:
        return

    config = _object(config_raw)
    stats = _object(stats_raw)
    if stats is not None:
        meta = stats.get(store.META_KEY)
        meta = dict(meta) if isinstance(meta, dict) else {}
        if not isinstance(meta.get("merged_into_aisleriot"), bool):
            merged = _merged(config, stats)
            if merged is not None:
                # the marker goes in stats.json, next to the stats it guards
                meta["merged_into_aisleriot"] = merged
                stats[store.META_KEY] = meta
                stats_raw = _dump(stats)
    had_config = config_raw is not None
    note = {"app": OLD_APP_DIR_NAME, "at": time.strftime("%Y-%m-%d")}
    if config_raw is None or config is not None:
        config_raw = _dump({**(config or {}), "migrated_from": note})

    # stats first: if we stop in between, they and their merge marker are
    # what matters
    copied: List[str] = []
    try:
        if stats_raw is not None:
            _write(store.stats_path(), stats_raw)
            copied.append(f"{old_stats} to {store.stats_path()}")
        _write(store.config_path(), config_raw)
        if had_config:
            copied.append(f"{old_config} to {store.config_path()}")
    except OSError as exc:
        _say(f"couldn't copy the aisle-cli settings and statistics over "
             f"({exc.strerror or exc}); the old files are left as they were")
        return
    _say("aisle-cli is now soliterm: copied " + " and ".join(copied)
         + "; the old files are left as they were")
