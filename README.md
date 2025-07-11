# CASSETTE_STORE
## Tools to decode/encode cassette-tape storage formats

This is a set of tools to decode and encode cassette tape storage formats
like the
[Kansas City Standard](https://en.wikipedia.org/wiki/Kansas_City_standard).

The project just started, so documentaion is lacking.

- I have no idea how to make this work on Windows
- The tool requires sox(1) to be installed (available on all Linux distros)
- The only protocol implemented at this point is the CASIO FX-502P
- The code is modular and more protocols are in development

### Installation

- Install sox(1) (via dnf or apt-get)
- Clone this Git repository
- Create and activate a Python3 virtual-env
- Run `pip install -e .` inside the checked out Git repo

### Usage

At this point your Python-3 virtual-env should have a command `cstore`
available:

```
$ cstore --help
usage: cstore [-h] [-i INPUT] [-o OUTPUT] [-b] [--gain GAIN]
              {fx502p} {save,load}

save/load cassette tape programs and data like the Kansas City Standard audio
protocol.

positional arguments:
  {fx502p}              calculator protocol to use
  {save,load}           action to perform

optional arguments:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        read from INPUT
  -o OUTPUT, --output OUTPUT
                        write result to OUTPUT
  -b, --binary          read/write binary data
  --gain GAIN           apply GAIN db
```

The help could mention that
- the default input for `save` is the active sound-card
- the default output for `save` is `stdout`
- the default input for `load` is `stdin`
- the default output for `load` is the active sound-card

### Example

This is decoding the CASIO Program Library Mathematics-8 example program,
**Solving a cubic equation by the Newton method**.

```
$ cstore fx502p save -i fx502p-math-8.wav
FP000
P0:
    HLT Min1 HLT Min2 HLT Min3 HLT Min4 HLT MinF
  LBL1:
    HLT Min5 HLT Min6
  LBL2:
    MR5 Min7 2 Min0
  LBL3:
    MR1 * MR5 X^2 * MR5 + MR2 * MR5 X^2 + MR3 * MR5 + MR4 = Min9 MR6 M+5 DSZ
    GOTO4 GOTO5
  LBL4:
    MR9 Min8 GOTO3
  LBL5:
    ( MR9 - MR8 ) / MR6 = Min9 MR7 - MR8 / MR9 = Min8 - MR7 = ABS X>=F GOTO6
    GOTO7
  LBL6:
    MR8 Min5 GOTO2
  LBL7:
    MR7 GOTO1
```
