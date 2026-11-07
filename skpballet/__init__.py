"""skp-ballet: read SketchUp (.skp) files. Clean-room reader, MIT."""
__version__ = "0.1.0"
from .container import open_skp
from .tlv import parse_tlv, Node
