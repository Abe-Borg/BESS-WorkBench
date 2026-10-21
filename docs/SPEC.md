# BESS WorkBench specification

Version 0.1.0. This is a design aid for engineers laying out lithium-ion BESS / ESS (UPS battery) rooms in United States hyperscale data centers. It is not a stamped calculation and it is not a substitute for the adopted code or the AHJ.

The banner in the app, and the header of every report, says: **Design aid. Verify values against adopted codes and AHJ.**

Where the 2026-10-21 fire-protection and fire-alarm lead notes conflict with a product wish, the lead notes win. Items they marked `~` or `VERIFY` are tagged `ASSUMED`. Items they flagged for a PE, including setpoint conversion, are tagged `NEEDS PE REVIEW`. Fire-alarm items are assumed by default.

## Scope lock

- United States only. Any other jurisdiction is `BLOCKED`.
- Sprinklers are wet, dry, or double-interlock preaction. Clean agent, foam, water mist, and single-interlock are not in the model, the system picker, or the reports except as names of things this app refuses.
- One rules file: `rules/ifc2024_nfpa855_2023.json`. Default editions are IFC/IBC/IMC 2024, NEC 2023, NFPA 855-2023, NFPA 72-2022, NFPA 13-2025, NFPA 69-2024. NEC is recorded. This app does not size conductors.

## Stack

Python 3.12. PySide6 UI. Pydantic project file. python-docx, openpyxl, and reportlab for reports. The Anthropic SDK for optional AI. keyring for the API key. PyInstaller and Inno Setup for the Windows package. The calculation and rules engine do not import Qt.

Run from source, including on Linux:

```bash
pip install -e ".[dev]"
python -m bess_workbench
```

## Project file

A `.bessproj` file is JSON, schema `1.0.0`. Unknown keys are rejected so a typo does not silently disappear.

| Object | Fields that matter |
| --- | --- |
| `meta` | Name, number, client, site, prepared by, notes, `synthetic` |
| `code_basis` | Edition strings, occupancy (default F-1, assumed for the fire-area table), jurisdiction, AHJ notes |
| `ruleset_id`, `ruleset_version` | The file the project was created against |
| `rooms[]` | Id, name, area (sf), height (ft), wall/floor/ceiling hours, fire-area id, smoke detection |
| `ess_groups[]` | Room, chemistry, kWh, spacing (inches, recorded only), UL 9540 listing, UL 9540A report |
| `fire_areas[]` | Barrier hours, floor/ceiling hours |
| `sprinklers` | `wet` / `dry` / `double_interlock_preaction`, density, hose gpm, hose minutes, duct K and psi |
| `exhaust` | IMC 509 flags, motorized damper fail-open and proven-open, per-room isolation damper, proofs, standby power, whether HVAC shutdown includes the exhaust, other-duct wall and damper hours |
| `gas` | Species list and source, 9540A gas-data flag, setpoint basis, alarm and design % LFL, monitoring-only, add-alternate, BACnet-only, explosion-control flag, horns on FA NACs, distinct notification, high-gas to FACP, landings shown, supervising station, latch and manual reset, controller relays/inputs/functions, sensors, release masses |
| `battery` | FACP and gas-panel currents, voice flag, margin, aging derate, temperature derate |
| `cause_effect[]` | Rows of causes and X marks. Regenerated until someone edits a cell |
| `rfis[]` | Auto, manual, and AI items. Assignee is Architect, Mech, Elec, Controls vendor, Owner, or AHJ |
| `provenance[]` | Field path, source document, page, time. Written when a document-intake field is accepted |
| `ai_narrative` | Optional basis-of-design prose. Labeled AI-drafted in the DOCX when a model id is stored |

## Engine

`ProjectController.recompute()` fills missing fire areas, rebuilds the cause-and-effect matrix unless it was edited, runs `analyze()`, and syncs the RFI register.

Each check has:

- status: `PASS`, `FAIL`, `WARN`, `BLOCKED`, or `INFO`
- value
- citation and edition, from the rules file
- tags

