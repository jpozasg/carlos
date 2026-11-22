"""Removes location and other identifying metadata from an uploaded photo (issue #411). Standard library only.

JPEG: APP1 (EXIF with GPS, thumbnail, XMP), APP3-APP13, APP15 and COM segments are dropped. APP0 (JFIF), the APP2 ICC
profile and APP14 (Adobe) stay: they describe colour, not the device. The EXIF Orientation tag is kept in a minimal
EXIF block, so a phone photo still shows upright.
PNG: tEXt, zTXt, iTXt, eXIf and tIME chunks are dropped (eXIf's orientation is dropped with it).
WebP: EXIF and XMP chunks are dropped and their flags cleared in VP8X.
Anything that does not parse raises ValueError, and the caller stores nothing.
"""
import struct

PNG_DROP = {b'tEXt', b'zTXt', b'iTXt', b'eXIf', b'tIME'}


def strip(body, ext):
    """`ext` is the extension from config.IMAGE_TYPES: 'jpg', 'png' or 'webp'. Returns the cleaned bytes."""
    try:
        return {'jpg': _jpeg, 'png': _png, 'webp': _webp}[ext](body)
    except (struct.error, IndexError):
        raise ValueError(f'Could not read the {ext.upper()} file to remove its metadata; not stored') from None


def _jpeg(b):
    out, i = [b[:2]], 2
    while True:
        if i + 4 > len(b) or b[i] != 0xFF:
            raise ValueError('JPEG structure is broken before the image data; not stored')
        m = b[i + 1]
        if m == 0xFF:  # fill byte
            i += 1
            continue
        if m == 0xDA:  # start of scan: the rest is image data and the end marker, copied as is
            return b''.join(out) + b[i:]
        if m in (0x01, 0xD8, 0xD9) or 0xD0 <= m <= 0xD7:  # standalone markers have no length
            out.append(b[i:i + 2])
            i += 2
            continue
        n = struct.unpack_from('>H', b, i + 2)[0]
        if n < 2 or i + 2 + n > len(b):
            raise ValueError('JPEG segment runs past the end of the file; not stored')
        payload = b[i + 4:i + 2 + n]
        if m == 0xE1 and payload.startswith(b'Exif\x00\x00'):
            orientation = _orientation(payload[6:])
            if orientation:
                out.append(_exif(orientation))
        elif m in (0xE0, 0xEE) or (m == 0xE2 and payload.startswith(b'ICC_PROFILE\x00')) or not (0xE0 <= m <= 0xEF or m == 0xFE):
            out.append(b[i:i + 2 + n])
        i += 2 + n


def _orientation(t):
    """The Orientation tag (0x0112) of IFD0, or None when absent or unreadable: the photo is then shown unrotated."""
    endian = {b'II': '<', b'MM': '>'}.get(t[:2])
    if endian is None:
        return None
    try:
        ifd = struct.unpack_from(endian + 'I', t, 4)[0]
        for k in range(struct.unpack_from(endian + 'H', t, ifd)[0]):
            at = ifd + 2 + 12 * k
            tag, typ, count = struct.unpack_from(endian + 'HHI', t, at)
            if tag == 0x0112 and typ == 3 and count == 1:
                value = struct.unpack_from(endian + 'H', t, at + 8)[0]
                return value if 1 <= value <= 8 else None
    except struct.error:
        pass
    return None


def _exif(orientation):
    """A minimal big-endian EXIF APP1 segment that holds only the Orientation tag."""
    tiff = b'MM\x00*' + struct.pack('>I', 8) + struct.pack('>H', 1) + struct.pack('>HHIHH', 0x0112, 3, 1, orientation, 0) + struct.pack('>I', 0)
    body = b'Exif\x00\x00' + tiff
    return b'\xff\xe1' + struct.pack('>H', len(body) + 2) + body


def _png(b):
    if b[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Not a PNG file; not stored')
    out, i = [b[:8]], 8
    while True:
        if i + 8 > len(b):
            raise ValueError('PNG chunks end before IEND; not stored')
        n, typ = struct.unpack_from('>I4s', b, i)
        end = i + 12 + n
        if end > len(b):
            raise ValueError('PNG chunk runs past the end of the file; not stored')
        if typ not in PNG_DROP:
            out.append(b[i:end])
        i = end
        if typ == b'IEND':
            return b''.join(out)


def _webp(b):
    if len(b) < 12 or b[8:12] != b'WEBP':
        raise ValueError('Not a WebP file; not stored')
    size = struct.unpack_from('<I', b, 4)[0]
    if 8 + size > len(b):
        raise ValueError('WebP file is shorter than its RIFF header; not stored')
    end, i, chunks = 8 + size, 12, []
    while i < end:
        if i + 8 > end:
            raise ValueError('WebP chunk header runs past the end of the file; not stored')
        typ, n = struct.unpack_from('<4sI', b, i)
        if i + 8 + n > end:
            raise ValueError('WebP chunk runs past the end of the file; not stored')
        nxt = min(i + 8 + n + (n & 1), end)  # chunks are padded to an even length
        if typ == b'VP8X' and n >= 1:  # clear the EXIF (0x08) and XMP (0x04) flags
            chunks.append(b[i:i + 8] + bytes([b[i + 8] & ~0x0C]) + b[i + 9:nxt])
        elif typ not in (b'EXIF', b'XMP '):
            chunks.append(b[i:nxt])
        i = nxt
    payload = b'WEBP' + b''.join(chunks)
    return b'RIFF' + struct.pack('<I', len(payload)) + payload
