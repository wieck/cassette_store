# ----
# cstore_base
#
# Base class for cassette_store. All higher calculater/computer specific
# classes are derived from this.
# ----
import io
import subprocess
import sys
from collections import deque
from itertools import islice

CSTORE_PARITY_EVEN  = 0
CSTORE_PARITY_ODD   = 1
CSTORE_PARITY_NONE  = None

CSTORE_SOX_SOX      = 'sox'
CSTORE_SOX_REC      = 'rec'
CSTORE_SOX_PLAY     = 'play'

CSTORE_SOX_RATE     = 48000
CSTORE_SOX_BITS     = 8
CSTORE_SOX_CHANNELS = 1
CSTORE_SOX_ENCODING = 'signed'
CSTORE_SOX_TYPE     = 'raw'

class CStoreException(Exception):
    def __init__(self, msg):
        self.msg = msg
        super().__init__(self.msg)

    def __str__(self):
        return self.msg

# ----
# CStoreBase
#
#   Base class of the cassette_store module.
# ----
class CStoreBase:
    def __init__(self, fname, mode, gain, sinc, basefreq, baud,
                 databits, parity, stopbits, debug = False):
        self.fname      = fname
        self.mode       = mode
        self.gain       = gain
        self.sinc       = sinc
        self.origfreq   = basefreq
        self.baud       = baud
        self.databits   = databits
        self.parity     = parity
        self.stopbits   = stopbits
        self.debug      = debug

        # Determine the used bitmasks from the number of databits and parity
        self.bitmasks = [1 << n for n in range(0, self.databits)]
        if self.parity is not None:
            self.bitmasks += [0]

        # Generate frame arrays for zero and one bits depending on the
        # base frequency and baud.
        fphw = int(CSTORE_SOX_RATE / basefreq / 2)
        len_0 = int(self.origfreq / self.baud / 2)
        len_1 = int(len_0 * 2)
        self.frames0 = ([120] * fphw * 2 + [-120 & 0xff] * fphw * 2) * len_0
        self.frames1 = ([120] * fphw + [-120 & 0xff] * fphw) * len_1

        if debug:
            print("bitmasks:", self.bitmasks)
            print("frames0: ", self.frames0)
            print("frames1: ", self.frames1)

        if mode == 'r':
            # This is 'save' mode, reading from the calculator
            if fname is None:
                # Build the sox(1) command line for reading from the sound-card
                cmd = [CSTORE_SOX_REC, '-q',
                       '-b', str(CSTORE_SOX_BITS),
                       '-c', str(CSTORE_SOX_CHANNELS),
                       '-r', str(CSTORE_SOX_RATE),
                       '-e', str(CSTORE_SOX_ENCODING),
                       '-t', str(CSTORE_SOX_TYPE),
                       '-'
                    ]
                if gain is not None:
                    cmd += ['gain', str(gain)]
                if sinc is not None:
                    cmd += ['sinc', str(sinc)]
            else:
                # Build the sox(1) command line for reading from a file
                cmd = [CSTORE_SOX_SOX, '-q',
                       fname,
                       '-b', str(CSTORE_SOX_BITS),
                       '-c', str(CSTORE_SOX_CHANNELS),
                       '-r', str(CSTORE_SOX_RATE),
                       '-e', str(CSTORE_SOX_ENCODING),
                       '-t', str(CSTORE_SOX_TYPE),
                       '-'
                    ]
                if gain is not None:
                    cmd += ['gain', str(gain)]
                if sinc is not None:
                    cmd += ['sinc', str(sinc)]

            # Launch the sox(1) process
            self.soxproc = subprocess.Popen(cmd, stdout = subprocess.PIPE,
                                            text = False)
            self.soxpipe = io.BufferedReader(self.soxproc.stdout)

            # Create the generator for sign-bit-changes
            self.sbc    = self._read_sbc_generator()

            # Wait for the lead-in and determine the actual basefreq from that
            self._wait_for_leadin(basefreq, 0.5)

            # From the basefreq we can calculate the midpoint between
            # number of samples for a basefreq halfwave and those for
            # a basefreq/2 (zero bit) halfwave.
            self.hwmidpoint = int(CSTORE_SOX_RATE / (self.basefreq * 1.5)
                                  + 0.5)

            # Create all the generators needed
            self.hw         = self._read_hw_generator()
            self.bits       = self._read_bit_generator()
            self.allbytes   = self._read_byte_generator()
        elif mode == 'w':
            # This is 'load' mode, writing to the calculator or a sound-file
            if fname is None:
                # Build the command line to write to the sound-card
                cmd = [CSTORE_SOX_PLAY, '-q',
                       '-b', str(CSTORE_SOX_BITS),
                       '-c', str(CSTORE_SOX_CHANNELS),
                       '-r', str(CSTORE_SOX_RATE),
                       '-e', str(CSTORE_SOX_ENCODING),
                       '-t', str(CSTORE_SOX_TYPE),
                       '-'
                    ]
            else:
                # Build the command line to write to an audio file
                cmd = [CSTORE_SOX_SOX, '-q',
                       '-b', str(CSTORE_SOX_BITS),
                       '-c', str(CSTORE_SOX_CHANNELS),
                       '-r', str(CSTORE_SOX_RATE),
                       '-e', str(CSTORE_SOX_ENCODING),
                       '-t', str(CSTORE_SOX_TYPE),
                       '-',
                       fname
                    ]
                if gain is not None:
                    cmd += ['gain', str(gain)]
                if sinc is not None:
                    cmd += ['sinc', str(sinc)]

            # Launch the sox(1) process
            self.soxproc = subprocess.Popen(cmd, stdin = subprocess.PIPE,
                                            text = False)
            self.soxpipe = io.BufferedWriter(self.soxproc.stdin)
        else:
            raise CStoreException("unknown open mode '{0}'".format(mode))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # Shutdown input or output
    def close(self):
        if self.soxproc is not None:
            self.soxproc.kill()
            self.soxproc.wait()
            self.soxproc = None
            self.soxpipe = None
            self.sbc = None

    # Generator emitting a sign-bit-change (sbc) stream. Every time the
    # audio signal's amplitude flips from positive to negative or vice versa,
    # emit a 1. Otherwise emit a 0. This lets higher functions determine
    # the current frequency.
    def _read_sbc_generator(self):
        last_sign = 0

        while True:
            frames = self.soxpipe.read(8192)
            if not frames:
                break

            sbytes = bytearray(frames)

            for byte in sbytes:
                sign = byte & 0x80
                yield 1 if (sign != last_sign) else 0
                last_sign = sign

    # Generator emitting a '#' for a ZERO frequency halfwave and a '.' for
    # a ONE frequency halfwave. The _read_bit_generator() is using this to
    # output a bit stream.
    def _read_hw_generator(self):
        n = 0
        for s in self.sbc:
            n += 1
            if s != 0 and n > 2:
                yield '.' if n <= self.hwmidpoint else '#'
                n = 0

    # Generate a stream of decoded bits
    def _read_bit_generator(self):
        # From the originally requested basefreq and the baud we can
        # determine the lengths of the zero and one patterns.
        len_1 = int(self.origfreq / self.baud * 2)
        len_0 = int(len_1 / 2)
        pattern_1 = '.' * len_1
        pattern_0 = '#' * len_0

        # Scan the incoming halfwaves for those patterns
        sample = deque(maxlen = len_1)
        sample.extend(islice(self.hw, len_1 - 1))

        for hw in self.hw:
            sample.append(hw)
            if ''.join(sample)[0:len_0] == pattern_0:
                # Got a ZERO pattern
                yield 0
                sample.extend(islice(self.hw, len_0 - 1))
            elif ''.join(sample) == pattern_1:
                # Got a ONE pattern
                yield 1
                sample.extend(islice(self.hw, len_1 - 1))

    # Generate a stream of decoded bytes
    def _read_byte_generator(self):
        # Calculate the number of meaningful bits (without stopbits)
        numbits = 1 + self.databits
        if self.parity != CSTORE_PARITY_NONE:
            numbits += 1

        # Setup a sample buffer including the stopbits
        sample = deque(maxlen = numbits + self.stopbits)
        sample.extend(islice(self.bits, numbits + self.stopbits - 1))

        # Now process bits into bytes
        for b in self.bits:
            # First we scan for a ZERO startbit
            sample.append(b)
            if sample[0] == 0:
                # Got the startbit, now we consume the requested number of
                # databits and parity. Count ONES while doing so.
                byteval = 0
                i = 1
                nones = 0
                for m in self.bitmasks:
                    if m != 0:
                        # This is a data bit, if set add it to the byteval.
                        if sample[i]:
                            byteval |= m
                            nones += 1
                    else:
                        # This is the parity bit, check it. Note: the
                        # class initialization adds a zero mask to the
                        # bitmasks if there is a parity.
                        if sample[i] != (nones + self.parity) % 2:
                            raise CStoreException("parity error")
                    i += 1
                # Skip ahead on the input bits so that the stopbits are
                # next in the sample processing.
                sample.extend(islice(self.bits, numbits - 1))

                # Return the byte we just produced.
                if self.debug:
                    char = chr(byteval)
                    if not char.isprintable() or char in ['\n', '\r', '\b']:
                        char = '.'
                    print("{0:02x} '{1}'".format(byteval, char))
                yield byteval

    def _wait_for_leadin(self, basefreq, duration = 0.5):
        # We create a sample buffer the size of number of audio frames
        # for the requested duration of the carrier signal.
        sample_size = int(CSTORE_SOX_RATE * duration)
        sample = deque(maxlen = sample_size)
        sample.extend(islice(self.sbc, sample_size - 1))

        # We then scan for a steady signal of the one-bit frequency.
        # Doesn't have to be 100% accurate
        for val in self.sbc:
            sample.append(val)
            if abs(sum(sample) - int(basefreq * duration * 2)) < basefreq / 25:
                # We found the carrier wave. Advance 0.2 seconds further to
                # eliminate any early junk, then measure the actual basefreq.
                sample.extend(islice(self.sbc, int(CSTORE_SOX_RATE / 5 - 1)))
                self.basefreq = int(sum(sample) / duration / 2)
                return True

            # If not found yet we just move ahead by 100ms so we don't
            # have to do the above for every single audio frame.
            sample.extend(islice(self.sbc, int(CSTORE_SOX_RATE / 10 - 1)))
        
        return False

    # Write raw frame data to the output (sound-card or sound-file)
    def _write_frames(self, frames):
        self.soxpipe.write(frames)

    # Write one-bits for the requested duration in seconds. This is a lead-in.
    def _write_ones(self, duration):
        numwaves = int(CSTORE_SOX_RATE / len(self.frames1) * duration)
        self._write_frames(bytes(self.frames1 * numwaves))

    # Encode data bytes as configured
    def _write_bytes(self, data):
        frames = deque()

        for b in data:
            # Add a zero-startbit
            frames.extend(self.frames0)
            nbits = 0
            for mask in self.bitmasks:
                # Add the requested number of databits and count the ones
                if mask != 0:
                    if b & mask:
                        frames.extend(self.frames1)
                        nbits += 1
                    else:
                        frames.extend(self.frames0)
                else:
                    # If configured add the parity bit
                    if nbits % 2 != self.parity:
                        frames.extend(self.frames1)
                    else:
                        frames.extend(self.frames0)
            # Add the one-stopbits
            for i in range(self.stopbits):
                frames.extend(self.frames1)

            # Push the audio frames to the putput
            self._write_frames(bytes(frames))
            frames.clear()
