# ----
# cstore_base
#
# Base class for cassette_store. All higher calculater/computer specific
# classes are derived from this.
# ----
import io
import subprocess
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
    def __init__(self, fname, mode, gain, sinc, baud, freq0, freq1, parity,
                 databits, stopbits):
        self.fname      = fname
        self.mode       = mode
        self.gain       = gain
        self.sinc       = sinc
        self.baud       = baud
        self.freq0      = freq0
        self.freq1      = freq1
        self.parity     = parity
        self.databits   = databits
        self.stopbits   = stopbits

        # Generate frame arrays for zero and one bits
        fphw = int(CSTORE_SOX_RATE / self.freq1 / 2)
        self.frames0 = ([0x80] * fphw * 2 + [0x00] * fphw * 2) * 4
        self.frames1 = ([0x80] * fphw + [0x00] * fphw) * 8

        # Determine the used bitmasks from the number of databits and parity
        self.bitmasks = [1 << n for n in range(0, self.databits)]
        if self.parity is not None:
            self.bitmasks += [0]

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

            # Create the generators for sign-bit-change and bytes
            self.sbc    = self._sbc_gen()
            self.bytes  = self._bytes_gen()
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
    def _sbc_gen(self):
        prev_sign = 0

        while True:
            frames = self.soxpipe.read(8192)
            if not frames:
                break

            sbytes = bytearray(frames)

            for byte in sbytes:
                sign = byte & 0x80
                yield 1 if (sign != prev_sign) else 0
                prev_sign = sign

    # Generator emitting a sequence of bytes as decoded from the above
    # sign-bit-change stream. 
    def _bytes_gen(self):
        sample_size = int(CSTORE_SOX_RATE / self.real_baud)
        stop_skip   = int(self.stopbits * sample_size -
                          CSTORE_SOX_RATE / self.real_freq1)
        sbc_per_0   = int(self.freq0 / self.baud * 2)
        sbc_per_1   = int(self.freq1 / self.baud * 2)
        sbc_cmp     = int((sbc_per_0 + sbc_per_1) / 2)

        sbc = self.sbc

        # We keep a sample buffer the size of audio frames in one bit.
        # Note that the frequencies may have been adjusted after waiting
        # for the lead-in for better alignment with bit-boundaries.
        sample = deque(maxlen = sample_size)
        sample.extend([0] * sample_size)
        sign_changes = 0

        for val in sbc:
            # Look for the start bit
            if val:
                sign_changes += 1
            if sample.popleft():
                sign_changes -= 1
            sample.append(val)

            # A start bit (zero) is a sample buffer that has a leading
            # sign-bit-change and approximately the number of sign bit
            # changes to make a zero bit.
            if sample[0] == 1 and sign_changes <= (sbc_per_0 + 1):
                byte = 0
                none = 0
                # Decode the protocol specific number of databits
                for mask in self.bitmasks:
                    if sum(islice(sbc, sample_size)) >= sbc_cmp:
                        byte |= mask
                        none += 1
                    # If there is a parity bit, check it
                    if mask == 0x00:
                        if none % 2 != self.parity:
                            raise Exception('parity error')
                # if we have stopbits, skip some (but not all) of the
                # one-frequency cycles.
                if stop_skip > 0 and False:
                    sample.extend(islice(sbc, stop_skip))
                else:
                    sample.extend([0x00] * sample_size)
                sign_changes = sum(sample)

                # We got one byte!
                yield byte

    # Almost all of these protocols start with a steady frequency of the
    # one-bit. In order to not get confused by noise at the beginning of
    # old recordings we can wait for that "carrier" signal.
    def _wait_for_leadin(self, duration = 0.5):
        # We create a sample buffer the size of number of audio frames
        # for the requested duration of the carrier signal.
        sample_size = int(CSTORE_SOX_RATE * duration)
        sample = deque(maxlen = sample_size)
        sample.extend(islice(self.sbc, sample_size - 1))

        # We then scan for a steady signal of the one-bit frequency
        for val in self.sbc:
            sample.append(val)
            if abs(sum(sample) - int(self.freq1 * duration * 2)) < 100:
                # We found the carrier wave. This also gives us the oppotunity
                # to fine tune the actual frequencies and baud-rate to what
                # the calculator is sending.
                self.real_freq1 = int(sum(sample) / duration / 2)
                self.real_freq0 = int(self.freq0 * self.real_freq1 / self.freq1)
                self.real_baud  = int(self.baud / self.freq1 * self.real_freq1)
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
