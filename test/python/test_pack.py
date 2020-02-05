#!/usr/bin/python3

import os
import pytest
import subprocess
import tarfile
import re
import shutil

from utils import basepath
from utils import tarantool_enterprise_is_used
from utils import find_archive
from utils import recursive_listdir
from utils import assert_distribution_dir_contents
from utils import assert_filemodes
from utils import assert_files_mode_and_owner_rpm
from utils import validate_version_file
from utils import check_package_files
from utils import assert_tarantool_dependency_deb
from utils import assert_tarantool_dependency_rpm


# #############
# Class Archive
# #############
class Archive:
    def __init__(self, filepath, project):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.project = project


# ########
# Fixtures
# ########
@pytest.fixture(scope="function")
def tgz_archive(tmpdir, light_project):
    project = light_project

    cmd = [os.path.join(basepath, "cartridge"), "pack", "tgz", project.path]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0, \
        "Error during creating of tgz archive with project"

    filepath = find_archive(tmpdir, project.name, 'tar.gz')
    assert filepath is not None, "TGZ archive isn't found in work directory"

    return Archive(filepath=filepath, project=project)


@pytest.fixture(scope="function")
def rpm_archive(tmpdir, light_project):
    project = light_project

    cmd = [os.path.join(basepath, "cartridge"), "pack", "rpm", project.path]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0, \
        "Error during creating of rpm archive with project"

    filepath = find_archive(tmpdir, project.name, 'rpm')
    assert filepath is not None, "RPM archive isn't found in work directory"

    return Archive(filepath=filepath, project=project)


@pytest.fixture(scope="function")
def deb_archive(tmpdir, light_project):
    project = light_project

    cmd = [os.path.join(basepath, "cartridge"), "pack", "deb", project.path]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0, \
        "Error during creating of deb archive with project"

    filepath = find_archive(tmpdir, project.name, 'deb')
    assert filepath is not None, "DEB archive isn't found in work directory"

    return Archive(filepath=filepath, project=project)


@pytest.fixture(scope="function")
def rpm_archive_with_custom_units(tmpdir, light_project):
    project = light_project

    unit_template = '''
[Unit]
Description=Tarantool service: ${name}
SIMPLE_UNIT_TEMPLATE
[Service]
Type=simple
ExecStart=${dir}/tarantool ${dir}/init.lua

Environment=TARANTOOL_WORK_DIR=${workdir}
Environment=TARANTOOL_CONSOLE_SOCK=/var/run/tarantool/${name}.control
Environment=TARANTOOL_PID_FILE=/var/run/tarantool/${name}.pid
Environment=TARANTOOL_INSTANCE_NAME=${name}

[Install]
WantedBy=multi-user.target
Alias=${name}
    '''

    instantiated_unit_template = '''
[Unit]
Description=Tarantool service: ${name} %i
INSTANTIATED_UNIT_TEMPLATE

[Service]
Type=simple
ExecStartPre=mkdir -p ${workdir}.%i
ExecStart=${dir}/tarantool ${dir}/init.lua

Environment=TARANTOOL_WORK_DIR=${workdir}.%i
Environment=TARANTOOL_CONSOLE_SOCK=/var/run/tarantool/${name}.%i.control
Environment=TARANTOOL_PID_FILE=/var/run/tarantool/${name}.%i.pid
Environment=TARANTOOL_INSTANCE_NAME=${name}@%i

[Install]
WantedBy=multi-user.target
Alias=${name}
    '''
    unit_template_filepath = os.path.join(tmpdir, "unit_template.tmpl")
    with open(unit_template_filepath, 'w') as f:
        f.write(unit_template)

    inst_unit_template_filepath = os.path.join(tmpdir, "instantiated_unit_template.tmpl")
    with open(inst_unit_template_filepath, 'w') as f:
        f.write(instantiated_unit_template)

    process = subprocess.run([
            os.path.join(basepath, "cartridge"), "pack", "rpm",
            "--unit_template", "unit_template.tmpl",
            "--instantiated_unit_template", "instantiated_unit_template.tmpl",
            project.path
        ],
        cwd=tmpdir
    )
    assert process.returncode == 0, \
        "Error during creating of rpm archive with project"

    filepath = find_archive(tmpdir, project.name, 'rpm')
    assert filepath is not None, "RPM archive isn't found in work directory"

    return Archive(filepath=filepath, project=project)


