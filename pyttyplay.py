import os
import gc
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
        self.truncated_payload = None
        if not encoding:
            self.possible_encodings = ["utf8", "cp437", "ascii"]
            self.guess_encoding()
        self.total_bytes = os.stat(self.filepath).st_size
        self.header = self.read_header()

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
        self.bg["brightmagenta"] = self.bg["bfightmagenta"]

    def quit(self):
        for t in self.temp_files:
            t.close()
        self.file.close()
        sys.stdout.write("\x1b[?25h")  # Show cursor
        sys.exit(0)

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
                self.quit()
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
            {y: dict(row) for y, row in self.screen._buffer.items()},
        )

    def render_buffer(self, cursor_x, cursor_y, buffer):
        total_columns = self.screen.columns
        lines = [" " * total_columns] * self.screen.lines
        for y, row in buffer.items():
            line = [" "] * total_columns
            for x, cell in row.items():
                try:
                    line[x] = self.render_cell(cell, is_cursor=x == cursor_x and y == cursor_y)
                except IndexError:
                    pass
            try:
                lines[y] = "".join(line)
            except IndexError:
                pass
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
        self.stream = pyte.Stream(self.screen)
        # pyte DEC graphics https://github.com/selectel/pyte/issues/182
        self.stream.use_utf8 = False

    def read_header(self):
        seconds = int.from_bytes(self.file.read(4), byteorder="little")
        useconds = int.from_bytes(self.file.read(4), byteorder="little")
        length = int.from_bytes(self.file.read(4), byteorder="little")
        self.bytes_processed += 12
        if length:
            return (seconds + useconds / 1000000, length)

    def guess_encoding(self):
        self.encoding = self.possible_encodings.pop(0)
        self.header = self.read_header()
        errors = 0
        while self.header:
            _, length = self.header
            if not (payload := self.file.read(length)):
                break
            if self.truncated_payload:
                payload = self.truncated_payload + payload
            try:
                payload = payload.decode(self.encoding)
                errors = 0
                self.truncated_payload = None
            except UnicodeDecodeError:
                # Probably the payload is split halfway
                self.truncated_payload = payload
                errors += 1
                if errors > 3:
                    if not self.possible_encodings:
                        print("No suitable encoding found. If you know what it is, specify it with `-e`")
                        self.quit()
                    self.encoding = self.possible_encodings.pop(0)
                    errors = 0
                    self.file.seek(0)
            self.header = self.read_header()
        self.file.seek(0)
        self.bytes_processed = 0

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
            elif key == "\x1b[H":
                self.seek(delta=-self.current_frame)
            elif key == "\x1b[F":
                self.seek(delta=self.total_frames)
            elif key in ("l", "\x1b[C"):
                self.seek(delta=1 * ceil(self.speed))
            elif key in ("L", "\x1b[1;2C"):
                self.seek(delta=(10 if self.mode == "frame" else 5) * ceil(self.speed))
            elif key == "\x1b[6~":
                self.seek(delta=(100 if self.mode == "frame" else 30) * ceil(self.speed))
            elif key in ("h", "\x1b[D"):
                self.seek(delta=-1 * ceil(self.speed))
            elif key in ("H", "\x1b[1;2D"):
                self.seek(delta=-(10 if self.mode == "frame" else 5) * ceil(self.speed))
            elif key == "\x1b[5~":
                self.seek(delta=-(100 if self.mode == "frame" else 30) * ceil(self.speed))
            elif key in ("j", "J", "\x1b[B"):
                self.multiply_speed(0.5)
            elif key in ("k", "K", "\x1b[A"):
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


description = """A simple ttyrec player tailored for NetHack.

<Space>   Toggle play / pause
m         Toggle frame-based seek or time-based seek
c         Toggle capping frame durations at 1 second max
q         Quit

<Home>    Jump to first frame
<End>     Jump to last frame

l         +1 frame / +1 second (multiplied by speed)
<Right>   +1 frame / +1 second (multiplied by speed)
L         +10 frames / +5 seconds (multiplied by speed)
<S-Right> +10 frames / +5 seconds (multiplied by speed)
<PgDn>    +100 frames / +30 seconds (multiplied by speed)

h         +1 frame / +1 second (multiplied by speed)
<Left>    +1 frame / +1 second (multiplied by speed)
H         +10 frames / +5 seconds (multiplied by speed)
<S-Left>  +10 frames / +5 seconds (multiplied by speed)
<PgUp>    +100 frames / +30 seconds (multiplied by speed)

j         Speed / 2
J         Speed / 2
<Down>    Speed / 2
k         Speed * 2
K         Speed * 2
<Up>      Speed * 2
"""
parser = argparse.ArgumentParser(
    prog="pyttyplay", description=description, formatter_class=argparse.RawDescriptionHelpFormatter
)
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
    help="Defaults to autodetecting in the order utf8, cp437, then ascii. Ttyrec files don't store encoding, so choose appropriately.",
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
gc.set_threshold(0)
App(args.filepath, width=width, height=height, timestep=timestep, encoding=args.encoding, should_show_ui=args.ui).run()
