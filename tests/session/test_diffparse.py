"""Patch parsing: unified diffs from Hermes results, V4A patches, replace-mode synthesis."""
from showreel_core.session import diffparse


def test_unified_single_file_counts_and_header():
    diff = ("--- a/src/app.py\n+++ b/src/app.py\n@@ -1,4 +1,5 @@ def main():\n import os\n-x = 1\n+x = 2\n+y = 3\n"
            " print(x)\n \n")
    (fp,) = diffparse.parse_unified(diff)
    assert fp["path"] == "src/app.py"
    assert (fp["adds"], fp["dels"]) == (2, 1)
    assert fp["hunks"][0]["header"].startswith("@@ -1,4 +1,5 @@")
    assert fp["hunks"][0]["lines"][0] == [" ", "import os"]


def test_unified_removed_line_that_looks_like_header_is_kept():
    diff = "--- a/notes.md\n+++ b/notes.md\n@@ -1,2 +1,1 @@\n--- old rule\n keep\n"
    (fp,) = diffparse.parse_unified(diff)
    assert fp["dels"] == 1 and fp["adds"] == 0
    assert fp["hunks"][0]["lines"][0] == ["-", "-- old rule"]


def test_unified_multi_file_and_windows_paths():
    diff = ("--- a/C:\\proj\\a.py\n+++ b/C:\\proj\\a.py\n@@ -1 +1 @@\n-a\n+b\n"
            "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n")
    a, b = diffparse.parse_unified(diff)
    assert a["path"] == "C:\\proj\\a.py" and (a["adds"], a["dels"]) == (1, 1)
    assert b["action"] == "add" and b["adds"] == 2


def test_v4a_update_add_delete_move():
    patch = ("*** Begin Patch\n*** Update File: src/a.py\n@@ def f():\n     x = 1\n-    return x\n+    return x + 1\n"
             "*** Add File: src/new.py\n+print('hi')\n+print('there')\n*** Delete File: old.py\n"
             "*** Update File: b.py\n*** Move to: c.py\n@@\n-a\n+b\n*** End Patch")
    files = diffparse.parse_v4a(patch)
    assert [f["action"] for f in files] == ["update", "add", "delete", "move"]
    assert (files[0]["adds"], files[0]["dels"]) == (1, 1)
    assert files[0]["hunks"][0]["header"] == "@@ def f():"
    assert files[1]["adds"] == 2 and files[1]["path"] == "src/new.py"
    assert files[3]["move_to"] == "c.py"


def test_synth_replace_has_context_and_blank_headers():
    (fp,) = diffparse.synth_replace("x.py", "a\nb\nc\nd", "a\nB\nc\nd")
    assert (fp["adds"], fp["dels"]) == (1, 1)
    assert all(h["header"] == "" for h in fp["hunks"])
    ops = [op for h in fp["hunks"] for op, _ in h["lines"]]
    assert " " in ops