# #####
# Tests
# #####
def test_tgz_pack(tgz_archive, tmpdir):
    project = tgz_archive.project

    # archive files should be extracted to the empty directory
    # to correctly check archive contents
    extract_dir = os.path.join(tmpdir, 'extract')
    os.makedirs(extract_dir)

    with tarfile.open(name=tgz_archive.filepath) as tgz_arch:
        # usr/share/tarantool is added to correctly run assert_filemodes
        distribution_dir = os.path.join(extract_dir, 'usr/share/tarantool', project.name)
        os.makedirs(distribution_dir, exist_ok=True)

        tgz_arch.extractall(path=os.path.join(extract_dir, 'usr/share/tarantool'))
        assert_distribution_dir_contents(
            dir_contents=recursive_listdir(distribution_dir),
            project=project
        )

        validate_version_file(project, distribution_dir)
        assert_filemodes(project, extract_dir)


def test_rpm_pack(rpm_archive, tmpdir):
    project = rpm_archive.project

    # archive files should be extracted to the empty directory
    # to correctly check archive contents
    extract_dir = os.path.join(tmpdir, 'extract')
    os.makedirs(extract_dir)

    ps = subprocess.Popen(
        ['rpm2cpio', rpm_archive.filepath], stdout=subprocess.PIPE)
    subprocess.check_output(['cpio', '-idmv'], stdin=ps.stdout, cwd=extract_dir)
    ps.wait()
    assert ps.returncode == 0, "Error during extracting files from rpm archive"

    if not tarantool_enterprise_is_used():
        assert_tarantool_dependency_rpm(rpm_archive.filepath)

    check_package_files(project, extract_dir)
    assert_files_mode_and_owner_rpm(project, rpm_archive.filepath)

    # check rpm signature
    cmd = [
        'rpm', '--checksig', '-v', rpm_archive.filepath
    ]
    process = subprocess.run(cmd)
    assert process.returncode == 0, "RPM signature isn't correct"


def test_deb_pack(deb_archive, tmpdir):
    project = deb_archive.project

    # archive files should be extracted to the empty directory
    # to correctly check archive contents
    extract_dir = os.path.join(tmpdir, 'extract')
    os.makedirs(extract_dir)

    # unpack ar
    process = subprocess.run([
            'ar', 'x', deb_archive.filepath
        ],
        cwd=extract_dir
    )
    assert process.returncode == 0, 'Error during unpacking of deb archive'

    for filename in ['debian-binary', 'control.tar.xz', 'data.tar.xz']:
        assert os.path.exists(os.path.join(extract_dir, filename))

    # check debian-binary
    with open(os.path.join(extract_dir, 'debian-binary')) as debian_binary_file:
        assert debian_binary_file.read() == '2.0\n'

    # check data.tar.xz
    with tarfile.open(name=os.path.join(extract_dir, 'data.tar.xz')) as data_arch:
        data_dir = os.path.join(extract_dir, 'data')
        data_arch.extractall(path=data_dir)
        check_package_files(project, data_dir)
        assert_filemodes(project, data_dir)

    # check control.tar.xz
    with tarfile.open(name=os.path.join(extract_dir, 'control.tar.xz')) as control_arch:
        control_dir = os.path.join(extract_dir, 'control')
        control_arch.extractall(path=control_dir)

        for filename in ['control', 'preinst', 'postinst']:
            assert os.path.exists(os.path.join(control_dir, filename))

        if not tarantool_enterprise_is_used():
            assert_tarantool_dependency_deb(os.path.join(control_dir, 'control'))

        # check if postinst script set owners correctly
        with open(os.path.join(control_dir, 'postinst')) as postinst_script_file:
            postinst_script = postinst_script_file.read()
            assert 'chown -R root:root /usr/share/tarantool/{}'.format(project.name) in postinst_script
            assert 'chown root:root /etc/systemd/system/{}.service'.format(project.name) in postinst_script
            assert 'chown root:root /etc/systemd/system/{}@.service'.format(project.name) in postinst_script
            assert 'chown root:root /usr/lib/tmpfiles.d/{}.conf'.format(project.name) in postinst_script


def test_systemd_units(rpm_archive_with_custom_units, tmpdir):
    project = rpm_archive_with_custom_units.project

    # archive files should be extracted to the empty directory
    # to correctly check archive contents
    extract_dir = os.path.join(tmpdir, 'extract')
    os.makedirs(extract_dir)

    ps = subprocess.Popen(
        ['rpm2cpio', rpm_archive_with_custom_units.filepath], stdout=subprocess.PIPE)
    subprocess.check_output(['cpio', '-idmv'], stdin=ps.stdout, cwd=extract_dir)
    ps.wait()
    assert ps.returncode == 0, "Error during extracting files from rpm archive"

    project_unit_file = os.path.join(extract_dir, 'etc/systemd/system', "%s.service" % project.name)
    with open(project_unit_file) as f:
        assert f.read().find('SIMPLE_UNIT_TEMPLATE') != -1

    project_inst_file = os.path.join(extract_dir, 'etc/systemd/system', "%s@.service" % project.name)
    with open(project_inst_file) as f:
        assert f.read().find('INSTANTIATED_UNIT_TEMPLATE') != -1

    project_tmpfiles_conf_file = os.path.join(extract_dir, 'usr/lib/tmpfiles.d', '%s.conf' % project.name)
    with open(project_tmpfiles_conf_file) as f:
        assert f.read().find('d /var/run/tarantool') != -1


