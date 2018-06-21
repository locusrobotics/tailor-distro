from datetime import datetime

from tailor_distro.publish_packages import build_deletion_list, version_date_format, PackageVersion

aptly_packages = [
    "package-1_20180101.100000bionic_amd64",
    "package-1_20180101.100000xenial_amd64",
    "package-1_20180102.100000bionic_amd64",
    "package-1_20180102.100000xenial_amd64",
    "package-1_20180102.200000bionic_amd64",
    "package-1_20180102.200000xenial_amd64",
    "package-1_20180103.100000bionic_amd64",
    "package-1_20180103.100000xenial_amd64",
    "package-1_20180103.300000bionic_amd64",
    "package-1_20180103.300000xenial_amd64",
    "package-2_20180102.100000xenial_amd64",
    "package-2_20180102.200000bionic_amd64",
    "package-2_20180102.200000xenial_amd64",
    "package-2_20180103.100000bionic_amd64",
    "package-2_20180103.100000xenial_amd64",
    "package-2_20180103.300000bionic_amd64",
    "package-2_20180103.300000xenial_amd64",
]

aptly_keep_last_two_num = {
    PackageVersion(package='package-1', version='20180101.100000'),
    PackageVersion(package='package-1', version='20180102.100000'),
    PackageVersion(package='package-1', version='20180102.200000'),
    PackageVersion(package='package-2', version='20180102.100000'),
    PackageVersion(package='package-2', version='20180102.200000'),
}

aptly_keep_last_two_days = {
    PackageVersion(package='package-1', version='20180101.100000'),
    PackageVersion(package='package-1', version='20180102.100000'),
    PackageVersion(package='package-2', version='20180102.100000'),
}


from_date = datetime.strptime('20180102.200000', version_date_format)


def test_num_to_keep():
    print(build_deletion_list(aptly_packages, num_to_keep=2))
    assert build_deletion_list(aptly_packages, num_to_keep=2) == aptly_keep_last_two_num


def test_date_to_keep():
    assert build_deletion_list(aptly_packages, date_to_keep=from_date) == aptly_keep_last_two_days


def test_num_date_to_keep():
    assert build_deletion_list(aptly_packages, date_to_keep=from_date, num_to_keep=2) == \
        aptly_keep_last_two_num | aptly_keep_last_two_days
