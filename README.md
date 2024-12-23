# pyttyplay

This is a ttyrec player.

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
usage: pyttyplay [-h] [--size SIZE] [--ui | --no-ui] [--encoding ENCODING] [--timestep TIMESTEP] filepath

A simple ttyrec player tailored for NetHack.

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

positional arguments:
  filepath              Path or URL to .ttyrec file. Supports .gz.

options:
  -h, --help            show this help message and exit
  --size SIZE, -s SIZE  WxH. Defaults to the active terminal size. Ttyrec doesn't store the terminal size, so choose appropriately. E.g. 80x24
  --ui, --no-ui         Whether to show the UI.
  --encoding ENCODING, -e ENCODING
                        Defaults to autodetecting in the order utf8, cp437, then ascii. Ttyrec files don't store encoding, so choose appropriately.
  --timestep TIMESTEP, -t TIMESTEP
                        Frames shorter than this microsecond duration are merged. Defaults to 100.
```
