import re
import os
import email.utils
import jinja2
import subprocess

from pathlib import Path
from typing import List


IGNORE_PATTERNS = [".catkin"]

DEFAULT_MAINTAINER = "Locus Robotics <tailor@locusrobotics.com>"

# dh_strip reports the full command it ran when a helper fails.
DH_STRIP_ERROR_PATTERN = re.compile(
    r"^dh_strip: error: (?P<arguments>.+) returned exit code \d+$", re.MULTILINE
)

# Bounds the exclude-and-retry loop; one attempt per unstrippable file, plus one.
MAX_STRIP_ATTEMPTS = 25

# package.xml allows several maintainers; debian/changelog accepts exactly one.
MAINTAINER_PATTERN = re.compile(r"[^<>]+<[^<>@\s]+@[^<>@\s]+>")

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


def retarget_symlink(link_path, replacements):
    """
    Apply the same replacements to a symlink's target string and recreate the link if changed.
    - `replacements` is [(compiled_regex, replacement_str), ...]
    """
    try:
        old_target = os.readlink(link_path)  # readlink does not dereference
    except OSError:
        return False

    new_target = old_target
    for pat, repl in replacements:
        new_target = pat.sub(repl, new_target)

    if new_target == old_target:
        return False  # no change

    # Preserve relative vs absolute semantics:
    link_dir = os.path.dirname(link_path)
    # If original target was absolute, keep absolute. If relative, keep relative.
    if not os.path.isabs(old_target) and os.path.isabs(new_target):
        # Convert absolute new_target back to a path relative to the link's directory
        try:
            abs_new = new_target
            # Compute a relative path that points to the absolute destination
            new_target = os.path.relpath(abs_new, start=link_dir)
        except Exception:
            # If relpath fails (shouldn't), fall back to absolute
            pass

    # Recreate the symlink atomically
    tmp = f"{link_path}.tmp.{os.getpid()}"
    try:
        os.symlink(new_target, tmp)
        os.replace(tmp, link_path)  # atomic on POSIX
    except Exception:
        # Cleanup tmp if anything goes wrong
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


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

            # Handle symlinks first (do NOT follow them)
            if os.path.islink(path):
                retarget_symlink(path, REPLACE_PATTERNS)
                continue

            # 1. Remove .pyc files
            if name.endswith(".pyc"):
                os.remove(path)
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


def changelog_maintainer(maintainers: str | None) -> str:
    if maintainers:
        match = MAINTAINER_PATTERN.search(maintainers)
        if match:
            return match.group(0).strip()
    return DEFAULT_MAINTAINER


def failed_strip_paths(stderr: str, package_prefix: str) -> List[str]:
    """Pull the files dh_strip could not process out of its error output.

    dh_strip shells out to both objcopy and strip, which take their input in
    different argument positions, so match on the staged package path instead.
    """
    paths = []

    for match in DH_STRIP_ERROR_PATTERN.finditer(stderr):
        for argument in match.group("arguments").split():
            if argument.startswith(package_prefix) and argument not in paths:
                paths.append(argument)

    return paths


def run_dh_strip(deb_name: str, build_dir: Path, dh_env: dict) -> List[str]:
    """Split debug symbols out, skipping any file the binutils helpers reject.

    Vendored third-party blobs are malformed in ways that are not reliably
    detectable up front - foreign architectures, truncated section headers,
    corrupt string tables. dh_strip aborts on the first one it hits and names
    it, so exclude what it reports and retry rather than trying to predict
    which files objcopy and strip will accept.
    """
    excluded: List[str] = []
    package_prefix = f"debian/{deb_name}/"

    for _ in range(MAX_STRIP_ATTEMPTS):
        command = ["dh_strip", "-p", deb_name, *(f"-X{path}" for path in excluded)]
        result = subprocess.run(
            command, cwd=build_dir, env=dh_env, capture_output=True, text=True
        )
        print(result.stdout, end="")

        if result.returncode == 0:
            return excluded

        rejected = [
            path for path in failed_strip_paths(result.stderr, package_prefix)
            if path not in excluded
        ]
        if not rejected:
            print(result.stderr, end="")
            raise RuntimeError(
                f"Failed to package {deb_name}: {' '.join(command)} exited with {result.returncode}"
            )

        for path in rejected:
            print(f"Not stripping {path}: binutils cannot process this file")
        excluded.extend(rejected)

    raise RuntimeError(f"Failed to package {deb_name}: dh_strip still failing after {MAX_STRIP_ATTEMPTS} attempts")


