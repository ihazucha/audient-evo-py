"""Curses TUI for Audient EVO devices"""

import curses
import sys

from evo.controller import (
    EVOController,
    _MIXER_DB_MIN,
    _MIXER_DB_MAX,
)
from evo.devices import DeviceSpec, detect_devices, DEVICES
from evo import config as cfg

C_GREEN, C_RED, C_CYAN, C_YELLOW, C_WHITE, C_BLUE = range(1, 7)

SLIDER_W = 69
BOX_IW = SLIDER_W + 2
SLIDER_OFF = 2
PICKER_LIST_H = 6

PAN_MIN, PAN_MAX, PAN_STEP = -100.0, 100.0, 5.0
MIXER_SECTION_IW = 17
MIXER_PAN_HALF = 7  # half-width of narrow pan slider (total = 2*HALF+1 = 15)


def _build_elements(spec: DeviceSpec):
    """Build focusable elements list from device spec."""
    elements = [("output", "volume", "OUTPUT", C_GREEN)]
    for i in range(spec.num_inputs):
        elements.append((f"input{i+1}", "gain", f"INPUT {i+1}", C_BLUE))
    if spec.has_monitor:
        elements.append(("monitor", None, "MONITOR", C_CYAN))
    return elements


def _build_ranges(spec: DeviceSpec):
    """Build value ranges dict from device spec."""
    ranges = {"output": (spec.vol_db_min, spec.vol_db_max, 1.0)}
    for i in range(spec.num_inputs):
        ranges[f"input{i+1}"] = (spec.gain_db_min, spec.gain_db_max, 1.0)
    if spec.has_monitor:
        ranges["monitor"] = (0, 100, 1)
    return ranges


