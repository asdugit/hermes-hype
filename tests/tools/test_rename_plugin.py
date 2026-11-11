"""tools/rename_plugin.py: the one-shot catalog rename (ISSUES #44) on synthetic trees."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rename_plugin", ROOT / "tools" / "rename_plugin.py")
assert SPEC and SPEC.loader
R = importlib.util.module_from_spec(SPEC)
sys.modules["rename_plugin"] = R
SPEC.loader.exec_module(R)


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    files = {
        "plugin.yaml": "name: showreel\nprovides_tools: [showreel_render, showreel_status]\n"
                       "homepage: https://github.com/asdugit/hermes-showreel\n",
        "__init__.py": 'PLUGIN = "showreel"\nfrom .showreel_core import handlers\n'
                       'ctx.register_command("showreel", h)\nctx.register_cli_command("showreel")\n',
        "showreel_core/env.py": 'ENV = "SHOWREEL_BLENDER"\nDATA = "plugin-data/showreel"\n'
                                'MSG = "A showreel is already rendering; use showreel_status."\n',
        "desktop/plugin.js": "const ID = 'showreel'\nconst label = 'Showreel: make a trailer of this chat'\n"
                             "import { sr } from '../runtime/showreel.js'\nconst t = job.title || 'Your showreel'\n"
                             "notify('Enable the showreel plugin', `/api/plugins/showreel/jobs`, 'plugin.showreel.job')\n",
        "skills/showreel/SKILL.md": '---\nname: showreel\ndescription: "Use when the user wants a demo reel or '
                                    'showreel of what was built."\n---\nA Showreel film. demo reel, "showreel" or\n',
        "README.md": "# Showreel\n`hermes plugins install asdugit/hermes-showreel` (not Duffey234/hermes-showreel)\n"
                     "Dev: ~/showreel-work and ~/showreel-scratch; a showreel of the session.\r\n",
        "runtime/showreel.js": "export const sr = {} // Showreel runtime\n",
        "assets/logo.png": "\x89PNG showreel",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("latin-1") if rel.endswith(".png") else text.encode("utf-8"))
    (root / "assets" / "bin.dat").write_bytes(b"showreel\x00\x01")
    (root / ".git").write_text("gitdir: C:/src/hermes-showreel/.git/worktrees/showreel\n", encoding="utf-8")
    return root


def test_rewrite_rules() -> None:
    t = R.rewrite
    assert t("/showreel lore and showreel_render, hermes showreel", "auteur", "Auteur") == \
        "/auteur lore and auteur_render, hermes auteur"
    assert t("SHOWREEL_DATA_DIR plugin.showreel.job", "trailer", "Trailer") == "TRAILER_DATA_DIR plugin.trailer.job"
    assert t("from showreel_core import x; '../runtime/showreel.js'", "auteur", "Auteur") == \
        "from showreel_core import x; '../runtime/showreel.js'"
    assert t("a Showreel film, the Showreel pane", "auteur", "Auteur") == "an Auteur film, the Auteur pane"
    assert t("a Showreel film", "trailer", "Trailer") == "a Trailer film"
    assert t("A showreel is rendering. Your showreels. No showreel yet.", "auteur", "Auteur") == \
        "A film is rendering. Your films. No film yet."
    assert t("Enable the showreel plugin", "auteur", "Auteur") == "Enable the auteur plugin"
    assert t("demo reel or showreel of it; demo reel, \"showreel\" or", "auteur", "Auteur") == \
        "demo reel or showreel of it; demo reel, \"showreel\" or"
    assert t("asdugit/hermes-showreel Duffey234/hermes-showreel", "auteur", "Auteur") == \
        "asdugit/hermes-showreel Duffey234/hermes-showreel"
    assert t("asdugit/hermes-showreel Duffey234/hermes-showreel", "auteur", "Auteur", repo_slug="auteur") == \
        "asdugit/auteur Duffey234/hermes-showreel"
    assert t('the manifest says "showreel.json"', "auteur", "Auteur") == 'the manifest says "auteur.json"'


def test_catalog_mode_drops_conflict_notes() -> None:
    yaml_text = ("name: showreel-studio\ntitle: Showreel Studio\n"
                 "known_issues:\n  - \"Cannot sit next to the other `showreel`.\"  # naming:conflict\n  - \"ok\"\n")
    out = R.rewrite(yaml_text, "auteur", "Auteur", catalog=True)
    assert out == "name: auteur\ntitle: Auteur\nknown_issues:\n  - \"ok\"\n"
    md = "# Add Showreel Studio\n<!-- naming:conflict -->\n> `showreel` is taken.\n<!-- /naming:conflict -->\nEnd\n"
    assert R.rewrite(md, "auteur", "Auteur", catalog=True) == "# Add Auteur\nEnd\n"
    assert R.new_path("showreel.template.yaml", "auteur", catalog=True) == "auteur.template.yaml"
    assert R.new_path("showreel-studio.yaml", "auteur", catalog=True) == "auteur.yaml"


def test_paths() -> None:
    assert R.new_path("skills/showreel/SKILL.md", "auteur") == "skills/auteur/SKILL.md"
    assert R.new_path("showreel_core/x.py", "auteur") == "showreel_core/x.py"
    assert R.new_path("runtime/showreel.js", "auteur") == "runtime/showreel.js"


def test_dry_run_apply_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert R.main(["--name", "auteur", "--title", "Auteur", "--root", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "move  skills/showreel/SKILL.md -> skills/auteur/SKILL.md" in out and "[dry run]" in out
    assert "edit  plugin.yaml" in out and "edit  desktop/plugin.js" in out and "logo.png" not in out
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before     # nothing written

    assert R.main(["--name", "auteur", "--title", "Auteur", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "still say" not in out                                                     # no stray 'showreel'
    assert (root / "plugin.yaml").read_text(encoding="utf-8").startswith(
        "name: auteur\nprovides_tools: [auteur_render, auteur_status]\nhomepage: https://github.com/asdugit/hermes")
    assert not (root / "skills" / "showreel").exists()
    skill = (root / "skills" / "auteur" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: auteur" in skill and "demo reel or showreel" in skill
    assert "an Auteur film" not in skill and "A Auteur" not in skill and "\nAn Auteur film." in skill
    js = (root / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "const ID = 'auteur'" in js and "'Auteur: make a trailer of this chat'" in js
    assert "runtime/showreel.js" in js and "'Your film'" in js and "/api/plugins/auteur/jobs" in js
    assert "Enable the auteur plugin" in js and "plugin.auteur.job" in js
    env = (root / "showreel_core" / "env.py").read_text(encoding="utf-8")
    assert '"AUTEUR_BLENDER"' in env and "plugin-data/auteur" in env and "A film is already rendering" in env
    readme = (root / "README.md").read_bytes()
    assert readme.endswith(b"a film of the session.\r\n") and b"showreel-work" in readme
    assert (root / "assets" / "logo.png").read_bytes() == "\x89PNG showreel".encode("latin-1")
    assert (root / "assets" / "bin.dat").read_bytes() == b"showreel\x00\x01"
    assert (root / ".git").read_text(encoding="utf-8").endswith("worktrees/showreel\n")   # worktree pointer

    snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert R.main(["--name", "auteur", "--title", "Auteur", "--root", str(root)]) == 0
    assert "0 file(s) to edit (0 lines), 0 to move" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == snapshot

    assert R.main(["--name", "auteur", "--title", "Auteur", "--root", str(root), "--repo-slug", "hermes-auteur"]) == 0
    assert "homepage: https://github.com/asdugit/hermes-auteur" in (root / "plugin.yaml").read_text(encoding="utf-8")
    assert "Duffey234/hermes-showreel" in (root / "README.md").read_text(encoding="utf-8")
    assert (root / ".git").read_text(encoding="utf-8").startswith("gitdir: C:/src/hermes-showreel/")


@pytest.mark.parametrize("args", [["--name", "Auteur"], ["--name", "my-film"], ["--name", "showreel"],
                                  ["--name", "auteur", "--title", "auteur"]])
def test_bad_names(args: list[str], tmp_path: Path) -> None:
    assert R.main([*args, "--root", str(tmp_path), "--dry-run"]) == 2


def test_cli_runs_standalone(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "rename_plugin.py"), "--name", "trailer", "--root",
                        str(root), "--dry-run", "--json"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert '"kind": "move"' in r.stdout and "skills/trailer/SKILL.md" in r.stdout


HYPE = R.Source("auteur", "Auteur")


def test_rename_again_from_a_previous_name() -> None:
    t = R.rewrite
    assert t("/auteur lore and auteur_render, hermes auteur, AUTEUR_BLENDER, plugin-data/auteur",
             "hype", "Hype", src=HYPE) == "/hype lore and hype_render, hermes hype, HYPE_BLENDER, plugin-data/hype"
    assert t("an Auteur film. An Auteur scene. the Auteur pane", "hype", "Hype", src=HYPE) == \
        "a Hype film. A Hype scene. the Hype pane"
    assert t("Enable the auteur plugin. An auteur plugin.", "hype", "Hype", src=HYPE) == \
        "Enable the hype plugin. A hype plugin."
    # internal names, the other author's plugin and the trigger phrases stay, whatever the source name
    kept = "from showreel_core import x; runtime/showreel.js; Duffey234/hermes-showreel; demo reel or showreel"
    assert t(kept, "hype", "Hype", src=HYPE) == kept
    # the repo slug: kept unless asked, then hermes-auteur -> hermes-hype
    assert t("asdugit/hermes-auteur", "hype", "Hype", src=HYPE) == "asdugit/hermes-auteur"
    assert t("asdugit/hermes-auteur", "hype", "Hype", src=HYPE, repo_slug="hermes-hype") == "asdugit/hermes-hype"
    # no common-noun rule for a name that isn't a word for a film
    assert t("Your auteur", "hype", "Hype", src=HYPE) == "Your hype"
    assert R.new_path("skills/auteur/SKILL.md", "hype", src=HYPE) == "skills/hype/SKILL.md"
    assert R.new_path("auteur.template.yaml", "hype", catalog=True, src=HYPE) == "hype.template.yaml"
    assert R.new_path("showreel_core/x.py", "hype", src=HYPE) == "showreel_core/x.py"


def test_cli_from_auteur(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)
    assert R.main(["--name", "auteur", "--title", "Auteur", "--root", str(root), "--repo-slug", "hermes-auteur"]) == 0
    assert R.main(["--from", "auteur", "--name", "hype", "--title", "Hype", "--root", str(root),
                   "--repo-slug", "hermes-hype"]) == 0
    out = capsys.readouterr().out
    assert "still say" not in out
    assert (root / "plugin.yaml").read_text(encoding="utf-8") == \
        "name: hype\nprovides_tools: [hype_render, hype_status]\nhomepage: https://github.com/asdugit/hermes-hype\n"
    skill = (root / "skills" / "hype" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: hype" in skill and "demo reel or showreel" in skill and "\nA Hype film." in skill
    js = (root / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert "const ID = 'hype'" in js and "runtime/showreel.js" in js and "Enable the hype plugin" in js
    assert '"HYPE_BLENDER"' in (root / "showreel_core" / "env.py").read_text(encoding="utf-8")
    assert not (root / "skills" / "auteur").exists()
    assert R.main(["--from", "auteur", "--name", "hype", "--root", str(root)]) == 0
    assert "0 file(s) to edit (0 lines), 0 to move" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--from", "auteur", "--name", "auteur"], ["--from", "Auteur", "--name", "hype"],
                                  ["--from", "hype", "--name", "hyper"]])
def test_bad_from(args: list[str], tmp_path: Path) -> None:
    assert R.main([*args, "--root", str(tmp_path), "--dry-run"]) == 2
