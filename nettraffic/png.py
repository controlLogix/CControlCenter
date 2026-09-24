"""RGB PNG encoder and tiny 3x5 bitmap drawing primitives."""
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Rows are three-bit masks; all chart labels use this alphabet.
_PATTERNS = {
'A':'010 101 111 101 101','B':'110 101 110 101 110','C':'011 100 100 100 011',
'D':'110 101 101 101 110','E':'111 100 110 100 111','F':'111 100 110 100 100',
'G':'011 100 101 101 011','H':'101 101 111 101 101','I':'111 010 010 010 111',
'J':'001 001 001 101 010','K':'101 101 110 101 101','L':'100 100 100 100 111',
'M':'101 111 111 101 101','N':'101 111 111 111 101','O':'010 101 101 101 010',
'P':'110 101 110 100 100','Q':'010 101 101 111 011','R':'110 101 110 101 101',
'S':'011 100 010 001 110','T':'111 010 010 010 010','U':'101 101 101 101 111',
'V':'101 101 101 101 010','W':'101 101 111 111 101','X':'101 101 010 101 101',
'Y':'101 101 010 010 010','Z':'111 001 010 100 111',
'0':'111 101 101 101 111','1':'010 110 010 010 111','2':'110 001 010 100 111',
'3':'110 001 010 001 110','4':'101 101 111 001 001','5':'111 100 110 001 110',
'6':'011 100 111 101 111','7':'111 001 010 010 010','8':'111 101 111 101 111',
'9':'111 101 111 001 110','-':'000 000 111 000 000','.':'000 000 000 000 010',
':':'000 010 000 010 000','/':'001 001 010 100 100',' ':'000 000 000 000 000'}
FONT = {c: [int(r, 2) for r in rows.split()] for c, rows in _PATTERNS.items()}


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


class Canvas:
    def __init__(self, width, height):
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError('canvas dimensions must be 1..4096')
        self.width, self.height = width, height
        self.pixels = bytearray((245, 248, 252)) * (width * height)

    def rect(self, x, y, width, height, color):
        left, right = max(0, x), min(self.width, x + width)
        if right <= left:
            return
        row = bytes(color) * (right - left)
        for yy in range(max(0, y), min(self.height, y + height)):
            start = (yy * self.width + left) * 3
            self.pixels[start:start + len(row)] = row

    def text(self, x, y, text, scale=2):
        for char in str(text).upper():
            for row, mask in enumerate(FONT.get(char, FONT[' '])):
                for col in range(3):
                    if mask & (4 >> col):
                        self.rect(x + col * scale, y + row * scale, scale, scale, (30, 44, 65))
            x += 4 * scale

    def write(self, path):
        stride = self.width * 3
        raw = b''.join(b'\0' + self.pixels[i:i + stride] for i in range(0, len(self.pixels), stride))
        header = struct.pack('>IIBBBBB', self.width, self.height, 8, 2, 0, 0, 0)
        with open(path, 'wb') as stream:
            stream.write(SIGNATURE + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
