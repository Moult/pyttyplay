# pyttyplay

This is a ttyrec player. See [website with screenshots /
features](https://thinkmoult.com/pyttyplay-nethack-player.html).

A special fork of pyte (Python terminal emulator) is required to run this. The
fork includes optimisations from [this
PR](https://github.com/selectel/pyte/pull/160) as well as support for more
escape codes ([repeat](https://github.com/selectel/pyte/pull/187),
[scroll](https://github.com/selectel/pyte/pull/188), and
[color](https://github.com/selectel/pyte/pull/189)). You can install it by doing:

```
pip install git+https://github.com/Moult/pyte-optimised.git
```

To run:

```
$ python pyttyplay.py path/to/recording.ttyrec
```

Help:

```
$ python pyttyplay.py -h
usage: pyttyplay [-h] [--size SIZE] [--terminal-size TERMINAL_SIZE] [--ui | --no-ui] [--encoding ENCODING] [--timestep TIMESTEP] [--timecap-duration TIMECAP_DURATION] filepath

A simple ttyrec player tailored for NetHack.

<Space>   Toggle play / pause
m         Toggle frame-based seek or time-based seek
c         Toggle capping frame durations at 1 second max
i         Toggle display of the interface
q         Quit

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

<Home>    Jump to first frame
<End>     Jump to last frame

j         Speed / 2
J         Speed / 2
<Down>    Speed / 2
k         Speed * 2
K         Speed * 2
<Up>      Speed * 2

positional arguments:
  filepath              Path or URL to .ttyrec file. Supports .gz and .bz2.

options:
  -h, --help            show this help message and exit
  --size SIZE, -s SIZE  WxH of the recorded ttyrec. Defaults to 500x200 which is typically bigger than most terminals. Ttyrec doesn't store this information so if this is critical you should define this. E.g. 80x24
  --terminal-size TERMINAL_SIZE
                        WxH of your output terminal display. Defaults to your autodetected terminal size. If this is smaller than the recorded ttyrec, output will be cropped (not wrapped). E.g. 80x24
  --ui, --no-ui         Whether to show the UI.
  --encoding ENCODING, -e ENCODING
                        Defaults to autodetecting in the order utf8, cp437, then ascii. Ttyrec files don't store encoding, so choose appropriately.
  --timestep TIMESTEP, -t TIMESTEP
                        Frames shorter than this microsecond duration are merged. Defaults to 100.
  --timecap-duration TIMECAP_DURATION, -c TIMECAP_DURATION
                        Frames longer than this second duration are capped at this duration. Defaults to 1.
```
