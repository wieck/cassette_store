# CASSETTE_STORE
## Tools to decode/encode cassette-tape storage formats

This is a set of tools to decode and encode cassette tape storage formats
like the
[Kansas City Standard](https://en.wikipedia.org/wiki/Kansas_City_standard).

The project just started, so documentaion is lacking.

- I have no idea how to make this work on Windows.
- The tool requires sox(1) to be installed (available on all Linux distros).
- The code is modular and more protocols are in development.

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
usage: cstore [-h] [-i INPUT] [-o OUTPUT] [-b] [-d] [--gain GAIN]
              [--sinc SINC]
              {fx502p,pc1211} {save,load}

save/load cassette tape programs and data like the Kansas City Standard audio
protocol.

positional arguments:
  {fx502p,pc1211}       calculator protocol to use
  {save,load}           action to perform

optional arguments:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        read from INPUT
  -o OUTPUT, --output OUTPUT
                        write result to OUTPUT
  -b, --binary          read/write binary data
  -d, --debug           enable debugging output (repeat for more verbosity)
  --gain GAIN           apply GAIN db
  --sinc SINC           apply SINC bandpass filter
```

The help could mention that
- the default input for `save` is the active sound-card
- the default output for `save` is `stdout`
- the default input for `load` is `stdin`
- the default output for `load` is the active sound-card
