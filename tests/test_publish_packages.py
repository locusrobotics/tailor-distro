from datetime import datetime

from tailor_distro.publish_packages import build_deletion_list, version_date_format, PackageEntry

packages = [
    PackageEntry(name='package-1', version='20180101.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180102.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180102.200000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180103.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180103.300000asdf', arch='amd64'),

    PackageEntry(name='package-2', version='20180102.100000asdf', arch='amd64'),
    PackageEntry(name='package-2', version='20180102.200000asdf', arch='amd64'),
    PackageEntry(name='package-2', version='20180103.100000asdf', arch='amd64'),
    PackageEntry(name='package-2', version='20180103.300000asdf', arch='amd64'),
]

keep_last_two_num = {
    PackageEntry(name='package-1', version='20180101.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180102.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180102.200000asdf', arch='amd64'),

    PackageEntry(name='package-2', version='20180102.100000asdf', arch='amd64'),
    PackageEntry(name='package-2', version='20180102.200000asdf', arch='amd64'),
}

keep_last_two_days = {
    PackageEntry(name='package-1', version='20180101.100000asdf', arch='amd64'),
    PackageEntry(name='package-1', version='20180102.100000asdf', arch='amd64'),

    PackageEntry(name='package-2', version='20180102.100000asdf', arch='amd64'),
}


from_date = datetime.strptime('20180102.200000', version_date_format)


def test_num_to_keep():
    assert build_deletion_list(packages, num_to_keep=2, distribution="asdf") == keep_last_two_num


def test_date_to_keep():
    assert build_deletion_list(packages, date_to_keep=from_date, distribution="asdf") == keep_last_two_days


def test_num_date_to_keep():
    assert build_deletion_list(packages, date_to_keep=from_date, num_to_keep=2, distribution="asdf") == \
        keep_last_two_num | keep_last_two_days