def test_packing_without_git(project_without_dependencies, tmpdir):
    project = project_without_dependencies

    # remove .git directory
    shutil.rmtree(os.path.join(project.path, '.git'))

    # try to build rpm w/o --version
    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", "rpm",
        project.path,
    ]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 1

    # pass version explicitly
    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", "rpm",
        "--version", "0.1.0",
        project.path,
    ]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0
    assert '{}-0.1.0-0.rpm'.format(project.name) in os.listdir(tmpdir)


def test_packing_with_git_file(project_without_dependencies, tmpdir):
    project = project_without_dependencies

    # remove .git directory
    shutil.rmtree(os.path.join(project.path, '.git'))

    # create file with name .git
    git_filepath = os.path.join(project.path, '.git')
    with open(git_filepath, 'w') as f:
        f.write("I am .git file")

    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", "rpm",
        "--version", "0.1.0",  # we have to pass version explicitly
        project.path,
    ]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0


@pytest.mark.parametrize('version,pack_format,expected_postfix',
                         [
                             ('0.1.0', 'rpm', '0.1.0-0.rpm'),
                             ('0.1.0', 'deb', '0.1.0-0.deb'),
                             ('0.1.0-42', 'rpm', '0.1.0-42.rpm'),
                             ('0.1.0-42', 'deb', '0.1.0-42.deb'),
                             ('0.1.0-42-g8bce594e', 'rpm', '0.1.0-42-g8bce594e.rpm'),
                             ('0.1.0-42-g8bce594e', 'deb', '0.1.0-42-g8bce594e.deb'),
                             ('0.1.0-g8bce594e', 'rpm', '0.1.0-g8bce594e.rpm'),
                             ('0.1.0-g8bce594e', 'deb', '0.1.0-g8bce594e.deb'),
                         ])
def test_packing_with_version(project_without_dependencies, tmpdir, version, pack_format, expected_postfix):
    project = project_without_dependencies

    # pass version explicitly
    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", pack_format,
        "--version", version,
        project.path,
    ]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 0
    expected_file = '{name}-{postfix}'.format(name=project.name, postfix=expected_postfix)
    assert expected_file in os.listdir(tmpdir)


def test_packing_with_wrong_filemodes(project_without_dependencies, tmpdir):
    project = project_without_dependencies

    # add file with invalid (700) mode
    filepath = os.path.join(project.path, 'wrong-mode-file.lua')
    with open(filepath, 'w') as f:
        f.write("return 'My filemode is wrong'")
    os.chmod(filepath, 0o700)

    # run `cartridge pack`
    cmd = [os.path.join(basepath, "cartridge"), "pack", "rpm", project.path]
    process = subprocess.run(cmd, cwd=tmpdir)
    assert process.returncode == 1, "Packing project with invalid filemode must fail"


def test_builddir(project_without_dependencies, tmpdir):
    project = project_without_dependencies

    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", "rpm",
        project.path,
    ]

    env = os.environ.copy()

    # pass application path as a builddir
    env['CARTRIDGE_BUILDDIR'] = project.path
    process = subprocess.run(cmd, cwd=tmpdir, env=env)
    assert process.returncode == 1

    # pass application subdirectory as a builddir
    env['CARTRIDGE_BUILDDIR'] = os.path.join(project.path, 'sub', 'sub', 'directory')
    process = subprocess.run(cmd, cwd=tmpdir, env=env)
    assert process.returncode == 1

    # pass correct directory as a builddir
    builddir = os.path.join(tmpdir, 'build')
    env['CARTRIDGE_BUILDDIR'] = builddir
    process_output = subprocess.check_output(cmd, cwd=tmpdir, env=env)
    process_output = process_output.decode()
    assert re.search(r'[Bb]uild directory .+{}'.format(builddir), process_output) is not None


def test_packing_without_path_specifying(project_without_dependencies, tmpdir):
    project = project_without_dependencies

    # say `cartridge pack rpm` in project directory
    cmd = [
        os.path.join(basepath, "cartridge"),
        "pack", "rpm",
    ]
    process = subprocess.run(cmd, cwd=project.path)
    assert process.returncode == 0, 'Packing application failed'

    filepath = find_archive(project.path, project.name, 'rpm')
    assert filepath is not None,  'Package not found'
