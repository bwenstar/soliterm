#!/usr/bin/env python3
"""Build dist/soliterm.pyz, the single-file zipapp.

  python3 tools/build_pyz.py           # dist/soliterm.pyz
  python3 tools/build_pyz.py --wheel   # and a wheel and sdist (needs `build`)

Either way dist/ is emptied first, so it only ever holds this build.

The zipapp needs nothing but the standard library to build or to run: the
src/soliterm package goes into a staging directory next to the LICENSE and
a small __main__.py, and zipapp packs that up behind a shebang. Run the
result as `python3 dist/soliterm.pyz`, or as `./dist/soliterm.pyz`.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "soliterm"
DIST = ROOT / "dist"
TARGET = DIST / "soliterm.pyz"

INTERPRETER = "/usr/bin/env python3"
ENTRY = "soliterm.cli:main"

# zipapp can write a __main__.py for an entry point itself, but that one
# throws away main()'s return value. This one hands it to sys.exit.
MAIN_PY = """\
import sys

from {module} import {func}

sys.exit({func}())
"""


def _not_shipped(folder: str, names: List[str]) -> List[str]:
    """copytree ignore hook: keep the sources and py.typed, drop the rest.

    A checkout collects caches and editor files next to the code, and none
    of them belong in the archive.
    """
    keep = []
    for name in names:
        if name.startswith(".") or name == "__pycache__":
            continue
        if (Path(folder) / name).is_dir() or name.endswith(".py") or name == "py.typed":
            keep.append(name)
    return [name for name in names if name not in keep]


def build_pyz(target: Path = TARGET) -> Path:
    """Pack src/soliterm into a compressed, runnable zipapp at target."""
    module, func = ENTRY.split(":")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(PACKAGE, stage / "soliterm", ignore=_not_shipped)
        shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        (stage / "__main__.py").write_text(MAIN_PY.format(module=module, func=func))
        target.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(stage, target, interpreter=INTERPRETER,
                              compressed=True)
    return target


def build_dist() -> int:
    """Build a wheel and an sdist into dist/ with `python -m build`."""
    if importlib.util.find_spec("build") is None:
        print("--wheel needs the build module: pip install build", file=sys.stderr)
        return 1
    # setuptools reuses build/ between runs, and a file left there by an
    # older layout would end up in the new wheel, so start clean.
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    for egg_info in (ROOT / "src").glob("*.egg-info"):
        shutil.rmtree(egg_info)
    return subprocess.call([sys.executable, "-m", "build",
                            "--outdir", str(DIST), str(ROOT)])


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="build_pyz.py",
                                description="Build dist/soliterm.pyz.")
    p.add_argument("--wheel", action="store_true",
                   help="also build a wheel and an sdist with python -m build")
    args = p.parse_args(argv)

    # Old wheels, sdists or an aisle.pyz from an earlier layout would
    # otherwise sit next to the new files and go out with them.
    shutil.rmtree(DIST, ignore_errors=True)
    target = build_pyz(TARGET)
    size = target.stat().st_size
    shown = target.relative_to(ROOT) if ROOT in target.parents else target
    print(f"built {shown} ({size / 1024:.1f} KiB)", flush=True)
    if args.wheel:
        return build_dist()
    return 0


if __name__ == "__main__":
    sys.exit(main())
