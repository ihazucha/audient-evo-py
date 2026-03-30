"""Curses TUI for Audient EVO4 - horizontal section layout."""

import curses
import sys

from evo4.controller import EVO4Controller
from evo4 import config as cfg

C_GREEN, C_RED, C_CYAN, C_YELLOW, C_WHITE, C_BLUE = range(1, 7)

SLIDER_W = 69
BOX_IW = SLIDER_W + 2
SLIDER_OFF = 2
PICKER_LIST_H = 6

# Focusable elements: (state_key, value_key, section_label, slider_color)
# state_key indexes into decode_status() dict
# value_key is the sub-key (None for top-level like "monitor")
ELEMENTS = [
    ("monitor", None, "MONITOR", C_CYAN),
    ("output", "volume", "OUTPUT", C_GREEN),
    ("input1", "gain", "INPUT 1", C_BLUE),
    ("input2", "gain", "INPUT 2", C_BLUE),
]

# Value ranges: (min, max, step) - dB for volume/gain, % for monitor
RANGES = {
    "monitor": (0, 100, 1),
    "output": (-96.0, 0.0, 1.0),
    "input1": (-8.0, 50.0, 1.0),
    "input2": (-8.0, 50.0, 1.0),
}

# -- Mixer (MU60) --
MIXER_DB_MIN, MIXER_DB_MAX, MIXER_DB_STEP = -128.0, 6.0, 1.0
PAN_MIN, PAN_MAX, PAN_STEP = -100.0, 100.0, 5.0

# Mixer layout constants
MIXER_SECTION_IW = 15  # inner width of each section column
MIXER_PAN_HALF = 7  # half-width of narrow pan slider (total = 2*HALF+1 = 15)