Screen badges use the worst status on that screen. Order is `BLOCKED`, then `FAIL`, then `WARN`, then `INFO`, then `PASS`. The RFI badge uses the worst open item.

`INFO` is a real status. The register lists every result that is not `PASS`, plus the lead-mandated automatic RFIs. Closing an automatic item records that a person closed it. The engine does not reopen a user-closed item. If the condition clears on its own, an still-open automatic item is closed with a one-line note.

### Fire areas

- Lithium-ion energy at or above 20 kWh in a room brings the room rules into effect (`FP-THRESH-20`, IFC 2024 Table 1207.1.1).
- In-scope rooms need a 2 hour wall. A lower floor or ceiling warns (`FP-ROOM-2H`, IFC 2024 1207.7.4).
- One claimed fire area is a single area even at 2 hours. Its lithium-ion kWh is summed.
- Two or more claimed areas are separate only when each separating area has a barrier and a floor/ceiling of at least 3 hours (IBC 2024 Table 707.3.10, occupancy F-1 assumed; IBC 2024 711.2.4.2). Areas that do not qualify are added together for the cap.
- Above 600 kWh fails. From 570 kWh through 600 kWh warns, including a value sitting on the cap. The 600 kWh figure is `ASSUMED` because the FP lead marked Table 1207.5 unconfirmed (`FP-FA-600`).
- Other chemistries are not added into that 600 kWh total. They warn for PE review.

### Sprinklers

- Demand for a room is density times `min(room area, 2500 sf)`.
- Dry and double-interlock preaction multiply that area by 1.30. The added square feet are shown (`FP-SPR-30`, NFPA 13-2025 19.2.3.2.5, `ASSUMED`).
- The system total is the governing room plus the hose allowance once. Hose defaults are 100 gpm and 60 minutes, assumed and editable. Worksheet gallons are that total times the duration. This is not a tank sizing method.
- Hazen-Williams C is fixed at 100 and is only recorded. There is no pipe model.
- Duct sprinkler flow is `q = K * sqrt(p)`. Pressure below 7 psi fails.
- Density below 0.3 gpm/sf fails unless every group with energy has a UL 9540A report (IFC 2024 1207.5.5).
- A group above 50 kWh without a UL 9540A report blocks sprinkler sign-off (`BLOCKED`). The arithmetic is still shown. The 50 kWh cutoff is a workbench gate, tagged `ASSUMED`.

### Exhaust, detection, and controls

- No fire, smoke, balancing, or backdraft damper on the gas exhaust (IMC 2024 509.6.1, 509.5.1, and the lead note on backdraft dampers).
- A rated shaft is required where the duct crosses a rated assembly, and not when the duct terminates at an exterior wall or roof (IMC 2024 509.6.1.1).
- A motorized damper fails open and proves open to the FACP.
- Other ducts through a BESS wall: 3 hour damper in a 3 hour wall, 1.5 hour damper otherwise (IBC 2024 Table 717.3.2.1).
- Low alarm from either hydrogen or DMC starts exhaust and makeup air, latched, manual reset.
- Alarm setpoint at or below 10% LFL. A design fraction above 25% LFL fails. Exactly 25% warns, because the FP lead said 25% and the FA lead said below 25%. Both citations are NFPA 855-2023 9.6.5.6, tagged `ASSUMED` and `NEEDS PE REVIEW`.
- Default gas list is H2 and DMC until UL 9540A names the species. At least one sensor per listed gas per room (IFC 2024 916.3).
- H2 is high, within 12 inches of the ceiling. DMC is low. There is no fixed code height. Each height stays an open item until the vendor justifies it from 9540A data and airflow with the exhaust on and with the exhaust failed.
- Single-gas % LEL without 9540A gas data is an open item.
- Monitoring-only or BACnet-only gas detection fails hard when it is the explosion control. An add-alternate is an open item on the same RFI.
- Gas horns on fire-alarm NACs fail hard (IFC 2024 916.8). Gas notification has to be distinct.
- Relay map: R1 exhaust and makeup, R2 gas alarm to the FACP, R3 horns and strobes, fault relay trouble to the FACP.
- Fan proof, makeup proof, and damper proven-open are supervisory. If the gas panel has fewer dry-contact inputs than proof points, the extra points are listed on FACP monitor modules. The sample has 6 proofs and 4 inputs, so 2 move.
- Fire alarm does not stop the gas exhaust. A matrix mark in the Stop exhaust column fails.
- Smoke detection in each in-scope room (IFC 2024 1207.5.4). Gas alarm, trouble, and supervisory go to the supervising station.
- Door hardware follows the 2 hour or 3 hour barrier, and hold-opens release on fire alarm. That coordination item is always seeded.

