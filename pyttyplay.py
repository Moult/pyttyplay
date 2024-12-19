import re
import os
import sys
import tty
import time
import pyte
import shutil
import tempfile
import datetime
import argparse
from math import ceil

# Use msvcrt on Windows
# https://stackoverflow.com/questions/2408560/non-blocking-console-input


DEC_SPECIAL_GRAPHICS = {
    "_": " ",
    "`": "◆",
    "a": "▒",
    "b": "\t",
    "c": "\f",
    "d": "\r",
    "e": "\n",
    "f": "°",
    "g": "±",
    "h": "\025",
    "i": "\v",
    "j": "┘",
    "k": "┐",
    "l": "┌",
    "m": "└",
    "n": "┼",
    "o": "⎺",
    "p": "⎻",
    "q": "─",
    "r": "⎼",
    "s": "⎽",
    "t": "├",
    "u": "┤",
    "v": "┴",
    "w": "┬",
    "x": "│",
    "y": "≤",
    "z": "≥",
    "{": "π",
    "|": "≠",
    "}": "£",
    "~": "·",
}

E_REPEAT = re.compile("([0-9]*?)b")
E_SCROLL_REGION = re.compile("([0-9]+);([0-9]+)r")
E_SCROLL_UP = re.compile("([0-9]*)S")
E_SCROLL_DOWN = re.compile("([0-9]*)T")
E_SET_COLOUR = re.compile("([0-9]+);rgb:(.{8})")


class CustomStream(pyte.Stream):
    def __init__(self, screen):
        super().__init__(screen)
        self.dec_mode = False
        self.scroll_region = [1, screen.lines]
        self.previous_char = ""

    def feed(self, data):
        i = 0
        total_data = len(data)
        while i < total_data:
            if data[i : i + 3] == "\x1b(0":
                self.dec_mode = True
                i += 3
            elif data[i : i + 3] == "\x1b(B":
                self.dec_mode = False
                i += 3
            elif data[i : i + 2] == "\x1b[" and (match := E_REPEAT.match(data[i + 2 : i + 6])):
                # pyte doesn't handle repeat sequences https://github.com/selectel/pyte/issues/184
                length = match[1]
                for j in range(int(length)):
                    super().feed(self.previous_char)
                i += len(length) + 3
            elif self.dec_mode and self._taking_plain_text and (dec_char := DEC_SPECIAL_GRAPHICS.get(data[i])):
                # pyte doesn't support DEC graphics https://github.com/selectel/pyte/issues/182
                self.previous_char = dec_char
                super().feed(dec_char)
                i += 1
            elif data[i : i + 2] == "\x1b[" and (match := E_SCROLL_REGION.match(data[i + 2 : i + 10])):
                # pyte doesn't support scroll up / down https://github.com/selectel/pyte/issues/186
                self.listener.set_margins(*tuple(int(x) for x in match.groups()))
                self.scroll_region = tuple(int(x) for x in match.groups())
                i += len(match[0]) + 2
            elif data[i : i + 2] == "\x1b[" and (match := E_SCROLL_UP.match(data[i + 2 : i + 6])):
                self.scroll_up(int(match[1] or 1))
                i += len(match[0]) + 2
            elif data[i : i + 2] == "\x1b[" and (match := E_SCROLL_DOWN.match(data[i + 2 : i + 6])):
                self.scroll_down(int(match[1] or 1))
                i += len(match[0]) + 2
            elif data[i : i + 3] == "\x1b[r":
                self.listener.set_margins(None, None)
                self.scroll_region = [1, self.listener.lines]
                i += 3
            elif data[i : i + 4] == "\x1b]4;" and (match := E_SET_COLOUR.match(data[i + 4 : i + 20])):
                # pyte doesn't handle colour pallettes https://github.com/selectel/pyte/issues/50
                # TODO: handle resetting pallette.
                index = int(match[1])
                color = match[2].replace("/", "").lower()
                if index > 15:
                    pyte.graphics.FG_BG_256[index] = color
                elif index > 7:  # Bright colors
                    pyte.graphics.FG_AIXTERM[index + 82] = color
                    pyte.graphics.BG_AIXTERM[index + 92] = color
                else:
                    pyte.graphics.FG_ANSI[index + 30] = color
                    pyte.graphics.BG_ANSI[index + 40] = color
                i += len(match[0]) + 4
            else:
                self.previous_char = data[i]
                super().feed(data[i])
                i += 1

    def scroll_up(self, number):
        for j in range(number):
            for k in range(self.scroll_region[0] - 1, self.scroll_region[1] - 1):
                self.listener.buffer[k] = self.listener.buffer[k + 1]
            self.listener.buffer[self.scroll_region[1] - 1] = pyte.screens.StaticDefaultDict(self.listener.default_char)

    def scroll_down(self, number):
        for j in range(number):
            for k in list(range(self.scroll_region[0] - 1, self.scroll_region[1] - 1))[::-1]:
                self.listener.buffer[k + 1] = self.listener.buffer[k]
            self.listener.buffer[self.scroll_region[0] - 1] = pyte.screens.StaticDefaultDict(self.listener.default_char)


