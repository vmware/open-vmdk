# Copyright (c) 2026 Broadcom.  All Rights Reserved.
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

# Tests for vmdk-convert with malformed and unusual input. These do not need
# any downloads.

import json
import os
import pytest
import struct
import subprocess


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR = os.path.join(os.getcwd(), "pytest-vmdk-robustness")

SECTOR_SIZE = 512
SPARSE_MAGICNUMBER = 0x564d444b
SPARSEFLAG_VALID_NEWLINE_DETECTOR = 1 << 0
SPARSEFLAG_COMPRESSED = 1 << 16
SPARSEFLAG_EMBEDDED_LBA = 1 << 17
DEFAULT_FLAGS = SPARSEFLAG_VALID_NEWLINE_DETECTOR | SPARSEFLAG_COMPRESSED | SPARSEFLAG_EMBEDDED_LBA

# generous timeout, to catch hangs
TIMEOUT = 60


def sparse_header(capacity, grain_size, descriptor_offset, descriptor_size,
                  num_gtes_per_gt, gd_offset, flags=DEFAULT_FLAGS, overhead=1):
    """Return a 512 byte sparse extent header (see vmware_vmdk.h)"""
    hdr = struct.pack("<IIIQQQQIQQQB4sH",
                      SPARSE_MAGICNUMBER, 3, flags,
                      capacity, grain_size, descriptor_offset, descriptor_size,
                      num_gtes_per_gt, 0, gd_offset, overhead,
                      0, b"\n \r\n", 1)
    return hdr + b"\0" * (SECTOR_SIZE - len(hdr))


def run_convert(args, **kwargs):
    process = subprocess.run([VMDK_CONVERT] + args, cwd=WORK_DIR,
                             capture_output=True, text=True,
                             timeout=TIMEOUT, **kwargs)
    # a negative return code means that we were killed by a signal (crash)
    assert process.returncode >= 0, f"vmdk-convert crashed with signal {-process.returncode}: {process.stderr}"
    return process


def write_file(name, data):
    path = os.path.join(WORK_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture(scope='module', autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)
    yield


def test_gdgt_size_overflow():
    """numGTEsPerGT is large enough to wrap the 32 bit grain table size computation"""
    num_gtes_per_gt = 1 << 31
    num_gts = 256
    gd = struct.pack(f"<{num_gts}I", *([3] * num_gts))
    data = sparse_header(num_gts * num_gtes_per_gt, 1, 0, 0, num_gtes_per_gt, 1) + gd + b"A" * 200000
    path = write_file("gdgt-overflow.vmdk", data)

    # the header must be rejected, so the file is handled as a flat image
    process = run_convert(["-i", "gdgt-overflow.vmdk"])
    assert process.returncode == 0
    info = json.loads(process.stdout)
    assert info["capacity"] == os.path.getsize(path)


def make_vmdk(name, data, args=[]):
    """Write data to a raw image and convert it to a VMDK with the given name"""
    raw_name = name + ".raw"
    write_file(raw_name, data)
    process = run_convert(args + [raw_name, name])
    assert process.returncode == 0, process.stderr
    return os.path.join(WORK_DIR, name)


def replace_descriptor(path, descriptor):
    """Overwrite the descriptor of a sparse VMDK in place"""
    with open(path, "r+b") as f:
        hdr = f.read(SECTOR_SIZE)
        descriptor_offset, descriptor_size = struct.unpack_from("<QQ", hdr, 28)
        assert len(descriptor) <= descriptor_size * SECTOR_SIZE
        f.seek(descriptor_offset * SECTOR_SIZE)
        f.write(descriptor + b"\0" * (descriptor_size * SECTOR_SIZE - len(descriptor)))


def get_descriptor(name):
    process = run_convert(["--get-descriptor", name])
    assert process.returncode == 0
    return process.stdout.encode()


def test_descriptor_long_entry():
    """a descriptor entry larger than twice the initial JSON buffer"""
    path = make_vmdk("desc-long.vmdk", os.urandom(65536))
    long_value = "V" * 5000
    replace_descriptor(path, get_descriptor("desc-long.vmdk") + f'\nddb.comment = "{long_value}"\n'.encode())

    process = run_convert(["-i", "--detailed", "desc-long.vmdk"])
    assert process.returncode == 0
    info = json.loads(process.stdout)
    assert info["descriptorFile"]["ddb.comment"] == long_value
