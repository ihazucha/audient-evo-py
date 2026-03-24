"""Curses TUI for Audient EVO4 - horizontal section layout."""

import curses
import sys

from evo4.controller import EVO4Controller
from evo4 import config as cfg

C_GREEN, C_RED, C_CYAN, C_YELLOW, C_WHITE, C_BLUE = range(1, 7)

SLIDER_W = 50
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


class EvoTUI:
    def __init__(self, evo: EVO4Controller):
        self.evo = evo
        self.cursor = 0
        self.status = ""
        self.status_err = False
        self.num_buf = ""
        self._mode = "normal"
        self._file_list = []
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input = ""
        self._slider_map = []
        self._box_attr = 0
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

    # -- actions --

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

    def _hslider(self, scr, row, x, frac, muted=False, sel=False, color=C_GREEN):
        filled = max(0, min(SLIDER_W, round(SLIDER_W * frac)))
        if muted:
            fill_attr = curses.color_pair(C_RED) | (curses.A_BOLD if sel else curses.A_DIM)
        else:
            fill_attr = curses.color_pair(color) | (curses.A_BOLD if sel else curses.A_DIM)
        empty_attr = curses.color_pair(C_WHITE) | curses.A_DIM
        if filled:
            self._safe(scr, row, x, "\u2588" * filled, fill_attr)
        if filled < SLIDER_W:
            self._safe(scr, row, x + filled, "\u2588" * (SLIDER_W - filled), empty_attr)

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

    # -- section drawing --

    def _draw_section(self, scr, row, cx, idx):
        key, sub, label, color = ELEMENTS[idx]
        active = self.cursor == idx
        val = self._val(idx)
        frac = self._frac(idx)
        muted = self._muted(idx)

        self._box_top(scr, row, cx, label, active)
        row += 1

        self._box_side(scr, row, cx)
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

        MIN_H, MIN_W = 21, BOX_IW + 4
        if h < MIN_H or w < MIN_W:
            self._safe(scr, 0, 0, f"Terminal too small ({w}x{h}, need {MIN_W}x{MIN_H})")
            return

        cx = (w - (BOX_IW + 2)) // 2
        row = max(0, (h - MIN_H) // 2)

        for idx in range(len(ELEMENTS)):
            row = self._draw_section(scr, row, cx, idx)
            if idx < len(ELEMENTS) - 1:
                row += 1

        unit = "dB" if self._is_db() else "%"
        help1 = f"j/k:move  h/l:\xb11{unit} (H/L\xb15{unit})"
        if self._has_mute(self.cursor):
            help1 += "  m:mute"
        if self._has_phantom(self.cursor):
            help1 += "  p:48V"
        self._safe(scr, row, cx + 1, help1, curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1

        self._safe(
            scr,
            row,
            cx + 1,
            "s:save  o:load  r:refresh  q:quit",
            curses.color_pair(C_WHITE) | curses.A_DIM,
        )
        row += 1

        if self.status or self.num_buf:
            self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
            self._safe(scr, row, cx, "\u250c" + "\u2500" * BOX_IW + "\u2510", self._box_attr)
            row += 1
            self._box_side(scr, row, cx)
            if self.num_buf:
                unit = "dB" if self._is_db() else "%"
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

        while True:
            self._draw(scr)
            scr.refresh()
            key = scr.getch()

            if self._mode in ("save", "load"):
                self._picker_key(key)
                continue

            if key == ord("q"):
                break
            elif key == ord("j"):
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
            elif key == ord("p"):
                self._toggle_phantom()
            elif key == 10:  # Enter
                if self.num_buf:
                    try:
                        self._set_val(float(self.num_buf))
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
            elif key == ord("r"):
                self._sync()
                self._set_status("Refreshed")
            elif key == ord("s"):
                self._enter_save_mode()
            elif key == ord("o"):
                self._enter_load_mode()
            elif key == curses.KEY_RESIZE:
                scr.clear()


def main():
    try:
        evo = EVO4Controller()
        with evo:
            curses.wrapper(EvoTUI(evo).run)
    except (OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
