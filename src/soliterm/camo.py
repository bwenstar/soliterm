"""soliterm.camo - camouflage ("boss") mode output for Soliterm.

Generates realistic-looking developer "work" output - compiler builds, test
runs, container builds, server logs - so the game can be hidden behind a screen
that looks like you are busy working. All content is generic and synthetic.

`stream(theme)` returns an endless generator of plausible terminal lines; the
TUI reveals them progressively (like watching a live build) and the text mode
prints a screenful. Themes: build, test, docker, logs, mixed.
"""

from __future__ import annotations

import os
import platform
import random
import sys
import time
from collections.abc import Iterator

THEMES = ["build", "test", "docker", "logs", "mixed"]
DEFAULT_THEME = "build"


def _home() -> str:
    """A home directory in this platform's style, for the fake paths.

    It is built from $USER alone, never looked up: with USER unset (as it
    usually is on Windows) the paths say ~ rather than name anyone.
    """
    name = os.environ.get("USER", "").split("@", 1)[0]  # drop any domain
    if not name:
        return "~"
    if sys.platform == "darwin":
        return f"/Users/{name}"
    if sys.platform == "win32":
        return f"C:/Users/{name}"
    return f"/home/{name}"


_PROJECTS = [
    "api-gateway",
    "payments-svc",
    "render-core",
    "data-pipeline",
    "auth-service",
    "search-indexer",
    "billing-worker",
    "edge-proxy",
]

_MODULES = [
    "http_server",
    "router",
    "session",
    "db_pool",
    "cache",
    "metrics",
    "auth",
    "crypto",
    "json_parse",
    "worker",
    "scheduler",
    "queue",
    "config",
    "logger",
    "tls",
    "buffer",
    "alloc",
    "hashmap",
    "vector",
    "utf8",
    "ratelimit",
    "retry",
    "trace",
    "pool",
    "codec",
]


def _build_scene(rng: random.Random) -> Iterator[str]:
    proj = rng.choice(_PROJECTS)
    jobs = rng.choice([4, 8, 12, 16])
    yield f"$ make -j{jobs} all"
    yield f"make[1]: Entering directory '{_home()}/work/{proj}/src'"
    flags = "-std=gnu17 -O2 -g -Wall -Wextra -Iinclude -MMD -MP -fPIC"
    mods = list(_MODULES)
    rng.shuffle(mods)
    n = rng.randint(14, len(mods))
    for m in mods[:n]:
        yield f"gcc {flags} -c src/{m}.c -o build/{m}.o"
        if rng.random() < 0.10:
            line = rng.randint(40, 320)
            col = rng.randint(3, 24)
            warn, flag = rng.choice(
                [
                    (
                        f"unused variable '{rng.choice(['tmp', 'ret', 'ctx', 'len', 'idx'])}'",
                        "-Wunused-variable",
                    ),
                    ("comparison of integer expressions of different signedness", "-Wsign-compare"),
                    (
                        f"'{rng.choice(['n', 'p', 'buf'])}' may be used uninitialized",
                        "-Wmaybe-uninitialized",
                    ),
                ]
            )
            yield f"src/{m}.c:{line}:{col}: warning: {warn} [{flag}]"
    yield (f"gcc -O2 -o build/{proj} build/*.o -lpthread -lm -lssl -lcrypto -ldl")
    yield f"make[1]: Leaving directory '{_home()}/work/{proj}/src'"
    yield "$ "


def _test_scene(rng: random.Random) -> Iterator[str]:
    yield "$ pytest -q"
    yield ("============================= test session starts =============================")
    yield (
        f"platform {sys.platform} -- Python {platform.python_version()}, pytest-8.1.1, pluggy-1.4.0"
    )
    total = rng.randint(90, 340)
    yield f"collected {total} items"
    yield ""
    files = [
        "test_engine",
        "test_router",
        "test_auth",
        "test_cache",
        "test_db",
        "test_serialize",
        "test_api",
        "test_model",
        "test_utils",
        "test_worker",
        "test_queue",
        "test_config",
        "test_session",
        "test_metrics",
    ]
    done = 0
    while done < total:
        f = rng.choice(files)
        cnt = min(rng.randint(4, 30), total - done)
        done += cnt
        pct = int(done * 100 / total)
        yield f"tests/{f + '.py':<24} {'.' * cnt} [{pct:3d}%]"
    secs = rng.uniform(3.0, 38.0)
    yield ""
    yield f"======================= {total} passed in {secs:.2f}s ======================="
    yield "$ "


def _docker_scene(rng: random.Random) -> Iterator[str]:
    proj = rng.choice(_PROJECTS)
    tag = rng.choice(["latest", "v1.4.2", "v2.0.1", "staging"])
    yield f"$ docker build -t {proj}:{tag} ."
    total = rng.randint(9, 15)
    steps = [
        "FROM python:3.12-slim",
        "WORKDIR /app",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "COPY . .",
        "RUN python -m compileall -q .",
        "RUN useradd -m appuser && chown -R appuser /app",
        "USER appuser",
        "EXPOSE 8080",
        "ENV PYTHONUNBUFFERED=1",
        "RUN python -c 'import app; app.selfcheck()'",
        "HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1",
        'ENTRYPOINT ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]',
    ]
    for i, step in enumerate(steps[:total], 1):
        yield f"Step {i}/{total} : {step}"
        sha = f"{rng.getrandbits(48):012x}"
        if step.startswith("RUN") and rng.random() < 0.7:
            yield f" ---> Running in {rng.getrandbits(48):012x}"
        yield f" ---> {sha}"
    img = f"{rng.getrandbits(64):016x}"
    yield f"Successfully built {img[:12]}"
    yield f"Successfully tagged {proj}:{tag}"
    yield "$ "


