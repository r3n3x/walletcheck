"""The version must be the same in the code, the README and the newest CHANGELOG entry."""
import os
import re

import walletcheck as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_readme_shows_current_version():
    assert f"Current version: **{W.__version__}**" in read("README.md")


def test_changelog_newest_entry_is_current_version():
    newest = re.search(r"^## (\S+)", read("CHANGELOG.md"), re.M).group(1)
    assert newest == W.__version__