def rename_artifacts(output_dir: Path, deb_name: str, deb_version: str, os_version: str) -> List[Path]:
    """Rewrite debhelper's standard filenames into tailor's <name>_<version>_<arch>_<os>.deb convention."""
    # dpkg strips the epoch from filenames; tailor keeps it.
    file_version = deb_version.split(":", 1)[-1]
    artifacts = []

    for name in (deb_name, f"{deb_name}-dbgsym"):
        for suffix in (".deb", ".ddeb"):
            source = output_dir / f"{name}_{file_version}_amd64{suffix}"
            if not source.exists():
                continue
            target = output_dir / f"{name}_{deb_version}_amd64_{os_version}.deb"
            source.replace(target)
            artifacts.append(target)

    if not artifacts:
        raise RuntimeError(f"No debian artifacts produced for {deb_name}")

    return artifacts


def package_debian(
    deb_name: str,
    deb_version: str,
    description: str,
    maintainers: str,
    os_version: str,
    build_dir: Path,
    run_depends: List[str] | None = None,
    build_depends: List[str] | None = None,
    build_time: float | None = None,
    output_dir: Path | None = None
) -> List[Path]:
    """Build a binary .deb (plus an automatic -dbgsym .deb) from a debhelper-style build directory.

    `build_dir` is expected to already contain the staged package tree at
    `<build_dir>/debian/<deb_name>/`.
    """
    if run_depends is None:
        run_depends = []
    if build_depends is None:
        build_depends = []

    build_dir = Path(build_dir)
    output_dir = Path(output_dir) if output_dir is not None else Path.cwd()
    debian_dir = build_dir / "debian"
    debian_dir.mkdir(parents=True, exist_ok=True)

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

    if len(run_depends) > 0:
        context["run_depends"] = run_depends

    if len(build_depends) > 0:
        context["build_depends"] = build_depends

    if build_time:
        context["build_time"] = build_time

    control = env.get_template("control.j2")
    control.stream(**context).dump(str(debian_dir / "control"))

    changelog = env.get_template("changelog.j2")
    changelog.stream(
        debian_name=deb_name,
        debian_version=deb_version,
        distribution=os_version,
        maintainer=changelog_maintainer(maintainers),
        date=email.utils.formatdate(localtime=True),
    ).dump(str(debian_dir / "changelog"))

    # dh_strip moves DWARF out of the ELF objects into an automatic <name>-dbgsym
    # package; dh_gencontrol and dh_builddeb then emit both packages. Honours
    # DEB_BUILD_OPTIONS=nostrip / noautodbgsym as a kill switch.
    commands = [
        ["dh_gencontrol", "-p", deb_name],
        ["dh_builddeb", "-p", deb_name, f"--destdir={output_dir.resolve()}"],
    ]

    # debhelper reads this from the environment, not debian/control. Without it the
    # helpers try to chown to root, which fails for an unprivileged build.
    dh_env = dict(os.environ, DEB_RULES_REQUIRES_ROOT="no")

    try:
        run_dh_strip(deb_name, build_dir, dh_env)
    except FileNotFoundError as e:
        raise RuntimeError("dh_strip not found - the packaging image is missing debhelper") from e

    for command in commands:
        try:
            p = subprocess.run(command, cwd=build_dir, env=dh_env)
        except FileNotFoundError as e:
            raise RuntimeError(
                f"{command[0]} not found - the packaging image is missing debhelper"
            ) from e
        if p.returncode != 0:
            print(f"Failed to package {deb_name}: {' '.join(command)} exited with {p.returncode}")
            print((debian_dir / "control").read_text())
            raise RuntimeError(f"Failed to package {deb_name}")

    return rename_artifacts(output_dir, deb_name, deb_version, os_version)

def environment_package_name(organization: str, release_label: str, distribution: str):
    return f"{organization}-environment-{release_label}-{distribution}"

def environment_package_version(build_date: str, os_version: str):
    return f"{build_date}{os_version}"

def environment_debian_info(
    organization: str,
    release_label: str,
    distribution: str,
    build_date: str,
    os_version: str
):
    # Use >= so reused packages from a prior build don't conflict with a newer environment
    return f"{environment_package_name(organization, release_label, distribution)} (>= {environment_package_version(build_date, os_version)})"

def build_package_name(organization: str, release_label: str, distribution: str):
    return f"{organization}-{release_label}-{distribution}-build-tools"

def build_package_version(build_date: str, os_version: str):
    return f"{build_date}{os_version}"

def build_debian_info(
    organization: str,
    release_label: str,
    distribution: str,
    build_date: str,
    os_version: str
):
    return f"{build_package_name(organization, release_label, distribution)} (= {build_package_version(build_date, os_version)})"
