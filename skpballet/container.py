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


def open_skp(src):
    """src: path or bytes. Raises ValueError for non-SKP or pre-2021 (MFC archive) files."""
    data = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    if data[:4] != MAGIC:
        raise SkpError("not a SketchUp file (bad magic)")
    z = data.find(b"PK\x03\x04", 4, 4096)
    if z < 0:
        raise SkpError("no embedded zip: SketchUp 2013-2020 (MFC archive) files are not supported yet")
    m = re.search(rb"\{\x00((?:[0-9]\x00|\.\x00)+)\}\x00", data[:z])
    ver = m.group(1).decode("utf-16-le") if m else "unknown"
    try:
        return SkpFile(ver, zipfile.ZipFile(io.BytesIO(data[z:])))
    except (zipfile.BadZipFile, NotImplementedError, OSError, EOFError) as e:
        raise SkpError("corrupt container: %s" % e)
