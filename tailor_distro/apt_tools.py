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
Dir::Etc::trusted "trusted.gpg";
Dir::Etc::trustedparts "trusted.gpg.d";
Dir::Etc::preferencesparts "preferences.d";
Dir::State "var/lib/apt";
Dir::Cache "var/cache/apt";
Dir::Cache::archives "archives";
APT::Architecture "{arch}";
Acquire::AllowInsecureRepositories "true";
"""


class AptSandbox:
    def __init__(self, sources: List[str], local_configs: List[Path] = []):
        self.root = Path(tempfile.mkdtemp(prefix="aptsandbox-"))

        for path in ["etc/apt", "etc/apt/preferences.d", "etc/apt/trusted.gpg.d", "var/lib/apt/lists", "var/cache/apt/archives", "var/cache/apt/archives/partial"]:
            (self.root / path).mkdir(parents=True, exist_ok=True)

        self._copy_host_apt_trust()

        (self.root / "etc/apt/sources.list").write_text(
            "\n".join(sources) + "\n"
        )

        (self.root / "etc/apt/apt.conf").write_text(
            APT_CONFIG_TEMPLATE.format(root=self.root, arch="amd64")
        )

        for local_path in local_configs:
            if not local_path.is_absolute():
                raise Exception(f"Path for local configs must be absolute: {local_path}")
            if not local_path.exists():
                raise Exception(f"Path does not exist: {local_path}")

            sandbox_path = self.root / local_path.relative_to(Path("/"))

            if local_path.is_dir():
                sandbox_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(local_path, sandbox_path, dirs_exist_ok=True)
                continue
            elif local_path.is_file():
                sandbox_path.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy(local_path, sandbox_path)

        dpkg_dir = self.root / "var/lib/dpkg"
        dpkg_dir.mkdir(parents=True, exist_ok=True)
        (dpkg_dir / "status").touch()

        # Run apt-get update (sandboxed)
        try:
            subprocess.run(
                [
                    "apt-get",
                    "-o", f"Dir={self.root}",
                    "-o", "Dir::Etc=etc/apt",
                    "-o", "Dir::Etc::preferencesparts=preferences.d",
                    "-o", "Dir::State=var/lib/apt",
                    "-o", "Dir::Cache=var/cache/apt",
                    "-o", "Dir::Cache::archives=archives",
                    "update",
                ],
                check=True
            )
        except subprocess.CalledProcessError:
            print("Could not run apt update, repo may not exist yet")

    def _copy_host_apt_trust(self):
        trusted_keyring = Path("/etc/apt/trusted.gpg")
        if trusted_keyring.exists():
            shutil.copy(trusted_keyring, self.root / "etc/apt/trusted.gpg")

        trusted_parts = Path("/etc/apt/trusted.gpg.d")
        if trusted_parts.exists():
            shutil.copytree(trusted_parts, self.root / "etc/apt/trusted.gpg.d", dirs_exist_ok=True)

    @property
    def cache(self):
        return apt.Cache(rootdir=str(self.root))
