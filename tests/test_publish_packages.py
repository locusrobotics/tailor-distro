import pathlib

from datetime import datetime
from unittest import mock

from tailor_distro.publish_packages import build_deletion_list, build_publish_plan, publish_packages, version_date_format, PackageEntry
from tailor_distro import aptly_remove_packages, parse_deb_package_entry, s3_list_published_packages

packages = [
    PackageEntry(name='package-1', version='1.0.0-20180101.100000+gitaaaa', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180102.100000+gitbbbb', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180102.200000+gitcccc', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180103.100000+gitdddd', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180103.300000+giteeee', arch='amd64'),

    PackageEntry(name='package-2', version='1.0.0-20180102.100000+gitffff', arch='amd64'),
    PackageEntry(name='package-2', version='1.0.0-20180102.200000+git1111', arch='amd64'),
    PackageEntry(name='package-2', version='1.0.0-20180103.100000+git2222', arch='amd64'),
    PackageEntry(name='package-2', version='1.0.0-20180103.300000+git3333', arch='amd64'),
]

keep_last_two_num = {
    PackageEntry(name='package-1', version='1.0.0-20180101.100000+gitaaaa', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180102.100000+gitbbbb', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180102.200000+gitcccc', arch='amd64'),

    PackageEntry(name='package-2', version='1.0.0-20180102.100000+gitffff', arch='amd64'),
    PackageEntry(name='package-2', version='1.0.0-20180102.200000+git1111', arch='amd64'),
}

keep_last_two_days = {
    PackageEntry(name='package-1', version='1.0.0-20180101.100000+gitaaaa', arch='amd64'),
    PackageEntry(name='package-1', version='1.0.0-20180102.100000+gitbbbb', arch='amd64'),

    PackageEntry(name='package-2', version='1.0.0-20180102.100000+gitffff', arch='amd64'),
}


from_date = datetime.strptime('20180102.200000', version_date_format)


def test_num_to_keep():
    assert build_deletion_list(packages, num_to_keep=2, distribution="asdf") == keep_last_two_num


def test_date_to_keep():
    assert build_deletion_list(packages, date_to_keep=from_date, distribution="asdf") == keep_last_two_days


def test_num_date_to_keep():
    assert build_deletion_list(packages, date_to_keep=from_date, num_to_keep=2, distribution="asdf") == \
        keep_last_two_num | keep_last_two_days


def test_date_to_keep_skips_non_timestamp_versions():
    packages_with_plain_version = packages + [
        PackageEntry(name='package-3', version='0.0.1-0', arch='amd64'),
        PackageEntry(name='package-3', version='0.0.2-0', arch='amd64'),
    ]

    assert build_deletion_list(
        packages_with_plain_version,
        date_to_keep=from_date,
        distribution="asdf",
    ) == keep_last_two_days


def test_date_to_keep_supports_epoch_versions():
    epoch_packages = [
        PackageEntry(name='package-4', version='1:1.0.0-20180101.100000+gitabcd123', arch='amd64'),
        PackageEntry(name='package-4', version='1:1.0.0-20180103.100000+gitabcd123', arch='amd64'),
    ]

    assert build_deletion_list(
        epoch_packages,
        date_to_keep=from_date,
        distribution="asdf",
    ) == {
        PackageEntry(name='package-4', version='1:1.0.0-20180101.100000+gitabcd123', arch='amd64'),
    }


def test_build_publish_plan_collects_adds_and_deletes():
    to_add = [pathlib.Path('/tmp/package-a.deb'), pathlib.Path('/tmp/package-b.deb')]

    plan = build_publish_plan(
        packages=to_add,
        release_label='stable',
        apt_repo='s3://example-bucket',
        distribution='jammy',
        num_to_keep=2,
        existing_packages=packages,
    )

    assert plan.repo_name == 'stable-jammy'
    assert plan.packages_to_add == tuple(to_add)
    assert set(plan.packages_to_delete) == keep_last_two_num


