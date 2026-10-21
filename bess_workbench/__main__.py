"""python -m bess_workbench"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bess-workbench", description="BESS WorkBench design aid")
    parser.add_argument("project", nargs="?", help="Optional .bessproj to open")
    parser.add_argument("--sample", action="store_true", help="Open the synthetic four-room sample")
    parser.add_argument("--export", nargs=2, metavar=("PROJECT", "OUTDIR"), help="Write DOCX, XLSX, and PDF without opening the window")
    args = parser.parse_args(argv)
    if args.export:
        from bess_workbench.controller import ProjectController, load_project
        from bess_workbench.reports import export_all

        project = load_project(args.export[0])
        controller = ProjectController(project)
        paths = export_all(controller.project, controller.analysis, args.export[1])
        for path in paths.values():
            print(path)
        return 0
    from bess_workbench.ui.main_window import install_excepthook, run

    install_excepthook()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
