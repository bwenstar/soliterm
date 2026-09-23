"""tools/build_pyz.py packs a zipapp that runs the game on its own."""

import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import soliterm
from soliterm.engine import GAME_ORDER

TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_pyz.py"

pytestmark = pytest.mark.skipif(not TOOL.exists(), reason="no tools/ in this tree")


@pytest.fixture(scope="module")
def pyz(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("build_pyz", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.build_pyz(tmp_path_factory.mktemp("dist") / "soliterm.pyz")


def run(pyz, *args):
    # no PYTHONPATH, so the archive has to bring the whole package along (the
    # isolated HOME from conftest is already in the environment)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, str(pyz), *args], capture_output=True,
                          text=True, env=env, cwd=str(pyz.parent), timeout=60)


def test_the_archive_holds_the_package_the_license_and_a_main(pyz):
    with zipfile.ZipFile(pyz) as z:
        infos = {i.filename: i for i in z.infolist()}
    for name in ("__main__.py", "LICENSE", "soliterm/cli.py", "soliterm/py.typed",
                 "soliterm/engine/core.py", "soliterm/engine/games/klondike.py"):
        assert name in infos
    assert not [n for n in infos if "__pycache__" in n or n.endswith(".pyc")]
    assert all(i.compress_type == zipfile.ZIP_DEFLATED
               for n, i in infos.items() if n.endswith(".py"))


def test_the_archive_starts_with_a_shebang(pyz):
    assert pyz.read_bytes().startswith(b"#!/usr/bin/env python3\n")
    if os.name == "posix":
        assert os.access(pyz, os.X_OK)


def test_the_archive_runs_version_and_list(pyz):
    r = run(pyz, "--version")
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"soliterm {soliterm.__version__}\n"
    r = run(pyz, "--list")
    assert r.returncode == 0, r.stderr
    assert [line.split()[0] for line in r.stdout.splitlines()[1:]] == GAME_ORDER
