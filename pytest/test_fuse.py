# Copyright (c) 2024 Broadcom, Inc.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the “License”); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at:
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an “AS IS” BASIS, without warranties or
# conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
# specific language governing permissions and limitations under the License.


import hashlib
import os
import pytest
import shutil
import subprocess
import time


THIS_DIR = os.path.dirname(os.path.abspath(__file__))

VMDK_CONVERT=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
VMDK_FUSE=os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-fuse")
if not os.path.exists(VMDK_FUSE):
    # skip this if we haven't built vmdk-fuse
    pytestmark = pytest.mark.skip

WORK_DIR=os.path.join(os.getcwd(), "pytest-fuse")

IMAGE_FILE="dummy.img"
VMDK_FILE="dummy.vmdk"


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    image_file = os.path.join(WORK_DIR, IMAGE_FILE)
    vmdk_file = VMDK_FILE

    os.makedirs(WORK_DIR, exist_ok=True)

    process = subprocess.run(["dd", "if=/dev/zero", f"of={image_file}", "bs=1024", "count=1024"], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run(["mke2fs", image_file], cwd=WORK_DIR)
    assert process.returncode == 0

    process = subprocess.run([VMDK_CONVERT, image_file, vmdk_file], cwd=WORK_DIR)
    assert process.returncode == 0

    yield
    shutil.rmtree(WORK_DIR)


def _get_hash(filename, blocksz=1024 * 1024):
    hash_type = "sha256"
    hash = hashlib.new(hash_type)
    with open(filename, "rb") as f:
        while True:
            buf = f.read(blocksz)
            if not buf:
                break
            hash.update(buf)
    return hash.hexdigest()


def test_mount():
    image_file = os.path.join(WORK_DIR, IMAGE_FILE)
    vmdk_file = VMDK_FILE

    mounted_image_path = os.path.join(WORK_DIR, "mounted.img")

    with open(mounted_image_path, "w") as f:
        pass

    hash_orig = _get_hash(image_file)

    try:
        process = subprocess.run([VMDK_FUSE, f"--file={vmdk_file}", mounted_image_path], cwd=WORK_DIR)
        assert process.returncode == 0

        hash_mounted = _get_hash(mounted_image_path)
        assert hash_mounted == hash_orig

    finally:
        subprocess.run(["fusermount", "-u", mounted_image_path], cwd=WORK_DIR, check=True)
        assert not os.path.ismount(mounted_image_path)


def test_mount_ext2():
    vmdk_file = VMDK_FILE

    mounted_image_path = os.path.join(WORK_DIR, "mounted.img")
    mount_dir_path = os.path.join(WORK_DIR, "mntdir")

    with open(mounted_image_path, "w") as f:
        pass

    os.makedirs(mount_dir_path, exist_ok=True)

    try:
        process = subprocess.run([VMDK_FUSE, f"--file={vmdk_file}", mounted_image_path], cwd=WORK_DIR)
        assert process.returncode == 0

        process = subprocess.run(["fuse2fs", mounted_image_path, mount_dir_path])
        assert process.returncode == 0
    finally:
        subprocess.run(["fusermount", "-u", mount_dir_path], cwd=WORK_DIR)
        while os.path.ismount(mount_dir_path):
            time.sleep(0.1)
        # avoid device busy, which can happen even after checking if the unmount is complete (there should be a better way)
        time.sleep(0.1)
        subprocess.run(["fusermount", "-u", mounted_image_path], cwd=WORK_DIR)