### Release helper

User-entered UL 9540A masses. Ideal gas at 70 F and 1 atm using `molar_volume_ft3` from the rules file (0.853). Mixture LFL is Le Chatelier on the combustible gases only. The conversion is tagged `NEEDS PE REVIEW`. It does not replace a dispersion analysis. Missing molecular weight or LFL falls back to the H2 and DMC defaults in the rules file, which are physical-property assumptions, not code values.

### Batteries

- FACP: 24 h standby + 5 min alarm, or 15 min when voice is checked (NFPA 72-2022 10.6.7.2).
- Gas panel, sensors, and horns: 24 h standby + 2 h alarm. Exhaust fan standby power is 2 h. Both cite IFC 2024 1207.6.1.2 and are tagged `ASSUMED` and `NEEDS PE REVIEW` because the FA lead said to verify NFPA 855 and that subsection.
- Required ampere-hours = (standby current × hours + alarm current × hours) × (1 + margin) × aging × temperature.
- Margin below 20% is raised to 20% and the check fails, so the published number is not undersized. A derate below 1 is raised to 1 for the same reason.
- The next standard size at or above the requirement is taken from `standard_battery_ah` in the rules file.

## Screens

Left navigation, status badge, and a results panel on the right. The AI assistant sits under the results.

1. Project & Code Basis. AHJ notes. Ruleset version.
2. Rooms & ESS inventory.
3. Thresholds & fire areas, including the 600 kWh rollup and the 5% band.
4. Explosion control & exhaust. IMC checklist, motorized damper checklist, LFL setpoints, release helper.
5. Gas detection & controls. Sensors, controller I/O, relay map, points list, shortfall.
6. Cause & effect. Editable. XLSX export.
7. Sprinklers. Density × area, dry/preaction delta, C=100, hose, duct `q`, `BLOCKED` banner.
8. FA & battery calcs.
9. Open items / RFI register.
10. Reports. DOCX basis of design, XLSX workbook, summary PDF.
11. Settings. API key, model, test connection. Not a rules screen. Badge is ON or OFF.

File menu: New, Open, Save, Save As, Open sample, Document intake, recent files. Autosave writes the open file, or a recovery copy under the app data directory when the project has no name yet. View menu switches light and dark. Help → About shows the version.

Reports request Arial. On Windows, the PDF uses Arial when `C:\Windows\Fonts\arial.ttf` is present. On a machine without Arial the PDF uses Liberation Sans or DejaVu and says so on the first page. The DOCX still names Arial so Word uses it.

## AI

All model calls go through `bess_workbench/ai/`. Tests use `MockClient` and do not touch the network.

The rules engine stays the source of truth. The model cannot set a check status. `set_input` and `add_rfi` only propose a change. The app shows the diff and applies it only after Approve. Read-only tools are `get_project`, `run_checks`, `get_rule`, and `list_open_items`.

The chat sends the current project JSON and the current checks with the question. The system prompt and the rules file are sent as cached ephemeral blocks. Project JSON is not cached, because it changes. Responses stream. Usage is totaled and priced with a labeled estimate (not an invoice). Transient API errors retry up to three times. The API key is registered with a log scrubber and is never put in the request body that gets logged.

