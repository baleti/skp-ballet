"""SKP outer container (SketchUp 2021+): UTF-16 header, then an embedded ZIP holding model.dat."""
import io
import re
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
            return self.zip.read(name)
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, OSError, KeyError) as e:
            raise SkpError("cannot read %s: %s" % (name, e))

    @property
    def model_dat(self):
        return self.read("model.dat")


class LegacySkp:
    """SketchUp 2013-2020 (MFC archive) file: decoded by skpballet.legacy (experimental, geometry only)."""
    def __init__(self, version, data):
        self.version, self.data = version, data


def open_skp(src):
    """src: path or bytes. Raises ValueError for non-SKP or pre-2021 (MFC archive) files."""
    if isinstance(src, (bytes, bytearray)):
        data = src
    else:
        with open(src, "rb") as fh:
            data = fh.read()
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
        return SkpFile(ver, zipfile.ZipFile(io.BytesIO(data[z:])))
    except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError) as e:
        raise SkpError("corrupt container: %s" % e)
