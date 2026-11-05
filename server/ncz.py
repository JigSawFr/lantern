"""What the reference server reads of a Switch .nsz: which NCZ extensions it
holds, so that the app says what it takes (SPEC.md Annex A.1, `requires`).
Nothing else, and defensively: every offset is checked against the file's
size before it is read, and a file that is not what it claims gives no
tokens, never an exception.

The layout read here:

- an .nsz is a PFS0 container: the magic "PFS0", a file count, the size of
  the string table, 4 reserved bytes; then one 0x18-byte entry per file (an
  offset and a size, little-endian 64-bit, then the file name's offset in the
  string table and 4 reserved bytes); the string table; the files, whose
  offsets count from the end of the string table;
- an .ncz file begins with the 0x4000 bytes of its NCA header, then a magic
  of 8 bytes: "NCZSECTN" (standard NSZ), "NCZSECT2" (a base stored sparse:
  `ncz-sparse`) or "NCZSECT3" (the platform's LZ4 blocks kept decompressed:
  `ncz-lz4`). Any other magic is read as no extension.

Only the header, the string table and 8 bytes per .ncz file are read.
"""
import struct

NCZ_MAGIC_AT = 0x4000       # after the NCA header
MAX_FILES = 4096            # a package holds a handful; a larger count is not read
MAX_STRINGS = 1 << 20
TOKENS = {b"NCZSECT2": "ncz-sparse", b"NCZSECT3": "ncz-lz4"}
ORDER = ("ncz-sparse", "ncz-lz4")


def requires(path):
    """The `requires` tokens of the .nsz at `path` (a list, empty for a standard one or a file not read)."""
    found = set()
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            head = f.read(16)
            if len(head) < 16 or head[:4] != b"PFS0":
                return []
            count, strings = struct.unpack_from("<II", head, 4)
            if count > MAX_FILES or strings > MAX_STRINGS:
                return []
            table = f.read(count * 0x18)
            names = f.read(strings)
            if len(table) < count * 0x18 or len(names) < strings:
                return []
            data = 16 + count * 0x18 + strings
            for i in range(count):
                offset, length, name = struct.unpack_from("<QQI", table, i * 0x18)
                end = names.find(b"\0", name) if name < strings else -1
                if end < 0 or not names[name:end].lower().endswith(b".ncz"):
                    continue
                at = data + offset
                if length < NCZ_MAGIC_AT + 8 or at + length > size:
                    continue
                f.seek(at + NCZ_MAGIC_AT)
                token = TOKENS.get(f.read(8))
                if token:
                    found.add(token)
    except (OSError, struct.error):
        return []
    return [t for t in ORDER if t in found]
