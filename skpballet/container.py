"""SKP outer container (SketchUp 2021+): UTF-16 header, then an embedded ZIP holding model.dat."""
import io
import os
import re
import struct
import zipfile
import zlib

MAGIC = b"\xff\xfe\xff\x0e"


class SkpError(ValueError):
    """Any problem with a file: bad, truncated, corrupt or unsupported input."""


class SkpFile:
    def __init__(self, version, zf):
        self.version = version
        self.zip = zf

    def names(self):
        return self.zip.namelist()

    def read(self, name):
        try:
            zi = self.zip.getinfo(name)
            if zi.file_size > MAX_MEMBER:   # zip bomb guard: zipfile never yields more than the declared size, so this bounds memory
                raise SkpError("zip member %s declares %d bytes (limit %d): refusing to inflate it" % (name, zi.file_size, MAX_MEMBER))
            return self.zip.read(zi)
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, OSError, KeyError, RuntimeError) as e:
            raise SkpError("cannot read %s: %s" % (name, e))

    @property
    def model_dat(self):
        return self.read("model.dat")


class LegacySkp:
    """SketchUp 2013-2020 (MFC archive) file: decoded by skpballet.legacy (experimental, geometry only)."""
    def __init__(self, version, data):
        self.version, self.data = version, data


MAX_MEMBER = 2 << 30   # largest zip member inflated into memory; real model.dat files are far smaller
MAX_BYTES = 4 << 30   # no real .skp is near this; refuse instead of reading an unbounded or device file into memory


def _read_regular(path):
    """Read a regular file only: a FIFO would block forever on open, /dev/zero would fill memory. O_NONBLOCK (where it exists)
    keeps the open of a FIFO from blocking; fstat then rejects anything that is not a regular file."""
    import stat
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SkpError("not a regular file (device, pipe or directory): %s" % os.path.basename(str(path)))
        if st.st_size > MAX_BYTES:
            raise SkpError("file is larger than %d GiB: refusing to read it into memory" % (MAX_BYTES >> 30))
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read()
    finally:
        os.close(fd)


def open_skp(src):
    """src: path or bytes. Raises ValueError for non-SKP or pre-2021 (MFC archive) files."""
    if isinstance(src, (bytes, bytearray)):
        data = src
    else:
        data = _read_regular(src)
    if data[:4] != MAGIC:
        raise SkpError("not a SketchUp file (bad magic)")
    z = data.find(b"PK\x03\x04", 4, 4096)
    if z < 0:
        v = re.search(rb"\{\x00((?:[0-9]\x00|\.\x00)+)\}\x00", data[:512])
        if not v:
            raise SkpError("no embedded zip and no version string: not a readable SketchUp file")
        return LegacySkp(v.group(1).decode("utf-16-le"), bytes(data))
    m = re.search(rb"\{\x00((?:[0-9]\x00|\.\x00)+)\}\x00", data[:z])
    ver = m.group(1).decode("utf-16-le") if m else "unknown"
    try:
        zf = zipfile.ZipFile(io.BytesIO(data[z:]))
        names = zf.namelist()
        if len(names) != len(set(names)):   # zipfile silently keeps the LAST of two equal names
            raise SkpError("corrupt container: duplicate zip member names")
        sk = SkpFile(ver, zf)
        eocd = data.rfind(b"PK\x05\x06")
        sk.container_notes = []
        if eocd >= 0 and len(data) >= eocd + 22:
            n_decl, c_decl = struct.unpack_from("<H", data, eocd + 10)[0], struct.unpack_from("<H", data, eocd + 20)[0]
            if n_decl != len(names):
                sk.container_notes.append("zip end record declares %d entries but the central directory has %d" % (n_decl, len(names)))
            if c_decl > len(data) - eocd - 22:
                sk.container_notes.append("zip end record declares a %d byte comment but only %d bytes follow it" % (c_decl, len(data) - eocd - 22))
        if ver == "unknown":
            sk.container_notes.append("version string in the file header is missing or damaged")
        if eocd >= 0 and len(data) > eocd + 22 + len(zf.comment):
            sk.container_notes.append("%d bytes after the end of the zip archive" % (len(data) - eocd - 22 - len(zf.comment)))
        try:
            mv = re.search(rb"\x75\x00\x08\x00\x00\x00([0-9]+\.[0-9]+\.[0-9]+)", zf.read("meta/meta.dat"))
        except (KeyError, zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError):
            mv = None
        if mv and ver != "unknown" and mv.group(1).decode() != ver:
            sk.container_notes.append("header version %s differs from meta/meta.dat version %s" % (ver, mv.group(1).decode()))
        if "meta/meta.dat" not in names:
            sk.container_notes.append("required member meta/meta.dat is missing")
        if not any(n.startswith("styles/") and n.endswith(".xml") for n in names):
            sk.container_notes.append("no styles/*.xml member")
        try:
            bad = zf.testzip()
        except (zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError, RuntimeError):
            bad = "?"
        if bad:
            sk.container_notes.append("zip member %s fails its CRC check" % bad)
        if zf.comment:
            sk.container_notes.append("zip comment present (%d bytes)" % len(zf.comment))
        return sk
    except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError, RuntimeError) as e:
        raise SkpError("corrupt container: %s" % e)
