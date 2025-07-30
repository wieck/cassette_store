# ----
# cstore_sharp_pc1211_res
# ----

from collections import deque
from itertools import islice
import re

from cassette_store.cstore_base import *
from cassette_store.cstore_sharp_pc1211 import *

CSTORE_PC1211_PROG  = 0x80

# ----
# CStoreSharpPC1211Res
#
#   Implementation of the Sharp PC-1211 Reserved Keys
# ----
class CStoreSharpPC1211Res(CStoreSharpPC1211):
    def __init__(self, fname = None, mode = 'r', gain = None, sinc = None,
                 debug = False):
        # Build the text->byte token table by reversing the byte->text one
        self.RESKEYS_T2B = {self.RESKEYS_B2T[b]: b
                            for b in self.RESKEYS_B2T}

        # Let the superclass handle the rest.
        super().__init__(fname, 
                         mode       = mode,
                         gain       = gain,
                         debug      = debug)

    def _write_data(self, data):
        # Behaves slightly different than CStoreSharpPC1211. There is
        # no special handling of line-numbers needed because no NUL
        # byte can occur inside of the reserved key data (only as pad
        # bytes at the end).
        bytegen = self._write_byte_generator(data)
        for b in bytegen:
            if b == CSTORE_PC1211_PROG:
                self.ident = CSTORE_PC1211_PROG
                self._write_filename(bytegen)
            else:
                self._write_byte(b)
        self._write_ones(0.5)

    def bytes2text(self, data):
        if data[0] == CSTORE_PC1211_PROG:
            return self._resbytes2text(data)
        else:
            raise CStoreException("unrecognized ident byte "
                                  + "{0:02x}".format(b))

    def _resbytes2text(self, data):
        # The first 8-byte record (after the 0x80 ident) contains the
        # filename.
        fname = ""
        for i in range(7, 0, -1):
            b = ((data[i] & 0xf0) >> 4) | ((data[i] & 0x0f) << 4)
            if b != 0x00:
                fname += self._progbyte2token(b)
        text = 'RESERVED "{0}"\n'.format(fname)

        # From here on we expect reserved key entries
        resdata = deque()
        resdata.extend(data[9:])

        while resdata[0] != 0xf0 and resdata[0] != 0x00:
            # Reserved key entries start with the reskey token
            key = resdata.popleft()
            if key not in self.RESKEYS_B2T:
                raise CStoreException("unknown reserved key token "
                                      + "0x{0:02x}".format(key))
            text += self.RESKEYS_B2T[key]
            
            # Entries end when the next entry starts, we encounter a NUL
            # byte or the EOF marker.
            while (resdata[0] != 0x00 and resdata[0] != 0xf0
                   and resdata[0] not in self.RESKEYS_B2T):
                text += self._progbyte2token(resdata.popleft())
            text += '\n'
        
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

        m = re.match('^RESERVED\s*"([^"]+)"$', lines[0].strip())
        if m:
            data = self._restext2bytes(m.group(1), lines[1:])
        else:
            raise CStoreException("failed to parse header "
                                  + "'{0}'".format(lines[0]))

        return data
        
    def _restext2bytes(self, fname, lines):
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

        # Now process all the reserved key lines
        re_line     = re.compile("(\d+):(.*)")
        re_string   = re.compile("(\"[^\"]*\")\s*(.*)")
        re_string_c = re.compile("(.)(.*)|(|E)(.*)")
        re_keyword  = re.compile("([A-Z][A-Z]+)\s*(.*)")
        re_special  = re.compile("(\|E)(.*)")
        re_char     = re.compile("([^\s])\s*(.*)")

        for line in lines:
            # Process the reserved key token at the beginning of the line
            key = line[0:2]
            if key not in self.RESKEYS_T2B:
                raise CStoreException("unknown reserved key "
                                      + "'{0}'".format(key))
            data.append(self.RESKEYS_T2B[key])
            line = line[2:]

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

        # Pad NUL bytes at the end
        while len(data) < 57:
            data.append(0x00)

        # Finally add the end-of-program marker 0xf0
        data.append(0xf0)

        if len(data) != 58:
            raise CStoreException("reserved key data length is", len(data),
                                  "- must be 58")

        return data

    # Mnemonic names of all reserved key tokens
    RESKEYS_B2T = {
        0xe1:   'A:',
        0xe2:   'B:',
        0xe3:   'C:',
        0xe4:   'D:',
        0xe6:   'F:',
        0xe7:   'G:',
        0xe8:   'H:',
        0xea:   'J:',
        0xeb:   'K:',
        0xec:   'L:',
        0xed:   'M:',
        0xee:   'N:',
        0xf1:   ' :',
        0xf3:   'S:',
        0xf4:   '=:',
        0xf6:   'V:',
        0xf8:   'X:',
        0xfa:   'Z:',
    }