def test_parse_deb_package_entry_supports_codename_suffix():
    assert parse_deb_package_entry(
        'locusrobotics-feature-per-package-ros1-a1_0.21.0-20260324.183130+git27dedc0_amd64_jammy.deb',
        distribution='jammy',
        package_prefix='locusrobotics-',
    ) == PackageEntry(
        name='locusrobotics-feature-per-package-ros1-a1',
        version='0.21.0-20260324.183130+git27dedc0',
        arch='amd64',
    )


def test_parse_deb_package_entry_rejects_wrong_distribution_and_prefix():
    assert parse_deb_package_entry(
        'docker-model-plugin_1.0.10-1~ubuntu.22.04~jammy_amd64_jammy.deb',
        distribution='jammy',
        package_prefix='locusrobotics-',
    ) is None

    assert parse_deb_package_entry(
        'locusrobotics-feature-per-package-ros1-a1_0.21.0-20260324.183130+git27dedc0_amd64_noble.deb',
        distribution='jammy',
        package_prefix='locusrobotics-',
    ) is None


def test_s3_list_published_packages_uses_history_and_deduplicates_entries():
    class FakePaginator:
        def paginate(self, **kwargs):
            assert kwargs == {
                'Bucket': 'example-bucket',
                'Prefix': 'stable/ubuntu/pool/',
            }
            return [
                {
                    'Versions': [
                        {
                            'Key': (
                                'stable/ubuntu/pool/jammy/l/lo/'
                                'locusrobotics-feature-per-package-ros1-a1_'
                                '0.21.0-20260324.183130+git27dedc0_amd64_jammy.deb'
                            )
                        },
                        {
                            'Key': (
                                'stable/ubuntu/pool/jammy/l/lo/'
                                'locusrobotics-feature-per-package-ros1-a1_'
                                '0.21.0-20260324.183130+git27dedc0_amd64_jammy.deb'
                            )
                        },
                        {
                            'Key': (
                                'stable/ubuntu/pool/jammy/l/lo/'
                                'locusrobotics-feature-per-package-ros1-a1_'
                                '0.21.0-20260507.130035+git83439a8_amd64_jammy.deb'
                            )
                        },
                    ]
                }
            ]

    fake_client = mock.Mock()
    fake_client.get_paginator.return_value = FakePaginator()

    with mock.patch('boto3.client', return_value=fake_client):
        assert s3_list_published_packages('s3://example-bucket', 'stable', 'jammy') == [
            PackageEntry(
                name='locusrobotics-feature-per-package-ros1-a1',
                version='0.21.0-20260324.183130+git27dedc0',
                arch='amd64',
            ),
            PackageEntry(
                name='locusrobotics-feature-per-package-ros1-a1',
                version='0.21.0-20260507.130035+git83439a8',
                arch='amd64',
            ),
        ]


def test_publish_packages_dry_run_uses_organization_prefix_for_s3_discovery():
    with mock.patch('tailor_distro.publish_packages.aptly_configure', return_value='endpoint'), \
            mock.patch('tailor_distro.publish_packages.s3_list_published_packages', return_value=[] ) as s3_list_mock, \
            mock.patch('tailor_distro.publish_packages.print_publish_plan'):
        publish_packages(
            packages=[],
            release_label='stable',
            apt_repo='s3://example-bucket',
            distribution='jammy',
            organization='acme',
            dry_run=True,
        )

    s3_list_mock.assert_called_once_with(
        's3://example-bucket',
        'stable',
        'jammy',
        package_prefix='acme-',
    )


def test_aptly_remove_packages_batches_large_commands():
    packages_to_remove = [
        PackageEntry(name='package-a', version='1.0.0-20180101.100000+gitaaaa', arch='amd64'),
        PackageEntry(name='package-b', version='1.0.0-20180101.100000+gitbbbb', arch='amd64'),
        PackageEntry(name='package-c', version='1.0.0-20180101.100000+gitcccc', arch='amd64'),
    ]

    with mock.patch('tailor_distro.run_command') as run_command_mock:
        aptly_remove_packages(
            'stable-jammy',
            packages_to_remove,
            max_command_chars=140,
        )

    assert run_command_mock.call_count == 3