The key is stored with keyring, which is Windows Credential Manager on Windows. `ANTHROPIC_API_KEY` is the fallback and is used only when keyring has no key. The key is not written to the project, to QSettings, or to logs. Without a key the rest of the app works and the assistant, intake, and draft buttons say that AI is off.

The default model id is `claude-sonnet-5-5`, which is the current Sonnet id in the installed Anthropic SDK. The field is editable.

Document intake sends the PDF as a base64 document block and asks for JSON: gases and masses, LFL, kWh, sensors, relay landings, monitoring-only, add-alternate. The user accepts fields in a table. Accepted values are stored with the document name and page.

RFI drafting and the basis-of-design narrative are one-shot drafts. The DOCX labels the narrative **AI-drafted**, or **AI-drafted and edited by the user** if it was changed afterward.

## Rule list

Numbers and citations live in `rules/ifc2024_nfpa855_2023.json` version 1.0.0. Summaries are paraphrases, not quotations.

| ID | Screen | Citation | Tags | Summary |
| --- | --- | --- | --- | --- |
| `SCOPE-US` | project | BESS WorkBench scope | — | This workbench blocks a project that is not in the United States. |
| `CODE-EDITION` | project | Project code basis | — | Warn when a project edition or ruleset version drifts from the rules file the engine is using. |
| `FP-THRESH-20` | thresholds | IFC 2024 Table 1207.1.1 | CODE | A room at or above the lithium-ion threshold is in scope for the ESS room rules. |
| `FP-FA-600` | thresholds | IFC 2024 Table 1207.5 | ASSUMED | Lithium-ion energy above the fire-area cap fails, and energy within five percent of the cap warns. |
| `FP-FA-SEP` | thresholds | IBC 2024 Table 707.3.10 | ASSUMED | Rooms in a two-hour enclosure are one fire area. A separate fire area needs a three-hour barrier and a three-hour floor and ceiling. |
| `FP-ROOM-2H` | rooms | IFC 2024 1207.7.4 | CODE | An in-scope BESS room enclosure is at least two hours. |
| `FP-UL9540` | rooms | IFC 2024 1207.3.1 | CODE | In-scope ESS groups are recorded as listed to UL 9540. Confirm the listing section in the adopted IFC. |
| `FP-SPACING` | rooms | Project record | — | Spacing is stored on the group. This ruleset does not apply a numeric spacing limit. |
| `FP-CHEM-OTHER` | rooms | IFC 2024 Table 1207.1.1 | — | A chemistry other than lithium-ion is flagged so a PE can pick the right threshold row. |
| `FA-SMOKE` | rooms | IFC 2024 1207.5.4 | ASSUMED, CODE | Each in-scope BESS room is recorded as having smoke detection. |
| `FP-SPR-TYPE` | sprinklers | BESS WorkBench scope | — | Only wet, dry, and double-interlock preaction systems are in scope. |
| `FP-SPR-DESIGN` | sprinklers | IFC 2024 1207.5.5 | CODE | Sprinkler demand is density times the lesser of the room area and the area cap. Density below the baseline needs a UL 9540A report. |
| `FP-SPR-30` | sprinklers | NFPA 13-2025 19.2.3.2.5 | ASSUMED | Dry and double-interlock preaction design areas increase by the ruleset factor, and the added area is shown. |
| `FP-SPR-9540A` | sprinklers | BESS WorkBench scope rule | ASSUMED | Sign-off is blocked when a group above the cutoff has no UL 9540A report. The density math is still shown. |
| `FP-SPR-C100` | sprinklers | FP lead 2026-10-21 | ASSUMED | C is fixed at the ruleset value and is recorded only. There is no pipe-friction model. |
| `FP-SPR-HOSE` | sprinklers | FP lead 2026-10-21 | ASSUMED | Hose flow and duration are project inputs that start from the assumed lead defaults. |
| `FP-SPR-DUCT` | sprinklers | NFPA 13-2025 minimum sprinkler pressure | ASSUMED | Duct sprinkler flow is K times the square root of pressure, and pressure under the minimum fails. |
| `FP-9540A-RFI` | sprinklers | FP lead 2026-10-21 | — | A missing UL 9540A report is an automatic open item for every group that has energy. |
| `FP-IMC-FSD` | explosion | IMC 2024 509.6.1 | CODE | The gas exhaust duct does not get a fire damper or a smoke damper. |
| `FP-IMC-BAL` | explosion | IMC 2024 509.5.1 | CODE | The gas exhaust duct does not get a balancing damper. |
| `FP-IMC-BD` | explosion | IMC 2024 509 | CODE | Avoid a backdraft damper on the gas exhaust. |
| `FP-IMC-SHAFT` | explosion | IMC 2024 509.6.1.1 | CODE | A duct that crosses a rated assembly uses a rated shaft, unless it terminates directly at an exterior wall or roof. |
| `FP-IMC-MOTOR` | explosion | FP lead 2026-10-21 | CODE | A motorized exhaust damper fails open and proves open to the FACP. |
| `FP-IMC-OTHER` | explosion | IBC 2024 Table 717.3.2.1 | CODE | Other ducts through a BESS wall use a three-hour damper in a three-hour wall and a 1.5-hour damper in a wall under three hours. |
| `FA-IMC-509` | explosion | IMC 2024 509 | ASSUMED | FA lead item 10 is the same gas-exhaust duct constraint set evaluated by the IMC line items. |
| `FP-EXH-LOGIC` | explosion | FP lead 2026-10-21 | CODE | A low alarm from either gas starts exhaust and makeup air, latched, with manual reset. |
| `FA-NO-SHUTDOWN` | explosion | FA lead 2026-10-21 | ASSUMED | An HVAC shutdown sequence that includes the gas exhaust fails. |
| `FA-EXH-STANDBY` | explosion | IFC 2024 1207.6.1.2 | ASSUMED, NEEDS PE REVIEW | The gas exhaust fan is on standby power for the ruleset duration. Verify the subsection before relying on it. |
| `FP-LFL-10` | explosion | NFPA 855-2023 9.6.5.6 | CODE, ASSUMED, NEEDS PE REVIEW | The low alarm and exhaust start are at or below 10 percent of the vent-gas LFL. The subsection needs PE review. |
| `FP-LFL-25` | explosion | NFPA 855-2023 9.6.5.6 | ASSUMED, NEEDS PE REVIEW | A design fraction above 25 percent fails. Exactly 25 percent warns because the FA lead requires a value below 25 percent. |
| `GAS-MB` | explosion | Ideal-gas helper at 70 F and 1 atm | ASSUMED | Ideal-gas release helper from user-entered UL 9540A masses. It does not replace a PE dispersion analysis. |
| `FA-SETPOINT-CONV` | explosion | NFPA 855-2023 9.6.5.6 | ASSUMED, NEEDS PE REVIEW | Converting a release case or a single-gas percent LEL into a mixture percent LFL needs PE review. |
| `FP-SENSOR-COVER` | gas | IFC 2024 916.3 | CODE | Each room has at least one sensor for every gas on the detection list. |
| `FP-LFL-SINGLE` | gas | NFPA 855-2023 9.6.5.6 | ASSUMED, NEEDS PE REVIEW | A single-gas percent LEL setpoint without UL 9540A mixture data is an open item. |
| `FA-HARD-MON` | gas | FA lead 2026-10-21 | ASSUMED | Gas detection that is monitoring-only or BACnet-only fails hard when it is the explosion control. Life safety is hardwired. |
| `FA-HARD-NAC` | gas | IFC 2024 916.8 | ASSUMED, CODE | Gas horns on fire-alarm notification appliance circuits fail hard. |
| `FA-DISTINCT` | gas | IFC 2024 916.8 | ASSUMED, CODE | Gas notification is distinct from the fire alarm. |
| `FA-RELAYS` | gas | FA lead 2026-10-21 | ASSUMED | Low alarm drives exhaust and makeup on R1 and a gas alarm to the FACP on R2. High alarm drives horns on R3. The fault relay is trouble to the FACP. |
| `FA-H2-CEILING` | gas | FA lead 2026-10-21 | ASSUMED | Hydrogen sensors are high and within 12 inches of the ceiling unless a PE accepts another spot. |
| `FA-DMC-LOW` | gas | FA lead 2026-10-21 | ASSUMED | DMC sensors are mounted low. There is no fixed dimension in the lead rules. |
| `FA-HEIGHT-OPEN` | gas | FA lead 2026-10-21 | ASSUMED | Each sensor height stays open until the vendor justifies it from UL 9540A data and airflow with exhaust on and exhaust failed. |
| `FA-PROOFS` | gas | FA lead 2026-10-21 | ASSUMED | Fan, makeup, and damper-open proofs are supervisory. Points that do not fit on the gas panel move to FACP monitor modules. |
| `FA-SUPERVISING` | gas | NFPA 72-2022 supervising station | ASSUMED | Gas alarm, trouble, and supervisory signals are indicated to the supervising station. |
| `FP-LAND-RFI` | gas | FP lead 2026-10-21 | — | Missing relay landings on the controls drawings are an automatic open item. |
| `FP-HIGH-RFI` | gas | FP lead 2026-10-21 | — | No high-gas signal to the FACP is an automatic open item. |
| `CE-STOP` | cause_effect | FA lead 2026-10-21 | ASSUMED | Any matrix mark that stops the gas exhaust fails. |
| `CE-SOURCE` | cause_effect | BESS WorkBench | — | The matrix is generated from the lead sequence until someone edits it. An edit that drifts from the room list warns. |
| `FA-BATT-FACP` | battery | NFPA 72-2022 10.6.7.2 | ASSUMED, CODE | FACP battery worksheet uses 24 hours of standby plus 5 minutes of alarm, or 15 minutes when voice is indicated. |
| `FA-BATT-GAS` | battery | IFC 2024 1207.6.1.2 | ASSUMED, NEEDS PE REVIEW | Gas panel, sensors, and horns use 24 hours of standby plus 2 hours of alarm. Verify the subsection. |
| `FA-BATT-MARGIN` | battery | FA lead 2026-10-21 | ASSUMED | The worksheet applies at least 20 percent spare capacity plus aging and temperature derates, then picks the next standard size. |
| `FA-DOOR` | rfi | FA lead 2026-10-21 | ASSUMED | Two-hour versus three-hour barriers drive door hardware, and hold-open devices release on fire alarm. This stays an open coordination item until it is closed. |

