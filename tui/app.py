"""Curses TUI for Audient EVO4 — horizontal section layout."""

import curses
import sys

from evo4.controller import EVO4Controller
from evo4 import config as cfg

C_GREEN  = 1
C_RED    = 2
C_CYAN   = 3
C_YELLOW = 4
C_WHITE  = 5
C_BLUE   = 6

# Focusable elements — sliders only; m/p toggle mute/phantom on focused slider
ELEMENTS = [
    ("mix",    None),   # 0 — MONITOR
    ("volume", None),   # 1 — OUTPUT
    ("gain",   1),      # 2 — INPUT 1
    ("gain",   2),      # 3 — INPUT 2
]

SECTION_STARTS = [0, 1, 2, 3]
SECTION_ENDS   = [1, 2, 3, 4]

# SLIDER_W: 100 segments, one per percent.
# Each segment is a ▌ (left half block) — the natural right-side gap gives visual separation.
# BOX_IW: inner width; content is inset 1 space each side, so SLIDER_W = BOX_IW - 2.
SLIDER_W      = 100
BOX_IW        = SLIDER_W + 2   # = 102
SLIDER_OFF    = 2               # content x-offset inside the box (1-space left margin)

PICKER_LIST_H = 6    # max visible files in picker dialog

_MUTE_FOR    = {1: "output", 2: "input1", 3: "input2"}
_PHANTOM_FOR = {2: "input1", 3: "input2"}


