"""Photo uploads lose their location and device metadata before storage (issue #411)."""
import hashlib, shutil, sqlite3, struct, tempfile, unittest
from pathlib import Path
from carlos import agent, config, photo_strip
from tests import fixture as fx

APP1, APP0, COM = 0xE1, 0xE0, 0xFE
XMP = b'http://ns.adobe.com/xap/1.0/\0<x:xmpmeta><exif:GPSLatitude>48,7N</exif:GPSLatitude></x:xmpmeta>'
JFIF = b'JFIF\0\x01\x01\0\0\x01\0\x01\0\0'
# a phone photo: EXIF with GPS, an XMP packet, a comment and the JFIF header
PHONE_JPEG = fx.jpeg([(APP0, JFIF), (APP1, fx.gps_exif()), (APP1, XMP), (COM, b'Taken at home')])


def segments(b):
    """(marker, payload) of the segments before the start of scan."""
    out, i = [], 2
    while b[i + 1] != 0xDA:
        n = struct.unpack_from('>H', b, i + 2)[0]
        out.append((b[i + 1], b[i + 4:i + 2 + n]))
        i += 2 + n
    return out


class StripTest(unittest.TestCase):
    def test_jpeg_loses_gps_xmp_comment_and_keeps_orientation(self):
        out = photo_strip.strip(PHONE_JPEG, 'jpg')
        for needle in (b'GPS', b'TestCam', b'home', b'xmpmeta'):
            self.assertNotIn(needle, out)
        self.assertEqual(segments(out), [(APP0, JFIF), (APP1, b'Exif\0\0MM\0*' + struct.pack('>I', 8) + struct.pack('>H', 1)
                                                      + struct.pack('>HHIHH', 0x0112, 3, 1, 6, 0) + struct.pack('>I', 0))])
        self.assertTrue(out.endswith(b'pixels\xff\xd9'))  # the image data is copied as is

    def test_jpeg_without_orientation_loses_the_whole_exif_block(self):
        self.assertEqual(photo_strip.strip(fx.jpeg([(APP1, b'Exif\0\0II*\0' + struct.pack('<I', 8) + struct.pack('<H', 0) + struct.pack('<I', 0))]), 'jpg'),
                         fx.jpeg())

    def test_jpeg_keeps_icc_profile(self):
        icc = b'ICC_PROFILE\0\x01\x01' + b'profile'
        self.assertEqual(segments(photo_strip.strip(fx.jpeg([(0xE2, icc), (APP1, fx.gps_exif())]), 'jpg')),
                         [(0xE2, icc), (APP1, b'Exif\0\0MM\0*' + struct.pack('>I', 8) + struct.pack('>H', 1)
                                        + struct.pack('>HHIHH', 0x0112, 3, 1, 6, 0) + struct.pack('>I', 0))])

    def test_png_text_chunks_and_time_are_removed(self):
        ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        body = fx.png([(b'IHDR', ihdr), (b'tEXt', b'Comment\0GPS 48.1 11.5'), (b'zTXt', b'Author\0\0x'), (b'iTXt', b'XML:com\0\0\0\0\0gps'),
                       (b'eXIf', fx.gps_exif()), (b'tIME', b'\x07\xe6\x0b\x16\x0c\x00\x00'), (b'IDAT', b'pixels'), (b'IEND', b'')])
        out = photo_strip.strip(body, 'png')
        self.assertEqual(out, fx.png([(b'IHDR', ihdr), (b'IDAT', b'pixels'), (b'IEND', b'')]))
        self.assertNotIn(b'GPS', out)

    def test_webp_exif_and_xmp_chunks_are_removed_and_flags_cleared(self):
        vp8x = bytes([0x0C | 0x20]) + b'\0\0\0' + b'\0\0\0\0\0\0'  # EXIF, XMP and ICC flags set
        exif, xmp = b'II*\0GPS' + b'\0' * 4, b'<x:xmpmeta>GPS</x:xmpmeta>'  # odd-length XMP is padded
        def chunk(typ, data):
            return typ + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b'')
        body = b'WEBP' + chunk(b'VP8X', vp8x) + chunk(b'EXIF', exif) + chunk(b'XMP ', xmp) + chunk(b'VP8 ', b'picture!')
        out = photo_strip.strip(b'RIFF' + struct.pack('<I', len(body)) + body, 'webp')
        kept = b'WEBP' + chunk(b'VP8X', bytes([0x20]) + vp8x[1:]) + chunk(b'VP8 ', b'picture!')
        self.assertEqual(out, b'RIFF' + struct.pack('<I', len(kept)) + kept)
        self.assertNotIn(b'GPS', out)

    def test_broken_files_are_refused(self):
        for body, ext in ((b'\xff\xd8\xff\xe0' + b'x' * 100, 'jpg'),                                   # APP0 length past the end
                          (b'\xff\xd8\xff\xe0', 'jpg'),                                          # segment header cut off
                          (b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 99) + b'tEXt', 'png'),           # chunk past the end
                          (b'\x89PNG\r\n\x1a\n' + fx.png([(b'IHDR', b'')])[8:], 'png'),              # no IEND
                          (b'RIFF\xff\xff\xff\xffWEBP', 'webp')):                                   # RIFF size past the end
            with self.subTest(ext=ext, head=body[:12]):
                with self.assertRaises(ValueError):
                    photo_strip.strip(body, ext)


class SaveMediaTest(unittest.TestCase):
    """The upload path: what save_media stores on disk and in the archive row."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        d = Path(self.tmp)
        self.saved = config.DB, config.MEDIA_DIR
        config.DB, config.MEDIA_DIR = d / 'cars.sqlite', d / 'media'
        fx.build(config.DB)
        self.c = sqlite3.connect(config.DB)

    def tearDown(self):
        self.c.close()
        config.DB, config.MEDIA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stored(self, media_id):
        rel = self.c.execute('SELECT file_path FROM listing_media WHERE id=?', (media_id,)).fetchone()[0]
        return (config.MEDIA_DIR / rel).read_bytes()

    def test_gps_photo_is_stored_without_location(self):
        media_id, created = agent.save_media(self.c, fx.CAR_A, PHONE_JPEG, {})
        self.assertTrue(created)
        data = self.stored(media_id)
        self.assertNotIn(b'GPS', data)
        self.assertNotIn(b'TestCam', data)
        self.assertEqual(self.c.execute('SELECT bytes, sha256 FROM listing_media WHERE id=?', (media_id,)).fetchone(),
                         (len(data), hashlib.sha256(data).hexdigest()))

    def test_png_with_text_chunk_is_stored_without_it(self):
        body = fx.png([(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)), (b'tEXt', b'Comment\0GPS here'), (b'IDAT', b'x'), (b'IEND', b'')])
        media_id, _ = agent.save_media(self.c, fx.CAR_A, body, {})
        self.assertNotIn(b'tEXt', self.stored(media_id))
        self.assertNotIn(b'GPS', self.stored(media_id))

    def test_non_image_and_broken_jpeg_are_refused_and_nothing_is_stored(self):
        with self.assertRaises(ValueError):
            agent.save_media(self.c, fx.CAR_A, b'<html>not a photo</html>', {})
        with self.assertRaises(ValueError):
            agent.save_media(self.c, fx.CAR_A, b'\xff\xd8\xff\xe1' + b'\0\x40' + b'short', {})
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM listing_media').fetchone()[0], 0)
        self.assertFalse(config.MEDIA_DIR.exists())


if __name__ == '__main__':
    unittest.main()
