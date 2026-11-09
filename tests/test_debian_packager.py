import shutil
import subprocess

import pytest

from debian_packager import (
    DEFAULT_MAINTAINER,
    changelog_maintainer,
    failed_strip_paths,
    is_strippable_elf,
    package_debian,
)
from debian_packager.debian_packager import _copy_no_overwrite


def test_copy_no_overwrite_succeeds_when_destination_absent(tmp_path):
    src = tmp_path / "src" / "file.txt"
    dst = tmp_path / "dst" / "file.txt"
    src.parent.mkdir()
    dst.parent.mkdir()
    src.write_text("hello")

    _copy_no_overwrite(str(src), str(dst))

    assert dst.read_text() == "hello"


def test_copy_no_overwrite_raises_when_destination_exists(tmp_path):
    src = tmp_path / "src" / "librectify.so"
    dst = tmp_path / "dst" / "librectify.so"
    src.parent.mkdir()
    dst.parent.mkdir()
    src.write_bytes(b"new")
    dst.write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="librectify.so"):
        _copy_no_overwrite(str(src), str(dst))

    assert dst.read_bytes() == b"existing"


@pytest.mark.parametrize("maintainers, expected", [
    ("James Prestwood <jprestwood@locusrobotics.com>", "James Prestwood <jprestwood@locusrobotics.com>"),
    # package.xml allows several maintainers, space joined by the graph
    ("A One <a@x.com> B Two <b@x.com>", "A One <a@x.com>"),
    ("nobody", DEFAULT_MAINTAINER),
    (None, DEFAULT_MAINTAINER),
])
def test_changelog_maintainer_picks_a_single_valid_maintainer(maintainers, expected):
    assert changelog_maintainer(maintainers) == expected


needs_debhelper = pytest.mark.skipif(
    shutil.which("dh_strip") is None or shutil.which("gcc") is None,
    reason="requires debhelper and gcc",
)


def stage_package(tmp_path, deb_name, with_binary):
    build_dir = tmp_path / "build"
    package_root = build_dir / "debian" / deb_name
    package_root.mkdir(parents=True)

    if with_binary:
        source = tmp_path / "hello.c"
        source.write_text("int main(void){ return 0; }\n")
        binary_dir = package_root / "opt" / "locusrobotics" / "hotdog" / "ros1" / "bin"
        binary_dir.mkdir(parents=True)
        subprocess.run(["gcc", "-g", "-o", str(binary_dir / "hello"), str(source)], check=True)

    return build_dir


@needs_debhelper
def test_package_debian_splits_debug_symbols_into_a_dbgsym_package(tmp_path):
    deb_name = "locusrobotics-hotdog-ros1-locus-base"
    build_dir = stage_package(tmp_path, deb_name, with_binary=True)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    artifacts = package_debian(
        deb_name, "1.2.3-20260929.020002+src0dabf00", "A package. A longer description.",
        "James Prestwood <jprestwood@locusrobotics.com>", "jammy", build_dir,
        output_dir=output_dir,
    )

    assert [path.name for path in artifacts] == [
        f"{deb_name}_1.2.3-20260929.020002+src0dabf00_amd64_jammy.deb",
        f"{deb_name}-dbgsym_1.2.3-20260929.020002+src0dabf00_amd64_jammy.deb",
    ]

    dbgsym_control = subprocess.run(
        ["dpkg-deb", "-f", str(artifacts[1])], check=True, capture_output=True, text=True,
    ).stdout
    assert "Auto-Built-Package: debug-symbols" in dbgsym_control
    assert f"Depends: {deb_name} (= 1.2.3-20260929.020002+src0dabf00)" in dbgsym_control
    assert "Build-Ids: " in dbgsym_control

    # The shipped package keeps the binary but not its DWARF.
    contents = subprocess.run(
        ["dpkg-deb", "-c", str(artifacts[0])], check=True, capture_output=True, text=True,
    ).stdout
    assert "/opt/locusrobotics/hotdog/ros1/bin/hello" in contents
    assert ".debug" not in contents


@needs_debhelper
def test_package_debian_skips_dbgsym_when_there_is_nothing_to_strip(tmp_path):
    deb_name = "locusrobotics-dev-hotdog"
    build_dir = stage_package(tmp_path, deb_name, with_binary=False)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    artifacts = package_debian(
        deb_name, "20260929.020002jammy", "Meta-package. Nothing to strip.",
        "James Prestwood <jprestwood@locusrobotics.com>", "jammy", build_dir,
        run_depends=["locusrobotics-hotdog-ros1-locus-base (= 1.0)"],
        output_dir=output_dir,
    )

    assert [path.name for path in artifacts] == [
        f"{deb_name}_20260929.020002jammy_amd64_jammy.deb",
    ]


