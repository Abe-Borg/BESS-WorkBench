"""The ten work screens plus Settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bess_workbench.calcs import CE_COLUMNS, RELAY_FUNCTIONS
from bess_workbench.formatting import fmt_fixed, fmt_num
from bess_workbench.models import ESSGroup, FireArea, RFI, ReleaseSpecies, Room, Sensor, display_rfi_id
from bess_workbench.reports import export_all, write_cause_effect
from bess_workbench.ui.dialogs import ConfirmDialog
from bess_workbench.ui.widgets import Screen, fill_table, ispin, muted, spin

SYSTEMS = [
    ("wet", "Wet"),
    ("dry", "Dry"),
    ("double_interlock_preaction", "Double-interlock preaction"),
]
ASSIGNEES = ["Architect", "Mech", "Elec", "Controls vendor", "Owner", "AHJ"]
RELAY_KEYS = list(RELAY_FUNCTIONS)


def _item(text, editable=True) -> QTableWidgetItem:
    cell = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return cell


def _table(headers: list[str], rows: int = 0) -> QTableWidget:
    table = QTableWidget(rows, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(160)
    return table


class ProjectScreen(Screen):
    screen_id = "project"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Project & code basis")
        self.body_layout.addWidget(muted("Editions default to the rules file. Changing one warns until a PE confirms it. Jurisdiction is the United States."))
        form = QFormLayout()
        self.name = QLineEdit()
        self.number = QLineEdit()
        self.client = QLineEdit()
        self.site = QLineEdit()
        self.prepared = QLineEdit()
        self.occupancy = QLineEdit()
        self.jurisdiction = QLineEdit()
        self.jurisdiction.setReadOnly(True)
        self.edits = {}
        for key, label in [
            ("name", "Project name"),
            ("number", "Project number"),
            ("client", "Client"),
            ("site", "Site"),
            ("prepared", "Prepared by"),
            ("occupancy", "Occupancy"),
            ("jurisdiction", "Jurisdiction"),
        ]:
            form.addRow(label, getattr(self, key if key != "prepared" else "prepared"))
        self.edition_fields = {}
        for key, label in [
            ("ifc", "IFC"),
            ("ibc", "IBC"),
            ("imc", "IMC"),
            ("nec", "NEC"),
            ("nfpa_855", "NFPA 855"),
            ("nfpa_72", "NFPA 72"),
            ("nfpa_13", "NFPA 13"),
            ("nfpa_69", "NFPA 69"),
        ]:
            box = QLineEdit()
            self.edition_fields[key] = box
            form.addRow(label, box)
            box.editingFinished.connect(self._save)
        for widget in (self.name, self.number, self.client, self.site, self.prepared, self.occupancy):
            widget.editingFinished.connect(self._save)
        self.body_layout.addLayout(form)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Project notes")
        self.notes.setFixedHeight(80)
        self.ahj = QPlainTextEdit()
        self.ahj.setPlaceholderText("AHJ notes")
        self.ahj.setFixedHeight(80)
        self.body_layout.addWidget(QLabel("Notes"))
        self.body_layout.addWidget(self.notes)
        self.body_layout.addWidget(QLabel("AHJ notes"))
        self.body_layout.addWidget(self.ahj)
        self.notes.textChanged.connect(self._save)
        self.ahj.textChanged.connect(self._save)
        self.rules_label = muted("")
        self.body_layout.addWidget(self.rules_label)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        project = self.project()
        self.name.setText(project.meta.name)
        self.number.setText(project.meta.project_number)
        self.client.setText(project.meta.client)
        self.site.setText(project.meta.site)
        self.prepared.setText(project.meta.prepared_by)
        self.occupancy.setText(project.code_basis.occupancy)
        self.jurisdiction.setText(project.code_basis.jurisdiction)
        for key, box in self.edition_fields.items():
            box.setText(str(getattr(project.code_basis, key)))
        self.notes.setPlainText(project.meta.notes)
        self.ahj.setPlainText(project.code_basis.ahj_notes)
        rules = self.host.controller.rules
        self.rules_label.setText(f"Rules file {rules.ruleset_id} version {rules.version}. Numbers in that file drive the checks.")
        self.loading = False

    def _save(self) -> None:
        if self.loading:
            return
        project = self.project()
        project.meta.name = self.name.text()
        project.meta.project_number = self.number.text()
        project.meta.client = self.client.text()
        project.meta.site = self.site.text()
        project.meta.prepared_by = self.prepared.text()
        project.meta.notes = self.notes.toPlainText()
        project.code_basis.occupancy = self.occupancy.text() or "F-1"
        project.code_basis.ahj_notes = self.ahj.toPlainText()
        for key, box in self.edition_fields.items():
            setattr(project.code_basis, key, box.text().strip())
        self.touch()


class RoomsScreen(Screen):
    screen_id = "rooms"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Rooms & ESS inventory")
        self.body_layout.addWidget(muted("Wall, floor, and ceiling ratings are hours. Smoke is yes or no. UL 9540 and UL 9540A are yes or no."))
        self.rooms = _table(["ID", "Name", "Area sf", "Height ft", "Wall h", "Floor h", "Ceiling h", "Fire area", "Smoke"])
        self.ess = _table(["ID", "Name", "Room", "Chemistry", "kWh", "Spacing in", "UL 9540", "UL 9540A"])
        self.body_layout.addWidget(QLabel("Rooms"))
        self.body_layout.addWidget(self.rooms)
        room_buttons = QHBoxLayout()
        add_room = QPushButton("Add room")
        remove_room = QPushButton("Remove room")
        remove_room.setObjectName("secondary")
        add_room.clicked.connect(self._add_room)
        remove_room.clicked.connect(self._remove_room)
        room_buttons.addWidget(add_room)
        room_buttons.addWidget(remove_room)
        room_buttons.addStretch(1)
        self.body_layout.addLayout(room_buttons)
        self.body_layout.addWidget(QLabel("ESS groups"))
        self.body_layout.addWidget(self.ess)
        ess_buttons = QHBoxLayout()
        add_ess = QPushButton("Add ESS group")
        remove_ess = QPushButton("Remove ESS group")
        remove_ess.setObjectName("secondary")
        add_ess.clicked.connect(self._add_ess)
        remove_ess.clicked.connect(self._remove_ess)
        ess_buttons.addWidget(add_ess)
        ess_buttons.addWidget(remove_ess)
        ess_buttons.addStretch(1)
        self.body_layout.addLayout(ess_buttons)
        self.rooms.itemChanged.connect(self._rooms_edited)
        self.ess.itemChanged.connect(self._ess_edited)

    def load(self) -> None:
        self.loading = True
        self.rooms.blockSignals(True)
        self.ess.blockSignals(True)
        project = self.project()
        self.rooms.setRowCount(len(project.rooms))
        for row, room in enumerate(project.rooms):
            values = [
                room.id,
                room.name,
                fmt_num(room.area_sf),
                fmt_num(room.height_ft),
                fmt_num(room.wall_rating_hr),
                fmt_num(room.floor_rating_hr),
                fmt_num(room.ceiling_rating_hr),
                room.fire_area_id,
                "yes" if room.smoke_detection else "no",
            ]
            for col, value in enumerate(values):
                self.rooms.setItem(row, col, _item(value, editable=col != 0))
        self.ess.setRowCount(len(project.ess_groups))
        for row, group in enumerate(project.ess_groups):
            values = [
                group.id,
                group.name,
                group.room_id,
                group.chemistry,
                fmt_num(group.kwh),
                "" if group.spacing_in is None else fmt_num(group.spacing_in),
                "yes" if group.ul_9540_listed else "no",
                "yes" if group.ul_9540a_report else "no",
            ]
            for col, value in enumerate(values):
                self.ess.setItem(row, col, _item(value, editable=col != 0))
        self.rooms.blockSignals(False)
        self.ess.blockSignals(False)
        self.loading = False

    def _yn(self, text: str) -> bool:
        return text.strip().lower() in {"y", "yes", "true", "1"}

    def _rooms_edited(self, _item) -> None:
        if self.loading:
            return
        try:
            for row, room in enumerate(self.project().rooms):
                room.name = self.rooms.item(row, 1).text()
                room.area_sf = float(self.rooms.item(row, 2).text())
                room.height_ft = float(self.rooms.item(row, 3).text())
                room.wall_rating_hr = float(self.rooms.item(row, 4).text())
                room.floor_rating_hr = float(self.rooms.item(row, 5).text())
                room.ceiling_rating_hr = float(self.rooms.item(row, 6).text())
                room.fire_area_id = self.rooms.item(row, 7).text().strip() or room.fire_area_id
                room.smoke_detection = self._yn(self.rooms.item(row, 8).text())
        except (TypeError, ValueError, AttributeError):
            self.host.status("Room numbers need to be numeric.")
            return
        self.touch()

    def _ess_edited(self, _item) -> None:
        if self.loading:
            return
        try:
            for row, group in enumerate(self.project().ess_groups):
                group.name = self.ess.item(row, 1).text()
                group.room_id = self.ess.item(row, 2).text().strip()
                group.chemistry = self.ess.item(row, 3).text().strip() or "lithium-ion"
                group.kwh = float(self.ess.item(row, 4).text() or 0)
                spacing = self.ess.item(row, 5).text().strip()
                group.spacing_in = float(spacing) if spacing else None
                group.ul_9540_listed = self._yn(self.ess.item(row, 6).text())
                group.ul_9540a_report = self._yn(self.ess.item(row, 7).text())
        except (TypeError, ValueError, AttributeError):
            self.host.status("ESS numbers need to be numeric.")
            return
        self.touch()

    def _add_room(self) -> None:
        project = self.project()
        number = len(project.rooms) + 1
        room_id = f"ROOM-{number}"
        project.rooms.append(Room(id=room_id, name=f"BESS Room {number}", area_sf=400, height_ft=12, fire_area_id="FA-1"))
        project.gas.sensors.extend(
            [
                Sensor(id=f"{room_id}-H2", room_id=room_id, gas="H2", mount="high", inches_from_ceiling=6),
                Sensor(id=f"{room_id}-DMC", room_id=room_id, gas="DMC", mount="low", inches_aff=18),
            ]
        )
        self.touch()
        self.load()

    def _remove_room(self) -> None:
        row = self.rooms.currentRow()
        project = self.project()
        if row < 0 or row >= len(project.rooms):
            return
        room_id = project.rooms[row].id
        del project.rooms[row]
        project.ess_groups = [group for group in project.ess_groups if group.room_id != room_id]
        project.gas.sensors = [sensor for sensor in project.gas.sensors if sensor.room_id != room_id]
        self.touch()
        self.load()

    def _add_ess(self) -> None:
        project = self.project()
        room_id = project.rooms[0].id if project.rooms else "ROOM-1"
        number = len(project.ess_groups) + 1
        project.ess_groups.append(ESSGroup(id=f"ESS-{number}", name=f"ESS-{number}", room_id=room_id))
        self.touch()
        self.load()

    def _remove_ess(self) -> None:
        row = self.ess.currentRow()
        groups = self.project().ess_groups
        if row < 0 or row >= len(groups):
            return
        del groups[row]
        self.touch()
        self.load()


class ThresholdsScreen(Screen):
    screen_id = "thresholds"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Thresholds & fire areas")
        rules = host.controller.rules
        limit = rules.param("max_kwh_fire_area")
        band = rules.param("fire_area_warn_band")
        low = float(limit) * (1 - float(band))
        self.body_layout.addWidget(
            muted(
                f"Lithium-ion threshold is {fmt_num(rules.param('li_ion_threshold_kwh'))} kWh per room. "
                f"Fire-area cap is {fmt_num(limit)} kWh. Warn band is {fmt_num(low)}–{fmt_num(limit)} kWh. "
                "Two-hour rooms in a claimed split are combined. A separate fire area needs a 3 h barrier and a 3 h floor/ceiling. "
                f"Occupancy {self.project().code_basis.occupancy} is assumed for that separation table."
            )
        )
        self.rollups = _table(["Fire area", "Rooms", "Li-ion kWh", "Barrier h", "Floor/ceiling h", "Separated", "Energy", "Note"])
        self.rollups.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.areas = _table(["ID", "Name", "Barrier h", "Floor/ceiling h"])
        self.body_layout.addWidget(self.rollups)
        self.body_layout.addWidget(QLabel("Fire area ratings (editable)"))
        self.body_layout.addWidget(self.areas)
        self.areas.itemChanged.connect(self._areas_edited)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        self.areas.blockSignals(True)
        areas = self.project().fire_areas
        self.areas.setRowCount(len(areas))
        for row, area in enumerate(areas):
            values = [area.id, area.name, fmt_num(area.barrier_hr), fmt_num(area.floor_ceiling_hr)]
            for col, value in enumerate(values):
                self.areas.setItem(row, col, _item(value, editable=col != 0))
        self.areas.blockSignals(False)
        self.loading = False
        self.show_analysis(self.host.controller.analysis)

    def show_analysis(self, analysis) -> None:
        if analysis is None:
            return
        rows = []
        for item in analysis.rollups:
            rows.append(
                [
                    item.fire_area_id,
                    ", ".join(item.room_ids),
                    fmt_num(item.li_ion_kwh),
                    fmt_num(item.barrier_hr),
                    fmt_num(item.horizontal_hr),
                    "yes" if item.separation_valid else "no",
                    item.energy_status.value if item.energy_checked else "—",
                    item.note,
                ]
            )
        fill_table(self.rollups, rows)

    def _areas_edited(self, _cell) -> None:
        if self.loading:
            return
        try:
            for row, area in enumerate(self.project().fire_areas):
                area.name = self.areas.item(row, 1).text()
                area.barrier_hr = float(self.areas.item(row, 2).text())
                area.floor_ceiling_hr = float(self.areas.item(row, 3).text())
        except (TypeError, ValueError, AttributeError):
            self.host.status("Barrier ratings need to be numeric.")
            return
        self.touch()


class ExplosionScreen(Screen):
    screen_id = "explosion"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Explosion control & exhaust")
        self.body_layout.addWidget(muted("NFPA 69 exhaust path, IMC 509 duct rules, and a release-mass helper from UL 9540A numbers you type."))
        box = QGroupBox("Motorized damper checklist and IMC 509")
        form = QFormLayout(box)
        self.checks = {}
        labels = [
            ("direct_to_exterior", "Direct to exterior wall or roof"),
            ("crosses_rated_assembly", "Crosses a rated assembly"),
            ("rated_shaft", "Rated shaft where it crosses"),
            ("fire_damper", "Fire damper on gas exhaust"),
            ("smoke_damper", "Smoke damper on gas exhaust"),
            ("balancing_damper", "Balancing damper"),
            ("backdraft_damper", "Backdraft damper"),
            ("motorized_damper", "Motorized damper"),
            ("motorized_fail_open", "Motorized damper fails open"),
            ("damper_proven_open", "Damper proven open to FACP"),
            ("per_room_isolation_damper", "Isolation damper at each room"),
            ("fan_proof", "Exhaust fan proof"),
            ("makeup_proof", "Makeup air proof"),
            ("standby_power_provided", "Standby power for the exhaust fan"),
            ("hvac_shutdown_includes_exhaust", "HVAC shutdown includes gas exhaust"),
            ("other_ducts_penetrate", "Other ducts penetrate BESS walls"),
        ]
        for key, label in labels:
            widget = QCheckBox(label)
            widget.toggled.connect(self._save_flags)
            self.checks[key] = widget
            form.addRow(widget)
        self.other_wall = spin(0, 8, 1, 0.5)
        self.other_damper = spin(0, 8, 1, 0.5)
        self.other_wall.valueChanged.connect(self._save_flags)
        self.other_damper.valueChanged.connect(self._save_flags)
        form.addRow("Other duct wall rating (h)", self.other_wall)
        form.addRow("Other duct damper rating (h)", self.other_damper)
        self.body_layout.addWidget(box)
        logic = QGroupBox("LFL setpoints and low-alarm sequence")
        logic_form = QFormLayout(logic)
        self.alarm = spin(0, 100, 1, 1)
        self.design = spin(0, 100, 1, 1)
        self.alarm.valueChanged.connect(self._save_flags)
        self.design.valueChanged.connect(self._save_flags)
        logic_form.addRow("Low alarm (% LFL)", self.alarm)
        logic_form.addRow("Design (% LFL)", self.design)
        for key, label in [
            ("low_alarm_starts_exhaust", "Low alarm starts exhaust"),
            ("low_alarm_starts_makeup", "Low alarm starts makeup air"),
            ("latched", "Latched"),
            ("manual_reset", "Manual reset"),
        ]:
            widget = QCheckBox(label)
            widget.toggled.connect(self._save_flags)
            self.checks[key] = widget
            logic_form.addRow(widget)
        self.body_layout.addWidget(logic)
        release = QGroupBox("UL 9540A release helper")
        release_layout = QVBoxLayout(release)
        self.volume = spin(0, 1_000_000, 0, 100)
        self.volume.valueChanged.connect(self._save_release_meta)
        volume_row = QFormLayout()
        volume_row.addRow("Room volume (ft3)", self.volume)
        release_layout.addLayout(volume_row)
        self.species = _table(["Name", "Mass g", "MW", "LFL vol %"])
        self.species.itemChanged.connect(self._species_edited)
        release_layout.addWidget(self.species)
        add = QPushButton("Add species row")
        add.clicked.connect(self._add_species)
        release_layout.addWidget(add)
        self.balance = muted("Enter a mass and a room volume.")
        release_layout.addWidget(self.balance)
        self.body_layout.addWidget(release)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        project = self.project()
        for key, widget in self.checks.items():
            widget.blockSignals(True)
            if hasattr(project.exhaust, key):
                widget.setChecked(bool(getattr(project.exhaust, key)))
            else:
                widget.setChecked(bool(getattr(project.gas, key)))
            widget.blockSignals(False)
        self.other_wall.blockSignals(True)
        self.other_damper.blockSignals(True)
        self.alarm.blockSignals(True)
        self.design.blockSignals(True)
        self.volume.blockSignals(True)
        self.other_wall.setValue(project.exhaust.other_duct_wall_hr)
        self.other_damper.setValue(project.exhaust.other_duct_damper_hr)
        self.alarm.setValue(project.gas.alarm_pct_lfl)
        self.design.setValue(project.gas.design_pct_lfl)
        self.volume.setValue(project.gas.release_room_volume_ft3 or 0)
        self.other_wall.blockSignals(False)
        self.other_damper.blockSignals(False)
        self.alarm.blockSignals(False)
        self.design.blockSignals(False)
        self.volume.blockSignals(False)
        self.species.blockSignals(True)
        species = project.gas.release_species
        self.species.setRowCount(len(species))
        for row, item in enumerate(species):
            self.species.setItem(row, 0, _item(item.name))
            self.species.setItem(row, 1, _item(fmt_num(item.mass_g)))
            self.species.setItem(row, 2, _item("" if item.molecular_weight is None else fmt_num(item.molecular_weight)))
            self.species.setItem(row, 3, _item("" if item.lfl_vol_pct is None else fmt_num(item.lfl_vol_pct)))
        self.species.blockSignals(False)
        self.loading = False
        self.show_analysis(self.host.controller.analysis)

    def _save_flags(self, *_args) -> None:
        if self.loading:
            return
        project = self.project()
        for key, widget in self.checks.items():
            target = project.exhaust if hasattr(project.exhaust, key) else project.gas
            setattr(target, key, widget.isChecked())
        project.exhaust.other_duct_wall_hr = self.other_wall.value()
        project.exhaust.other_duct_damper_hr = self.other_damper.value()
        project.gas.alarm_pct_lfl = self.alarm.value()
        project.gas.design_pct_lfl = self.design.value()
        self.touch()

    def _save_release_meta(self, *_args) -> None:
        if self.loading:
            return
        value = self.volume.value()
        self.project().gas.release_room_volume_ft3 = value or None
        self.touch()

    def _species_edited(self, _cell) -> None:
        if self.loading:
            return
        species = []
        for row in range(self.species.rowCount()):
            name_item = self.species.item(row, 0)
            if name_item is None or not name_item.text().strip():
                continue
            def cell(col):
                item = self.species.item(row, col)
                return item.text().strip() if item else ""

            def maybe(col):
                text = cell(col)
                return float(text) if text else None

            try:
                species.append(
                    ReleaseSpecies(
                        name=name_item.text().strip(),
                        mass_g=float(cell(1) or 0),
                        molecular_weight=maybe(2),
                        lfl_vol_pct=maybe(3),
                    )
                )
            except ValueError:
                self.host.status("Release masses and LFL need to be numeric.")
                return
        self.project().gas.release_species = species
        self.touch()

    def _add_species(self) -> None:
        self.project().gas.release_species.append(ReleaseSpecies(name="H2", mass_g=0))
        self.touch()
        self.load()

    def show_analysis(self, analysis) -> None:
        if analysis is None or analysis.mass_balance is None:
            self.balance.setText("Enter at least one release mass and a room volume. The helper uses the ideal-gas molar volume in the rules file.")
            return
        balance = analysis.mass_balance
        bits = [f"{item.name}: {fmt_fixed(item.volume_ft3)} ft3, {fmt_fixed(item.vol_pct)} vol%, {fmt_fixed(item.pct_of_lfl)}% of its LFL" for item in balance.species]
        self.balance.setText(
            f"Mixture {fmt_fixed(balance.mixture_vol_pct)} vol% = {fmt_fixed(balance.mixture_pct_of_lfl)}% of mixture LFL "
            f"({fmt_fixed(balance.mixture_lfl_vol_pct)} vol%). " + "; ".join(bits) + ". " + balance.method
        )


class GasScreen(Screen):
    screen_id = "gas"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Gas detection & controls")
        flags = QGroupBox("Life-safety flags")
        form = QFormLayout(flags)
        self.flags = {}
        for key, label in [
            ("monitoring_only", "Monitoring only"),
            ("add_alternate", "Add alternate"),
            ("bacnet_only", "BACnet only"),
            ("is_explosion_control", "This sequence is the explosion control"),
            ("gas_horns_on_fa_nacs", "Gas horns on fire-alarm NACs"),
            ("distinct_notification", "Gas notification distinct from fire alarm"),
            ("high_gas_to_facp", "High-gas signal to the FACP"),
            ("relay_landings_shown", "Relay landings shown on drawings"),
            ("supervising_station", "Alarm, trouble, and supervisory to supervising station"),
            ("has_9540a_gas_data", "UL 9540A gas data on file"),
        ]:
            widget = QCheckBox(label)
            widget.toggled.connect(self._save_flags)
            self.flags[key] = widget
            form.addRow(widget)
        self.basis = QComboBox()
        self.basis.addItem("Vent-gas mixture", "vent_gas_mix")
        self.basis.addItem("Single-gas % LEL", "single_gas_lel")
        self.basis.currentIndexChanged.connect(self._save_flags)
        form.addRow("Setpoint basis", self.basis)
        self.relays = ispin(0, 16)
        self.inputs = ispin(0, 64)
        self.fault = QCheckBox("Fault relay")
        self.relays.valueChanged.connect(self._save_flags)
        self.inputs.valueChanged.connect(self._save_flags)
        self.fault.toggled.connect(self._save_flags)
        form.addRow("Programmable relays", self.relays)
        form.addRow("Dry-contact inputs", self.inputs)
        form.addRow(self.fault)
        self.body_layout.addWidget(flags)
        self.shortfall = muted("")
        self.body_layout.addWidget(self.shortfall)
        self.body_layout.addWidget(QLabel("Sensors"))
        self.sensors = _table(["ID", "Room", "Gas", "Mount", "Inches from ceiling", "Inches AFF", "Justified", "Justification"])
        self.sensors.itemChanged.connect(self._sensors_edited)
        self.body_layout.addWidget(self.sensors)
        add = QPushButton("Add sensor")
        add.clicked.connect(self._add_sensor)
        self.body_layout.addWidget(add)
        self.body_layout.addWidget(QLabel("Relay map"))
        self.relay_table = _table(["Relay", "Function"])
        self.body_layout.addWidget(self.relay_table)
        self.body_layout.addWidget(QLabel("Points list"))
        self.points = _table(["Point", "Description", "Kind", "Landing", "Normal", "Off-normal"])
        self.points.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.body_layout.addWidget(self.points)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        gas = self.project().gas
        for key, widget in self.flags.items():
            widget.blockSignals(True)
            widget.setChecked(bool(getattr(gas, key)))
            widget.blockSignals(False)
        self.basis.blockSignals(True)
        index = self.basis.findData(gas.setpoint_basis)
        self.basis.setCurrentIndex(max(index, 0))
        self.basis.blockSignals(False)
        for widget, value in ((self.relays, gas.controller.programmable_relays), (self.inputs, gas.controller.dry_contact_inputs)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.fault.blockSignals(True)
        self.fault.setChecked(gas.controller.has_fault_relay)
        self.fault.blockSignals(False)
        self.sensors.blockSignals(True)
        self.sensors.setRowCount(len(gas.sensors))
        for row, sensor in enumerate(gas.sensors):
            values = [
                sensor.id,
                sensor.room_id,
                sensor.gas,
                sensor.mount,
                "" if sensor.inches_from_ceiling is None else fmt_num(sensor.inches_from_ceiling),
                "" if sensor.inches_aff is None else fmt_num(sensor.inches_aff),
                "yes" if sensor.height_justified else "no",
                sensor.justification,
            ]
            for col, value in enumerate(values):
                self.sensors.setItem(row, col, _item(value, editable=col != 0))
        self.sensors.blockSignals(False)
        self._load_relays()
        self.loading = False
        self.show_analysis(self.host.controller.analysis)

    def _load_relays(self) -> None:
        gas = self.project().gas
        keys = [f"R{index}" for index in range(1, gas.controller.programmable_relays + 1)]
        if gas.controller.has_fault_relay:
            keys.append("FAULT")
        self.relay_table.blockSignals(True)
        self.relay_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            self.relay_table.setItem(row, 0, _item(key, editable=False))
            combo = QComboBox()
            for function, label in RELAY_FUNCTIONS.items():
                combo.addItem(label, function)
            current = gas.controller.relay_functions.get(key, "spare" if key != "FAULT" else "trouble_to_facp")
            found = combo.findData(current)
            if found < 0:
                combo.addItem(current, current)
                found = combo.count() - 1
            combo.blockSignals(True)
            combo.setCurrentIndex(found)
            combo.blockSignals(False)
            combo.currentIndexChanged.connect(self._relays_edited)
            self.relay_table.setCellWidget(row, 1, combo)
        self.relay_table.blockSignals(False)

    def _save_flags(self, *_args) -> None:
        if self.loading:
            return
        gas = self.project().gas
        for key, widget in self.flags.items():
            setattr(gas, key, widget.isChecked())
        gas.setpoint_basis = self.basis.currentData()
        gas.controller.programmable_relays = self.relays.value()
        gas.controller.dry_contact_inputs = self.inputs.value()
        gas.controller.has_fault_relay = self.fault.isChecked()
        self.touch()
        self._load_relays()

    def _relays_edited(self, *_args) -> None:
        if self.loading:
            return
        functions = {}
        for row in range(self.relay_table.rowCount()):
            name = self.relay_table.item(row, 0).text()
            combo = self.relay_table.cellWidget(row, 1)
            functions[name] = combo.currentData()
        self.project().gas.controller.relay_functions = functions
        self.touch()

    def _sensors_edited(self, _cell) -> None:
        if self.loading:
            return
        sensors = []
        for row in range(self.sensors.rowCount()):
            def text(col, row=row):
                item = self.sensors.item(row, col)
                return item.text().strip() if item else ""

            mount = text(3).lower()
            if mount not in {"high", "low"}:
                mount = "high"
            try:
                ceiling = float(text(4)) if text(4) else None
                aff = float(text(5)) if text(5) else None
            except ValueError:
                self.host.status("Sensor heights need to be numeric.")
                return
            sensors.append(
                Sensor(
                    id=text(0),
                    room_id=text(1),
                    gas=text(2) or "H2",
                    mount=mount,
                    inches_from_ceiling=ceiling,
                    inches_aff=aff,
                    height_justified=text(6).lower() in {"y", "yes", "true", "1"},
                    justification=text(7),
                )
            )
        self.project().gas.sensors = sensors
        self.touch()

    def _add_sensor(self) -> None:
        project = self.project()
        room_id = project.rooms[0].id if project.rooms else "ROOM-1"
        number = len(project.gas.sensors) + 1
        project.gas.sensors.append(Sensor(id=f"S-{number}", room_id=room_id, gas="H2", mount="high", inches_from_ceiling=6))
        self.touch()
        self.load()

    def show_analysis(self, analysis) -> None:
        if analysis is None:
            return
        self.shortfall.setText(
            f"Proof points required: {analysis.proof_required}. "
            f"On the gas panel: {analysis.proof_on_panel}. "
            f"Moved to FACP monitor modules: {analysis.proof_on_facp}."
        )
        fill_table(
            self.points,
            [[point.point_id, point.description, point.kind, point.landing, point.normal_state, point.offnormal_state] for point in analysis.points],
        )


class CauseScreen(Screen):
    screen_id = "cause_effect"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Cause & effect")
        self.body_layout.addWidget(muted("Generated from the lead sequence until you edit a cell. X means the effect happens. Stop exhaust should stay blank."))
        headers = ["Cause", *CE_COLUMNS, "Notes"]
        self.table = _table(headers)
        self.table.itemChanged.connect(self._edited)
        self.body_layout.addWidget(self.table)
        row = QHBoxLayout()
        regen = QPushButton("Regenerate")
        regen.setObjectName("secondary")
        regen.clicked.connect(self._regenerate)
        export = QPushButton("Export XLSX")
        export.clicked.connect(self._export)
        row.addWidget(regen)
        row.addWidget(export)
        row.addStretch(1)
        self.body_layout.addLayout(row)

    def load(self) -> None:
        self.loading = True
        self.table.blockSignals(True)
        rows = self.project().cause_effect
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, _item(row.cause, editable=False))
            for col, name in enumerate(CE_COLUMNS, start=1):
                self.table.setItem(row_index, col, _item(row.effects.get(name, "")))
            self.table.setItem(row_index, 1 + len(CE_COLUMNS), _item(row.notes))
        self.table.blockSignals(False)
        self.loading = False

    def _edited(self, _cell) -> None:
        if self.loading:
            return
        project = self.project()
        built = []
        from bess_workbench.models import CauseEffectRow

        for row_index, existing in enumerate(project.cause_effect):
            effects = {}
            for col, name in enumerate(CE_COLUMNS, start=1):
                item = self.table.item(row_index, col)
                text = item.text().strip().upper() if item else ""
                effects[name] = "X" if text == "X" else ""
            notes_item = self.table.item(row_index, 1 + len(CE_COLUMNS))
            built.append(CauseEffectRow(cause=existing.cause, effects=effects, notes=notes_item.text() if notes_item else ""))
        project.cause_effect = built
        project.cause_effect_manual = True
        self.touch()

    def _regenerate(self) -> None:
        self.project().cause_effect_manual = False
        self.touch()
        self.load()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export cause and effect", "Cause-and-Effect.xlsx", "Excel (*.xlsx)")
        if path:
            write_cause_effect(self.project(), path)
            self.host.status(f"Wrote {path}")


class SprinklerScreen(Screen):
    screen_id = "sprinklers"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Sprinklers")
        self.blocked = QLabel("")
        self.blocked.setWordWrap(True)
        self.body_layout.addWidget(self.blocked)
        form = QFormLayout()
        self.system = QComboBox()
        for value, label in SYSTEMS:
            self.system.addItem(label, value)
        self.density = spin(0, 2, 3, 0.05)
        self.hose = spin(0, 1000, 0, 25)
        self.duration = spin(0, 240, 0, 15)
        self.k_factor = spin(0, 50, 1, 0.1)
        self.pressure = spin(0, 100, 1, 1)
        for widget in (self.system,):
            widget.currentIndexChanged.connect(self._save)
        for widget in (self.density, self.hose, self.duration, self.k_factor, self.pressure):
            widget.valueChanged.connect(self._save)
        form.addRow("System", self.system)
        form.addRow("Density (gpm/sf)", self.density)
        form.addRow("Hose (gpm)", self.hose)
        form.addRow("Hose duration (min)", self.duration)
        self.c_label = QLabel("C = 100")
        form.addRow("Hazen-Williams C", self.c_label)
        form.addRow("Duct K-factor", self.k_factor)
        form.addRow("Duct pressure (psi)", self.pressure)
        self.body_layout.addLayout(form)
        self.formula = muted("")
        self.body_layout.addWidget(self.formula)
        self.table = _table(["Room", "Area", "Base sf", "Increase sf", "Design sf", "gpm", "Governing"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.body_layout.addWidget(self.table)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        sprinklers = self.project().sprinklers
        self.system.blockSignals(True)
        if self.system.findData(sprinklers.system_type) < 0:
            self.system.addItem(sprinklers.system_type, sprinklers.system_type)
        self.system.setCurrentIndex(self.system.findData(sprinklers.system_type))
        self.system.blockSignals(False)
        for widget, value in (
            (self.density, sprinklers.density_gpm_sf),
            (self.hose, sprinklers.hose_gpm),
            (self.duration, sprinklers.hose_duration_min),
            (self.k_factor, sprinklers.duct.k_factor),
            (self.pressure, sprinklers.duct.pressure_psi),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        c_value = self.host.controller.rules.param("hazen_williams_c")
        self.c_label.setText(f"{fmt_num(c_value)} (fixed, not a pipe model)")
        self.loading = False
        self.show_analysis(self.host.controller.analysis)

    def _save(self, *_args) -> None:
        if self.loading:
            return
        sprinklers = self.project().sprinklers
        sprinklers.system_type = self.system.currentData()
        sprinklers.density_gpm_sf = self.density.value()
        sprinklers.hose_gpm = self.hose.value()
        sprinklers.hose_duration_min = self.duration.value()
        sprinklers.duct.k_factor = self.k_factor.value()
        sprinklers.duct.pressure_psi = self.pressure.value()
        self.touch()

    def show_analysis(self, analysis) -> None:
        if analysis is None:
            return
        blocked = next((item for item in analysis.checks if item.id == "FP-SPR-9540A" and item.status.value == "BLOCKED"), None)
        if blocked:
            self.blocked.setText("BLOCKED — " + blocked.message)
            self.blocked.setStyleSheet("color: #7A271A; font-weight: 700;")
        else:
            self.blocked.setText("")
        summary = analysis.sprinkler_summary
        self.formula.setText(
            summary.formula
            + f" Total with hose {fmt_fixed(summary.total_gpm)} gpm for {fmt_num(summary.duration_min)} min "
            + f"({fmt_num(summary.volume_gal)} gal). "
            + analysis.duct.formula
        )
        fill_table(
            self.table,
            [
                [
                    row.room_name,
                    fmt_num(row.room_area_sf),
                    fmt_num(row.base_area_sf),
                    fmt_num(row.increase_sf),
                    fmt_num(row.design_area_sf),
                    fmt_fixed(row.sprinkler_gpm),
                    "yes" if row.governing else "",
                ]
                for row in analysis.sprinkler_rows
            ],
        )


class BatteryScreen(Screen):
    screen_id = "battery"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("FA & battery calcs")
        self.body_layout.addWidget(
            muted(
                "Durations come from the rules file: FACP 24 h + 5 min, or 15 min when voice is checked; "
                "gas panel 24 h + 2 h. Margin below 20% is raised to 20% and the check fails. "
                "The next standard size is taken from the rules file."
            )
        )
        form = QFormLayout()
        self.facp_standby = spin(0, 50, 3, 0.05)
        self.facp_alarm = spin(0, 50, 3, 0.1)
        self.gas_standby = spin(0, 50, 3, 0.05)
        self.gas_alarm = spin(0, 50, 3, 0.1)
        self.margin = spin(0, 1, 2, 0.05)
        self.aging = spin(0.5, 3, 2, 0.05)
        self.temp = spin(0.5, 3, 2, 0.05)
        self.voice = QCheckBox("Voice evacuation (15 min alarm)")
        for widget in (self.facp_standby, self.facp_alarm, self.gas_standby, self.gas_alarm, self.margin, self.aging, self.temp):
            widget.valueChanged.connect(self._save)
        self.voice.toggled.connect(self._save)
        form.addRow("FACP standby (A)", self.facp_standby)
        form.addRow("FACP alarm (A)", self.facp_alarm)
        form.addRow("Gas panel standby (A)", self.gas_standby)
        form.addRow("Gas panel alarm (A)", self.gas_alarm)
        form.addRow("Margin fraction", self.margin)
        form.addRow("Aging derate", self.aging)
        form.addRow("Temperature derate", self.temp)
        form.addRow(self.voice)
        self.body_layout.addLayout(form)
        self.facp_out = muted("")
        self.gas_out = muted("")
        self.body_layout.addWidget(self.facp_out)
        self.body_layout.addWidget(self.gas_out)
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        battery = self.project().battery
        pairs = [
            (self.facp_standby, battery.facp_standby_a),
            (self.facp_alarm, battery.facp_alarm_a),
            (self.gas_standby, battery.gas_standby_a),
            (self.gas_alarm, battery.gas_alarm_a),
            (self.margin, battery.margin_fraction),
            (self.aging, battery.aging_derate),
            (self.temp, battery.temp_derate),
        ]
        for widget, value in pairs:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.voice.blockSignals(True)
        self.voice.setChecked(battery.voice_evac)
        self.voice.blockSignals(False)
        self.loading = False
        self.show_analysis(self.host.controller.analysis)

    def _save(self, *_args) -> None:
        if self.loading:
            return
        battery = self.project().battery
        battery.facp_standby_a = self.facp_standby.value()
        battery.facp_alarm_a = self.facp_alarm.value()
        battery.gas_standby_a = self.gas_standby.value()
        battery.gas_alarm_a = self.gas_alarm.value()
        battery.margin_fraction = self.margin.value()
        battery.aging_derate = self.aging.value()
        battery.temp_derate = self.temp.value()
        battery.voice_evac = self.voice.isChecked()
        self.touch()

    def show_analysis(self, analysis) -> None:
        if analysis is None:
            return
        facp = analysis.battery_facp
        gas = analysis.battery_gas
        self.facp_out.setText(f"FACP required {fmt_fixed(facp.required_ah)} Ah. Next standard size: {facp.next_standard_ah or 'above catalog'} Ah. {facp.formula}")
        self.gas_out.setText(f"Gas panel required {fmt_fixed(gas.required_ah)} Ah. Next standard size: {gas.next_standard_ah or 'above catalog'} Ah. {gas.formula}")


class RFIScreen(Screen):
    screen_id = "rfi"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Open items / RFI register")
        self.body_layout.addWidget(muted("Auto rows come from the lead lists and from every result that is not PASS. Close an auto row when the coordination is done; it stays closed if you closed it."))
        self.table = _table(["ID", "Status", "Assignee", "Due", "Source", "Rule", "Title", "Text"])
        self.table.itemChanged.connect(self._edited)
        self.body_layout.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton("Add manual item")
        close = QPushButton("Close selected")
        close.setObjectName("secondary")
        reopen = QPushButton("Reopen selected")
        reopen.setObjectName("secondary")
        delete = QPushButton("Delete manual / AI")
        delete.setObjectName("secondary")
        draft = QPushButton("Draft wording with AI")
        add.clicked.connect(self._add)
        close.clicked.connect(lambda: self._set_status("closed"))
        reopen.clicked.connect(lambda: self._set_status("open"))
        delete.clicked.connect(self._delete)
        draft.clicked.connect(self._draft)
        for button in (add, close, reopen, delete, draft):
            row.addWidget(button)
        row.addStretch(1)
        self.body_layout.addLayout(row)

    def load(self) -> None:
        self.loading = True
        self.table.blockSignals(True)
        items = self.project().rfis
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [display_rfi_id(item), item.status, item.assignee, item.due, item.source, item.rule_id, item.title, item.text]
            for col, value in enumerate(values):
                editable = col in {1, 2, 3, 6, 7}
                self.table.setItem(row, col, _item(value, editable=editable))
        self.table.blockSignals(False)
        self.loading = False

    def _selected(self):
        row = self.table.currentRow()
        items = self.project().rfis
        if row < 0 or row >= len(items):
            return None, -1
        return items[row], row

    def _edited(self, cell) -> None:
        if self.loading:
            return
        item, row = self.project().rfis[cell.row()], cell.row()
        if cell.column() == 1:
            status = cell.text().strip().lower()
            if status not in {"open", "closed", "deferred"}:
                self.host.status("Status is open, closed, or deferred.")
                return
            item.status = status
            item.user_closed = status == "closed"
            if status == "open":
                item.auto_closed = False
                item.user_closed = False
        elif cell.column() == 2:
            assignee = cell.text().strip()
            if assignee not in ASSIGNEES:
                self.host.status("Assignee must be one of: " + ", ".join(ASSIGNEES))
                return
            item.assignee = assignee
            item.assignee_edited = True
        elif cell.column() == 3:
            item.due = cell.text().strip()
        elif cell.column() == 6:
            item.title = cell.text()
            item.text_edited = True
        elif cell.column() == 7:
            item.text = cell.text()
            item.text_edited = True
        else:
            return
        self.touch()

    def _add(self) -> None:
        project = self.project()
        number = max((item.number for item in project.rfis), default=0) + 1
        project.rfis.append(
            RFI(number=number, key=f"manual:{number}", source="manual", title="Manual item", text="", assignee="Owner", status="open")
        )
        self.touch()
        self.load()

    def _set_status(self, status: str) -> None:
        item, _row = self._selected()
        if item is None:
            return
        item.status = status
        item.user_closed = status == "closed"
        if status == "open":
            item.auto_closed = False
            item.user_closed = False
        self.touch()
        self.load()

    def _delete(self) -> None:
        item, row = self._selected()
        if item is None:
            return
        if item.source == "auto":
            self.host.status("Auto items can be closed. They are not deleted.")
            return
        del self.project().rfis[row]
        self.touch()
        self.load()

    def _draft(self) -> None:
        item, _row = self._selected()
        if item is None:
            return
        if not self.host.ai_available():
            self.host.status("AI is off. Add an API key in Settings.")
            return
        from bess_workbench.ai.drafting import draft_rfi_text

        client = self.host.make_client()
        try:
            text, usage = draft_rfi_text(client, self.host.controller, item)
        except Exception as exc:
            from bess_workbench.ai.redact import scrub

            QMessageBox.warning(self, "AI draft", scrub(str(exc)))
            return
        self.host.note_usage(usage)
        dialog = ConfirmDialog(f"Replace the RFI text?\n\n- {item.text}\n\n+ {text}", self)
        if dialog.exec() != ConfirmDialog.DialogCode.Accepted:
            return
        item.text = text
        item.text_edited = True
        item.ai_drafted = True
        self.touch()
        self.load()


class ReportsScreen(Screen):
    screen_id = "reports"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Reports")
        self.body_layout.addWidget(muted("DOCX, XLSX, and PDF use the current engine results. An AI narrative is labeled as a draft and does not change a check."))
        row = QHBoxLayout()
        export = QPushButton("Export DOCX, XLSX, and PDF")
        export.clicked.connect(self._export)
        draft = QPushButton("Draft narrative with AI")
        draft.setObjectName("secondary")
        draft.clicked.connect(self._draft)
        row.addWidget(export)
        row.addWidget(draft)
        row.addStretch(1)
        self.body_layout.addLayout(row)
        self.narrative = QTextEdit()
        self.narrative.setPlaceholderText("Narrative for the Basis of Design. Leave blank to omit it.")
        self.narrative.textChanged.connect(self._narrative_edited)
        self.body_layout.addWidget(self.narrative)
        self.label = muted("")
        self.body_layout.addWidget(self.label)

    def load(self) -> None:
        self.loading = True
        self.narrative.setPlainText(self.project().ai_narrative)
        self._refresh_label()
        self.loading = False

    def _refresh_label(self) -> None:
        project = self.project()
        if project.ai_narrative.strip() and project.ai_narrative_model:
            state = "AI-drafted and edited by the user" if project.ai_narrative_edited else "AI-drafted"
            self.label.setText(f"{state} with {project.ai_narrative_model}. The DOCX repeats that label.")
        elif project.ai_narrative.strip():
            self.label.setText("This narrative was typed in the app. It is not labeled AI-drafted.")
        else:
            self.label.setText("No narrative yet.")

    def _narrative_edited(self) -> None:
        if self.loading:
            return
        project = self.project()
        project.ai_narrative = self.narrative.toPlainText()
        if project.ai_narrative_model:
            project.ai_narrative_edited = True
        self._refresh_label()
        self.touch()

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export folder")
        if not folder:
            return
        paths = export_all(self.project(), self.host.controller.analysis, folder)
        self.host.status("Exported " + ", ".join(path.name for path in paths.values()))

    def _draft(self) -> None:
        if not self.host.ai_available():
            self.host.status("AI is off. Add an API key in Settings.")
            return
        from bess_workbench.ai.drafting import draft_narrative

        client = self.host.make_client()
        try:
            text, usage = draft_narrative(client, self.host.controller)
        except Exception as exc:
            from bess_workbench.ai.redact import scrub

            QMessageBox.warning(self, "AI narrative", scrub(str(exc)))
            return
        self.host.note_usage(usage)
        dialog = ConfirmDialog("Save this AI draft into the narrative?\n\n" + text, self)
        if dialog.exec() != ConfirmDialog.DialogCode.Accepted:
            return
        project = self.project()
        project.ai_narrative = text
        project.ai_narrative_model = client.model
        project.ai_narrative_edited = False
        self.touch()
        self.load()


class SettingsScreen(Screen):
    screen_id = "settings"

    def __init__(self, host) -> None:
        super().__init__(host)
        self.add_title("Settings")
        self.body_layout.addWidget(muted("The API key is stored with keyring (Windows Credential Manager on Windows). ANTHROPIC_API_KEY is the fallback. The key is not written to the project file or to logs."))
        self.status_label = muted("")
        self.body_layout.addWidget(self.status_label)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste a key to store it. A saved key is not loaded back into this box.")
        self.model = QComboBox()
        self.model.setEditable(True)
        for model in ("claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"):
            self.model.addItem(model)
        form.addRow("Anthropic API key", self.key)
        form.addRow("Model", self.model)
        self.body_layout.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton("Save key")
        clear = QPushButton("Clear stored key")
        clear.setObjectName("secondary")
        test = QPushButton("Test connection")
        test.setObjectName("secondary")
        save.clicked.connect(self._save_key)
        clear.clicked.connect(self._clear_key)
        test.clicked.connect(self._test)
        self.model.currentTextChanged.connect(self._model_changed)
        row.addWidget(save)
        row.addWidget(clear)
        row.addWidget(test)
        row.addStretch(1)
        self.body_layout.addLayout(row)
        self.body_layout.addWidget(muted("AI features stay off until a key is present. The rest of the app does not need a network connection."))
        self.body_layout.addStretch(1)

    def load(self) -> None:
        self.loading = True
        self.status_label.setText(self.host.keystore.status()["hint"])
        self.model.blockSignals(True)
        self.model.setCurrentText(self.host.model_name())
        self.model.blockSignals(False)
        self.key.clear()
        self.loading = False

    def _save_key(self) -> None:
        try:
            self.host.keystore.save(self.key.text())
        except Exception as exc:
            from bess_workbench.ai.redact import scrub

            self.host.status(scrub(str(exc)))
            return
        self.key.clear()
        self.load()
        self.host.ai_panel.refresh_state()
        self.host.status("Key stored in the OS credential store.")

    def _clear_key(self) -> None:
        self.host.keystore.clear()
        self.load()
        self.host.ai_panel.refresh_state()
        self.host.status("Stored key cleared. An environment variable is still used if it is set.")

    def _model_changed(self, text: str) -> None:
        if self.loading:
            return
        self.host.set_model(text.strip())

    def _test(self) -> None:
        if not self.host.ai_available():
            self.status_label.setText(self.host.keystore.status()["hint"])
            return
        self.status_label.setText("Contacting the model…")
        try:
            from bess_workbench.ai.request import build_text_kwargs

            client = self.host.make_client()
            kwargs = build_text_kwargs(model=client.model, system="Reply with the single word OK.", user="Reply with the single word OK.", max_tokens=16)
            text, usage = client.complete_text(kwargs)
            self.host.note_usage(usage)
            self.status_label.setText(f"Connected to {client.model}. Response: {text[:80]}")
        except Exception as exc:
            from bess_workbench.ai.redact import scrub

            self.status_label.setText("Connection failed: " + scrub(str(exc)))


def all_screens(host) -> list[Screen]:
    return [
        ProjectScreen(host),
        RoomsScreen(host),
        ThresholdsScreen(host),
        ExplosionScreen(host),
        GasScreen(host),
        CauseScreen(host),
        SprinklerScreen(host),
        BatteryScreen(host),
        RFIScreen(host),
        ReportsScreen(host),
        SettingsScreen(host),
    ]