class App:
    def __init__(self, filepath, width=None, height=None, timestep=None, encoding=None, should_show_ui=True):
        self.temp_files = []

        if "://" in filepath:
            import urllib.request

            tmp = tempfile.NamedTemporaryFile(suffix=os.path.basename(filepath))
            self.temp_files.append(tmp)
            urllib.request.urlretrieve(filepath, tmp.name)
            filepath = tmp.name

        if filepath.lower().endswith(".gz"):
            import gzip

            with gzip.open(filepath, "rb") as f_in:
                tmp = tempfile.NamedTemporaryFile(suffix=os.path.basename(filepath[:-3]))
                self.temp_files.append(tmp)
                shutil.copyfileobj(f_in, tmp)
                filepath = tmp.name

        if os.path.exists(filepath):
            self.filepath = filepath
        else:
            print("Could not open file", filepath)
            sys.exit(1)

        self.file = open(self.filepath, "rb")
        self.i = 0
        self.bytes_processed = 0
        self.timestep = timestep
        self.encoding = encoding
        self.total_bytes = os.stat(self.filepath).st_size
        self.header = self.read_header()
        self.truncated_payload = None

        self.mode = "frame"
        self.should_show_ui = should_show_ui
        self.width = width
        self.height = height
        self.state = "play"
        self.is_dirty = True
        self.current_frame_time = 0
        self.speed = 1
        self.has_timecap = True
        self.cache = []
        self.current_frame = 1
        self.total_frames = 0
        self.tz = datetime.timezone(datetime.timedelta())
        self.fg = {v: k for k, v in pyte.graphics.FG_ANSI.items()}
        self.bg = {v: k for k, v in pyte.graphics.BG_ANSI.items()}
        self.fg.update({v: k for k, v in pyte.graphics.FG_AIXTERM.items()})
        self.bg.update({v: k for k, v in pyte.graphics.BG_AIXTERM.items()})

    def run(self):
        tty.setcbreak(sys.stdin)
        self.setup_terminal()
        self.load()
        while True:
            os.set_blocking(sys.stdin.fileno(), False)
            if key := sys.stdin.read(1):
                if key == "\x1b":
                    key += sys.stdin.read(5)
                self.on_press(key)
            os.set_blocking(sys.stdin.fileno(), True)
            self.load()
            if self.state == "quit":
                for t in self.temp_files:
                    t.close()
                self.file.close()
                sys.stdout.write("\x1b[?25h")  # Show cursor
                sys.exit(0)
            if self.is_dirty:
                self.display(self.current_frame)
                if self.should_show_ui:
                    self.show_ui()
                self.is_dirty = False
            if self.state == "play":
                duration = self.cache[self.current_frame - 1][2]
                if self.has_timecap and duration > 1:
                    duration = 1
                duration /= self.speed
                if time.time() - self.current_frame_time >= duration and self.current_frame < self.total_frames:
                    self.seek()
            if not self.header:
                time.sleep(min(self.timestep, 50) / 1000000)

    def seek(self, delta=0, pause=0.5):
        previous_frame = self.current_frame
        if delta:
            if self.mode == "frame":
                self.current_frame += delta
            elif self.mode == "time":
                total_duration = 0
                while total_duration < abs(delta):
                    total_duration += self.cache[self.current_frame - 1][2]
                    self.current_frame += 1 if delta > 0 else -1
                    if self.current_frame > self.total_frames or self.current_frame < 1:
                        break
        else:
            self.current_frame += 1
        if self.current_frame > self.total_frames:
            self.current_frame = self.total_frames
        elif self.current_frame < 1:
            self.current_frame = 1
        if self.current_frame != previous_frame:
            # After seeking (e.g. due to hotkey) a pause lets us wait to detect
            # new keypresses (of which the keypress signal is slower than the
            # frame duration) and reorient the viewer to the new frame.
            self.current_frame_time = time.time() + (pause if delta else 0)
            self.is_dirty = True

    def show_ui(self):
        timestamp = self.cache[self.current_frame - 1][0]
        dt = (
            datetime.datetime.fromtimestamp(timestamp, tz=self.tz)
            .isoformat()
            .split("+")[0]
            .split(".")[0]
            .replace("T", " ")
        )
        elapsed_time = int(timestamp - self.cache[0][0])
        if self.mode == "frame":
            progress = int(self.current_frame / self.total_frames * 80)
            mode = "[Frame]"
            elapsed = f"{self.current_frame} / {self.total_frames} frames"
        elif self.mode == "time":
            progress = int(elapsed_time / self.total_time * 80)
            mode = "[Time]"
            elapsed = f"{self.format_duration(elapsed_time)} / {self.format_duration(self.total_time)}"
        remaining = 80 - progress
        progress = "=" * progress
        play_icon = ">" if self.state == "play" else "|"
        if progress:
            progress = progress[:-1] + play_icon
        else:
            progress = play_icon
            remaining -= 1
        remaining = "-" * remaining
        bar = f"\n[{progress}{remaining}]"
        if self.header:
            percent = int(self.bytes_processed / self.total_bytes * 100)
            loading = f"{percent}%"
            bar = bar[: -len(loading) - 1] + loading + "]"
        sys.stdout.write(bar)
        timecap = ""
        if self.has_timecap:
            timecap = " [Timecap]"
        sys.stdout.write(f"\n{dt} - {elapsed} - [{self.speed}X speed] {mode}{timecap}")
        sys.stdout.flush()

    def format_duration(self, seconds):
        h, m, s = str(datetime.timedelta(seconds=seconds)).split(".")[0].split(":")
        elapsed = ""
        if h != "0":
            if h.startswith("0"):
                h = h[1:]
            elapsed = f"{h}h "
        if m != "00":
            if m.startswith("0"):
                m = m[1:]
            elapsed += f"{m}m "
        if s.startswith("0"):
            s = s[1:]
        elapsed += f"{s}s"
        return elapsed

    def render(self):
        cursor_x = self.screen.cursor.x
        cursor_y = self.screen.cursor.y
        total_lines = self.screen.lines
        total_columns = self.screen.columns
        lines = [" " * total_columns] * total_lines
        for y, row in self.screen.buffer.items():
            line = [" "] * total_columns
            for x, cell in row.items():
                line[x] = self.render_cell(cell, is_cursor=x == cursor_x and y == cursor_y)
            lines[y] = "".join(line)
        return "\n".join(lines)

    def copy_buffer(self):
        return (
            self.screen.cursor.x,
            self.screen.cursor.y,
            {y: {x: cell for x, cell in row.items()} for y, row in self.screen.buffer.items()},
        )

    def render_buffer(self, cursor_x, cursor_y, buffer):
        total_columns = self.screen.columns
        lines = [" " * total_columns] * self.screen.lines
        for y, row in buffer.items():
            line = [" "] * total_columns
            for x, cell in row.items():
                line[x] = self.render_cell(cell, is_cursor=x == cursor_x and y == cursor_y)
            lines[y] = "".join(line)
        return "\n".join(lines)

    def render_cell(self, cell, is_cursor=False):
        fg = cell.fg
        bg = cell.bg
        if cell.reverse:
            fg, bg = bg, fg
            if bg == "default":
                bg = "white"
        if bg != "default" and fg == "default":
            fg = "black"
        if is_cursor:
            fg = "black"
            bg = "white"
        indexed_colours = []
        rgb_colours = []
        try:
            indexed_colours.append(str(self.fg[fg]))
        except:
            rgb_colours.append(f"\033[38;2;{int(fg[0:2], 16)};{int(fg[2:4], 16)};{int(fg[4:6], 16)}m")
        try:
            indexed_colours.append(str(self.bg[bg]))
        except:
            rgb_colours.append(f"\033[48;2;{int(bg[0:2], 16)};{int(bg[2:4], 16)};{int(bg[4:6], 16)}m")
        if cell.bold:
            indexed_colours.append("1")
        if cell.italics:
            indexed_colours.append("3")
        if cell.underscore:
            indexed_colours.append("4")
        result = []
        if indexed_colours:
            result.append(f"\033[{';'.join(indexed_colours)}m")
        result.extend(rgb_colours)
        result.append(cell.data or " ")
        if indexed_colours or rgb_colours:
            result.append("\033[m")
        return "".join(result)

    def display(self, frame):
        sys.stdout.write("\x1b[2J\x1b[H")  # Clear screen
        sys.stdout.write("\x1b[?25l")  # Hide cursor
        sys.stdout.write(self.render_buffer(*self.cache[frame - 1][1]))
        sys.stdout.flush()

    def setup_terminal(self):
        ui_lines = 2 if self.should_show_ui else 0
        terminal_size = shutil.get_terminal_size((80, 24 + ui_lines))
        width, height = self.width or terminal_size.columns, self.height or (terminal_size.lines - ui_lines)
        self.screen = pyte.Screen(width, height)
        self.stream = CustomStream(self.screen)

    def read_header(self):
        seconds = int.from_bytes(self.file.read(4), byteorder="little")
        useconds = int.from_bytes(self.file.read(4), byteorder="little")
        length = int.from_bytes(self.file.read(4), byteorder="little")
        self.bytes_processed += 12
        if length:
            return (seconds + useconds / 1000000, length)

    def load(self):
        if not self.header:
            return
        timestamp, length = self.header
        if self.i % 500 == 0:
            self.is_dirty = True
        self.bytes_processed += length
        if not (payload := self.file.read(length)):
            self.header = None
            self.is_dirty = True
            return
        if self.truncated_payload:
            payload = self.truncated_payload + payload
        try:
            payload = payload.decode(self.encoding)
            self.truncated_payload = None
            self.stream.feed(payload)
        except UnicodeDecodeError:
            # Probably the payload is split halfway
            self.truncated_payload = payload
        self.header = self.read_header()
        if self.header:
            duration = self.header[0] - timestamp
            if self.i == 0 or duration >= (self.timestep / 1000000):
                self.cache.append([timestamp, self.copy_buffer(), duration])
                # self.cache.append([timestamp, self.render(), duration])
        else:
            self.cache.append([timestamp, self.copy_buffer(), 0])
            self.header = None
            self.is_dirty = True
            return
        self.i += 1
        self.total_frames = len(self.cache)
        self.total_time = timestamp - self.cache[0][0]

    def on_press(self, key):
        self.is_dirty = True
        try:
            if key == " ":
                self.state = "play" if self.state == "pause" else "pause"
            elif key == "q":
                self.state = "quit"
            elif key in ("l", "\x1b[C"):
                self.seek(delta=1 * ceil(self.speed))
            elif key in ("L", "\x1b[1;2C"):
                self.seek(delta=(10 if self.mode == "frame" else 5) * ceil(self.speed))
            elif key in ("h", "\x1b[D"):
                self.seek(delta=-1 * ceil(self.speed))
            elif key in ("H", "\x1b[1;2D"):
                self.seek(delta=-(10 if self.mode == "frame" else 5) * ceil(self.speed))
            elif key in ("j", "\x1b[B"):
                self.multiply_speed(0.5)
            elif key in ("k", "\x1b[A"):
                self.multiply_speed(2)
            elif key == "c":
                self.has_timecap = not self.has_timecap
            elif key == "m":
                self.mode = "time" if self.mode == "frame" else "frame"
        except:
            pass

    def multiply_speed(self, factor):
        self.speed *= factor
        self.speed = round(self.speed, 2)
        if self.speed >= 1:
            self.speed = int(self.speed)
        elif self.speed < 0.25:
            self.speed = 0.25


