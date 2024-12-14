import re
import os
import sys
import time
import pyte
import shutil
import tempfile
import datetime
import argparse
import tty

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


class CustomStream(pyte.Stream):
    def __init__(self, screen):
        super().__init__(screen)
        self.dec_mode = False
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
            elif data[i : i + 2] == "\x1b[" and (match := re.match("([0-9]*?)b", data[i + 2 : i + 6])):
                # pyte doesn't handle repeat sequences https://github.com/selectel/pyte/issues/184
                length = match.groups(0)[0]
                for j in range(int(length)):
                    super().feed(self.previous_char)
                i += len(length) + 3
            elif self.dec_mode and self._taking_plain_text and (dec_char := DEC_SPECIAL_GRAPHICS.get(data[i])):
                # pyte doesn't support DEC graphics https://github.com/selectel/pyte/issues/182
                self.previous_char = dec_char
                super().feed(dec_char)
                i += 1
            else:
                self.previous_char = data[i]
                super().feed(data[i])
                i += 1


class App:
    def __init__(self, filepath, width=None, height=None, timestep=None):
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
        self.total_bytes = os.stat(self.filepath).st_size
        self.bytes_processed = 0
        self.timestep = timestep

        self.width = width
        self.height = height
        self.state = "play"
        self.is_dirty = True
        self.current_frame_time = 0
        self.speed = 1
        self.has_timecap = True
        self.is_loaded = False
        self.cache = []
        self.current_frame = 1
        self.total_frames = 0
        self.tz = datetime.timezone(datetime.timedelta())
        self.fg_codes = {
            "black": "30",
            "red": "31",
            "green": "32",
            "brown": "33",
            "blue": "34",
            "magenta": "35",
            "cyan": "36",
            "white": "37",
            "brightblack": "90",
            "brightred": "91",
            "brightgreen": "92",
            "brightbrown": "93",
            "brightblue": "94",
            "brightmagenta": "95",
            "brightcyan": "96",
            "brightwhite": "97",
        }
        self.bg_codes = {
            "black": "40",
            "red": "41",
            "green": "42",
            "brown": "43",
            "blue": "44",
            "magenta": "45",
            "cyan": "46",
            "white": "47",
            "brightblack": "100",
            "brightred": "101",
            "brightgreen": "102",
            "brightbrown": "103",
            "brightblue": "104",
            "brightmagenta": "105",
            "bfightmagenta": "105",  # See https://github.com/selectel/pyte/pull/183
            "brightcyan": "106",
            "brightwhite": "107",
        }

    def run(self):
        tty.setcbreak(sys.stdin)
        self.setup_terminal()
        self.load()
        while True:
            os.set_blocking(sys.stdin.fileno(), False)
            if key := sys.stdin.read(1):
                self.on_press(key)
            os.set_blocking(sys.stdin.fileno(), True)
            self.load()
            if self.state == "quit":
                for t in self.temp_files:
                    t.close()
                self.file.close()
                sys.exit(0)
            if self.is_dirty:
                self.display(self.current_frame)
                self.show_ui()
                self.is_dirty = False
            if self.state == "play":
                duration = self.cache[self.current_frame - 1][2]
                if self.has_timecap and duration > 1:
                    duration = 1
                duration /= self.speed
                if time.time() - self.current_frame_time >= duration:
                    self.seek(delta=1)
            time.sleep(self.timestep / 1000000)

    def seek(self, frame=0, delta=0):
        previous_frame = self.current_frame
        if delta:
            self.current_frame += delta
        else:
            self.current_frame = frame
        if self.current_frame > self.total_frames:
            self.current_frame = self.total_frames
        elif self.current_frame < 1:
            self.current_frame = 1
        if self.current_frame != previous_frame:
            self.current_frame_time = time.time()
            self.is_dirty = True

    def show_ui(self):
        seconds = self.cache[self.current_frame - 1][0]
        dt = (
            datetime.datetime.fromtimestamp(seconds, tz=self.tz)
            .isoformat()
            .split("+")[0]
            .split(".")[0]
            .replace("T", " ")
        )
        elapsed = int(seconds - self.cache[0][0])
        h, m, s = str(datetime.timedelta(seconds=elapsed)).split(":")
        elapsed = ""
        if h != "0":
            elapsed = f"{h}h "
        if m != "00":
            elapsed += f"{m}m "
        if s == "00":
            s = "0"
        elapsed += f"{s}s elapsed"

        progress = int(self.current_frame / self.total_frames * 80)
        remaining = 80 - progress
        progress = "=" * progress
        play_icon = ">" if self.state == "play" else "|"
        if progress:
            progress = progress[:-1] + play_icon
        else:
            progress = play_icon
            remaining -= 1
        remaining = "-" * remaining
        sys.stdout.write("\n")
        if not self.is_loaded:
            percent = int(self.bytes_processed / self.total_bytes * 100)
            sys.stdout.write(f"{percent}% loaded ...")
        sys.stdout.write(f"\n[{progress}{remaining}]")
        timecap = ""
        if self.has_timecap:
            timecap = " [Timecap]"
        sys.stdout.write(
            f"\n{dt} - {elapsed} - {self.current_frame} / {self.total_frames} frames ({self.speed}X speed){timecap}"
        )
        play = "Pause" if self.state == "play" else "Play"
        sys.stdout.write(f"\n[q Quit] [<space> {play}] [lL +1/10 Next] [hH -1/10 Prev] [jk Speed] [c Timecap]")
        sys.stdout.flush()

    def render(self):
        total_lines = self.screen.lines
        total_columns = self.screen.columns
        lines = [" " * total_columns] * total_lines
        for y, row in self.screen.buffer.items():
            line = [" "] * total_columns
            for x, cell in row.items():
                line[x] = self.render_cell(cell)
            lines[y] = "".join(line)
        return "\n".join(lines)

    def render_cell(self, cell):
        fg = cell.fg
        bg = cell.bg
        if cell.reverse:
            fg, bg = bg, fg
            if bg == "default":
                bg = "white"
        if bg != "default" and fg == "default":
            fg = "black"
        codes = []
        if code := self.fg_codes.get(fg, None):
            codes.append(code)
        if code := self.bg_codes.get(bg, None):
            codes.append(code)
        if cell.bold:
            codes.append("1")
        if cell.italics:
            codes.append("3")
        if cell.underscore:
            codes.append("4")
        char = cell.data or " "
        if codes:
            codes = ";".join(codes)
            return f"\033[{codes}m{char}\033[0m"
        return char

    def display(self, frame):
        sys.stdout.write("\x1b[2J\x1b[H")  # Clear screen
        sys.stdout.write(self.cache[frame - 1][1])
        sys.stdout.flush()

    def setup_terminal(self):
        terminal_size = shutil.get_terminal_size((80, 24 + 4))  # 4 UI rows
        width, height = self.width or terminal_size.columns, self.height or (terminal_size.lines - 4)
        self.screen = pyte.Screen(width, height)
        self.stream = CustomStream(self.screen)

    def load(self):
        if self.is_loaded:
            return
        seconds = int.from_bytes(self.file.read(4), byteorder="little")
        useconds = int.from_bytes(self.file.read(4), byteorder="little")
        length = int.from_bytes(self.file.read(4), byteorder="little")
        seconds += useconds / 1000000
        if self.i % 200 == 0:
            self.is_dirty = True
        payload = self.file.read(length)
        self.bytes_processed += 12 + length
        if not payload:
            self.is_loaded = True
            self.is_dirty = True
            return
        # print(repr(payload))
        # sys.stdout.write(payload.decode("cp437"))
        # sys.stdout.flush()
        self.stream.feed(payload.decode("cp437"))
        # stream.feed(payload.decode("ascii"))
        # stream.feed(payload.decode("utf8"))
        if self.i != 0:
            duration = seconds - self.cache[-1][0]
            if duration > (self.timestep / 1000000):  # Merge frames
                self.cache[-1][2] = duration
                self.cache.append([seconds, self.render(), 0])
            else:
                self.cache[-1] = [seconds, self.render(), 0]
        else:
            self.cache.append([seconds, self.render(), 0])
        self.i += 1
        # if self.i == 1000:
        #     break
        self.total_frames = len(self.cache)

    def on_press(self, key):
        self.is_dirty = True
        try:
            if key == " ":
                self.state = "play" if self.state == "pause" else "pause"
            elif key == "q":
                self.state = "quit"
            elif key == "l":
                self.seek(delta=1 * self.speed)
            elif key == "L":
                self.seek(delta=10 * self.speed)
            elif key == "h":
                self.seek(delta=-1 * self.speed)
            elif key == "H":
                self.seek(delta=-10 * self.speed)
            elif key == "c":
                self.has_timecap = not self.has_timecap
            elif key == "j":
                self.multiply_speed(0.5)
            elif key == "k":
                self.multiply_speed(2)
        except:
            pass

    def multiply_speed(self, factor):
        self.speed *= factor
        self.speed = round(self.speed, 2)
        if self.speed >= 1:
            self.speed = int(self.speed)
        elif self.speed < 0.25:
            self.speed = 0.25


parser = argparse.ArgumentParser(prog="pyttyplay", description="A simple ttyrec player tailored for NetHack")
parser.add_argument("filepath", help="Path or URL to .ttyrec file. Supports .gz.")
parser.add_argument("--size", "-s", help="WxH. Defaults to the active terminal size. E.g. 80x24")
parser.add_argument(
    "--timestep", "-t", help="Frames shorter than this microsecond duration are merged. Defaults to 50.", default=50
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
timestep = 50
try:
    timestep = int(args.timestep)
except:
    pass
App(args.filepath, width=width, height=height, timestep=timestep).run()