def _build_mixer_sections(spec: DeviceSpec):
    """Build mixer sections list from device spec."""
    sections = []
    for i in range(spec.num_inputs):
        sections.append((
            f"input{i+1}",
            f"INPUT {i+1}",
            C_BLUE,
            [
                ("pan", "Pan", PAN_MIN, PAN_MAX, PAN_STEP),
                ("volume", "Vol", _MIXER_DB_MIN, _MIXER_DB_MAX, 1.0),
            ],
        ))
    sections.append((
        "main",
        "MAIN OUT 1|2",
        C_GREEN,
        [
            ("pan_l", "Pan L", PAN_MIN, PAN_MAX, PAN_STEP),
            ("pan_r", "Pan R", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", _MIXER_DB_MIN, _MIXER_DB_MAX, 1.0),
        ],
    ))
    sections.append((
        "loopback",
        "LOOP OUT 1|2",
        C_YELLOW,
        [
            ("pan_l", "Pan L", PAN_MIN, PAN_MAX, PAN_STEP),
            ("pan_r", "Pan R", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", _MIXER_DB_MIN, _MIXER_DB_MAX, 1.0),
        ],
    ))
    return sections


def _build_mixer_state(spec: DeviceSpec):
    """Build initial mixer state dict from device spec."""
    state = {}
    for i in range(spec.num_inputs):
        state[f"input{i+1}"] = {"volume": -128.0, "pan": 0.0}
    state["main"] = {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}
    state["loopback"] = {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0}
    return state


class EvoTUI:
    def __init__(self, evo: EVOController):
        self.evo = evo
        self.spec = evo.spec
        self.cursor = 0
        self.status = ""
        self.status_err = False
        self.num_buf = ""
        self._mode = "normal"
        self._window = "controls"
        self._file_list = []
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input = ""
        self._slider_map = []
        self._box_attr = 0

        # Build dynamic layout from spec
        self._elements = _build_elements(self.spec)
        self._ranges = _build_ranges(self.spec)
        self._mixer_sections = _build_mixer_sections(self.spec)

        self._mixer_section = 0
        self._mixer_param = len(self._mixer_sections[0][3]) - 1
        self._mixer_state = _build_mixer_state(self.spec)

        self._max_pan = max(
            sum(1 for s in sec[3] if s[0].startswith("pan")) for sec in self._mixer_sections
        )
        self._mixer_section_h = self._max_pan * 2 + 5
        self._controls_body_h = len(self._elements) * 4 + (len(self._elements) - 1)
        self._total_h = 2 + self._controls_body_h + 2

        self._config_dir = cfg._device_dir(self.spec.name)
        self._load_mixer_state()
        self._sync()

    # -- state --

    def _sync(self):
        try:
            self.state = self.evo.decode_status(self.evo.get_status_raw())
        except OSError as e:
            self._set_status(f"USB error: {e}", err=True)

    def _set_status(self, msg, err=False):
        self.status, self.status_err = msg, err

    def _val(self, idx=None):
        if idx is None:
            idx = self.cursor
        key, sub = self._elements[idx][:2]
        return self.state[key] if sub is None else self.state[key][sub]

    def _frac(self, idx):
        key = self._elements[idx][0]
        lo, hi, _ = self._ranges[key]
        return max(0.0, min(1.0, (self._val(idx) - lo) / (hi - lo)))

    def _muted(self, idx):
        key = self._elements[idx][0]
        return self.state[key].get("mute", False) if key != "monitor" else False

    def _has_mute(self, idx):
        return self._elements[idx][0] != "monitor"

    def _has_phantom(self, idx):
        return self._elements[idx][0].startswith("input")

    def _is_db(self, idx=None):
        return self._elements[self.cursor if idx is None else idx][0] != "monitor"

    def _current_unit(self):
        if self._window == "controls":
            return "dB" if self._is_db() else "%"
        param = self._mixer_sections[self._mixer_section][3][self._mixer_param][0]
        return "dB" if param == "volume" else ""

    # -- controls actions --

    def _set_val(self, val):
        key, sub = self._elements[self.cursor][:2]
        lo, hi, _ = self._ranges[key]
        val = max(lo, min(hi, val))
        try:
            if key == "monitor":
                self.evo.set_monitor(round(val))
            elif key == "output":
                self.evo.set_volume(val)
            else:
                self.evo.set_gain(key, val)
            if sub is None:
                self.state[key] = val
            else:
                self.state[key][sub] = val
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _adjust(self, delta):
        _, _, step = self._ranges[self._elements[self.cursor][0]]
        self._set_val(self._val() + delta * step)

    def _toggle_mute(self):
        key = self._elements[self.cursor][0]
        if key == "monitor":
            return
        try:
            new = not self.state[key]["mute"]
            self.evo.set_mute(key, new)
            self.state[key]["mute"] = new
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _toggle_phantom(self):
        key = self._elements[self.cursor][0]
        if not key.startswith("input"):
            return
        try:
            new = not self.state[key]["phantom"]
            self.evo.set_phantom(key, new)
            self.state[key]["phantom"] = new
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- mixer state persistence --

    def _load_mixer_state(self):
        """Load mixer state from disk into TUI state (maps 'output' key to 'main')."""
        data = cfg.load_mixer_state(self.spec.name)
        if data is None:
            return
        for i in range(self.spec.num_inputs):
            key = f"input{i+1}"
            if key in data:
                self._mixer_state[key].update(data[key])
        if "output" in data:
            self._mixer_state["main"].update(data["output"])
        if "loopback" in data:
            self._mixer_state["loopback"].update(data["loopback"])

    def _save_mixer_state(self):
        """Persist TUI mixer state to disk (maps 'main' key to 'output')."""
        data = {}
        for i in range(self.spec.num_inputs):
            key = f"input{i+1}"
            data[key] = dict(self._mixer_state[key])
        data["output"] = dict(self._mixer_state["main"])
        data["loopback"] = dict(self._mixer_state["loopback"])
        cfg.save_mixer_state(self.spec.name, data)

    # -- mixer actions --

    def _mixer_val(self):
        key = self._mixer_sections[self._mixer_section][0]
        param = self._mixer_sections[self._mixer_section][3][self._mixer_param][0]
        return self._mixer_state[key][param]

    def _mixer_set_val(self, val):
        key, _, _, sliders = self._mixer_sections[self._mixer_section]
        param, _, lo, hi, _ = sliders[self._mixer_param]
        self._mixer_state[key][param] = max(lo, min(hi, val))
        self._apply_mixer(key)

    def _mixer_adjust(self, delta):
        _, _, _, _, step = self._mixer_sections[self._mixer_section][3][self._mixer_param]
        self._mixer_set_val(self._mixer_val() + delta * step)

    def _apply_mixer(self, key):
        try:
            s = self._mixer_state[key]
            if key.startswith("input"):
                input_num = int(key[5:])
                self.evo.set_mixer_input(input_num, s["volume"], s["pan"])
            elif key == "main":
                self.evo.set_mixer_output(s["volume"], s["pan_l"], s["pan_r"])
            elif key == "loopback":
                self.evo.set_mixer_loopback(s["volume"], s["pan_l"], s["pan_r"])
            self._save_mixer_state()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- file picker --

    def _scan_files(self):
        d = self._config_dir
        return (
            sorted(f for f in d.glob("*.json") if not f.name.startswith(".")) if d.exists() else []
        )

    def _enter_save_mode(self):
        self._file_list = self._scan_files()
        self._file_cursor = self._file_scroll = 0
        self._file_input = "config.json"
        self._mode = "save"

    def _enter_load_mode(self):
        files = self._scan_files()
        if not files:
            self._set_status(f"No configs in {self._config_dir}", err=True)
            return
        self._file_list = files
        self._file_cursor = self._file_scroll = 0
        self._mode = "load"

    def _picker_move(self, delta):
        n = len(self._file_list)
        if not n:
            return
        self._file_cursor = max(0, min(n - 1, self._file_cursor + delta))
        if self._file_cursor < self._file_scroll:
            self._file_scroll = self._file_cursor
        elif self._file_cursor >= self._file_scroll + PICKER_LIST_H:
            self._file_scroll = self._file_cursor - PICKER_LIST_H + 1

    def _picker_key(self, key):
        if key == 27:
            self._mode = "normal"
            return
        if self._mode == "load":
            if key in (curses.KEY_UP, ord("k")):
                self._picker_move(-1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self._picker_move(1)
            elif key == 10 and self._file_list:
                path = self._file_list[self._file_cursor]
                try:
                    cfg.load_and_apply(self.evo, path)
                    self._sync()
                    self._load_mixer_state()
                    self._set_status(f"Loaded \u2190 {path.name}")
                except Exception as e:
                    self._set_status(f"Load error: {e}", err=True)
                self._mode = "normal"
        else:  # save
            if key == curses.KEY_UP:
                self._picker_move(-1)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].name
            elif key == curses.KEY_DOWN:
                self._picker_move(1)
                if self._file_list:
                    self._file_input = self._file_list[self._file_cursor].name
            elif key in (curses.KEY_BACKSPACE, 127):
                self._file_input = self._file_input[:-1]
            elif 32 <= key <= 126:
                self._file_input += chr(key)
            elif key == 10:
                name = self._file_input.strip()
                if name:
                    if not name.endswith(".json"):
                        name += ".json"
                    try:
                        cfg.save(self.evo, self._config_dir / name)
                        self._set_status(f"Saved \u2192 {name}")
                    except Exception as e:
                        self._set_status(f"Save error: {e}", err=True)
                self._mode = "normal"

    # -- drawing primitives --

    def _safe(self, scr, row, col, text, *args):
        try:
            h, w = scr.getmaxyx()
            if row < 0 or row >= h or col >= w - 1:
                return
            scr.addnstr(row, col, text, w - col - 1, *args)
        except curses.error:
            pass

    def _box_top(self, scr, row, cx, label, active=False, iw=BOX_IW):
        self._box_attr = curses.A_NORMAL if active else curses.color_pair(C_WHITE) | curses.A_DIM
        dashes = iw - len(label) - 3
        self._safe(scr, row, cx, "\u250c\u2500 ", self._box_attr)
        self._safe(scr, row, cx + 3, label, self._box_attr)
        self._safe(
            scr, row, cx + 3 + len(label), " " + "\u2500" * dashes + "\u2510", self._box_attr
        )

    def _box_top_centered(self, scr, row, cx, label, active=False, iw=MIXER_SECTION_IW):
        self._box_attr = curses.A_NORMAL if active else curses.color_pair(C_WHITE) | curses.A_DIM
        label = label[: iw - 2]
        inner = iw - len(label) - 2
        left_d = inner // 2
        self._safe(
            scr,
            row,
            cx,
            "\u250c"
            + "\u2500" * left_d
            + " "
            + label
            + " "
            + "\u2500" * (inner - left_d)
            + "\u2510",
            self._box_attr,
        )

    def _box_side(self, scr, row, cx, iw=BOX_IW):
        self._safe(scr, row, cx, "\u2502", self._box_attr)
        self._safe(scr, row, cx + iw + 1, "\u2502", self._box_attr)

    def _box_bot(self, scr, row, cx, iw=BOX_IW):
        self._safe(scr, row, cx, "\u2514" + "\u2500" * iw + "\u2518", self._box_attr)

    def _box_bot_labeled(self, scr, row, cx, label, iw=BOX_IW):
        dashes = iw - len(label) - 3
        self._safe(
            scr,
            row,
            cx,
            "\u2514" + "\u2500" * dashes + " " + label + " \u2500\u2518",
            self._box_attr,
        )

    def _box_sep(self, scr, row, cx, iw):
        self._safe(scr, row, cx, "\u251c" + "\u2500" * iw + "\u2524", self._box_attr)

    def _hslider(self, scr, row, x, frac, muted=False, sel=False, color=C_GREEN, w=SLIDER_W):
        slots = w * 2
        filled_slots = max(0, min(slots, round(slots * frac)))
        full_chars = filled_slots // 2
        partial = filled_slots % 2
        fill_attr = curses.color_pair(C_RED if muted else color) | (
            curses.A_NORMAL if sel else curses.A_DIM
        )
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        pos = x
        if full_chars:
            self._safe(scr, row, pos, "\u2588" * full_chars, fill_attr)
            pos += full_chars
        if partial:
            self._safe(scr, row, pos, "\u258c", fill_attr)
            pos += 1
        empty = w - full_chars - partial
        if empty:
            self._safe(scr, row, pos, "\u2591" * empty, empty_attr)

    def _dual_slider(self, scr, row, x, frac, sel=False, color=C_GREEN):
        """Dual-side slider: fills from center outward with half-block precision."""
        half = SLIDER_W // 2
        fill_attr = curses.color_pair(color) | (curses.A_NORMAL if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        self._safe(scr, row, x, "\u2591" * SLIDER_W, empty_attr)

        left_slots = max(0, min(half * 2, round((1.0 - frac) * half * 2)))
        right_slots = half * 2 - left_slots
        left_full = left_slots // 2
        left_partial = left_slots % 2
        right_full = right_slots // 2
        right_partial = right_slots % 2

        if left_full:
            self._safe(scr, row, x + half - left_full, "\u2588" * left_full, fill_attr)
        if left_partial:
            self._safe(scr, row, x + half - left_full - 1, "\u2590", fill_attr)
        if right_full:
            self._safe(scr, row, x + half + 1, "\u2588" * right_full, fill_attr)
        if right_partial:
            self._safe(scr, row, x + half + 1 + right_full, "\u258c", fill_attr)
        self._safe(scr, row, x + half, "\u2502", curses.A_BOLD)

    def _narrow_pan_slider(self, scr, row, x, frac, sel=False, color=C_GREEN):
        """Narrow pan slider using half/full block precision. Width = 2*MIXER_PAN_HALF+1."""
        H = MIXER_PAN_HALF
        total_slots = H * 2
        fill_attr = curses.color_pair(color) | (curses.A_NORMAL if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)

        left_slots = max(0, min(total_slots, round((1.0 - frac) * total_slots)))
        right_slots = total_slots - left_slots
        left_full = left_slots // 2
        left_partial = left_slots % 2
        right_full = right_slots // 2
        right_partial = right_slots % 2

        self._safe(scr, row, x, "\u2591" * H, empty_attr)
        self._safe(scr, row, x + H + 1, "\u2591" * H, empty_attr)

        if left_full:
            self._safe(scr, row, x + H - left_full, "\u2588" * left_full, fill_attr)
        if left_partial:
            self._safe(scr, row, x + H - left_full - 1, "\u2590", fill_attr)
        if right_full:
            self._safe(scr, row, x + H + 1, "\u2588" * right_full, fill_attr)
        if right_partial:
            self._safe(scr, row, x + H + 1 + right_full, "\u258c", fill_attr)

        self._safe(scr, row, x + H, "\u2502", curses.A_BOLD)

    def _mute_ind(self, scr, row, x, key):
        if self.state[key]["mute"]:
            self._safe(scr, row, x, "[M]", curses.A_BOLD | curses.color_pair(C_RED))
        else:
            self._safe(scr, row, x, "[m]", curses.A_DIM)

    def _phantom_ind(self, scr, row, x, key):
        if self.state[key]["phantom"]:
            self._safe(scr, row, x, "[48V]", curses.A_BOLD | curses.color_pair(C_YELLOW))
        else:
            self._safe(scr, row, x, "[48v]", curses.A_DIM)

    # -- tab bar --

    def _draw_tab_bar(self, scr, row, cx, content_w, section_w):
        ctrl_label = " CONTROLS "
        mix_label = " MIXER "
        tabs_w = len(ctrl_label) + 1 + len(mix_label)
        tab_x = cx + (content_w - tabs_w) // 2
        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        self._safe(scr, row, cx, self.spec.display_name, dim)
        if self._window == "controls":
            ctrl_attr = curses.A_REVERSE | curses.A_BOLD
            mix_attr = dim
        else:
            ctrl_attr = dim
            mix_attr = curses.A_REVERSE | curses.A_BOLD
        self._safe(scr, row, tab_x, ctrl_label, ctrl_attr)
        self._safe(scr, row, tab_x + len(ctrl_label) + 1, mix_label, mix_attr)
        self._safe(scr, row + 1, cx, "\u2500" * section_w, dim)
        if self._window == "controls":
            active_x = tab_x
        else:
            active_x = tab_x + len(ctrl_label) + 1
        active_label_w = len(ctrl_label) if self._window == "controls" else len(mix_label)
        self._safe(scr, row + 1, active_x, " " * active_label_w, dim)

    # -- section drawing (controls) --

    def _draw_section(self, scr, row, cx, idx):
        key, sub, label, color = self._elements[idx]
        active = self.cursor == idx
        val = self._val(idx)
        frac = self._frac(idx)
        muted = self._muted(idx)

        self._box_top(scr, row, cx, label, active)
        row += 1

        self._box_side(scr, row, cx)
        if sub is None:
            self._dual_slider(scr, row, cx + SLIDER_OFF, frac, active, color)
        else:
            self._hslider(scr, row, cx + SLIDER_OFF, frac, muted, active, color)
        self._slider_map.append((row, cx + SLIDER_OFF, SLIDER_W, idx))
        row += 1

        self._box_side(scr, row, cx)
        lbl_attr = curses.A_BOLD if active else curses.A_DIM
        if sub is None:
            self._safe(scr, row, cx + SLIDER_OFF, "IN", lbl_attr)
            pct = f"Mix: {val:3.0f}%"
            mid = cx + SLIDER_OFF + (SLIDER_W - len(pct)) // 2
            self._safe(scr, row, mid, pct, lbl_attr)
            self._safe(scr, row, cx + SLIDER_OFF + SLIDER_W - 3, "OUT", lbl_attr)
        else:
            vlabel = "Vol:" if key == "output" else "Gain:"
            val_str = f"{vlabel:5s} {val:+6.1f} dB"
            val_attr = curses.color_pair(C_RED) if muted else (lbl_attr)
            self._safe(scr, row, cx + SLIDER_OFF, val_str, val_attr)
            if self._has_phantom(idx):
                self._phantom_ind(scr, row, cx + BOX_IW - 9, key)
            if self._has_mute(idx):
                self._mute_ind(scr, row, cx + BOX_IW - 3, key)
        row += 1

        self._box_bot(scr, row, cx)
        return row + 1

    # -- mixer section drawing --

    def _draw_mixer_section(self, scr, top_row, cx, sec_idx):
        key, label, color, sliders = self._mixer_sections[sec_idx]
        sel_sec = self._mixer_section == sec_idx
        pan_params = [(i, s) for i, s in enumerate(sliders) if s[0].startswith("pan")]
        vol_param_idx = next(i for i, s in enumerate(sliders) if s[0] == "volume")

        self._box_top_centered(scr, top_row, cx, label, sel_sec)
        row = top_row + 1

        for slot in range(2):
            self._box_side(scr, row, cx, MIXER_SECTION_IW)
            if slot < len(pan_params):
                pidx, (param, _, lo, hi, _) = pan_params[slot]
                val = self._mixer_state[key][param]
                sel = sel_sec and self._mixer_param == pidx
                self._narrow_pan_slider(scr, row, cx + 2, (val - lo) / (hi - lo), sel, color)
            row += 1

            self._box_side(scr, row, cx, MIXER_SECTION_IW)
            if slot < len(pan_params):
                pidx, (param, plabel, lo, hi, _) = pan_params[slot]
                val = self._mixer_state[key][param]
                sel = sel_sec and self._mixer_param == pidx
                self._safe(
                    scr,
                    row,
                    cx + 2,
                    f"{plabel + ':':<9} {val:+5.0f}",
                    curses.A_BOLD if sel else curses.A_DIM,
                )
            row += 1

        self._box_sep(scr, row, cx, MIXER_SECTION_IW)
        row += 1

        vol_val = self._mixer_state[key]["volume"]
        vol_frac = max(0.0, min(1.0, (vol_val - _MIXER_DB_MIN) / (_MIXER_DB_MAX - _MIXER_DB_MIN)))
        vol_sel = sel_sec and self._mixer_param == vol_param_idx
        self._box_side(scr, row, cx, MIXER_SECTION_IW)
        self._hslider(scr, row, cx + 2, vol_frac, sel=vol_sel, color=color, w=MIXER_SECTION_IW - 2)
        row += 1

        self._box_side(scr, row, cx, MIXER_SECTION_IW)
        self._safe(
            scr,
            row,
            cx + 2,
            f"{'Vol:':<5} {vol_val:+6.1f} dB",
            curses.A_BOLD if vol_sel else curses.A_DIM,
        )
        row += 1

        self._box_bot(scr, row, cx, MIXER_SECTION_IW)

    # -- file picker dialog --

    def _draw_file_picker(self, scr):
        scr.erase()
        h, w = scr.getmaxyx()
        cx = (w - (BOX_IW + 2)) // 2
        title = "SAVE CONFIG" if self._mode == "save" else "LOAD CONFIG"
        total_h = PICKER_LIST_H + 7 + (1 if self._mode == "save" else 0)
        row = max(0, (h - total_h) // 2)

        self._box_attr = curses.color_pair(C_CYAN) | curses.A_BOLD
        dashes = BOX_IW - len(title) - 3
        self._safe(scr, row, cx, "\u250c\u2500 ", self._box_attr)
        self._safe(scr, row, cx + 3, title, self._box_attr)
        self._safe(
            scr, row, cx + 3 + len(title), " " + "\u2500" * dashes + "\u2510", self._box_attr
        )
        row += 1

        self._box_side(scr, row, cx)
        self._safe(scr, row, cx + SLIDER_OFF, f"{self._config_dir}/"[: BOX_IW - 2], curses.A_DIM)
        row += 1

        self._box_side(scr, row, cx)
        row += 1

        for i in range(PICKER_LIST_H):
            self._box_side(scr, row, cx)
            abs_i = self._file_scroll + i
            if not self._file_list and i == 0:
                self._safe(scr, row, cx + SLIDER_OFF, "(no configs found)", curses.A_DIM)
            elif abs_i < len(self._file_list):
                f = self._file_list[abs_i]
                sel = abs_i == self._file_cursor
                pre = "\u25b6 " if sel else "  "
                attr = curses.color_pair(C_CYAN) | curses.A_NORMAL if sel else 0
                self._safe(scr, row, cx + SLIDER_OFF, f"{pre}{f.name}"[: BOX_IW - 2], attr)
            row += 1

        self._box_side(scr, row, cx)
        row += 1

        if self._mode == "save":
            self._box_side(scr, row, cx)
            self._safe(
                scr, row, cx + SLIDER_OFF, f"File: {self._file_input}_"[: BOX_IW - 2], curses.A_BOLD
            )
            row += 1

        self._box_side(scr, row, cx)
        hint = (
            "\u2191/\u2193:select  Enter:save  Esc:cancel"
            if self._mode == "save"
            else "\u2191/\u2193:select  Enter:load  Esc:cancel"
        )
        self._safe(scr, row, cx + SLIDER_OFF, hint, curses.A_DIM)
        row += 1

        self._safe(scr, row, cx, "\u2514" + "\u2500" * BOX_IW + "\u2518", self._box_attr)

    # -- main draw --

    def _draw(self, scr):
        if self._mode in ("save", "load"):
            self._draw_file_picker(scr)
            return

        scr.erase()
        h, w = scr.getmaxyx()
        self._slider_map = []

        mixer_w = len(self._mixer_sections) * (MIXER_SECTION_IW + 3) - 1
        content_w = max(BOX_IW + 2, mixer_w)
        cx = max(0, (w - content_w) // 2)

        if h < self._total_h or w < content_w:
            self._safe(scr, 0, 0, f"Terminal too small ({w}x{h}, need {content_w}x{self._total_h})")
            return

        row = max(0, (h - self._total_h) // 2)
        section_w = mixer_w if self._window == "mixer" else BOX_IW + 2
        self._draw_tab_bar(scr, row, cx, content_w, section_w)
        row += 2

        if self._window == "controls":
            row = self._draw_controls_body(scr, row, cx)
        else:
            row = self._draw_mixer_body(scr, row, cx)

        self._draw_status_bar(scr, row, cx)

    def _draw_controls_body(self, scr, row, cx):
        for idx in range(len(self._elements)):
            row = self._draw_section(scr, row, cx, idx)
            if idx < len(self._elements) - 1:
                row += 1

        unit = "dB" if self._is_db() else "%"
        help1 = f"j/k:section  h/l:\xb11{unit} (H/L:\xb15{unit})"
        if self._has_mute(self.cursor):
            help1 += "  m:mute"
        if self._has_phantom(self.cursor):
            help1 += "  P:48V"
        self._safe(scr, row, cx + 1, help1, curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1
        self._safe(
            scr,
            row,
            cx + 1,
            "s:save  o:load  Tab:mixer  q:quit",
            curses.color_pair(C_WHITE) | curses.A_DIM,
        )
        return row + 1

    def _draw_mixer_body(self, scr, row, cx):
        sec_ow = MIXER_SECTION_IW + 3
        for sec_idx in range(len(self._mixer_sections)):
            self._draw_mixer_section(scr, row, cx + sec_idx * sec_ow, sec_idx)
        row += self._controls_body_h

        param = self._mixer_sections[self._mixer_section][3][self._mixer_param][0]
        if param == "volume":
            help1 = "n/p:section  j/k:param  h/l:\xb11dB (H/L:\xb15dB)"
        else:
            help1 = "n/p:section  j/k:param  h/l:\xb15 (H/L:\xb125)"
        self._safe(scr, row, cx + 1, help1, curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1
        self._safe(
            scr,
            row,
            cx + 1,
            "s:save  o:load  Tab:controls  q:quit",
            curses.color_pair(C_WHITE) | curses.A_DIM,
        )
        return row + 1

    def _draw_status_bar(self, scr, row, cx):
        if not self.status and not self.num_buf:
            return
        self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
        self._safe(scr, row, cx, "\u250c" + "\u2500" * BOX_IW + "\u2510", self._box_attr)
        row += 1
        self._box_side(scr, row, cx)
        if self.num_buf:
            unit = self._current_unit()
            self._safe(
                scr,
                row,
                cx + SLIDER_OFF,
                f"= {self.num_buf}_ {unit} (Enter=confirm  Esc=cancel)",
                curses.color_pair(C_YELLOW),
            )
        else:
            attr = (
                curses.color_pair(C_RED) | curses.A_BOLD
                if self.status_err
                else curses.color_pair(C_YELLOW)
            )
            self._safe(scr, row, cx + SLIDER_OFF, self.status, attr)
        row += 1
        self._box_bot_labeled(scr, row, cx, "STATUS")

    # -- key handlers --

    def _handle_adjust(self, key, fn):
        """Handle h/l/H/L adjustment keys. Returns True if consumed."""
        if key == ord("h"):
            fn(-1)
        elif key == ord("l"):
            fn(1)
        elif key == ord("H"):
            fn(-5)
        elif key == ord("L"):
            fn(5)
        else:
            return False
        return True

    def _controls_key(self, key):
        if key == ord("j"):
            self.cursor = (self.cursor + 1) % len(self._elements)
        elif key == ord("k"):
            self.cursor = (self.cursor - 1) % len(self._elements)
        elif key == ord("m"):
            self._toggle_mute()
        elif key == ord("P"):
            self._toggle_phantom()
        else:
            self._handle_adjust(key, self._adjust)

    def _mixer_key(self, key):
        n = len(self._mixer_sections)
        n_params = len(self._mixer_sections[self._mixer_section][3])
        if key == ord("n"):
            self._mixer_section = (self._mixer_section + 1) % n
            self._mixer_param = len(self._mixer_sections[self._mixer_section][3]) - 1
        elif key == ord("p"):
            self._mixer_section = (self._mixer_section - 1) % n
            self._mixer_param = len(self._mixer_sections[self._mixer_section][3]) - 1
        elif key == ord("k"):
            self._mixer_param = (self._mixer_param - 1) % n_params
        elif key == ord("j"):
            self._mixer_param = (self._mixer_param + 1) % n_params
        elif key == curses.KEY_UP:
            self._mixer_adjust(1)
        elif key == curses.KEY_DOWN:
            self._mixer_adjust(-1)
        else:
            self._handle_adjust(key, self._mixer_adjust)

    # -- event loop --

    def run(self, scr):
        curses.curs_set(0)
        curses.use_default_colors()
        for i, color in enumerate(
            [
                curses.COLOR_GREEN,
                curses.COLOR_RED,
                curses.COLOR_CYAN,
                curses.COLOR_YELLOW,
                curses.COLOR_WHITE,
                curses.COLOR_BLUE,
            ],
            1,
        ):
            curses.init_pair(i, color, -1)
        curses.set_escdelay(25)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        scr.timeout(20)

        while True:
            self._sync()
            self._draw(scr)
            scr.refresh()
            key = scr.getch()

            if self._mode in ("save", "load"):
                self._picker_key(key)
                continue

            if key == ord("q"):
                break
            elif key == ord("s"):
                self._enter_save_mode()
            elif key == ord("o"):
                self._enter_load_mode()
            elif key == 9:  # Tab
                self._window = "mixer" if self._window == "controls" else "controls"
                self.num_buf = ""
            elif key == curses.KEY_RESIZE:
                scr.clear()
            elif key == 10:  # Enter
                if self.num_buf:
                    try:
                        val = float(self.num_buf)
                        if self._window == "controls":
                            self._set_val(val)
                        else:
                            self._mixer_set_val(val)
                    except ValueError:
                        pass
                    self.num_buf = ""
            elif key == 27:  # Esc
                self.num_buf = ""
            elif key in (curses.KEY_BACKSPACE, 127) and self.num_buf:
                self.num_buf = self.num_buf[:-1]
            elif key == ord("-") and not self.num_buf:
                self.num_buf = "-"
            elif key == ord(".") and "." not in self.num_buf:
                self.num_buf += "."
            elif 48 <= key <= 57:  # 0-9
                self.num_buf += chr(key)
            elif self._window == "controls":
                self._controls_key(key)
            else:
                self._mixer_key(key)


def main():
    devices = detect_devices()
    if not devices:
        print("error: no EVO device found (check /dev/evo*)", file=sys.stderr)
        sys.exit(1)
    if len(devices) > 1:
        print("Multiple devices found. Use --device to select:", file=sys.stderr)
        for d in devices:
            print(f"  python -m tui --device {d.name}", file=sys.stderr)
        sys.exit(1)
    spec = devices[0]
    try:
        evo = EVOController(spec)
        with evo:
            curses.wrapper(EvoTUI(evo).run)
    except (OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