class EvoTUI:
    def __init__(self, evo):
        self.evo        = evo
        self.cursor     = 0
        self.status     = ""
        self.status_err = False
        self.num_buf    = ""
        # file-picker state
        self._mode        = "normal"   # "normal" | "save" | "load"
        self._file_list   = []
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input  = ""
        self.state = {
            "volume":  [(0, 0, -96.0), (0, 0, -96.0)],
            "gain":    [(0, 0, -8.0),  (0, 0, -8.0)],
            "mix":     0,
            "mute":    {"input1": False, "input2": False, "output": False},
            "phantom": {"input1": False, "input2": False},
        }
        self._slider_map = []   # (row, x, width_chars, elem_idx)
        self._box_attr   = 0    # updated per section in _box_top
        self._refresh()

    # ── status ────────────────────────────────────────────────────

    def _set_status(self, msg, err=False):
        self.status     = msg
        self.status_err = err

    # ── state ────────────────────────────────────────────────────

    def _refresh(self):
        try:
            self.state = {
                "volume":  self.evo.get_volume_debug(),
                "gain":    self.evo.get_gain_debug(),
                "mix":     self.evo.get_mix(),
                "mute":    {t: self.evo.get_mute(t)
                            for t in ("input1", "input2", "output")},
                "phantom": {t: self.evo.get_phantom(t)
                            for t in ("input1", "input2")},
            }
        except OSError as e:
            self._set_status(f"USB error: {e}", err=True)

    def _val(self, idx):
        etype, target = ELEMENTS[idx]
        if etype == "volume":
            pct, _, db = self.state["volume"][0]
            return pct, db
        if etype == "gain":
            pct, _, db = self.state["gain"][target - 1]
            return pct, db
        return self.state["mix"], None

    # ── navigation ───────────────────────────────────────────────

    def _step(self, delta):
        self.cursor = (self.cursor + delta) % len(ELEMENTS)

    # ── value changes ─────────────────────────────────────────────

    def _adjust(self, delta):
        etype, target = ELEMENTS[self.cursor]
        val, _ = self._val(self.cursor)
        new = max(0, min(100, val + delta))
        try:
            if etype == "volume":
                self.evo.set_volume(new)
            elif etype == "gain":
                self.evo.set_gain(new, channel=target)
            else:
                self.evo.set_mix(new)
            self._refresh()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _do_mute(self):
        if self.cursor not in _MUTE_FOR:
            return
        target = _MUTE_FOR[self.cursor]
        try:
            self.evo.set_mute(target, not self.state["mute"][target])
            self._refresh()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _do_phantom(self):
        if self.cursor not in _PHANTOM_FOR:
            return
        target = _PHANTOM_FOR[self.cursor]
        try:
            self.evo.set_phantom(target, not self.state["phantom"][target])
            self._refresh()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    def _set_value(self, val):
        etype, target = ELEMENTS[self.cursor]
        val = max(0, min(100, val))
        try:
            if etype == "volume":
                self.evo.set_volume(val)
            elif etype == "gain":
                self.evo.set_gain(val, channel=target)
            else:
                self.evo.set_mix(val)
            self._refresh()
        except OSError as e:
            self._set_status(f"Error: {e}", err=True)

    # ── file picker ───────────────────────────────────────────────

    def _scan_files(self):
        d = cfg.CONFIG_DIR
        if d.exists():
            return sorted(d.glob("*.json"))
        return []

    def _enter_save_mode(self):
        self._file_list   = self._scan_files()
        self._file_cursor = 0
        self._file_scroll = 0
        self._file_input  = "config.json"
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
        if key == 27:   # Esc
            self._mode = "normal"
            return

        if self._mode == "load":
            if key in (curses.KEY_UP, ord('k')):
                self._picker_move(-1)
            elif key in (curses.KEY_DOWN, ord('j')):
                self._picker_move(1)
            elif key == 10 and self._file_list:   # Enter
                path = self._file_list[self._file_cursor]
                try:
                    cfg.load_and_apply(self.evo, path)
                    self._refresh()
                    self._set_status(f"Loaded \u2190 {path.name}")
                except Exception as e:
                    self._set_status(f"Load error: {e}", err=True)
                self._mode = "normal"

        else:   # save — only arrow keys navigate; all printable chars go to input
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
            elif key == 10:   # Enter — confirm save
                name = self._file_input.strip()
                if name:
                    if not name.endswith(".json"):
                        name += ".json"
                    path = cfg.CONFIG_DIR / name
                    try:
                        cfg.save(self.evo, path)
                        self._set_status(f"Saved \u2192 {name}")
                    except Exception as e:
                        self._set_status(f"Save error: {e}", err=True)
                self._mode = "normal"

    # ── drawing helpers ───────────────────────────────────────────

    def _safe(self, scr, row, col, text, *args):
        try:
            h, w = scr.getmaxyx()
            if row < 0 or row >= h or col >= w - 1:
                return
            scr.addnstr(row, col, text, w - col - 1, *args)
        except curses.error:
            pass

    def _box_top(self, scr, row, cx, label, active=False):
        """Draw top border; set self._box_attr for subsequent side/bot calls."""
        if active:
            self._box_attr = curses.A_BOLD
            lbl_attr       = curses.A_BOLD
        else:
            self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
            lbl_attr       = self._box_attr
        dashes = BOX_IW - len(label) - 3
        self._safe(scr, row, cx,                   "┌─ ",                   self._box_attr)
        self._safe(scr, row, cx + 3,               label,                   lbl_attr)
        self._safe(scr, row, cx + 3 + len(label),  " " + "─" * dashes + "┐", self._box_attr)

    def _box_top_plain(self, scr, row, cx):
        """Draw unlabelled top border using current self._box_attr."""
        self._safe(scr, row, cx, "┌" + "─" * BOX_IW + "┐", self._box_attr)

    def _box_side(self, scr, row, cx):
        self._safe(scr, row, cx,              "│", self._box_attr)
        self._safe(scr, row, cx + BOX_IW + 1, "│", self._box_attr)

    def _box_bot(self, scr, row, cx):
        self._safe(scr, row, cx, "└" + "─" * BOX_IW + "┘", self._box_attr)

    def _box_bot_labeled(self, scr, row, cx, label):
        """Bottom border with label in the bottom-right corner."""
        # └ + dashes + " " + label + " ─┘"
        # total = 1 + dashes + 1 + len + 3 = BOX_IW + 2
        dashes = BOX_IW - len(label) - 3
        self._safe(scr, row, cx,
                   "└" + "─" * dashes + " " + label + " ─┘",
                   self._box_attr)

    def _hslider(self, scr, row, x, pct, muted=False, sel=False, color=C_GREEN):
        """100-segment slider: each char is ▌ (filled) or ░ (empty).
        ▌ fills only the left half of a cell, so adjacent segments are visually separated."""
        filled = max(0, min(SLIDER_W, round(SLIDER_W * pct / 100)))
        if muted:
            filled_attr = curses.color_pair(C_RED) | (curses.A_BOLD if sel else curses.A_DIM)
        else:
            filled_attr = curses.color_pair(color) | (curses.A_BOLD if sel else curses.A_DIM)
        if filled:
            self._safe(scr, row, x, '▌' * filled, filled_attr)
        if filled < SLIDER_W:
            self._safe(scr, row, x + filled, '▌' * (SLIDER_W - filled),
                       curses.color_pair(C_WHITE) | curses.A_DIM)

    def _mute_ind(self, scr, row, x, target):
        if self.state["mute"][target]:
            self._safe(scr, row, x, "[M]", curses.A_BOLD | curses.color_pair(C_RED))
        else:
            self._safe(scr, row, x, "[m]", curses.A_DIM)

    def _phantom_ind(self, scr, row, x, target):
        if self.state["phantom"][target]:
            self._safe(scr, row, x, "[48V]", curses.A_BOLD | curses.color_pair(C_YELLOW))
        else:
            self._safe(scr, row, x, "[48v]", curses.A_DIM)

    # ── section drawers ───────────────────────────────────────────
    # Each section: top border + slider + info + bottom = 4 rows.
    # Content x = cx + SLIDER_OFF (= cx+2, 1-space left margin).
    # Right-aligned indicators end 1 space before right border (at cx+BOX_IW).
    #   [M]      (3 chars): starts at cx + BOX_IW - 3
    #   [48v][M] (9 chars): starts at cx + BOX_IW - 9, mute at cx + BOX_IW - 3

    def _draw_monitor_section(self, scr, row, cx):
        active = (self.cursor == 0)
        self._box_top(scr, row, cx, "MONITOR", active); row += 1
        pct, _ = self._val(0)
        self._box_side(scr, row, cx)
        self._hslider(scr, row, cx + SLIDER_OFF, pct, sel=active, color=C_CYAN)
        self._slider_map.append((row, cx + SLIDER_OFF, SLIDER_W, 0))
        row += 1
        self._box_side(scr, row, cx)
        self._safe(scr, row, cx + SLIDER_OFF, f"Mix:  {pct:3d}%",
                   curses.A_BOLD if active else 0)
        row += 1
        self._box_bot(scr, row, cx); row += 1
        return row

    def _draw_output_section(self, scr, row, cx):
        active = (self.cursor == 1)
        self._box_top(scr, row, cx, "OUTPUT", active); row += 1
        pct, db = self._val(1)
        muted   = self.state["mute"]["output"]
        self._box_side(scr, row, cx)
        self._hslider(scr, row, cx + SLIDER_OFF, pct, muted, active)
        self._slider_map.append((row, cx + SLIDER_OFF, SLIDER_W, 1))
        row += 1
        self._box_side(scr, row, cx)
        val_str  = f"Vol:  {pct:3d}%  {db:+5.1f}dB"
        val_attr = curses.color_pair(C_RED) if muted else (curses.A_BOLD if active else 0)
        self._safe(scr, row, cx + SLIDER_OFF, val_str, val_attr)
        self._mute_ind(scr, row, cx + BOX_IW - 3, "output")
        row += 1
        self._box_bot(scr, row, cx); row += 1
        return row

    def _draw_input_section(self, scr, row, cx, ch):
        ei     = 2 + ch
        active = (self.cursor == ei)
        self._box_top(scr, row, cx, f"INPUT {ch + 1}", active); row += 1
        pct, db = self._val(ei)
        muted   = self.state["mute"][f"input{ch + 1}"]
        self._box_side(scr, row, cx)
        self._hslider(scr, row, cx + SLIDER_OFF, pct, muted, active, color=C_BLUE)
        self._slider_map.append((row, cx + SLIDER_OFF, SLIDER_W, ei))
        row += 1
        self._box_side(scr, row, cx)
        val_str  = f"Gain: {pct:3d}%  {db:+5.1f}dB"
        val_attr = curses.color_pair(C_RED) if muted else (curses.A_BOLD if active else 0)
        self._safe(scr, row, cx + SLIDER_OFF, val_str, val_attr)
        self._phantom_ind(scr, row, cx + BOX_IW - 9, f"input{ch + 1}")
        self._mute_ind(   scr, row, cx + BOX_IW - 3, f"input{ch + 1}")
        row += 1
        self._box_bot(scr, row, cx); row += 1
        return row

    # ── file picker dialog ────────────────────────────────────────

    def _draw_file_picker(self, scr):
        scr.erase()
        h, w  = scr.getmaxyx()
        cx    = (w - (BOX_IW + 2)) // 2
        title = "SAVE CONFIG" if self._mode == "save" else "LOAD CONFIG"
        # fixed height: top + dir + blank + PICKER_LIST_H + blank + [input] + help + bottom
        total_h = PICKER_LIST_H + 7 + (1 if self._mode == "save" else 0)
        row     = max(0, (h - total_h) // 2)

        self._box_attr = curses.color_pair(C_CYAN) | curses.A_BOLD
        dashes = BOX_IW - len(title) - 3
        self._safe(scr, row, cx,                   "┌─ ",                   self._box_attr)
        self._safe(scr, row, cx + 3,               title,                   self._box_attr)
        self._safe(scr, row, cx + 3 + len(title),  " " + "─" * dashes + "┐", self._box_attr)
        row += 1

        self._box_side(scr, row, cx)
        self._safe(scr, row, cx + SLIDER_OFF, f"{cfg.CONFIG_DIR}/"[:BOX_IW - 2], curses.A_DIM)
        row += 1

        self._box_side(scr, row, cx); row += 1

        if not self._file_list:
            self._box_side(scr, row, cx)
            self._safe(scr, row, cx + SLIDER_OFF, "(no configs found)", curses.A_DIM)
            row += 1
            for _ in range(PICKER_LIST_H - 1):
                self._box_side(scr, row, cx); row += 1
        else:
            visible = self._file_list[self._file_scroll:self._file_scroll + PICKER_LIST_H]
            for i, f in enumerate(visible):
                abs_i = self._file_scroll + i
                sel   = (abs_i == self._file_cursor)
                self._box_side(scr, row, cx)
                pre  = "\u25b6 " if sel else "  "
                attr = curses.color_pair(C_CYAN) | curses.A_BOLD if sel else 0
                self._safe(scr, row, cx + SLIDER_OFF, f"{pre}{f.name}"[:BOX_IW - 2], attr)
                row += 1
            for _ in range(PICKER_LIST_H - len(visible)):
                self._box_side(scr, row, cx); row += 1

        self._box_side(scr, row, cx); row += 1

        if self._mode == "save":
            self._box_side(scr, row, cx)
            inp = f"File: {self._file_input}_"
            self._safe(scr, row, cx + SLIDER_OFF, inp[:BOX_IW - 2], curses.A_BOLD)
            row += 1

        self._box_side(scr, row, cx)
        hint = " \u2191/\u2193:select  Enter:save  Esc:cancel" if self._mode == "save" \
               else " \u2191/\u2193:select  Enter:load  Esc:cancel"
        self._safe(scr, row, cx + SLIDER_OFF, hint[1:], curses.A_DIM)
        row += 1

        self._safe(scr, row, cx, "└" + "─" * BOX_IW + "┘", self._box_attr)

    # ── main draw ─────────────────────────────────────────────────

    def _draw(self, scr):
        if self._mode in ("save", "load"):
            self._draw_file_picker(scr)
            return

        scr.erase()
        h, w = scr.getmaxyx()
        self._slider_map = []

        # 4 sections × 4 rows + 3 gaps + 2 help rows = 21
        MIN_H = 21
        MIN_W = BOX_IW + 4
        if h < MIN_H or w < MIN_W:
            self._safe(scr, 0, 0,
                       f"Terminal too small ({w}x{h}, need {MIN_W}x{MIN_H})")
            return

        cx  = (w - (BOX_IW + 2)) // 2
        row = max(0, (h - MIN_H) // 2)

        row = self._draw_monitor_section(scr, row, cx); row += 1
        row = self._draw_output_section(scr, row, cx);  row += 1
        row = self._draw_input_section(scr, row, cx, 0); row += 1
        row = self._draw_input_section(scr, row, cx, 1)

        # Help row 1 — contextual m/p hints
        help1 = "j/k:move  h/l:\xb11 (^\xb15)"
        if self.cursor in _MUTE_FOR:
            help1 += "  m:mute"
        if self.cursor in _PHANTOM_FOR:
            help1 += "  p:48V"
        self._safe(scr, row, cx + 1, help1, curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1

        # Help row 2
        self._safe(scr, row, cx + 1,
                   "s:save  o:load  r:refresh  q:quit",
                   curses.color_pair(C_WHITE) | curses.A_DIM)
        row += 1

        # Status box — only shown when there is content; label in bottom-right
        if self.status or self.num_buf:
            self._box_attr = curses.color_pair(C_WHITE) | curses.A_DIM
            self._box_top_plain(scr, row, cx); row += 1
            self._box_side(scr, row, cx)
            if self.num_buf:
                self._safe(scr, row, cx + SLIDER_OFF,
                           f"set {self.num_buf}_ (Enter=confirm  Esc=cancel)",
                           curses.color_pair(C_YELLOW))
            else:
                attr = (curses.color_pair(C_RED) | curses.A_BOLD
                        if self.status_err else curses.color_pair(C_YELLOW))
                self._safe(scr, row, cx + SLIDER_OFF, self.status, attr)
            row += 1
            self._box_bot_labeled(scr, row, cx, "STATUS")

    # ── event loop ────────────────────────────────────────────────

    def run(self, scr):
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(C_GREEN,  curses.COLOR_GREEN,  -1)
        curses.init_pair(C_RED,    curses.COLOR_RED,    -1)
        curses.init_pair(C_CYAN,   curses.COLOR_CYAN,   -1)
        curses.init_pair(C_YELLOW, curses.COLOR_YELLOW, -1)
        curses.init_pair(C_WHITE,  curses.COLOR_WHITE,  -1)
        curses.init_pair(C_BLUE,   curses.COLOR_BLUE,   -1)
        curses.set_escdelay(25)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)

        while True:
            self._draw(scr)
            scr.refresh()
            key = scr.getch()

            # Picker mode — delegate all input
            if self._mode in ("save", "load"):
                self._picker_key(key)
                continue

            # Normal mode
            if key == ord('q'):
                break

            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                    if bstate & curses.BUTTON1_CLICKED:
                        for (sr, sx, sw, ei) in self._slider_map:
                            if my == sr and sx <= mx < sx + sw:
                                pct = max(0, min(100, round((mx - sx) * 100 / sw)))
                                self.cursor = ei
                                self._set_value(pct)
                                break
                except curses.error:
                    pass

            elif key == ord('j'):
                self._step(1)
            elif key == ord('k'):
                self._step(-1)

            elif key == ord('h'):
                self._adjust(-1)
            elif key == ord('l'):
                self._adjust(1)
            elif key == ord('H'):
                self._adjust(-5)
            elif key == ord('L'):
                self._adjust(5)

            elif key == ord('m'):
                self._do_mute()
            elif key == ord('p'):
                self._do_phantom()

            elif key == 10:   # Enter
                if self.num_buf:
                    try:
                        self._set_value(int(self.num_buf))
                    except ValueError:
                        pass
                    self.num_buf = ""
            elif key == 27:   # Esc
                self.num_buf = ""
            elif 48 <= key <= 57:   # 0-9
                if len(self.num_buf) < 3:
                    self.num_buf += chr(key)

            elif key == ord('r'):
                self._refresh()
                self._set_status("Refreshed")
            elif key == ord('s'):
                self._enter_save_mode()
            elif key == ord('o'):
                self._enter_load_mode()

            elif key == curses.KEY_RESIZE:
                scr.clear()


def run_tui(evo):
    """Launch TUI with an existing controller (used from evoctl.py)."""
    with evo:
        tui = EvoTUI(evo)
        curses.wrapper(tui.run)


def main():
    """Standalone entry point."""
    try:
        evo = EVO4Controller()
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        run_tui(evo)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
