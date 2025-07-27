# ----
# cstore_sharp_pc1211
# ----

from collections import deque
from itertools import islice
import re

from cassette_store.cstore_base import *

CSTORE_PC1211_PROG  = 0x80

# ----
# CStoreSharpPC1211
#
#   Implementation of the Sharp PC-1211
# ----
class CStoreSharpPC1211(CStoreBase):
    def __init__(self, fname = None, mode = 'r', gain = None, sinc = None,
                 debug = False):
        # Build the text->byte token table by reversing the byte->text one
        self.TOKENS_T2B = {self.TOKENS_B2T[b].upper(): b
                           for b in self.TOKENS_B2T}
        # Add convenience tokens for text input
        self.TOKENS_T2B['SQRT '] = 0x1a

        # Open the requested input and configure the protocol.
        super().__init__(fname, 
                         mode       = mode,
                         gain       = gain,
                         sinc       = sinc,
                         basefreq   = 4000,
                         baud       = 500,
                         bitpattern = 'S4567----S0123-----',
                         debug      = debug)

        # If we are reading data (save mode), wait for a lead-in of
        # continuous 1-bits at least 0.5 seconds long
        if mode == 'r':
            self.bytes = self._read_bytes_until_eof()

    def _read_bytes_until_eof(self):
        # First byte must be the file type ident byte
        b = next(self.allbytes)
        if b == CSTORE_PC1211_PROG:
            ident = b
        else:
            raise CStoreException("unrecognized ident byte "
                                  + "{0:02x}".format(b))
        yield b

        have_filename = False

        chksum = 0
        chkcount = 0
        for b in self.allbytes:
            chkcount += 1

            if ident == CSTORE_PC1211_PROG:
                # The PC1211 emits a checksum byte every 8 bytes. This
                # checksum adds the upper with an ADD and the lower
                # nibble with ADDC to a virtual 8-bit accumulator.
                if (chkcount % 9) == 0:
                    # This is a checksum byte. Check it.
                    if self.debug >= 2:
                        print("DBG: {0:02x} {1:02x} ".format(b, chksum)
                              + "checksum")
                    if b != chksum:
                        raise CStoreException("checksum error: "
                                  + "{0:02x} != {1:02x}".format(b, chksum))
                    if not have_filename:
                        have_filename = True
                        chksum = 0
                        chkcount = 0
                    else:
                        # Every 80 bytes the checksum counters are reset
                        if chkcount == 90:
                            chksum = 0
                            chkcount = 0
                else:
                    # Regular data byte processing. Add up checksum.
                    chksum += (b & 0xf0) >> 4
                    if chksum > 0xff:
                        chksum = (chksum + 1) & 0xff
                    chksum = (chksum + (b & 0x0f)) & 0xff

                    if self.debug >= 2:
                        char = chr(b)
                        if not char.isprintable() or char in ['\n', '\r', '\b']:
                            char = '.'
                        print("DBG: {0:02x} '{1}'".format(b, char))

                    # Emit the data byte and stop after reading the
                    # EOF marker.
                    yield b
                    if b == 0xf0:
                        break

    def write(self, data):
        self._write_reset_chksum()

        # Write the lead-in
        self._write_ones(4.0)

        # Write the filename and record(s) data
        self._write_data(data)

    def _write_reset_chksum(self):
        self.chksum = 0
        self.chkcount = 0
        
    def _write_data(self, data):
        bytegen = self._write_byte_generator(data)
        for b in bytegen:
            if b == CSTORE_PC1211_PROG:
                self.ident = CSTORE_PC1211_PROG
                self._write_filename(bytegen)
            elif (b & 0xf0) == 0xe0:
                self._write_progline(b, bytegen)
            elif b == 0xf0:
                if self.debug >= 2:
                    print("DBG: writing EOF")
                self._write_byte(b)
                self._write_ones(0.5)
                break
            else:
                raise CStoreException("unknown record type 0x{0:02x}".format(b))

    def _write_byte_generator(self, data):
        for b in data:
            yield b

    def _write_filename(self, bytegen):
        if self.debug >= 1:
            print("DBG: writing filename")
        self._write_byte(self.ident)
        self._write_reset_chksum()

        fname = deque()
        fname.extend(islice(bytegen, 8))
        for b in fname:
            self._write_byte(b)
        self._write_reset_chksum()
        self._write_ones(0.25)

    def _write_progline(self, firstbyte, bytegen):
        self._write_byte(firstbyte)
        self._write_byte(next(bytegen))
        for b in bytegen:
            self._write_byte(b)
            if b == 0:
                break

    def _write_byte(self, byteval, is_checksum = False):
        # Use our superclass to write the actual byte audio
        super()._write_byte(byteval)

        # If this was a checksum we're done
        if is_checksum:
            return

        # Handle checksum
        self.chksum += (byteval & 0xf0) >> 4
        if self.chksum > 0xff:
            self.chksum += 1
        self.chksum = (self.chksum + (byteval & 0x0f)) & 0xff
        self.chkcount += 1

        # Emit a checksum every 8 bytes
        if (self.chkcount % 8) == 0:
            if self.debug >= 2:
                print("DBG: {0:02x} checksum".format(self.chksum))
            super()._write_byte(self.chksum)
            # Reset checksum and emit 4s ones every 80 bytes
            if self.chkcount == 80:
                self._write_reset_chksum()
                self._write_ones(4.0)

    def bytes2text(self, data):
        if data[0] == CSTORE_PC1211_PROG:
            return self._progbytes2text(data)
        else:
            raise CStoreException("unrecognized ident byte "
                                  + "{0:02x}".format(b))

    def _progbytes2text(self, data):
        # The first 8-byte record (after the 0x80 ident) contains the
        # filename.
        fname = ""
        for i in range(7, 0, -1):
            b = ((data[i] & 0xf0) >> 4) | ((data[i] & 0x0f) << 4)
            if b != 0x00:
                fname += self._progbyte2token(b)
        text = 'PROGRAM "{0}"\n'.format(fname)

        # From here on we expect program code lines
        linedata = deque()
        linedata.extend(data[9:])

        while linedata[0] != 0xf0:
            # Program lines start with the line number encode in BCD as
            # 0xEnnn
            b1 = linedata.popleft()
            b2 = linedata.popleft()
            if (b1 & 0xf0) == 0xE0:
                lineno = (int(b1 & 0x0f) * 100 + int((b2 & 0xf0) >> 4) * 10
                          + int(b2 & 0x0f))
                text += "{0:d}:".format(lineno)
            else:
                raise CStoreException("unknown line number format 0x"
                                      + "{0:02X}{1:02X}".format(b1, b2))
            
            # Lines end with a 0x00
            while linedata[0] != 0x00:
                text += self._progbyte2token(linedata.popleft())
            text += '\n'
            linedata.popleft()
        
        return text

    def _progbyte2token(self, byte):
        if byte in self.TOKENS_B2T:
            return self.TOKENS_B2T[byte]
        else:
            return "[{0:02X}]".format(byte)

    def text2bytes(self, txt):
        # Split the text into lines and determine from the first
        # line what to do.
        lines = txt.upper().strip().split('\n')

        m = re.match('^PROGRAM\s*"([^"]+)"$', lines[0].strip())
        if m:
            data = self._progtext2bytes(m.group(1), lines[1:])
        else:
            raise CStoreException("failed to parse header "
                                  + "'{0}'".format(lines[0]))

        return data
        
    def _progtext2bytes(self, fname, lines):
        data = deque()

        # Start with the PC-1211 Program Ident (0x80)
        data.append(CSTORE_PC1211_PROG)
        
        # Add the filename. This is a strange format. The max 7-byte
        # filename is sent in reverse byte-order and with reversed
        # nibbles and terminated with 0x5f.
        fdata = deque()
        fname = fname[0:7]
        for c in fname:
            if c not in self.TOKENS_T2B:
                raise CStoreException("cannot encode filename character "
                                      + "'{0}'".format(c))
            fdata.insert(0, self.TOKENS_T2B[c])
        while len(fdata) < 7:
            fdata.insert(0, 0x00)
        for b in fdata:
            data.append(((b & 0xf0) >> 4) | ((b & 0x0f) << 4))
        data.append(0x5f)

        # Now process all the program lines
        re_line     = re.compile("(\d+):(.*)")
        re_string   = re.compile("(\"[^\"]*\")\s*(.*)")
        re_string_c = re.compile("(.)(.*)|(|E)(.*)")
        re_keyword  = re.compile("([A-Z][A-Z]+)\s*(.*)")
        re_special  = re.compile("(\|E)(.*)")
        re_char     = re.compile("([^\s])\s*(.*)")

        for line in lines:
            # Separate the line number from the rest of it
            m = re_line.match(line)
            if not m:
                raise CStoreException("cannot parse '{0}'".format(line))
            # Encode the line number into the byte data as Ennn
            lno = 'e' + str('{0:03d}'.format(int(m.group(1))))
            data.append(int(lno[0:2], 16))
            data.append(int(lno[2:4], 16))

            line = m.group(2)

            while len(line) > 0:
                # First we try to parse keywords (we don't support
                # the abbreviated dot notations at this point).
                m = re_keyword.match(line)
                if m and (m.group(1) + ' ') in self.TOKENS_T2B:
                    data.append(self.TOKENS_T2B[m.group(1) + ' '])
                    line = m.group(2)
                    continue
                
                # Next we try to match a double quoted string.
                m = re_string.match(line)
                if m:
                    s = m.group(1)
                    while len(s) > 0:
                        mm = re_string_c.match(s)
                        if mm:
                            if mm.group(1) in self.TOKENS_T2B:
                                data.append(self.TOKENS_T2B[mm.group(1)])
                            else:
                                raise CStoreException("unsupported string "
                                        + "character "
                                        + "'{0}'".format(mm.group(1)))
                            s = mm.group(2)
                    line = m.group(2)
                    continue
                
                # Special characters, like |E (for the exponent part of a
                # number.
                m = re_special.match(line)
                if m:
                    if m.group(1) in self.TOKENS_T2B:
                        data.append(self.TOKENS_T2B[m.group(1)])
                        line = m.group(2)
                        continue
                    else:
                        raise CStoreException("unsupported character "
                                + "'{0}'".format(m.group(1)))

                # Finally anything left must be a single character.
                m = re_char.match(line)
                if m:
                    if m.group(1) in self.TOKENS_T2B:
                        data.append(self.TOKENS_T2B[m.group(1)])
                        line = m.group(2)
                        continue
                    else:
                        raise CStoreException("unsupported character "
                                + "'{0}'".format(m.group(1)))

                # This we cannot make any sense of any more
                raise CStoreException("failed to parse '{0}".format(line))

            # Add the line terminator 0x00
            data.append(0x00)
        
        # Finally add the end-of-program marker 0xf0
        data.append(0xf0)

        return data

    # Mnemonic names of all byte tokens
    TOKENS_B2T = {
        0x11:   ' ',
        0x12:   '"',
        0x13:   '?',
        0x14:   '!',
        0x15:   '#',
        0x16:   '%',
        0x17:   '¥',
        0x18:   '$',
        0x19:   'π',
        0x1a:   '√',
        0x1b:   ',',
        0x1c:   ';',
        0x1d:   ':',

        0x30:   '(',
        0x31:   ')',
        0x32:   '>',
        0x33:   '<',
        0x34:   '=',
        0x35:   '+',
        0x36:   '-',
        0x37:   '*',
        0x38:   '/',
        0x39:   '^',

        0x40:   '0',
        0x41:   '1',
        0x42:   '2',
        0x43:   '3',
        0x44:   '4',
        0x45:   '5',
        0x46:   '6',
        0x47:   '7',
        0x48:   '8',
        0x49:   '9',
        0x4b:   '|E',

        0x51:   'A',
        0x52:   'B',
        0x53:   'C',
        0x54:   'D',
        0x55:   'E',
        0x56:   'F',
        0x57:   'G',
        0x58:   'H',
        0x59:   'I',
        0x5a:   'J',
        0x5b:   'K',
        0x5c:   'L',
        0x5d:   'M',
        0x5e:   'N',
        0x5f:   'O',
        0x60:   'P',
        0x61:   'Q',
        0x62:   'R',
        0x63:   'S',
        0x64:   'T',
        0x65:   'U',
        0x66:   'V',
        0x67:   'W',
        0x68:   'X',
        0x69:   'Y',
        0x6a:   'Z',

        0x91:   'STEP ',
        0x92:   'THEN ',

        0xa0:   'SIN ',
        0xa1:   'COS ',
        0xa2:   'TAN ',
        0xa3:   'ASN ',
        0xa4:   'ACS ',
        0xa5:   'ATN ',
        0xa6:   'EXP ',
        0xa7:   'LN ',
        0xa8:   'LOG ',
        0xa9:   'INT ',
        0xaa:   'ABS ',
        0xab:   'SGN ',
        0xac:   'DEG ',
        0xad:   'DMS ',

        0xb0:   'RUN ',
        0xb1:   'NEW ',
        0xb2:   'MEM ',
        0xb3:   'LIST ',
        0xb4:   'CONT ',
        0xb5:   'DEBUG ',
        0xb6:   'CSAVE ',
        0xb7:   'CLOAD ',

        0xc0:   'GRAD ',
        0xc1:   'PRINT ',
        0xc2:   'INPUT ',
        0xc3:   'RADIAN ',
        0xc4:   'DEGREE ',
        0xc5:   'CLEAR ',

        0xd0:   'IF ',
        0xd1:   'FOR ',
        0xd2:   'LET ',
        0xd3:   'REM ',
        0xd4:   'END ',
        0xd5:   'NEXT ',
        0xd6:   'STOP ',
        0xd7:   'GOTO ',
        0xd8:   'GOSUB ',
        0xd9:   'CHAIN ',
        0xda:   'PAUSE ',
        0xdb:   'BEEP ',
        0xdc:   'AREAD ',
        0xde:   'RETURN ',
        0xdd:   'USING ',
    }
