"""Command line: python -m wowconv <addon folder or zip> [-o OUTPUT]"""

import argparse
import sys
from pathlib import Path

from . import apidb
from .converter import NoAddonFound, convert_path


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="wowconv",
        description="Convert a retail or WoW Forever addon so it loads on WoW Classic where possible.")
    p.add_argument("input", help="addon folder, folder of addons, or .zip as downloaded")
    p.add_argument("-o", "--output", help="output folder, or a path ending in .zip (default: <input>-classic)")
    p.add_argument("-t", "--target", action="append", choices=sorted(apidb.TARGETS),
                   help="Classic flavor to target; repeatable (default: all)")
    p.add_argument("--interface", action="append", default=[], metavar="TARGET=NUMBER",
                   help="override the TOC ## Interface for a target, e.g. vanilla=11508")
    p.add_argument("--rewrite-libs", action="store_true",
                   help="also rewrite embedded libraries (Libs/ folders); off by default since "
                        "common libraries already support Classic")
    args = p.parse_args(argv)

    targets = args.target or list(apidb.TARGETS)
    interfaces = {t: apidb.TARGETS[t][1] for t in targets}
    for item in args.interface:
        t, _, num = item.partition("=")
        if t not in apidb.TARGETS or not num:
            p.error(f"--interface expects TARGET=NUMBER with TARGET one of {', '.join(apidb.TARGETS)}")
        interfaces[t] = num

    src = Path(args.input).resolve()
    if not src.exists():
        p.error(f"{src} does not exist")
    out = Path(args.output).resolve() if args.output else src.with_name(src.stem + "-classic")

    try:
        results, report = convert_path(src, out, targets, interfaces, args.rewrite_libs)
    except NoAddonFound as e:
        print(e, file=sys.stderr)
        return 1

    for r in results:
        print(f"{r.name}: wrote {', '.join(r.tocs_written) or 'no TOC'}; "
              f"{r.files_rewritten} files rewritten, {len(r.apis_shimmed)} APIs shimmed, "
              f"{len(r.findings)} items need manual attention")
    print(f"Output: {out}")
    print(f"Report: {report}")
    print("Interface numbers used: " + "; ".join(f"{t}={interfaces[t]}" for t in targets)
          + "  (check in game: /dump select(4, GetBuildInfo()))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
