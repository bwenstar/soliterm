"""soliterm.tui.app - the curses session: menu, dialogs and the play loop.

Statistics use AisleRiot's Wins/Total/Percentage/Best/Worst model.
"""

from __future__ import annotations

import curses
import time
from typing import List, Optional

from .. import APP_NAME, camo, engine, store
from ..engine import GAME_ORDER, GAMES, Solitaire
from .board import BoardUI


class _Quit(Exception):
    pass


def selected_n_for_hint(g, hint):
    # used only to highlight a hint's source run; default 1 card
    return 1


def run(stdscr, start_key: Optional[str] = None, seed: Optional[int] = None,
        color: bool = True):
    curses.curs_set(0)
    stdscr.keypad(True)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except curses.error:
        pass
    # Separate the terminal's colour CAPABILITY from the player's PREFERENCE so
    # colour can be toggled live (even if launched with --no-color). We always
    # initialise the colour pairs when the terminal supports colour; `has_color`
    # is the live "show colour" flag the renderer reads, and flips on toggle.
    color_capable = curses.has_colors()
    has_color = color_capable and bool(color)
    cfg = store.load_config()
    # a saved preference (from a previous toggle) overrides the launch default
    if "color" in cfg:
        has_color = color_capable and bool(cfg["color"])
    if color_capable:
        curses.start_color()
        curses.use_default_colors()
        # Face-up cards are drawn like real cards: a white card face with the
        # suit colour as the text - red for hearts/diamonds, true black for
        # spades/clubs - so black suits read as black, not white, on any
        # terminal background.
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_WHITE)     # red card face
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)   # black card face
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_GREEN)   # selection
        curses.init_pair(4, curses.COLOR_CYAN, -1)                    # chrome
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # cursor
        curses.init_pair(6, curses.COLOR_YELLOW, -1)                  # hint/msg
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLUE)    # card back
        curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_GREEN)   # red card, selected

    def CP(n):
        return curses.color_pair(n) if has_color else 0

    def safe_add(y, x, text, attr=0):
        h, w = stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                stdscr.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    # ---- menu ---- #
    def chooser() -> Optional[str]:
        sel = GAME_ORDER.index(cfg.get("last_game", "klondike")) \
            if cfg.get("last_game") in GAME_ORDER else 0
        extra = ["__stats__", "__quit__"]
        items = GAME_ORDER + extra
        while True:
            stdscr.erase()
            safe_add(1, 4, f"{APP_NAME}  -  choose a game", CP(4) | curses.A_BOLD)
            safe_add(2, 4, "solitaire for your terminal, AisleRiot-compatible", CP(4))
            for i, key in enumerate(GAME_ORDER):
                cls = GAMES[key]
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(4 + i, 6, f"{marker}{cls.name:<16} {cls.blurb}", attr)
            base = 4 + len(GAME_ORDER) + 1
            for j, key in enumerate(extra):
                i = len(GAME_ORDER) + j
                label = "View statistics" if key == "__stats__" else "Quit"
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(base + j, 6, f"{marker}{label}", attr)
            safe_add(base + len(extra) + 1, 6,
                     "Up/Down move - Enter select - mouse click - q quit", CP(4))
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(items)
            elif key in (ord("q"), ord("Q")):
                return None
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                idx = my - 4
                if 0 <= idx < len(GAME_ORDER):
                    sel = idx
                    if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                        return items[sel]
                else:
                    bidx = my - base
                    if 0 <= bidx < len(extra):
                        sel = len(GAME_ORDER) + bidx
                        if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                            return items[sel]
            elif key in (curses.KEY_ENTER, 10, 13):
                return items[sel]

    # ---- statistics dialog (AisleRiot fields) ---- #
    def stats_screen(focus_key: Optional[str] = None):
        stdscr.erase()
        safe_add(1, 4, "Statistics", CP(4) | curses.A_BOLD)
        safe_add(2, 4, "Wins / Total / Percentage / Best & Worst winning time", CP(4))
        if store.syncing():
            safe_add(3, 4, "(shared with GNOME AisleRiot - sol)",
                     CP(6) if has_color else 0)
        y = 4
        header = f"  {'Game':<16}{'Wins':>6}{'Total':>7}{'Win%':>7}{'Best':>8}{'Worst':>8}"
        safe_add(y, 4, header, CP(6) | curses.A_BOLD)
        y += 1
        for key in GAME_ORDER:
            s = store.get_stat(key)
            pct = store.percentage(s)
            pcts = "N/A" if pct is None else f"{pct:.0f}%"
            best = "N/A" if s["best"] == 0 else store.fmt_time(s["best"])
            worst = "N/A" if s["worst"] == 0 else store.fmt_time(s["worst"])
            attr = (CP(5) | curses.A_BOLD) if key == focus_key else 0
            safe_add(y, 4,
                     f"  {GAMES[key].name:<16}{s['wins']:>6}{s['total']:>7}"
                     f"{pcts:>7}{best:>8}{worst:>8}", attr)
            y += 1
        safe_add(y + 1, 4, "Press any key to continue.", CP(4))
        stdscr.refresh()
        stdscr.getch()

    # ---- options dialog ---- #
    def options_screen(key: str) -> dict:
        cls = GAMES[key]
        spec = cls.option_spec()
        opts = {**cls.default_options(), **store.game_options(cfg, key)}
        if not spec:
            return opts
        sel = 0
        while True:
            stdscr.erase()
            safe_add(1, 4, f"{cls.name} - options", CP(4) | curses.A_BOLD)
            for i, (okey, label, values) in enumerate(spec):
                cur = opts.get(okey, values[0])
                vals = "  ".join(f"[{v}]" if v == cur else f" {v} " for v in values)
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(3 + i, 6, f"{marker}{label:<18} {vals}", attr)
            safe_add(3 + len(spec) + 1, 6,
                     "Left/Right change - Enter/q accept (saved)", CP(4))
            stdscr.refresh()
            k = stdscr.getch()
            okey, label, values = spec[sel]
            cur = opts.get(okey, values[0])
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(spec)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(spec)
            elif k in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
                idx = values.index(cur) if cur in values else 0
                idx = (idx + (1 if k != curses.KEY_LEFT else -1)) % len(values)
                opts[okey] = values[idx]
            elif k in (curses.KEY_ENTER, 10, 13, ord("q"), ord("Q")):
                store.set_game_options(cfg, key, opts)
                store.save_config(cfg)
                return opts

    # ---- help overlay ---- #
    def help_screen():
        lines = [
            f"{APP_NAME} - controls",
            "",
            "  Arrow keys          move the cursor between slots",
            "  Enter / Space       pick up the cursor's run; press again to drop",
            "  Mouse click         click a card to pick it up; click a target",
            "                      to drop. Click a card mid-stack to split the",
            "                      pile and lift it plus the cards below it.",
            "  Mouse double-click   send a card to a foundation; deal on stock",
            "  Esc                 cancel the current selection / clear hint",
            "  d                   deal from the stock (where applicable)",
            "  a                   autoplay safe cards to the foundations",
            "  f                   send the selected/cursor card to a foundation",
            "  h                   show a hint (highlights a legal move)",
            "  b / F2              boss mode: hide the game behind 'work' output",
            "                      (any key returns; Tab cycles the disguise)",
            "  c                   code skin: keep playing inside a code file",
            "  v                   toggle colour on / off (monochrome)",
            "  x                   toggle view: full cards <-> compact cells",
            "  n  new deal   N  restart this deal   u  undo   r  redo",
            "  o  options    s  statistics   ?  help   m  menu   q  quit",
            "",
            "  Foundations build up by suit; tableau rules vary by game.",
            "  Press any key to continue.",
        ]
        stdscr.erase()
        for i, ln in enumerate(lines):
            safe_add(1 + i, 2, ln, curses.A_BOLD if i == 0 else 0)
        stdscr.refresh()
        stdscr.getch()

    # ---- camouflage / boss mode ---- #
    def camouflage_screen():
        """Hide the game behind live-scrolling fake 'work' output.

        Looks like an active build/test/log session. ANY key returns to the
        game exactly where it was left. The theme comes from the config
        ('camo_theme'); cycle it live with Tab/space while in camo mode.
        """
        theme = cfg.get("camo_theme", camo.DEFAULT_THEME)
        if theme not in camo.THEMES:
            theme = camo.DEFAULT_THEME
        gen = camo.stream(theme)
        h, w = stdscr.getmaxyx()
        buf: List[str] = []
        # Make a key wait briefly so the screen scrolls on its own, like a
        # live session, but returns instantly when the player taps a key.
        stdscr.nodelay(True)
        try:
            stdscr.erase()
            while True:
                h, w = stdscr.getmaxyx()
                # add a few new lines per tick so it visibly scrolls
                for _ in range(2):
                    buf.append(next(gen))
                if len(buf) > h:
                    buf = buf[-h:]
                stdscr.erase()
                for i, ln in enumerate(buf[-(h - 1):]):
                    # plain default colour - looks like an ordinary terminal
                    try:
                        stdscr.addnstr(i, 0, ln, w - 1)
                    except curses.error:
                        pass
                stdscr.refresh()
                # poll for a keypress while the output "runs"
                slept = 0.0
                while slept < 0.22:
                    k = stdscr.getch()
                    if k != -1:
                        if k in (ord("\t"),):
                            # cycle theme without leaving camo
                            idx = camo.THEMES.index(theme)
                            theme = camo.THEMES[(idx + 1) % len(camo.THEMES)]
                            cfg["camo_theme"] = theme
                            store.save_config(cfg)
                            gen = camo.stream(theme)
                            buf = []
                            break
                        return        # any other key exits camo mode
                    time.sleep(0.04)
                    slept += 0.04
        finally:
            stdscr.nodelay(False)

    # ---- play one game ---- #
    def play(key: str):
        nonlocal has_color           # the colour toggle ('v') flips this live
        opts = {**GAMES[key].default_options(), **store.game_options(cfg, key)}
        game = engine.new_solitaire(key, seed=seed, options=opts)
        cfg["last_game"] = key
        store.save_config(cfg)
        ui = BoardUI(stdscr, game, cfg.get("symbols", True), has_color,
                     view=cfg.get("view", "expanded"))
        ui.code_skin = bool(cfg.get("code_skin", False))

        start = time.time()
        selected: Optional[int] = None
        selected_n = 1
        selected_exact = False        # True when the player split by clicking a card
        cursor = game.ids_of("tableau")[0] if game.ids_of("tableau") else 0
        hint = None
        message = "? help  h hint  m menu. Click or use arrows + Enter."
        recorded = False

        def order_for_cursor() -> List[int]:
            return [s.sid for s in game.slots]

        def move_cursor(dr: int, dc: int):
            nonlocal cursor
            slots = game.slots
            cy, cx = ui.slot_origin.get(cursor, (ui.origin_y, 2))
            best = None
            bestcost = 1e9
            for s in slots:
                if s.sid == cursor:
                    continue
                oy, ox = ui.slot_origin.get(s.sid, (0, 0))
                dy, dx = oy - cy, ox - cx
                if dr < 0 and dy >= 0:   # want up
                    continue
                if dr > 0 and dy <= 0:
                    continue
                if dc < 0 and dx >= 0:
                    continue
                if dc > 0 and dx <= 0:
                    continue
                cost = abs(dy) * (1 if dr else 4) + abs(dx) * (1 if dc else 4)
                if cost < bestcost:
                    bestcost, best = cost, s.sid
            if best is not None:
                cursor = best

        def select_here(sid: int, card_idx: Optional[int] = None):
            """Select a run to move.

            With no card_idx (keyboard Enter / clicking the top), grab the
            largest legal run. With card_idx (clicking a specific card in a
            fanned column), split the stack: grab from that card to the bottom,
            so the player can move a sub-run just like in Spider.
            """
            nonlocal selected, selected_n, selected_exact, message
            pile = game.cards(sid)
            if card_idx is not None and 0 <= card_idx < len(pile):
                want = len(pile) - card_idx          # from clicked card down
                if game.can_pickup(sid, want):
                    selected = sid
                    selected_n = want
                    selected_exact = True
                    message = (f"picked up {want} card(s) from {pile[card_idx]}"
                               if want > 1 else "")
                    return
                # that exact split isn't movable as a unit; fall through to auto
                message = "those cards can't be lifted together"
            n = game.default_pickup(sid)
            if n <= 0:
                message = "nothing to pick up there"
                selected = None
                return
            selected = sid
            selected_n = n
            selected_exact = False
            message = ""

        def drop_on(sid: int):
            nonlocal selected, selected_exact, message, hint
            if selected is None:
                return
            ok = game.attempt_move(selected, sid, selected_n)
            if not ok and not selected_exact:
                # The default selection grabs the largest movable run, but the
                # whole run may not legally land here while a SUB-run does (e.g.
                # the pile top is 4S-3S and you drop on 4H: 4S-3S won't go, but
                # the 3S alone will). Try smaller sub-runs, largest first, and
                # use the first that lands legally.
                for n in range(selected_n - 1, 0, -1):
                    if game.attempt_move(selected, sid, n):
                        ok = True
                        break
            message = "" if ok else "illegal move"
            selected = None
            selected_exact = False
            hint = None

        def to_foundation(sid: int):
            nonlocal selected, message, hint
            if game.double_click(sid):
                message = ""
            else:
                message = "no foundation move for that card"
            selected = None
            hint = None

        def maybe_record_loss():
            # A started-but-unfinished game counts as a loss (AisleRiot does the
            # same: any game you start moving in counts in the total).
            nonlocal recorded
            if not recorded and not game.is_won() and game.moves > 0:
                store.record_result(key, False, time.time() - start)
                recorded = True

        def reset_for(new_game_fn):
            """Run a (re)deal and reset the per-game UI state."""
            nonlocal start, recorded, selected, selected_exact, hint, cursor, message
            new_game_fn()
            start = time.time()
            recorded = False
            selected = None
            selected_exact = False
            hint = None
            cursor = game.ids_of("tableau")[0] if game.ids_of("tableau") else 0

        def finish(won: bool) -> bool:
            """Record the result and show the end banner. Returns True to keep
            playing (same/new deal chosen) or False to go back to the menu."""
            nonlocal recorded, message
            if not recorded:
                store.record_result(key, won, time.time() - start)
                recorded = True
            choice = end_banner(key, game, time.time() - start, won)
            if choice == "same":
                reset_for(game.restart)
                message = "replaying the same deal"
                return True
            if choice == "new":
                reset_for(game.new_game)
                message = "new deal"
                return True
            return False        # menu

        while True:
            game.update_status()
            ui.draw(selected, selected_n, cursor, hint, time.time() - start, message)
            if game.is_won() and not recorded:
                if finish(True):
                    continue
                return
            # stuck: no productive move and the player has actually started
            if game.moves > 0 and not recorded and game.is_stuck():
                if finish(False):
                    continue
                return
            k = stdscr.getch()
            if k == curses.KEY_RESIZE:
                # terminal resized: just loop to redraw at the new size (draw()
                # reads getmaxyx() each frame and re-lays-out / guards on size)
                continue
            if k in (ord("q"), ord("Q")):
                maybe_record_loss()
                raise _Quit()
            if k in (ord("m"), ord("M")):
                maybe_record_loss()
                return
            if k == ord("?"):
                help_screen(); continue
            if k in (ord("b"), ord("B"), curses.KEY_F2):
                # boss / camouflage mode: hide the game behind fake work output
                camouflage_screen()
                message = ""
                continue
            if k in (ord("c"), ord("C")):
                # code skin: keep playing with the board wrapped in source
                ui.code_skin = not ui.code_skin
                cfg["code_skin"] = ui.code_skin
                store.save_config(cfg)
                message = ("code skin on" if ui.code_skin else "code skin off")
                continue
            if k in (ord("v"), ord("V")):
                # toggle colour on/off live (persisted as the new default)
                if not color_capable:
                    message = "this terminal has no colour support"
                else:
                    has_color = not has_color
                    ui.has_color = has_color
                    cfg["color"] = has_color
                    store.save_config(cfg)
                    message = ("colour on" if has_color else "colour off "
                               "(monochrome)")
                continue
            if k in (ord("x"), ord("X")):
                # toggle the board view: expanded card boxes <-> legacy cells
                new_view = "legacy" if ui.view == "expanded" else "expanded"
                ui.set_view(new_view)
                cfg["view"] = new_view
                store.save_config(cfg)
                message = (f"{new_view} view"
                           + (" (compact)" if new_view == "legacy"
                              else " (full cards)"))
                continue
            if k == 27:
                selected = None; hint = None; message = ""; continue
            if k in (curses.KEY_UP, ord("k")):
                hint = None; move_cursor(-1, 0); continue
            if k in (curses.KEY_DOWN, ord("j")):
                hint = None; move_cursor(1, 0); continue
            if k == curses.KEY_LEFT:
                hint = None; move_cursor(0, -1); continue
            if k in (curses.KEY_RIGHT, ord("l")):
                hint = None; move_cursor(0, 1); continue
            if k in (ord("h"), ord("H")):
                hint = game.hint()
                if hint is None:
                    message = game.no_hint_reason()
                else:
                    hsrc, hdst, desc = hint
                    # move the cursor to the suggested source for convenience
                    cursor = hsrc
                    message = f"Hint: {desc}"
                continue
            if k in (curses.KEY_ENTER, 10, 13, ord(" ")):
                hint = None
                if selected is None:
                    if game.kind(cursor) == "stock":
                        if not game.click(cursor):
                            message = game.deal_blocked_reason()
                    else:
                        select_here(cursor)
                else:
                    if cursor == selected:
                        selected = None
                    else:
                        drop_on(cursor)
                continue
            if k in (ord("d"), ord("D")):
                hint = None
                if not game.deal():
                    message = game.deal_blocked_reason()
                selected = None; continue
            if k in (ord("a"), ord("A")):
                hint = None
                n = game.autoplay()
                message = f"autoplayed {n}" if n else "nothing to autoplay"
                selected = None; continue
            if k in (ord("f"), ord("F")):
                to_foundation(selected if selected is not None else cursor)
                continue
            if k in (ord("u"), ord("U")):
                message = "" if game.undo() else "nothing to undo"
                selected = None; hint = None; continue
            if k in (ord("r"), ord("R")):
                message = "" if game.redo() else "nothing to redo"
                selected = None; hint = None; continue
            if k == ord("n"):
                # new deal: an abandoned game counts as a loss first
                maybe_record_loss()
                reset_for(game.new_game)
                message = "new deal"
                continue
            if k in (ord("N"),):
                # restart THIS deal (replay the same shuffle); no loss recorded
                # since it's the same hand continuing
                reset_for(game.restart)
                message = "restarted this deal"
                continue
            if k in (ord("o"), ord("O")):
                maybe_record_loss()
                newopts = options_screen(key)
                game = engine.new_solitaire(key, seed=seed, options=newopts)
                ui = BoardUI(stdscr, game, cfg.get("symbols", True), has_color,
                             view=cfg.get("view", "expanded"))
                ui.code_skin = bool(cfg.get("code_skin", False))
                reset_for(lambda: None)   # game already dealt by new_solitaire
                message = "options applied"; continue
            if k in (ord("s"), ord("S")):
                stats_screen(key); continue
            if k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                target = ui.hit_test(my, mx)
                if target is None:
                    continue
                tsid, tidx = target
                cursor = tsid
                hint = None
                dbl = bstate & curses.BUTTON1_DOUBLE_CLICKED
                clicked = bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED |
                                    curses.BUTTON1_RELEASED)
                if dbl:
                    # double-clicking the stock is the natural "just deal"
                    # gesture; elsewhere it sends the card to a foundation
                    if game.kind(tsid) == "stock":
                        if not game.click(tsid):
                            message = game.deal_blocked_reason()
                    else:
                        to_foundation(tsid)
                elif clicked:
                    if selected is None:
                        if game.kind(tsid) == "stock":
                            if not game.click(tsid):
                                message = game.deal_blocked_reason()
                        else:
                            # split the stack at the exact card the user clicked
                            select_here(tsid, tidx)
                    else:
                        if tsid == selected:
                            selected = None
                            selected_exact = False
                        else:
                            drop_on(tsid)
                continue

    def end_banner(key: str, game: Solitaire, elapsed: float, won: bool) -> str:
        """Show the end-of-game banner with choices. Returns one of:
        'same' (replay this deal), 'new' (fresh deal), 'menu'."""
        s = store.get_stat(key)
        pct = store.percentage(s)
        choices = [("same", "Replay this deal"),
                   ("new", "New deal"),
                   ("menu", "Back to menu")]
        sel = 0
        while True:
            stdscr.erase()
            if won:
                safe_add(2, 6, "*** YOU WIN! ***", CP(6) | curses.A_BOLD)
            else:
                safe_add(2, 6, "No moves left - game over.",
                         CP(6) | curses.A_BOLD)
            safe_add(4, 6, f"Game        : {game.gamedef.name}")
            safe_add(5, 6, f"Time        : {store.fmt_time(elapsed)}")
            safe_add(6, 6, f"Score       : {game.score}")
            safe_add(7, 6, f"Moves       : {game.moves}")
            pcts = "N/A" if pct is None else f"{pct:.0f}%"
            safe_add(9, 6, f"Wins/Total  : {s['wins']}/{s['total']}  ({pcts})")
            if s["best"]:
                safe_add(10, 6, f"Best time   : {store.fmt_time(s['best'])}")
            for i, (_, label) in enumerate(choices):
                marker = "> " if i == sel else "  "
                attr = (CP(5) | curses.A_BOLD) if i == sel else 0
                safe_add(12 + i, 6, f"{marker}{label}", attr)
            safe_add(12 + len(choices) + 1, 6,
                     "Up/Down + Enter, or s/n/m. Click to choose.", CP(4))
            stdscr.refresh()
            k = stdscr.getch()
            if k in (curses.KEY_UP, ord("k")):
                sel = (sel - 1) % len(choices)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = (sel + 1) % len(choices)
            elif k in (ord("s"), ord("S")):
                return "same"
            elif k in (ord("n"), ord("N")):
                return "new"
            elif k in (ord("m"), ord("M"), ord("q"), ord("Q")):
                return "menu"
            elif k in (curses.KEY_ENTER, 10, 13, ord(" ")):
                return choices[sel][0]
            elif k == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                row = my - 12
                if 0 <= row < len(choices):
                    return choices[row][0]

    # ---- top loop ---- #
    try:
        if start_key:
            play(start_key)
        while True:
            choice = chooser()
            if choice is None or choice == "__quit__":
                return 0
            if choice == "__stats__":
                stats_screen()
                continue
            play(choice)
    except _Quit:
        return 0


def main(start_key: Optional[str] = None, seed: Optional[int] = None,
         color: bool = True) -> int:
    try:
        return curses.wrapper(run, start_key, seed, color)
    except curses.error as exc:
        import sys
        print(f"curses error: {exc}", file=sys.stderr)
        return 1

