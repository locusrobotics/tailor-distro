import re
import os
import shutil
import jinja2
import subprocess

from pathlib import Path
from typing import List

from tailor_distro.blossom import Graph

IGNORE_PATTERNS = [".catkin"]

def is_text_file(path, blocksize=512):
    """
    Rough equivalent of `grep -I`: detect binary files by checking for null bytes.
    """
    try:
        with open(path, 'rb') as f:
            chunk = f.read(blocksize)
        return b"\0" not in chunk
    except Exception:
        return False


def replace_in_file(path, replacements):
    """
    Safely replace text in a file in-place.
    `replacements` = [(old, new), ...]
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    new_content = content
    for old, new in replacements:
        new_content = old.sub(new, new_content)

    if new_content != content:
        # Preserve mode bits
        st = os.stat(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.chmod(path, st.st_mode)


def fix_local_paths(
    organization: str,
    release_label: str,
    distribution: str,
    staging_dir,
    install_dir
):
    """
    Replaces the local workspace paths in various package files with the correct
    /opt based path that they'll ultimately install into. With the prior monolithic
    debian the colcon install directory roughly matched what would get packaged
    into a debian. This is no longer the case.

    The install structure now is:
    <install_path>/<pkg>/... (lib/bin/share/etc)

    And we want it to be:
    <install_path>/{lib,bin,share,etc}/<pkg>/<local files>

    i.e. all the global package bins/libs should go at the root of the install
    path. This is handled when we copy the install tree for packaging, but the
    files internally within packages (cmake/venv) use the isolated install
    structure.

    """
    opt_prefix = f"/opt/{organization}/{release_label}/{distribution}"
    install_base = Path(install_dir).parent

    REPLACE_PATTERNS = [
        (re.compile(rf"{install_base}/([^\r\n/]+)/lib\b"), rf"{opt_prefix}/lib"),
        (re.compile(rf"{install_base}/([^\r\n/]+)/bin\b"), rf"{opt_prefix}/bin"),
        (re.compile(rf"{install_base}/([^\r\n/]+)/etc\b"), rf"{opt_prefix}/etc"),
        (re.compile(rf"{install_base}/([^\r\n/]+)/include\b"), rf"{opt_prefix}/include"),
        (re.compile(rf"{install_dir}"), rf"{opt_prefix}"),
        (re.compile(r"/opt/tailor_venv/bin/python3"), r"/usr/bin/python3")
    ]
    for root, dirs, files in os.walk(staging_dir):
        for name in files:
            path = os.path.join(root, name)

            # 1. Remove .pyc files
            if name.endswith(".pyc"):
                os.remove(path)
                continue

            # 2. Skip binary libs (.so, .so.X)
            if name.endswith(".so") or ".so." in name:
                continue

            # 3. Process only text files
            if not is_text_file(path):
                continue

            replace_in_file(path, REPLACE_PATTERNS)
# Taken from bloom to format the description:
# https://github.com/ros-infrastructure/bloom/blob/master/bloom/generators/debian/generator.py
def debianize_string(value):
    markup_remover = re.compile(r'<.*?>')
    value = markup_remover.sub('', value)
    value = re.sub(r'\s+', ' ', value)
    value = value.strip()
    return value


def format_description(value):
    """
    Format proper <synopsis, long desc> string following Debian control file
    formatting rules. Treat first line in given string as synopsis, everything
    else as a single, large paragraph.

    Future extensions of this function could convert embedded newlines and / or
    html into paragraphs in the Description field.

    https://www.debian.org/doc/debian-policy/ch-controlfields.html#s-f-Description
    """
    value = debianize_string(value)
    # NOTE: bit naive, only works for 'properly formatted' pkg descriptions (ie:
    #       'Text. Text'). Extra space to avoid splitting on arbitrary sequences
    #       of characters broken up by dots (version nrs fi).
    parts = value.split('. ', 1)
    if len(parts) == 1 or len(parts[1]) == 0:
        # most likely single line description
        return value
    # format according to rules in linked field documentation
    return u"{0}.\n {1}".format(parts[0], parts[1].strip())


def package_debian(
    deb_name: str,
    deb_version: str,
    description: str,
    maintainers: str,
    os_version: str,
    staging_dir: Path,
    depends: List[str] = [],
    installed_size: str | None = None
):
    # Create DEBIAN control directory
    debian_dir = staging_dir / "DEBIAN"
    debian_dir.mkdir()

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )

    context = {
        "debian_name": deb_name,
        "description": format_description(description),
        "debian_version": deb_version,
        "maintainer": maintainers,
    }

    if len(depends) > 0:
        context["run_depends"] = depends

    if installed_size:
        context["installed_size"] = installed_size

    control = env.get_template("control.j2")
    stream = control.stream(**context)
    stream.dump(str(debian_dir / "control"))

    p = subprocess.run(
        [
            "dpkg-deb",
            "--build",
            staging_dir,
            f"{deb_name}_{deb_version}_amd64_{os_version}.deb",
        ]
    )
    if p.returncode != 0:
        print(f"Failed to package {deb_name}")
        print((debian_dir / "control").read_text())
        raise RuntimeError(f"Failed to package {deb_name}")