# (key, label, color, sliders[])  slider: (param, label, min, max, step)
# Params ordered: pan(s) first, volume last
MIXER_SECTIONS = [
    (
        "input1",
        "INPUT 1",
        C_BLUE,
        [
            ("pan", "Pan", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", MIXER_DB_MIN, MIXER_DB_MAX, MIXER_DB_STEP),
        ],
    ),
    (
        "input2",
        "INPUT 2",
        C_BLUE,
        [
            ("pan", "Pan", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", MIXER_DB_MIN, MIXER_DB_MAX, MIXER_DB_STEP),
        ],
    ),
    (
        "main",
        "MAIN OUT",
        C_GREEN,
        [
            ("pan_l", "Pan L", PAN_MIN, PAN_MAX, PAN_STEP),
            ("pan_r", "Pan R", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", MIXER_DB_MIN, MIXER_DB_MAX, MIXER_DB_STEP),
        ],
    ),
    (
        "loopback",
        "LOOPBACK",
        C_YELLOW,
        [
            ("pan_l", "Pan L", PAN_MIN, PAN_MAX, PAN_STEP),
            ("pan_r", "Pan R", PAN_MIN, PAN_MAX, PAN_STEP),
            ("volume", "Vol", MIXER_DB_MIN, MIXER_DB_MAX, MIXER_DB_STEP),
        ],
    ),
]

# Derived layout constants (computed from ELEMENTS and MIXER_SECTIONS)
_max_pan = max(
    sum(1 for s in sec[3] if s[0].startswith("pan")) for sec in MIXER_SECTIONS
)
MIXER_SECTION_H = _max_pan * 2 + 5  # top + pans*2 + sep + vol_slider + vol_val + bottom
CONTROLS_BODY_H = len(ELEMENTS) * 4 + (len(ELEMENTS) - 1)  # section rows + gap rows
TOTAL_H = 2 + CONTROLS_BODY_H + 2  # tab bar + body + help lines


class EvoTUI:
    def __init__(self, evo: EVO4Controller):
        self.evo = evo
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
        self._mixer_section = 0
        self._mixer_param = len(MIXER_SECTIONS[0][3]) - 1  # default to volume
        self._mixer_state = {
            "input1": {"volume": -128.0, "pan": 0.0},
            "input2": {"volume": -128.0, "pan": 0.0},
            "main": {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0},
            "loopback": {"volume": -128.0, "pan_l": -100.0, "pan_r": 100.0},
        }
        self._sync()

    # -- state --

    def _sync(self):
        try:
            self.state = EVO4Controller.decode_status(self.evo.get_status_raw())
        except OSError as e:
            self._set_status(f"USB error: {e}", err=True)

    def _set_status(self, msg, err=False):
        self.status, self.status_err = msg, err

    def _val(self, idx=None):
        if idx is None:
            idx = self.cursor
        key, sub = ELEMENTS[idx][:2]
        return self.state[key] if sub is None else self.state[key][sub]

    def _frac(self, idx):
        """Slider fill fraction 0.0-1.0."""
        key = ELEMENTS[idx][0]
        val = self._val(idx)
        lo, hi, _ = RANGES[key]
        return max(0.0, min(1.0, (val - lo) / (hi - lo)))

    def _muted(self, idx):
        key = ELEMENTS[idx][0]
        return self.state[key].get("mute", False) if key != "monitor" else False

    def _has_mute(self, idx):
        return ELEMENTS[idx][0] != "monitor"

    def _has_phantom(self, idx):
        return ELEMENTS[idx][0].startswith("input")

    def _is_db(self, idx=None):
        if idx is None:
            idx = self.cursor
        return ELEMENTS[idx][0] != "monitor"

    def _current_unit(self):
        if self._window == "controls":
            return "dB" if self._is_db() else "%"
        param = MIXER_SECTIONS[self._mixer_section][3][self._mixer_param][0]
        return "dB" if param == "volume" else ""

    # -- controls actions --

    def _set_val(self, val):
        key, sub = ELEMENTS[self.cursor][:2]
        lo, hi, _ = RANGES[key]
        val = max(lo, min(hi, val))
        try:
            if key == "monitor":
                self.evo.set_mix(round(val))
            elif key == "output":
                self.evo.set_volume_db(val)
            else:
                self.evo.set_gain_db(key, val)
            if sub is None:
                self.state[key] = val
            else:
                self.state[key][sub] = val
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _adjust(self, delta):
        key = ELEMENTS[self.cursor][0]
        _, _, step = RANGES[key]
        self._set_val(self._val() + delta * step)

    def _toggle_mute(self):
        key = ELEMENTS[self.cursor][0]
        if key == "monitor":
            return
        try:
            self.evo.set_mute(key, not self.state[key]["mute"])
            self.state[key]["mute"] = not self.state[key]["mute"]
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _toggle_phantom(self):
        key = ELEMENTS[self.cursor][0]
        if not key.startswith("input"):
            return
        try:
            self.evo.set_phantom(key, not self.state[key]["phantom"])
            self.state[key]["phantom"] = not self.state[key]["phantom"]
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- mixer actions --

    def _mixer_val(self):
        key = MIXER_SECTIONS[self._mixer_section][0]
        param = MIXER_SECTIONS[self._mixer_section][3][self._mixer_param][0]
        return self._mixer_state[key][param]

    def _mixer_set_val(self, val):
        key, _, _, sliders = MIXER_SECTIONS[self._mixer_section]
        param, _, lo, hi, _ = sliders[self._mixer_param]
        val = max(lo, min(hi, val))
        self._mixer_state[key][param] = val
        self._apply_mixer(key)

    def _mixer_adjust(self, delta):
        _, _, _, sliders = MIXER_SECTIONS[self._mixer_section]
        _, _, _, _, step = sliders[self._mixer_param]
        self._mixer_set_val(self._mixer_val() + delta * step)

    def _apply_mixer(self, key):
        try:
            s = self._mixer_state[key]
            if key == "input1":
                self.evo.set_mixer_input(1, s["volume"], s["pan"])
            elif key == "input2":
                self.evo.set_mixer_input(2, s["volume"], s["pan"])
            elif key == "main":
                self.evo.set_mixer_output(s["volume"], s["pan_l"], s["pan_r"])
            elif key == "loopback":
                self.evo.set_mixer_loopback(s["volume"], s["pan_l"], s["pan_r"])
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # -- file picker --

    def _scan_files(self):
        d = cfg.CONFIG_DIR
        return sorted(d.glob("*.json")) if d.exists() else []

    def _enter_save_mode(self):
        self._file_list = self._scan_files()
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input = "config.json"
        self._mode = "save"

    def _enter_load_mode(self):
        self._file_list = self._scan_files()
        if not self._file_list:
            self._set_status(f"No configs in {cfg.CONFIG_DIR}", err=True)
            return
        self._file_cursor = 0
        self._file_scroll = 0
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
                        cfg.save(self.evo, cfg.CONFIG_DIR / name)
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

    def _box_top(self, scr, row, cx, label, active=False):
        if active:
            self._box_attr = curses.A_BOLD
        else:
            self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
        dashes = BOX_IW - len(label) - 3
        self._safe(scr, row, cx, "\u250c\u2500 ", self._box_attr)
        self._safe(scr, row, cx + 3, label, self._box_attr)
        self._safe(
            scr, row, cx + 3 + len(label), " " + "\u2500" * dashes + "\u2510", self._box_attr
        )

    def _box_side(self, scr, row, cx):
        self._safe(scr, row, cx, "\u2502", self._box_attr)
        self._safe(scr, row, cx + BOX_IW + 1, "\u2502", self._box_attr)

    def _box_bot(self, scr, row, cx):
        self._safe(scr, row, cx, "\u2514" + "\u2500" * BOX_IW + "\u2518", self._box_attr)

    def _box_bot_labeled(self, scr, row, cx, label):
        dashes = BOX_IW - len(label) - 3
        self._safe(
            scr,
            row,
            cx,
            "\u2514" + "\u2500" * dashes + " " + label + " \u2500\u2518",
            self._box_attr,
        )

    def _box_top_narrow(self, scr, row, cx, label, active=False):
        if active:
            self._box_attr = curses.A_BOLD
        else:
            self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
        label = label[: MIXER_SECTION_IW - 2]
        inner = MIXER_SECTION_IW - len(label) - 2
        left_d = inner // 2
        right_d = inner - left_d
        self._safe(
            scr,
            row,
            cx,
            "\u250c" + "\u2500" * left_d + " " + label + " " + "\u2500" * right_d + "\u2510",
            self._box_attr,
        )

    def _box_side_narrow(self, scr, row, cx):
        self._safe(scr, row, cx, "\u2502", self._box_attr)
        self._safe(scr, row, cx + MIXER_SECTION_IW + 1, "\u2502", self._box_attr)

    def _hslider(self, scr, row, x, frac, muted=False, sel=False, color=C_GREEN, w=SLIDER_W):
        filled = max(0, min(w, round(w * frac)))
        if muted:
            fill_attr = curses.color_pair(C_RED) | (curses.A_BOLD if sel else curses.A_DIM)
        else:
            fill_attr = curses.color_pair(color) | (curses.A_BOLD if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        if filled:
            self._safe(scr, row, x, "\u2588" * filled, fill_attr)
        if filled < w:
            self._safe(scr, row, x + filled, "\u2588" * (w - filled), empty_attr)

    def _dual_slider(self, scr, row, x, frac, sel=False, color=C_GREEN, fill_char="\u2588"):
        """Dual-side slider: fills from center outward.
        frac=0.5 -> both halves half-full; frac<0.5 -> more left; frac>0.5 -> more right."""
        half = SLIDER_W // 2
        left_fill = max(0, min(half, round((1.0 - frac) * half)))
        right_fill = half - left_fill
        fill_attr = curses.color_pair(color) | (curses.A_BOLD if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)
        self._safe(scr, row, x, "\u2588" * SLIDER_W, empty_attr)
        if left_fill > 0:
            self._safe(scr, row, x + half - left_fill, fill_char * left_fill, fill_attr)
        if right_fill > 0:
            self._safe(scr, row, x + half, fill_char * right_fill, fill_attr)
        self._safe(scr, row, x + half, "\u2502", curses.A_BOLD)

    def _narrow_pan_slider(self, scr, row, x, frac, sel=False, color=C_GREEN):
        """Narrow pan slider using half/full block precision. Width = 2*MIXER_PAN_HALF+1."""
        H = MIXER_PAN_HALF
        total_slots = H * 2
        fill_attr = curses.color_pair(color) | (curses.A_BOLD if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | (curses.A_NORMAL if sel else curses.A_DIM)

        left_slots = max(0, min(total_slots, round((1.0 - frac) * total_slots)))
        right_slots = total_slots - left_slots
        left_full = left_slots // 2
        left_partial = left_slots % 2
        right_full = right_slots // 2
        right_partial = right_slots % 2

        # Empty track (░ light shade)
        self._safe(scr, row, x, "\u2591" * H, empty_attr)
        self._safe(scr, row, x + H + 1, "\u2591" * H, empty_attr)

        # Left fill: full blocks from center (x+H-1) going left
        if left_full > 0:
            self._safe(scr, row, x + H - left_full, "\u2588" * left_full, fill_attr)
        # Partial boundary char: ▐ (right half dark = center-facing side filled)
        if left_partial:
            self._safe(scr, row, x + H - left_full - 1, "\u2590", fill_attr)

        # Right fill: full blocks from center (x+H+1) going right
        if right_full > 0:
            self._safe(scr, row, x + H + 1, "\u2588" * right_full, fill_attr)
        # Partial boundary char: ▌ (left half dark = center-facing side filled)
        if right_partial:
            self._safe(scr, row, x + H + 1 + right_full, "\u258c", fill_attr)

        # Center divider
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

    def _draw_tab_bar(self, scr, row, cx, content_w):
        ctrl_label = " CONTROLS "
        mix_label = " MIXER "
        tabs_w = len(ctrl_label) + 1 + len(mix_label)
        tab_x = cx + (content_w - tabs_w) // 2
        dim = curses.color_pair(C_WHITE) | curses.A_DIM
        if self._window == "controls":
            ctrl_attr = curses.A_REVERSE | curses.A_BOLD
            mix_attr = dim
            active_x, active_w = tab_x, len(ctrl_label)
        else:
            ctrl_attr = dim
            mix_attr = curses.A_REVERSE | curses.A_BOLD
            active_x, active_w = tab_x + len(ctrl_label) + 1, len(mix_label)
        self._safe(scr, row, tab_x, ctrl_label, ctrl_attr)
        self._safe(scr, row, tab_x + len(ctrl_label) + 1, mix_label, mix_attr)
        # Separator line - dashes across content width, gap under active tab
        self._safe(scr, row + 1, cx, "\u2500" * content_w, dim)
        self._safe(scr, row + 1, active_x, " " * active_w, dim)

    # -- section drawing (controls) --

    def _draw_section(self, scr, row, cx, idx):
        key, sub, label, color = ELEMENTS[idx]
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
        if sub is None:
            lbl_attr = curses.A_BOLD if active else curses.A_DIM
            self._safe(scr, row, cx + SLIDER_OFF, "IN", lbl_attr)
            pct = f"Mix: {val:3.0f}%"
            mid = cx + SLIDER_OFF + (SLIDER_W - len(pct)) // 2
            self._safe(scr, row, mid, pct, curses.A_BOLD if active else 0)
            self._safe(scr, row, cx + SLIDER_OFF + SLIDER_W - 3, "OUT", lbl_attr)
        else:
            vlabel = "Vol:" if key == "output" else "Gain:"
            val_str = f"{vlabel:5s} {val:+6.1f} dB"
            val_attr = curses.color_pair(C_RED) if muted else (curses.A_BOLD if active else 0)
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
        key, label, color, sliders = MIXER_SECTIONS[sec_idx]
        sel_sec = self._mixer_section == sec_idx
        pan_params = [(i, s) for i, s in enumerate(sliders) if s[0].startswith("pan")]
        vol_param_idx = next(i for i, s in enumerate(sliders) if s[0] == "volume")

        self._box_top_narrow(scr, top_row, cx, label, sel_sec)
        row = top_row + 1

        # 2 pan slots for uniform height across all sections
        for slot in range(2):
            self._box_side_narrow(scr, row, cx)
            if slot < len(pan_params):
                pidx, (param, _, lo, hi, _) = pan_params[slot]
                val = self._mixer_state[key][param]
                pan_frac = (val - lo) / (hi - lo)
                sel = sel_sec and self._mixer_param == pidx
                self._narrow_pan_slider(scr, row, cx + 1, pan_frac, sel, color)
            row += 1

            self._box_side_narrow(scr, row, cx)
            if slot < len(pan_params):
                pidx, (param, plabel, lo, hi, _) = pan_params[slot]
                val = self._mixer_state[key][param]
                sel = sel_sec and self._mixer_param == pidx
                val_str = f"{plabel:<5} {val:+5.0f}"
                self._safe(scr, row, cx + 1, val_str, curses.A_BOLD if sel else 0)
            row += 1

        # Separator
        self._safe(
            scr,
            row,
            cx,
            "\u251c" + "\u2500" * MIXER_SECTION_IW + "\u2524",
            self._box_attr,
        )
        row += 1

        # Horizontal volume slider
        vol_val = self._mixer_state[key]["volume"]
        vol_frac = max(0.0, min(1.0, (vol_val - MIXER_DB_MIN) / (MIXER_DB_MAX - MIXER_DB_MIN)))
        vol_sel = sel_sec and self._mixer_param == vol_param_idx
        self._box_side_narrow(scr, row, cx)
        self._hslider(scr, row, cx + 1, vol_frac, sel=vol_sel, color=color, w=MIXER_SECTION_IW)
        row += 1

        # Volume value row
        self._box_side_narrow(scr, row, cx)
        vol_str = f"{'Vol':<5} {vol_val:+6.1f}dB"
        self._safe(scr, row, cx + 1, vol_str, curses.A_BOLD if vol_sel else 0)
        row += 1

        # Box bottom
        self._safe(scr, row, cx, "\u2514" + "\u2500" * MIXER_SECTION_IW + "\u2518", self._box_attr)

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
        self._safe(scr, row, cx + SLIDER_OFF, f"{cfg.CONFIG_DIR}/"[: BOX_IW - 2], curses.A_DIM)
        row += 1

        self._box_side(scr, row, cx)
        row += 1

        if not self._file_list:
            self._box_side(scr, row, cx)
            self._safe(scr, row, cx + SLIDER_OFF, "(no configs found)", curses.A_DIM)
            row += 1
            for _ in range(PICKER_LIST_H - 1):
                self._box_side(scr, row, cx)
                row += 1
        else:
            visible = self._file_list[self._file_scroll : self._file_scroll + PICKER_LIST_H]
            for i, f in enumerate(visible):
                abs_i = self._file_scroll + i
                sel = abs_i == self._file_cursor
                self._box_side(scr, row, cx)
                pre = "\u25b6 " if sel else "  "
                attr = curses.color_pair(C_CYAN) | curses.A_BOLD if sel else 0
                self._safe(scr, row, cx + SLIDER_OFF, f"{pre}{f.name}"[: BOX_IW - 2], attr)
                row += 1
            for _ in range(PICKER_LIST_H - len(visible)):
                self._box_side(scr, row, cx)
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

        mixer_w = len(MIXER_SECTIONS) * (MIXER_SECTION_IW + 3) - 1
        content_w = max(BOX_IW + 2, mixer_w)
        cx = max(0, (w - content_w) // 2)
        total_h = TOTAL_H

        if h < total_h or w < content_w:
            self._safe(scr, 0, 0, f"Terminal too small ({w}x{h}, need {content_w}x{total_h})")
            return

        row = max(0, (h - total_h) // 2)
        self._draw_tab_bar(scr, row, cx, content_w)
        row += 2

        if self._window == "controls":
            row = self._draw_controls_body(scr, row, cx)
        else:
            row = self._draw_mixer_body(scr, row, cx)

        self._draw_status_bar(scr, row, cx)

    def _draw_controls_body(self, scr, row, cx):
        for idx in range(len(ELEMENTS)):
            row = self._draw_section(scr, row, cx, idx)
            if idx < len(ELEMENTS) - 1:
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
        row += 1
        return row

    def _draw_mixer_body(self, scr, row, cx):
        sec_ow = MIXER_SECTION_IW + 3  # section width + 1-space gap
        for sec_idx in range(len(MIXER_SECTIONS)):
            self._draw_mixer_section(scr, row, cx + sec_idx * sec_ow, sec_idx)
        row += CONTROLS_BODY_H  # jump to same help row as controls tab

        _, _, _, sliders = MIXER_SECTIONS[self._mixer_section]
        param = sliders[self._mixer_param][0]
        if param == "volume":
            help1 = "n/p:section  j/k:param  h/l:\xb11dB (H/L:\xb15dB)"
        else:
            help1 = "n/p:section  j/k:param  h/l:\xb15 (H/L:\xb125)"
        self._safe(scr, row, cx + 1, help1, curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1
        self._safe(scr, row, cx + 1, "Tab:controls  q:quit", curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1
        return row

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
                f"set {self.num_buf}_ {unit} (Enter=confirm  Esc=cancel)",
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

    def _controls_key(self, key):
        if key == ord("j"):
            self.cursor = (self.cursor + 1) % len(ELEMENTS)
        elif key == ord("k"):
            self.cursor = (self.cursor - 1) % len(ELEMENTS)
        elif key == ord("h"):
            self._adjust(-1)
        elif key == ord("l"):
            self._adjust(1)
        elif key == ord("H"):
            self._adjust(-5)
        elif key == ord("L"):
            self._adjust(5)
        elif key == ord("m"):
            self._toggle_mute()
        elif key == ord("P"):
            self._toggle_phantom()
        elif key == ord("s"):
            self._enter_save_mode()
        elif key == ord("o"):
            self._enter_load_mode()

    def _mixer_key(self, key):
        n = len(MIXER_SECTIONS)
        n_params = len(MIXER_SECTIONS[self._mixer_section][3])
        if key == ord("n"):
            self._mixer_section = (self._mixer_section + 1) % n
            self._mixer_param = len(MIXER_SECTIONS[self._mixer_section][3]) - 1
        elif key == ord("p"):
            self._mixer_section = (self._mixer_section - 1) % n
            self._mixer_param = len(MIXER_SECTIONS[self._mixer_section][3]) - 1
        elif key == ord("k"):
            self._mixer_param = (self._mixer_param - 1) % n_params
        elif key == ord("j"):
            self._mixer_param = (self._mixer_param + 1) % n_params
        elif key == ord("h"):
            self._mixer_adjust(-1)
        elif key == ord("l"):
            self._mixer_adjust(1)
        elif key == curses.KEY_UP:
            self._mixer_adjust(1)
        elif key == curses.KEY_DOWN:
            self._mixer_adjust(-1)
        elif key == ord("H"):
            self._mixer_adjust(-5)
        elif key == ord("L"):
            self._mixer_adjust(5)

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
    try:
        evo = EVO4Controller()
        with evo:
            curses.wrapper(EvoTUI(evo).run)
    except (OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