@needs_debhelper
def test_package_debian_keeps_debug_info_when_nostrip_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("DEB_BUILD_OPTIONS", "nostrip")
    deb_name = "locusrobotics-hotdog-ros1-locus-base"
    build_dir = stage_package(tmp_path, deb_name, with_binary=True)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    artifacts = package_debian(
        deb_name, "1.2.3-20260929.020002+src0dabf00", "A package. A longer description.",
        "James Prestwood <jprestwood@locusrobotics.com>", "jammy", build_dir,
        output_dir=output_dir,
    )

    assert [path.name for path in artifacts] == [
        f"{deb_name}_1.2.3-20260929.020002+src0dabf00_amd64_jammy.deb",
    ]

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    subprocess.run(["dpkg-deb", "-x", str(artifacts[0]), str(extracted)], check=True)
    sections = subprocess.run(
        ["readelf", "-S", str(extracted / "opt/locusrobotics/hotdog/ros1/bin/hello")],
        check=True, capture_output=True, text=True,
    ).stdout
    assert ".debug_info" in sections


def build_shared_library(tmp_path, name, patches=()):
    source = tmp_path / "lib.c"
    source.write_text("int f(void){ return 1; }\n")
    library = tmp_path / name
    library.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gcc", "-g", "-shared", "-fPIC", "-o", str(library), str(source)], check=True)

    if patches:
        content = bytearray(library.read_bytes())
        for offset, value, width in patches:
            content[offset:offset + width] = value.to_bytes(width, "little")
        library.write_bytes(bytes(content))

    return library


