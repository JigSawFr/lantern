"""What the reference server reads of a Switch homebrew (.nro): its name,
author and version, from the control data (NACP) in its asset section
(SPEC.md Annex A.1). Nothing else, and defensively: every offset is checked
against the file's size before it is read, and a file that is not what it
claims gives None, never an exception.

The layout read here:

- at 0x10, the header: the magic "NRO0", then at 0x18 the size of the
  executable part, after which the assets begin;
- the asset header: the magic "ASET", a version, then three sections
  (icon, NACP, RomFS), each an offset (from the asset header) and a size,
  little-endian 64-bit integers;
- the NACP: 16 languages of 0x300 bytes (a name of 0x200, an author of
  0x100), then at 0x3060 the display version (0x10 bytes). Since firmware
  21.0.0, the byte at 0x3215 (TitlesDataFormat) may be 1: the title block,
  the first 0x3000 bytes, is then Deflate-compressed (raw, no zlib header):
  a little-endian 16-bit size at 0, the compressed bytes after it, which
  inflate to 32 languages of 0x300 bytes (0x6000). Inflating stops at that
  size, so a "zip bomb" costs nothing. Any other value of the byte: a format
  this reader does not know, read as no control data.

The NACP has no integer version: a homebrew's `build` comes from its
homebrew.json (SPEC.md Annex A.1), never from here.
"""
import io
import struct
import zlib

HEADER = 0x80               # NroStart and NroHeader
ASSET_HEADER = 0x38         # magic, version, then 3 x (offset, size)
NACP_NEEDED = 0x3216        # up to TitlesDataFormat, after the display version
TITLES = 0x3000             # the title block, 16 languages
TITLES_FORMAT = 0x3215      # 0: as is; 1: Deflate-compressed (21.0.0+)
INFLATED = 0x6000           # the compressed block inflates to 32 languages
ENTRY = 0x300


def text(raw, limit=512):
    """A NUL-terminated UTF-8 field, without control characters, cut to `limit` bytes."""
    raw = raw.split(b"\0", 1)[0]
    value = raw.decode("utf-8", errors="replace")
    value = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127).strip()
    return value.encode()[:limit].decode(errors="ignore")


def read_nro(f, size):
    """{"name", "author", "version"} of the .nro open in `f` (`size` bytes), or None."""
    try:
        f.seek(0)
        head = f.read(HEADER)
        if len(head) < HEADER or head[0x10:0x14] != b"NRO0":
            return None
        nro_size = struct.unpack_from("<I", head, 0x18)[0]
        if nro_size < HEADER or nro_size + ASSET_HEADER > size:
            return None         # no asset section: nothing to read
        f.seek(nro_size)
        assets = f.read(ASSET_HEADER)
        if len(assets) < ASSET_HEADER or assets[:4] != b"ASET":
            return None
        nacp_offset, nacp_size = struct.unpack_from("<QQ", assets, 0x18)
        start = nro_size + nacp_offset
        if nacp_size < NACP_NEEDED or nacp_offset > size or start + NACP_NEEDED > size:
            return None
        f.seek(start)
        nacp = f.read(NACP_NEEDED)
        if len(nacp) < NACP_NEEDED:
            return None
    except (OSError, ValueError, struct.error):
        return None
    titles = title_block(nacp)
    if titles is None:
        return None
    names = [(text(titles[i * ENTRY:i * ENTRY + 0x200]), text(titles[i * ENTRY + 0x200:(i + 1) * ENTRY]))
             for i in range(len(titles) // ENTRY)]
    # American English first, then the first language that has a name.
    name, author = next(((n, a) for n, a in names if n), ("", ""))
    info = {"name": name, "author": author or next((a for _, a in names if a), ""),
            "version": text(nacp[0x3060:0x3070], 16)}
    return {k: v for k, v in info.items() if v} or None


def title_block(nacp):
    """The NACP's languages, inflated when compressed; None for a format it does not know or a broken one."""
    fmt = nacp[TITLES_FORMAT]
    if fmt == 0:
        return nacp[:TITLES]
    if fmt != 1:
        return None
    size = struct.unpack_from("<H", nacp, 0)[0]
    if size == 0 or 2 + size > TITLES:
        return None
    inflater = zlib.decompressobj(-15)
    try:
        out = inflater.decompress(nacp[2:2 + size], INFLATED)
    except zlib.error:
        return None
    if not inflater.eof and not inflater.unconsumed_tail and len(out) < INFLATED:
        return None     # cut short: not a whole Deflate stream
    return out[:INFLATED - INFLATED % ENTRY]


def parse_nro(data):
    """read_nro() over bytes."""
    return read_nro(io.BytesIO(data), len(data))
