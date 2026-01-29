import tempfile
import subprocess
import apt
import shutil

from typing import List
from pathlib import Path

APT_CONFIG_TEMPLATE = """
Dir "{root}";
Dir::Etc "etc/apt";
Dir::Etc::sourcelist "sources.list";
Dir::Etc::authconf "auth.conf";
Dir::Etc::authconfparts "auth.conf.d";
Dir::State "var/lib/apt";
Dir::Cache "var/cache/apt";
APT::Architecture "{arch}";
Acquire::AllowInsecureRepositories "true";
"""


class AptSandbox:
    def __init__(self, sources: List[str]):
        self.root = Path(tempfile.mkdtemp(prefix="aptsandbox-"))

        for path in ["etc/apt", "var/lib/apt/lists", "var/cache/apt/archives"]:
            (self.root / path).mkdir(parents=True, exist_ok=True)

        (self.root / "etc/apt/sources.list").write_text(
            "\n".join(sources) + "\n"
        )

        (self.root / "etc/apt/apt.conf").write_text(
            APT_CONFIG_TEMPLATE.format(root=self.root, arch="amd64")
        )

        auth_src = Path("/etc/apt/auth.conf.d")
        auth_dst = Path(self.root) / "etc/apt/auth.conf.d"

        if auth_src.exists():
            auth_dst.mkdir(parents=True, exist_ok=True)
            for f in auth_src.iterdir():
                shutil.copy(f, auth_dst / f.name)

        dpkg_dir = self.root / "var/lib/dpkg"
        dpkg_dir.mkdir(parents=True, exist_ok=True)
        (dpkg_dir / "status").touch()

        # Run apt-get update (sandboxed)
        subprocess.run(
            [
                "apt-get",
                "-o", f"Dir={self.root}",
                "-o", "Dir::Etc=etc/apt",
                "-o", "Dir::State=var/lib/apt",
                "-o", "Dir::Cache=var/cache/apt",
                "update",
            ],
            check=True
        )

    @property
    def cache(self):
        return apt.Cache(rootdir=str(self.root))

if __name__ == "__main__":
    sources = [
        "deb [arch=amd64 trusted=yes] https://artifacts.locusbots.io/feature-per-package/ubuntu noble main",
        "deb [arch=amd64 trusted=yes] https://artifacts.locusbots.io/feature-per-package/ubuntu noble-mirror noble"
    ]


    apt_sandbox = AptSandbox(sources)

    print(apt_sandbox.cache["locusrobotics-feature-per-package-ros1-catkin"])