## Sample

`samples/Sample - 4 Room UPS BESS.bessproj` is synthetic. Four lithium-ion rooms at 150 kWh share one 2 hour fire area (600 kWh, on the cap). Wet sprinklers. Shared exhaust. H2 and DMC in each room. The controller has 4 programmable relays, a fault relay, and 4 inputs, so two proof points move to the FACP. Gas detection is monitoring-only and an add-alternate, which is the hard fail. UL 9540A is missing, so sprinkler sign-off is blocked and the automatic RFIs are populated.

## Roadmap

- Pipe-by-pipe NFPA 13 calculations. C=100 stays a recorded basis until then.
- More chemistry rows after a PE confirms the threshold table values. Only lithium-ion is encoded.
- An AHJ amendment library keyed by jurisdiction, still US-only.
- Drawing or model takeoff so damper and relay checks are not typed by hand.
- A second rules file for a later edition, selected explicitly, instead of one file with a warning on drift.

Still out of scope: clean agent, foam, water mist, single-interlock preaction, and non-US codes.

## Tests

`pytest` covers the engine, the rules file as the source of the 600 kWh figure, report validity, the AI mock (including a rejected edit that does not change the project), key redaction, and an offscreen pass through every screen. UI modules are omitted from the coverage gate. The gate is 75 percent of the logic package; the suite currently sits above that.
