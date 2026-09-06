"""Shared ORDER thumbnail policy used by public fallback and offline backfill."""
from io import BytesIO
import hashlib

from PIL import Image, ImageOps

THUMB_MAX_EDGE = 480
THUMB_QUALITY = 85
THUMB_SUBSAMPLING = 0


def thumb_object_key(asset_sha256: str) -> str:
    value = str(asset_sha256 or '').strip().lower()
    if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('asset sha256 is invalid')
    return f'order-cloud/thumbs/{value[:2]}/{value}.jpg'


def make_thumb_bytes(source_bytes: bytes) -> tuple[bytes, tuple[int, int], str]:
    with Image.open(BytesIO(source_bytes)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', im.size, 'white')
            alpha = im.getchannel('A') if 'A' in im.getbands() else None
            bg.paste(im.convert('RGBA'), mask=alpha)
            im = bg
        else:
            im = im.convert('RGB')
        im.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
        out = BytesIO()
        try:
            im.save(out, format='JPEG', quality=THUMB_QUALITY, subsampling=THUMB_SUBSAMPLING, optimize=True, progressive=True)
        except OSError:
            out = BytesIO()
            im.save(out, format='JPEG', quality=THUMB_QUALITY, subsampling=THUMB_SUBSAMPLING, optimize=False, progressive=False)
        data = out.getvalue()
        return data, tuple(im.size), hashlib.sha256(data).hexdigest()
