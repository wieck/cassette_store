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
                 bitpattern = 'S01234567E--', debug = 0):
        self.fname      = fname
        self.mode       = mode
        self.gain       = gain
        self.sinc       = sinc
        self.origfreq   = basefreq
        self.baud       = baud
        self.bitpattern = bitpattern
        self.debug      = debug

        if debug:
            print("DBG: debug level", debug)

        # Generate frame arrays for zero and one bits depending on the
        # base frequency and baud.
        fphw = int(CSTORE_SOX_RATE / basefreq / 2)
        len_0 = int(self.origfreq / self.baud / 2)
        len_1 = int(len_0 * 2)
        self.frames0 = ([120] * fphw * 2 + [-120 & 0xff] * fphw * 2) * len_0
        self.frames1 = ([120] * fphw + [-120 & 0xff] * fphw) * len_1

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
            self.startbit   = self._read_startbit_generator()
            self.bits       = self._read_bit_generator()
            self.allbytes   = self._read_byte_generator()

            # Set up the half-wave sample buffer for the _read_hw_generator
            self.hwlen_0    = int(self.origfreq / self.baud)
            self.hwlen_1    = self.hwlen_0 * 2
            self.hwbuffer   = deque(maxlen = self.hwlen_1)
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
            if self.debug >= 1:
                print("DBG: sox cmd =", cmd)
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
            if self.mode == 'w':
                if self.debug >= 1:
                    print("DBG: flushing output")
                self.soxproc.stdin.flush()
                self.soxproc.stdin.close()
            else:
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
            # Read the next chunk of binary frames from the sound input
            # and turn it into a bytearray.
            frames = self.soxpipe.read(8192)
            if not frames:
                break
            sbytes = bytearray(frames)

            # Produce a 1 for every time the sign of the frame changes,
            # and a 0 otherwise.
            for byte in sbytes:
                sign = byte & 0x80
                yield 1 if (sign != last_sign) else 0
                last_sign = sign

    # Generator emitting a '#' for a ZERO frequency halfwave and a '.' for
    # a ONE frequency halfwave. The _read_bit_generator() is using this to
    # output a bit stream.
    def _read_hw_generator(self):
        # Measure the number of frames from 1 to the next 1.
        n = 0
        for s in self.sbc:
            n += 1
            if s != 0 and n > 2:
                # If the number of frames is below the threshold this is
                # a ZERO halfwave, otherwise a ONE halfwave.
                yield '.' if n <= self.hwmidpoint else '#'
                n = 0

    def _read_startbit_generator(self):
        # Calculate how many halfwaves to skip once we found
        # a full wave of the ZERO frequency
        skip = self.hwlen_0 - 2

        # Fill the sample buffer with enought samples for each pattern.
        # The startbit generator is called before the bit generator,
        # so this is where it needs to happen.
        self.hwbuffer.extend(islice(self.hw, self.hwlen_1))

        # Process halfwave patterns.
        while True:
            # Wait for at least a single ONE frequency full wave. That is
            # two consecutive '.'.
            if self.hwbuffer[0] != '.' or self.hwbuffer[1] != '.':
                if self.debug >= 4:
                    print("DBG: advance from", ''.join(self.hwbuffer))
                self.hwbuffer.append(next(self.hw))
                continue

            # Now wait for at least two ZERO waves and consume the remaining
            # halfwaves for that.
            # While at it count the number of idle ONE halfwaves we
            # are skipping over for debug purposes.
            lead = 2
            for hw in self.hw:
                lead += 1
                self.hwbuffer.append(hw)
                if self.debug >= 4:
                    print("DBG: scanning for ZERO in", ''.join(self.hwbuffer))
                if (self.hwbuffer[0] == '#' and self.hwbuffer[1] == '#' and
                    self.hwbuffer[2] == '#' and self.hwbuffer[3] == '#'):
                    if self.debug >= 3:
                        # Report lead/idle time
                        if lead > int(5 * self.hwlen_1 * 2.5):
                            ms = lead / self.basefreq / 2.0 * 1000.0
                            print("DBG: lead of {0:.2f}ms".format(ms))
                        print("DBG: START from", ''.join(self.hwbuffer))
                    self.hwbuffer.extend(islice(self.hw, self.hwlen_0))

                    # Return the ZERO startbit and wait for the
                    # next call.
                    yield 0
                    break

    # Generate a stream of decoded bits. This is only called from
    # higher generators after a startbit has been detected and we
    # are synchronized on a bit-boundary. So we can simply scan
    # a sufficient number of frames and look at the frequency detected
    # in the middle of them.
    def _read_bit_generator(self):
        while True:
            if self.hwbuffer[int(self.hwlen_0 / 2)] == '#':
                if self.debug >= 3:
                    print("DBG: ZERO  from", ''.join(self.hwbuffer))
                self.hwbuffer.extend(islice(self.hw, self.hwlen_0))
                yield 0
            elif self.hwbuffer[int(self.hwlen_1 / 2)] == '.':
                if self.debug >= 3:
                    print("DBG: ONE   from", ''.join(self.hwbuffer))
                self.hwbuffer.extend(islice(self.hw, self.hwlen_1))
                yield 1
            else:
                raise CStoreException("could not determine bit from " +
                                      "".join(map(str, self.hwbuffer)))


    # Generate a stream of decoded bytes.
    def _read_byte_generator(self):
        try:
            while True:
                byteval = 0
                num_one = 0
                for state in self.bitpattern:
                    if state in ['0', '1', '2', '3', '4', '5', '6', '7']:
                        if next(self.bits):
                            byteval |= (1 << int(state))
                            num_one += 1
                    elif state == 'S':
                        next(self.startbit)
                    elif state == 'E':
                        b = next(self.bits)
                        if (num_one % 2) != b:
                            raise CStoreException("parity error")
                    elif state == 'O':
                        b = next(self.bits)
                        if (num_one % 2) == b:
                            raise CStoreException("parity error")
                    elif state == '-':
                        pass

                # Generate the byte we just decoded.
                if self.debug >= 2:
                    char = chr(byteval)
                    if not char.isprintable() or char in ['\n','\r','\b']:
                        char = '.'
                    print("DBG: {0:02x} '{1}'".format(byteval, char))
                yield byteval
        except StopIteration:
            pass

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
                if self.debug >= 1:
                    print("DBG: detected basefreq =", self.basefreq)
                return True

            # If not found yet we just move ahead by 100ms so we don't
            # have to do the above for every single audio frame.
            sample.extend(islice(self.sbc, int(CSTORE_SOX_RATE / 10 - 1)))

        raise CStoreException("no carrier signal detected")

    # Write raw frame data to the output (sound-card or sound-file)
    def _write_frames(self, frames):
        self.soxpipe.write(frames)

    # Write one-bits for the requested duration in seconds. This is a lead-in.
    def _write_ones(self, duration):
        numwaves = int(CSTORE_SOX_RATE / len(self.frames1) * duration)
        self._write_frames(bytes(self.frames1 * numwaves))

    # Encode data bytes as configured
    def _write_byte(self, b):
        frames = deque()

        if self.debug >= 2:
            print("DBG: writing byte {0:02x}".format(b))
        # Build the whole frame sequence and count one-bits
        num_ones = 0
        for state in self.bitpattern:
            if state in ['0', '1', '2', '3', '4', '5', '6', '7']:
                # Emit the databit
                if b & (1 << int(state)):
                    frames.extend(self.frames1)
                    num_ones += 1
                else:
                    frames.extend(self.frames0)
            elif state == 'S':
                # Emit a sartbit
                frames.extend(self.frames0)
            elif state == 'E':
                # Emit an EVEN paritybit
                if (num_ones % 2) == 0:
                    frames.extend(self.frames0)
                else:
                    frames.extend(self.frames1)
            elif state == 'O':
                # Emit an ODD paritybit
                if (num_ones % 2) == 0:
                    frames.extend(self.frames1)
                else:
                    frames.extend(self.frames0)
            elif state == '-':
                # Emit a stopbit
                frames.extend(self.frames1)

        # Push the audio frames to the output
        self._write_frames(bytes(frames))