def _git_scene(rng: random.Random) -> Iterator[str]:
    branch = rng.choice(
        ["main", "develop", "feature/cache-layer", "fix/retry-backoff", "release/2.1"]
    )
    yield "$ git status"
    yield f"On branch {branch}"
    yield "Your branch is up to date with 'origin/" + branch + "'."
    yield ""
    yield "nothing to commit, working tree clean"
    yield "$ git pull --rebase"
    yield "Already up to date."
    yield "$ "


def _log_scene(rng: random.Random) -> Iterator[str]:
    threads = [f"http-nio-8080-exec-{i}" for i in range(1, 17)]
    svcs = [
        "OrderService",
        "UserRepository",
        "PaymentClient",
        "CacheManager",
        "KafkaConsumer",
        "AuthFilter",
        "SessionStore",
        "RateLimiter",
        "MetricsReporter",
        "RetryPolicy",
    ]
    templates = [
        "processed request {id} in {ms}ms",
        "cache hit ratio {pct}% over last {n} requests",
        "committed offset {id} for partition {p}",
        "issued token for user_id={id} (ttl={ms}ms)",
        "connection pool: {n} active, {p} idle",
        "scheduled job {id} completed in {ms}ms",
        "GET /api/v1/items/{id} 200 {ms}ms",
        "POST /api/v1/orders 201 {ms}ms",
        "flushed {n} metrics to collector",
        "rotated log segment {id}",
    ]
    while True:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        level = rng.choices(["INFO", "DEBUG", "WARN"], weights=[8, 3, 1])[0]
        msg = rng.choice(templates).format(
            id=rng.randint(1000, 99999),
            ms=rng.randint(1, 480),
            pct=rng.randint(70, 99),
            n=rng.randint(2, 64),
            p=rng.randint(0, 12),
        )
        yield (f"{ts} {level:<5} [{rng.choice(threads)}] c.a.svc.{rng.choice(svcs)} - {msg}")


_SCENES = {
    "build": _build_scene,
    "test": _test_scene,
    "docker": _docker_scene,
    "logs": _log_scene,
}


def stream(theme: str = DEFAULT_THEME, seed=None) -> Iterator[str]:
    """An endless generator of plausible 'work' lines for the given theme.

    build/test/docker repeat their scene (with a blank-line gap) to look like
    an active session; logs streams forever; mixed chains several scene types.
    """
    rng = random.Random(seed)
    if theme == "mixed":
        order = [_build_scene, _test_scene, _git_scene, _docker_scene]
        while True:
            for scene in order:
                yield from scene(rng)
                for _ in range(rng.randint(0, 2)):
                    yield ""
        return
    scene = _SCENES.get(theme, _build_scene)
    while True:
        yield from scene(rng)
        if theme != "logs":
            for _ in range(rng.randint(0, 2)):
                yield ""


def screenful(theme: str = DEFAULT_THEME, lines: int = 40, seed=None) -> list[str]:
    """A fixed block of `lines` work lines (for the text-mode boss command)."""
    gen = stream(theme, seed=seed)
    return [next(gen) for _ in range(lines)]


# --------------------------------------------------------------------------- #
# Code skin - plausible source lines to frame a live game in (the "code skin"
# play mode). Deterministic for a given seed so it stays stable across redraws.
# --------------------------------------------------------------------------- #

# A coherent-looking module preamble (thematically a little solver, which pairs
# naturally with a card board showing in the middle of the file).
_CODE_PREAMBLE = [
    "import random",
    "from dataclasses import dataclass, field",
    "from typing import List, Optional, Tuple",
    "",
    'RANKS = "A23456789TJQK"',
    'SUITS = "SHDC"',
    "",
    "@dataclass",
    "class Card:",
    "    rank: int",
    "    suit: str",
    "    face_up: bool = False",
    "",
    "def legal_moves(state):",
    "    moves = []",
    "    for col in state.tableau:",
    "        if col and col[-1].face_up:",
    "            moves.append(col[-1])",
    "    return moves",
    "",
    "def heuristic(state):",
    "    score = 0",
    "    for pile in state.foundations:",
    "        score += len(pile) * 13",
    "    return score - state.buried_count()",
    "",
    "def solve(state, depth=0, limit=64):",
    "    if state.is_won():",
    "        return depth",
    "    if depth >= limit:",
    "        return None",
    "    for mv in sorted(legal_moves(state), key=heuristic):",
    "        result = solve(state.apply(mv), depth + 1, limit)",
    "        if result is not None:",
    "            return result",
    "    return None",
    "",
]


def code_lines(n: int = 80, seed=None) -> list[str]:
    """`n` plausible Python source lines (no line numbers), deterministic.

    Used to frame the live board so the screen reads as a code file. Starts
    with a coherent module and extends with filler helper functions.
    """
    rng = random.Random(seed)
    lines = list(_CODE_PREAMBLE)
    while len(lines) < n:
        name = rng.choice(_MODULES)
        k = rng.randint(2, 9)
        lines += [
            f"def {name}_weight(state, k={k}):",
            "    acc = 0",
            "    for i in range(k):",
            f"        acc += state.rank_at(i) * {rng.randint(2, 7)}",
            "    return acc",
            "",
        ]
    return lines[:n]
