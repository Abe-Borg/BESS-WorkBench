# Editing the rules file

The engine reads `rules/ifc2024_nfpa855_2023.json`. That file is the place for code numbers, citations, and the one-line paraphrases shown on each check. It does not contain licensed standard text. Keep every `summary` to a single sentence you wrote yourself.

## What a change does

- `parameters.<name>.value` is the number the engine uses. Change `max_kwh_fire_area` from 600 to another number and the fire-area check follows the file. A test locks this in.
- `parameters.<name>.citation`, `edition`, `summary`, and `tags` are what the results panel shows for that input. Tags are `CODE`, `ASSUMED`, and `NEEDS PE REVIEW`.
- `rules[]` is the catalog. Each check looks up its `id` here for the title, citation, edition, and tags. If you add an id, the engine has to reference that same string or the check will not appear.
- `version` is shown on Project & Code Basis. Bump it when the numbers change. A project saved against an older version warns.
- `scope.sprinkler_systems_allowed` is the only sprinkler list the app will treat as in scope. Do not add clean agent, foam, water mist, or single-interlock.
- `editions` is the set the project is compared with. A project edition that differs warns and is tagged for PE review. The engine does not retune the numbers for a different edition.

## Tags

| Tag | When to use it |
| --- | --- |
| `CODE` | The lead gave the provision without marking it unconfirmed, and a section is cited. |
| `ASSUMED` | The lead marked the item with `~`, marked it `VERIFY`, or said the fire-alarm list is assumed by default. |
| `NEEDS PE REVIEW` | The lead flagged the item for a PE. Today that is FA items 2 and 12, and setpoint conversion. The 25 percent design fraction also carries it because the two leads do not agree. |

An empty tag list means the line is a workbench coordination rule (for example an automatic RFI) rather than a code section.

## Reload

Use **Tools → Reload rules file** after you save the JSON. You do not need to restart if you use that command. A bad JSON file is reported in the status bar and the previous rules stay loaded only if you do not replace the process; if the file fails to parse, fix it and reload again.

## Worked example

To change the hose default from 100 gpm to 250 gpm:

1. Set `parameters.hose_allowance_gpm.value` to `250`.
2. Bump `version` (for example `1.1.0`) and add a changelog line.
3. Reload the rules file.
4. **File → New**. Existing projects keep the hose value already saved on them, because hose is an editable project input that was copied from the rules file at creation. The check still cites the rules file and still tags the value `ASSUMED`.

Do not put a formula in the JSON. Behavioral changes (a new comparison, a new screen) belong in `bess_workbench/engine.py` with a test in `tests/`.

## Where the file is found

Source and an editable install use the `rules/` directory in the repo. A frozen `BESS-WorkBench.exe` uses the copy bundled beside the executable. `BESS_RULES_FILE` overrides both.
