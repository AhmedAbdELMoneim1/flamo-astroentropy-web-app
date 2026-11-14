"""Round 16 review 2 item 5: scripts/sync_flameo.sh must keep glossary.json (it used to rm -rf the vendor folder and not copy it back)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_flameo.sh"


def test_the_script_copies_glossary_json_and_checks_it():
    t = SCRIPT.read_text(encoding="utf-8")
    assert "glossary.json" in t.split("cp ", 1)[1].split("\n", 1)[0] and 'glossary.json missing after the sync' in t


def test_the_sync_keeps_glossary_json(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for n in ("registry.py", "tools.py", "README.md", "router_examples.yaml", "glossary.json"):
        (src / n).write_text("x")
    # run the script against a copy of the repo layout so the real vendor folder is not touched
    fake = tmp_path / "backend-api"
    (fake / "scripts").mkdir(parents=True)
    (fake / "vendor" / "flameo_tools").mkdir(parents=True)
    (fake / "scripts" / "sync_flameo.sh").write_text(SCRIPT.read_text(encoding="utf-8"))
    r = subprocess.run(["bash", str(fake / "scripts" / "sync_flameo.sh"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (fake / "vendor" / "flameo_tools" / "glossary.json").exists()
    (src / "glossary.json").unlink()
    r = subprocess.run(["bash", str(fake / "scripts" / "sync_flameo.sh"), str(src)], capture_output=True, text=True)
    assert r.returncode != 0