description = """A simple ttyrec player tailored for NetHack. <Space> to toggle play / pause. <m> to toggle frame-based seek or time-based seek. <l> / <Right> to go forward, <h> or <Left> to rewind 1 frame or 1 second. <L> / <S-right> to go forward, <H> / <S-left> to rewind 10 frames or 5 seconds. <j> / <Down> to halve the speed. <k> / <Up> to double the speed. <c> to toggle capping durations between frames at 1 second.
"""
parser = argparse.ArgumentParser(prog="pyttyplay", description=description)
parser.add_argument("filepath", help="Path or URL to .ttyrec file. Supports .gz.")
parser.add_argument(
    "--size",
    "-s",
    help="WxH. Defaults to the active terminal size. Ttyrec doesn't store the terminal size, so choose appropriately. E.g. 80x24",
)
parser.add_argument("--ui", help="Whether to show the UI.", action=argparse.BooleanOptionalAction, default=True)
parser.add_argument(
    "--encoding",
    "-e",
    help="Defaults to utf8. Try cp437 if you have problems. Ttyrec files don't store encoding, so choose appropriately.",
    default="utf8",
)
parser.add_argument(
    "--timestep", "-t", help="Frames shorter than this microsecond duration are merged. Defaults to 100.", default=100
)
args = parser.parse_args()
size = args.size
width, height = None, None
if size:
    try:
        width, height = size.lower().split("x")
        width, height = int(width), int(height)
    except:
        pass
timestep = 100
try:
    timestep = int(args.timestep)
except:
    pass
App(args.filepath, width=width, height=height, timestep=timestep, encoding=args.encoding, should_show_ui=args.ui).run()
