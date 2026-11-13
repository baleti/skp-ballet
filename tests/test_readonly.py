"""The tool must never modify, replace or remove its input .skp."""
import glob, hashlib, os, shutil
import pytest
from skpballet import cli

DATA = os.path.join(os.path.dirname(__file__), "data")
FILES = sorted(glob.glob(os.path.join(DATA, "*.skp")) + glob.glob(os.path.join(DATA, "legacy", "*.skp")))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.mark.parametrize("src", FILES, ids=os.path.basename)
def test_commands_leave_input_untouched(src, tmp_path, capsys):
    f = str(tmp_path / "in.skp")
    shutil.copy(src, f)
    os.chmod(f, 0o444)
    before = sha(f)
    st = os.stat(f)
    cli.main(["info", f])
    cli.main(["info", "--json", f])
    cli.main(["convert", f, str(tmp_path / "o.glb")])
    cli.main(["cache", f, str(tmp_path / "cache")])
    assert sha(f) == before
    assert os.stat(f).st_mtime_ns == st.st_mtime_ns
    assert sorted(os.listdir(tmp_path)) == ["cache", "in.skp", "o.glb"]


def test_refuses_output_over_input(tmp_path, capsys):
    f = str(tmp_path / "in.skp")
    shutil.copy(FILES[0], f)
    before = sha(f)
    link = str(tmp_path / "link.glb")
    os.symlink(f, link)
    assert cli.main(["convert", f, f]) == 2
    assert cli.main(["convert", f, link]) == 2
    assert cli.main(["convert", f, str(tmp_path / "x.SKP")]) == 2
    assert sha(f) == before
