import json

from tools.repo_scanner import scan_repo


def test_scans_polyglot_repo(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "pom.xml").write_text("<project><properties><java.version>17</java.version></properties></project>")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(json.dumps({"name": "web", "scripts": {"start": "x"}, "devDependencies": {"typescript": "5"}}))
    (tmp_path / "worker").mkdir()
    (tmp_path / "worker" / "go.mod").write_text("module w\n\ngo 1.22\n")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package.json").write_text("{}")

    found = {a["name"]: a for a in scan_repo(str(tmp_path))}
    assert set(found) == {"api", "web", "worker"}
    assert found["api"]["tech"] == "java" and found["api"]["version"] == "17"
    assert found["web"]["tech"] == "typescript" and found["web"]["start_command"] == "npm start"
    assert found["worker"]["version"] == "1.22"
