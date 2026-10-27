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
import zlib


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


def stream_optimized(capacity, grains, grain_size=128):
    """Return a minimal stream optimized VMDK without descriptor.
       grains is a dict of grain number -> uncompressed grain data"""
    num_gtes_per_gt = 512
    num_gtes = -(-capacity // grain_size)
    num_gts = -(-num_gtes // num_gtes_per_gt)
    gd_sectors = -(-num_gts * 4 // SECTOR_SIZE)
    gt_sectors = num_gtes_per_gt * 4 // SECTOR_SIZE

    gd_offset = 1
    gt_offset = gd_offset + gd_sectors
    overhead = gt_offset + gt_sectors * num_gts
    gd = [gt_offset + i * gt_sectors for i in range(num_gts)]
    gt = [0] * (num_gts * num_gtes_per_gt)

    data = b""
    sector = overhead
    for grain_nr, grain in sorted(grains.items()):
        cmp = zlib.compress(grain)
        blob = struct.pack("<QI", grain_nr * grain_size, len(cmp)) + cmp
        blob += b"\0" * (-len(blob) % SECTOR_SIZE)
        gt[grain_nr] = sector
        sector += len(blob) // SECTOR_SIZE
        data += blob

    hdr = sparse_header(capacity, grain_size, 0, 0, num_gtes_per_gt, gd_offset, overhead=overhead)
    gd_data = struct.pack(f"<{num_gts}I", *gd)
    gd_data += b"\0" * (gd_sectors * SECTOR_SIZE - len(gd_data))
    gt_data = struct.pack(f"<{len(gt)}I", *gt)
    # end of stream marker
    eos = b"\0" * SECTOR_SIZE
    return hdr + gd_data + gt_data + data + eos


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


@pytest.mark.parametrize("size", [102400, 65536 + 512, 512])
def test_partial_last_grain(size):
    """capacity is not a multiple of the grain size (64k), and the last grain has data"""
    data = os.urandom(size)
    make_vmdk("partial.vmdk", data)

    process = run_convert(["-i", "partial.vmdk"])
    assert process.returncode == 0
    info = json.loads(process.stdout)
    assert info["capacity"] == size
    assert info["used"] == size

    process = run_convert(["partial.vmdk", "partial-back.raw"])
    assert process.returncode == 0
    with open(os.path.join(WORK_DIR, "partial-back.raw"), "rb") as f:
        assert f.read() == data


@pytest.mark.parametrize("threads", ["1", "4"])
@pytest.mark.parametrize("size", [1000, 65536 + 1000])
def test_size_not_sector_aligned(size, threads):
    """the raw image size is not a multiple of the sector size"""
    data = os.urandom(size)
    make_vmdk("unaligned.vmdk", data, args=["-n", threads])

    process = run_convert(["unaligned.vmdk", "unaligned-back.raw"])
    assert process.returncode == 0, process.stderr
    with open(os.path.join(WORK_DIR, "unaligned-back.raw"), "rb") as f:
        back = f.read()
    # the capacity is rounded up to full sectors
    assert len(back) == -(-size // SECTOR_SIZE) * SECTOR_SIZE
    assert back[:size] == data
    assert back[size:] == b"\0" * (len(back) - size)


def test_last_grain_not_padded():
    """VMDKs created by older versions have a last grain that is not padded to a full sector"""
    data = os.urandom(1000)
    write_file("unpadded.vmdk", stream_optimized(2, {0: data}))

    process = run_convert(["unpadded.vmdk", "unpadded-back.raw"])
    assert process.returncode == 0, process.stderr
    with open(os.path.join(WORK_DIR, "unpadded-back.raw"), "rb") as f:
        assert f.read() == data + b"\0" * 24


def test_grain_too_short():
    """a grain that is shorter than the grain size, not only by padding, is an error"""
    write_file("short-grain.vmdk", stream_optimized(256, {0: os.urandom(65536 - 512)}))

    process = run_convert(["short-grain.vmdk", "short-grain-back.raw"])
    assert process.returncode != 0


def test_descriptor_too_large():
    """the descriptor must fit into the space reserved for it"""
    write_file("desc-large.raw", os.urandom(65536))
    process = run_convert(["-t", "1" * 11000, "desc-large.raw", "desc-large.vmdk"])
    assert process.returncode != 0
    assert "Success" not in process.stdout


@pytest.mark.parametrize("args", [
    ["-n", "0"],
    ["-n", "100000000"],
    ["-n", "4294967297"],
    ["-c", "10"],
    ["-c", "4294967297"],
    ["-s", "1000"],
    ["-s", "4294967808"],
    ["-t", "4294967296"],
])
def test_invalid_options(args):
    write_file("options.raw", os.urandom(65536))
    process = run_convert(args + ["options.raw", "options.vmdk"])
    assert process.returncode == 1
    assert "invalid" in process.stderr or "must be" in process.stderr


@pytest.mark.parametrize("args", [
    ["-n", "1024"],
    ["-c", "0"],
    ["-s", "0"],
    ["-s", "512"],
    ["-s", "4096"],
    ["-t", "2147483647"],
])
def test_valid_options(args):
    write_file("options.raw", os.urandom(65536))
    process = run_convert(args + ["options.raw", "options.vmdk"])
    assert process.returncode == 0, process.stderr
