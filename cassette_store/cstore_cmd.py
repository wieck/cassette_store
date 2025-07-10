#!/usr/bin/env python3
# ----
# cstore_cmd.py
#
# Command line entry points for cassette_store.
# ----
import sys
import argparse
from collections import deque
from itertools import islice

from cassette_store import *

# ----
# Entry point for cstore(1)
# ----
def main():
    # ----
    # Parse command line
    # ----
    parser = argparse.ArgumentParser(
            prog = 'cstore',
            description = """save/load cassette tape programs and data
                    like the Kansas City Standard audio protocol.
                    """
        )
    parser.add_argument('protocol', choices = ['fx502p',],
                        help = 'calculator protocol to use')
    parser.add_argument('action', choices = ['save', 'load'],
                        help = 'action to perform')
    parser.add_argument('-i', '--input', default = None,
                        help = 'read from INPUT')
    parser.add_argument('-o', '--output', 
                        help = 'write result to OUTPUT')
    parser.add_argument('-b', '--binary', action = 'store_true',
                        help = 'read/write binary data')
    parser.add_argument('--gain', default = None, type = int,
                        help = 'apply GAIN db')

    args = parser.parse_args(sys.argv[1:])

    # ----
    # Pick the requested protocol handler class
    # ----
    if args.protocol == 'fx502p':
        handler = CStoreCasioFX502P

    # ----
    # Perform the requested action
    # ----
    if args.action == 'save':
        _cstore_save(handler, args)
    elif args.action == 'load':
        _cstore_load(handler, args)

# ----
# Entry point for cstore-analyze(1)
# ----
def cstore_analyze():
    # ----
    # Parse command line
    # ----
    parser = argparse.ArgumentParser(
            prog = 'cstore-analyze',
            description = """tool commands to analyze cassette-tape audio
                    protocols
                    """
        )
    parser.add_argument('action', choices = ['basefreq',],
                        help = 'action to perform')
    parser.add_argument('-i', '--input', default = None,
                        help = 'read audio from INPUT (soundcard)')
    parser.add_argument('--gain', default = None, type = int,
                        help = 'apply GAIN db')
    parser.add_argument('--skip', default = 0.0, type = float,
                        help = 'skip over SKIP seconds of noise')
    parser.add_argument('--seconds', default = 0.5, type = float,
                        help = 'sample SECONDS of audio (default 0.5s)')

    args = parser.parse_args(sys.argv[1:])

    if args.action == 'basefreq':
        # Determine the base frequency. Most protocols have a lead-in
        # consisting of one-bits for about 3+ seconds. Simply counting
        # the sign-bit-changes in any interval will yield the frequency
        # of a one-bit, which is usually the base frequency.

        # Open the input with just some default values (don't matter)
        cstore = CStoreBase(args.input, mode = 'r',
                            gain        = args.gain,
                            sinc        = None,
                            baud        = 300,
                            freq0       = 1200,
                            freq1       = 2400,
                            parity      = CSTORE_PARITY_NONE,
                            databits    = 8,
                            stopbits    = 1)

        # Skip the requested number of seconds to get over recorded noise
        nskip = int(CSTORE_SOX_RATE * args.skip)
        islice(cstore.sbc, nskip)

        # Read the requested number of sign-bit-change frames and calculate
        # the frequency from that sample.
        nframes = int(CSTORE_SOX_RATE * args.seconds)
        sample = deque()
        sample.extend(islice(cstore.sbc, nframes))
        print(int(sum(sample) / 2 / args.seconds))

# ----
# save action - Calculator is sending audio and cstore is saving it
# ----
def _cstore_save(handler, args):
    # Open the input (file or sound-card)
    with handler(args.input, 'r') as cstore:
        # Get the raw data as a bytearray, stop at the first EOF (0xff)
        data = deque()
        for b in cstore.bytes:
            if b == 0xff:
                break
            data.append(b)
        data = bytearray(data)

        if args.output is None:
            if args.binary:
                # Binary data requested on stdout
                sys.stdout.buffer.write(data)
            else:
                # Text data (mnemonics) requested on stdout
                prog = cstore.bytes2text(data)
                print(prog, end = '')
        else:
            if args.binary:
                # Binary data requested as OUTPUT file
                with open(args.output, 'wb') as fd:
                    fd.write(data)
            else:
                # Text data (mnemonics) requested as OUTPUT file
                prog = cstore.bytes2text(data)
                with open(args.output, 'w') as fd:
                    fd.write(prog)
# ----
# load action - cstore is reading input and calculator is recieving the audio
# ----
def _cstore_load(handler, args):
    # Open the output (file or sound-card)
    with handler(args.output, 'w') as cstore:
        # Get the raw data bytes to sent to the calculator
        if args.input is None:
            if args.binary:
                # Binary data is provided on stdin
                data = sys.stdin.buffer.read()
            else:
                # Text data (mnemonics) is provided on stdin
                prog = sys.stdin.read()
                data = cstore.text2bytes(prog)
        else:
            if args.binary:
                # Binary data is provided as INPUT file
                with open(args.input, 'rb') as fd:
                    data = fd.read()
            else:
                # Text data (mnemonics) is provided as INPUT file
                with open(args.input, 'r') as fd:
                    prog = fd.read()
                    data = cstore.text2bytes(prog)

        # Send the data to the calculator as audio
        cstore.write(data)
