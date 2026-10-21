"""PyInstaller entry. Keeps the package importable as bess_workbench."""

from bess_workbench.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