@needs_debhelper
def test_package_debian_skips_binaries_objcopy_cannot_handle(tmp_path):
    deb_name = "locusrobotics-hotdog-ros1-orbbec-camera"
    build_dir = stage_package(tmp_path, deb_name, with_binary=True)
    prefix = build_dir / "debian" / deb_name / "opt/locusrobotics/hotdog/ros1"

    build_shared_library(prefix, "share/orbbec_camera/SDK/lib/arm64/libOrbbecSDK.so.2.7.6", ((18, 183, 2),))
    build_shared_library(
        prefix, "share/tycho_py/venv/lib/python3.10/site-packages/shapely/lib.cpython-310.so",
        ((0x3E, 0xFEFE, 2),),
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    artifacts = package_debian(
        deb_name, "1.0-20260929.185101+srcabc", "Orbbec Camera package. A longer description.",
        "Joe Dong <mocun@orbbec.com>", "jammy", build_dir, output_dir=output_dir,
    )

    assert len(artifacts) == 2

    # Only the package's own binary is split out; the vendored blobs are left alone.
    build_ids = subprocess.run(
        ["dpkg-deb", "-f", str(artifacts[1]), "Build-Ids"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert len(build_ids) == 1


# Verbatim from CI and from dh_strip locally. dh_strip drives both objcopy and
# strip, which take their input in different argument positions.
FOREIGN_ARCHITECTURE_STDERR = """\
objcopy: Unable to recognise the format of the input file `debian/pkg/opt/share/SDK/lib/arm64/libOrbbecSDK.so.2.7.6'
dh_strip: error: objcopy --only-keep-debug --compress-debug-sections debian/pkg/opt/share/SDK/lib/arm64/libOrbbecSDK.so.2.7.6 debian/.debhelper/pkg/dbgsym-root/usr/lib/debug/.build-id/c0/72ced.debug returned exit code 1
dh_strip: error: Aborting due to earlier error
"""

CORRUPT_STRING_TABLE_STDERR = """\
readelf: Error: no .dynamic section in the dynamic segment
objcopy: warning: debian/pkg/opt/venv/numpy.libs/libscipy_openblas64_.so has a corrupt string table index - ignoring
objcopy: unable to modify 'debian/pkg/opt/venv/numpy.libs/libscipy_openblas64_.so' due to errors
dh_strip: error: objcopy --only-keep-debug --compress-debug-sections debian/pkg/opt/venv/numpy.libs/libscipy_openblas64_.so debian/.debhelper/pkg/dbgsym-root/usr/lib/debug/.build-id/c3/51dd6.debug returned exit code 1
dh_strip: error: Aborting due to earlier error
"""

# strip puts the output behind -o, so the input is the last argument.
STRIP_FAILURE_STDERR = """\
strip: unable to modify 'debian/pkg/opt/venv/shapely/lib.cpython-310.so' due to errors
dh_strip: error: strip --remove-section=.comment --remove-section=.note -o /tmp/hGLLL_3nHD/stripowj4ap debian/pkg/opt/venv/shapely/lib.cpython-310.so returned exit code 1
dh_strip: error: Aborting due to earlier error
"""


@pytest.mark.parametrize("stderr, expected", [
    (FOREIGN_ARCHITECTURE_STDERR, ["debian/pkg/opt/share/SDK/lib/arm64/libOrbbecSDK.so.2.7.6"]),
    (CORRUPT_STRING_TABLE_STDERR, ["debian/pkg/opt/venv/numpy.libs/libscipy_openblas64_.so"]),
    (STRIP_FAILURE_STDERR, ["debian/pkg/opt/venv/shapely/lib.cpython-310.so"]),
])
def test_failed_strip_paths_reports_the_rejected_input(stderr, expected):
    assert failed_strip_paths(stderr, "debian/pkg/") == expected


def test_failed_strip_paths_ignores_unrelated_output():
    assert failed_strip_paths("dh_strip: error: Aborting due to earlier error\n", "debian/pkg/") == []


ELF_CORRUPTIONS = [
    # Vendored blob built for another architecture (EM_AARCH64).
    ("foreign architecture", 18, 183, 2),
    # Some manylinux wheels carry a section header string table index out of range.
    ("corrupt section header index", 0x3E, 0xFEFE, 2),
    # Section headers pointing past the end of the file.
    ("section headers past EOF", 0x28, 0x7FFFFFFF, 8),
]


@needs_debhelper
def test_is_strippable_elf_accepts_libraries_dh_strip_can_handle(tmp_path):
    assert is_strippable_elf(build_shared_library(tmp_path, "libnative.so"))

    # Vendored wheels are usually shipped already stripped, which is fine.
    prestripped = build_shared_library(tmp_path, "libprestripped.so")
    subprocess.run(["strip", "--strip-debug", str(prestripped)], check=True)
    assert is_strippable_elf(prestripped)


@needs_debhelper
@pytest.mark.parametrize("description, offset, value, width", ELF_CORRUPTIONS)
def test_is_strippable_elf_agrees_with_dh_strip(tmp_path, description, offset, value, width):
    """The probe has to run the same commands dh_strip does, or it mispredicts."""
    library = build_shared_library(tmp_path, "libvendored.so", ((offset, value, width),))

    assert not is_strippable_elf(library)

    extract_debug = subprocess.run(
        ["objcopy", "--only-keep-debug", "--compress-debug-sections",
         str(library), str(tmp_path / "out.debug")],
        capture_output=True,
    )
    strip_binary = subprocess.run(
        ["strip", "--strip-unneeded", "--remove-section=.comment", "--remove-section=.note",
         "-o", str(tmp_path / "out.stripped"), str(library)],
        capture_output=True,
    )
    assert extract_debug.returncode != 0 or strip_binary.returncode != 0


@needs_debhelper
def test_package_debian_handles_many_unstrippable_binaries_in_one_pass(tmp_path, capsys):
    """A virtualenv can hold far more bad wheels than the retry loop allows attempts."""
    deb_name = "locusrobotics-hotdog-ros1-locus-byte-tracker"
    build_dir = stage_package(tmp_path, deb_name, with_binary=True)
    prefix = build_dir / "debian" / deb_name / "opt/locusrobotics/hotdog/ros1"
    site_packages = "share/locus_byte_tracker/venv/lib/python3.10/site-packages"

    for index in range(40):
        description, offset, value, width = ELF_CORRUPTIONS[index % len(ELF_CORRUPTIONS)]
        build_shared_library(prefix, f"{site_packages}/numpy.libs/libvendored{index}.so",
                             ((offset, value, width),))

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    artifacts = package_debian(
        deb_name, "1.0-20260930.131942+srcabc", "Byte tracker. A longer description.",
        "Locus Robotics <tailor@locusrobotics.com>", "jammy", build_dir, output_dir=output_dir,
    )

    assert len(artifacts) == 2

    # Everything was excluded up front, so dh_strip only had to run once.
    assert "missed by probe" not in capsys.readouterr().out

    build_ids = subprocess.run(
        ["dpkg-deb", "-f", str(artifacts[1]), "Build-Ids"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert len(build_ids) == 1
