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

# Tests for converting sparse raw images: holes in the source must be skipped
# (conversion time depends on the data, not the virtual size), and the result
# must be the same as reading every grain.

import errno
import os
import shutil
import struct
import subprocess
import time

import pytest


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VMDK_CONVERT = os.path.join(THIS_DIR, "..", "build", "vmdk", "vmdk-convert")
WORK_DIR = os.path.join(os.getcwd(), "pytest-vmdk-sparse")

KiB = 1024
MiB = 1024 * KiB
GiB = 1024 * MiB
GRAIN = 64 * KiB
SECTOR = 512

# offset, length, source ("random" or "zero")
MIXED_LAYOUT = [
    (0, 1 * MiB, "random"),
    # not aligned to a grain or a 4k block
    (1 * GiB + 12345, 100 * KiB, "random"),
    # straddles a grain boundary
    (2 * GiB + GRAIN - 3000, 6000, "random"),
    # two writes in the same grain, with a hole between them
    (3 * GiB + 2 * 4096, 100, "random"),
    (3 * GiB + 12 * 4096, 100, "random"),
    # real zeros, written, not a hole
    (4 * GiB, 256 * KiB, "zero"),
    # zeros and data in the same grain
    (5 * GiB, 8192, "zero"),
    (5 * GiB + 8192, 100, "random"),
    # data in the last grain
    (64 * GiB - 5000, 5000, "random"),
]

ODD_SIZE = 10 * GiB + 3 * SECTOR


def make_image(path, size, layout):
    with open(path, "wb") as f:
        f.truncate(size)
        for off, length, src in layout:
            f.seek(off)
            f.write(os.urandom(length) if src == "random" else bytes(length))


def data_regions(path):
    """Yield (start, end) of the data regions of a file, using SEEK_DATA."""
    size = os.path.getsize(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        pos = 0
        while pos < size:
            try:
                start = os.lseek(fd, pos, os.SEEK_DATA)
            except OSError as e:
                if e.errno == errno.ENXIO:
                    return
                raise
            end = os.lseek(fd, start, os.SEEK_HOLE)
            yield start, end
            pos = end
    finally:
        os.close(fd)


def sparse_cmp(a, b):
    """Compare two files, reading only their data regions. Holes read as zeros.
    The VMDK capacity is in sectors, so b may be a padded to a full sector."""
    size_a = os.path.getsize(a)
    size_b = os.path.getsize(b)
    assert size_b == (size_a + SECTOR - 1) // SECTOR * SECTOR, f"{a} and {b} differ in size"
    regions = sorted(list(data_regions(a)) + list(data_regions(b)))
    with open(a, "rb") as fa, open(b, "rb") as fb:
        fb.seek(size_a)
        assert not any(fb.read()), f"padding at the end of {b} is not zero"
        for start, end in regions:
            end = min(end, size_a)
            pos = start
            while pos < end:
                n = min(end - pos, 16 * MiB)
                fa.seek(pos)
                fb.seek(pos)
                da = fa.read(n)
                db = fb.read(n)
                assert da == db, f"{a} and {b} differ in range {pos}-{pos + n}"
                pos += n


def nonzero_grains(path):
    """Set of grain numbers of a raw image that are not all zeros."""
    grains = set()
    with open(path, "rb") as f:
        for start, end in data_regions(path):
            g = start // GRAIN
            while g * GRAIN < end:
                if g not in grains:
                    f.seek(g * GRAIN)
                    if any(f.read(GRAIN)):
                        grains.add(g)
                g += 1
    return grains


def vmdk_grains(path):
    """List of grain numbers in a stream optimized VMDK, in file order.
    Walks the stream: each grain starts with a 12 byte header (lba, size),
    markers have size 0 and are followed by lba sectors of metadata."""
    grains = []
    with open(path, "rb") as f:
        hdr = f.read(SECTOR)
        magic, version, flags, capacity, grain_size = struct.unpack_from("<IIIQQ", hdr, 0)
        assert magic == 0x564d444b
        over_head = struct.unpack_from("<Q", hdr, 64)[0]
        pos = over_head * SECTOR
        while True:
            f.seek(pos)
            item = f.read(SECTOR)
            if len(item) < 12:
                break
            lba, size = struct.unpack_from("<QI", item, 0)
            if size != 0:
                assert lba % grain_size == 0
                grains.append(lba // grain_size)
                pos += (12 + size + SECTOR - 1) // SECTOR * SECTOR
            else:
                marker = struct.unpack_from("<I", item, 12)[0]
                if marker == 0:  # end of stream
                    break
                pos += SECTOR + lba * SECTOR
    return grains


def check_vmdk(img, vmdk, back):
    grains = vmdk_grains(vmdk)
    assert len(grains) == len(set(grains)), f"{vmdk} has grains written more than once"
    assert set(grains) == nonzero_grains(img), f"grains in {vmdk} do not match the non-zero grains of {img}"

    subprocess.check_call([VMDK_CONVERT, vmdk, back], cwd=WORK_DIR)
    sparse_cmp(img, back)
    os.remove(back)


@pytest.fixture(scope="module", autouse=True)
def setup_test():
    os.makedirs(WORK_DIR, exist_ok=True)

    empty = os.path.join(WORK_DIR, "empty.img")
    with open(empty, "wb") as f:
        f.truncate(512 * GiB)

    make_image(os.path.join(WORK_DIR, "mixed.img"), 64 * GiB, MIXED_LAYOUT)
    make_image(os.path.join(WORK_DIR, "odd.img"), ODD_SIZE,
               [(0, 3 * GRAIN + 77, "random"), (ODD_SIZE - 1000, 1000, "random")])
    # data at the very end, and a capacity that is not a multiple of a sector
    make_image(os.path.join(WORK_DIR, "odd-sector.img"), 1 * GiB + 1000,
               [(GRAIN, 10, "random"), (1 * GiB, 1000, "random")])
    # mostly data, so the threads have to share data regions
    make_image(os.path.join(WORK_DIR, "dense.img"), 64 * MiB,
               [(0, 20 * MiB, "random"), (24 * MiB + 1, 30 * MiB, "random")])

    yield

    shutil.rmtree(WORK_DIR)


IMAGES = ["empty", "mixed", "odd", "odd-sector", "dense"]
THREADS = [[], ["-n", "1"], ["-n", "3"]]


@pytest.mark.parametrize("name", IMAGES)
@pytest.mark.parametrize("threads", THREADS, ids=["default", "n1", "n3"])
def test_roundtrip(name, threads):
    img = os.path.join(WORK_DIR, f"{name}.img")
    vmdk = os.path.join(WORK_DIR, f"{name}.vmdk")
    back = os.path.join(WORK_DIR, f"{name}-back.img")

    subprocess.check_call([VMDK_CONVERT] + threads + [img, vmdk], cwd=WORK_DIR)
    check_vmdk(img, vmdk, back)

    if threads == ["-n", "1"]:
        grains = vmdk_grains(vmdk)
        assert grains == sorted(grains), "grains should be in order with one thread"


@pytest.mark.parametrize("name", ["mixed", "odd", "odd-sector"])
def test_vmdk_to_vmdk(name):
    """VMDK source: holes are skipped using the grain table (SparseNextData)."""
    img = os.path.join(WORK_DIR, f"{name}.img")
    vmdk = os.path.join(WORK_DIR, f"{name}-src.vmdk")
    vmdk2 = os.path.join(WORK_DIR, f"{name}-dst.vmdk")
    back = os.path.join(WORK_DIR, f"{name}-back.img")

    subprocess.check_call([VMDK_CONVERT, img, vmdk], cwd=WORK_DIR)
    subprocess.check_call([VMDK_CONVERT, vmdk, vmdk2], cwd=WORK_DIR)
    check_vmdk(img, vmdk2, back)


def test_empty_is_fast():
    """Regression test: holes used to be read and checked grain by grain,
    so a 512 GiB empty image took about 2 minutes."""
    img = os.path.join(WORK_DIR, "empty.img")
    vmdk = os.path.join(WORK_DIR, "empty-fast.vmdk")

    start = time.monotonic()
    subprocess.check_call([VMDK_CONVERT, img, vmdk], cwd=WORK_DIR)
    elapsed = time.monotonic() - start

    assert elapsed < 20, f"converting a 512 GiB empty image took {elapsed:.1f}s"
    assert vmdk_grains(vmdk) == []


# lseek() shim: SEEK_DATA and SEEK_HOLE fail with the errno given in
# SEEK_DATA_ERRNO and SEEK_HOLE_ERRNO, if set. With SEEK_HOLE_SAME set,
# SEEK_HOLE returns its offset, so every data region is empty.
LSEEK_SHIM_SRC = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <unistd.h>

static off_t (*real_lseek)(int, off_t, int);

off_t lseek(int fd, off_t off, int whence)
{
    const char *err = NULL;

    if (whence == SEEK_HOLE && getenv("SEEK_HOLE_SAME"))
        return off;
    if (whence == SEEK_DATA)
        err = getenv("SEEK_DATA_ERRNO");
    else if (whence == SEEK_HOLE)
        err = getenv("SEEK_HOLE_ERRNO");
    if (err) {
        errno = atoi(err);
        return -1;
    }
    if (!real_lseek)
        real_lseek = dlsym(RTLD_NEXT, "lseek");
    return real_lseek(fd, off, whence);
}

off_t lseek64(int fd, off_t off, int whence)
{
    return lseek(fd, off, whence);
}
"""

SMALL_LAYOUT = [(0, 10, "random"), (100 * MiB + 1, 5000, "random"), (256 * MiB, 1000, "random")]


@pytest.fixture(scope="module")
def lseek_shim():
    if shutil.which("gcc") is None:
        pytest.skip("gcc is needed to build the lseek shim")

    shim_c = os.path.join(WORK_DIR, "lseek_shim.c")
    shim = os.path.join(WORK_DIR, "lseek_shim.so")
    with open(shim_c, "w") as f:
        f.write(LSEEK_SHIM_SRC)
    subprocess.check_call(["gcc", "-shared", "-fPIC", "-o", shim, shim_c, "-ldl"])

    img = os.path.join(WORK_DIR, "small.img")
    make_image(img, 256 * MiB + 1000, SMALL_LAYOUT)
    # data not at the start, so the first region is after the read position
    make_image(os.path.join(WORK_DIR, "late.img"), 16 * MiB,
               [(1 * MiB + 100, 5000, "random"), (8 * MiB, 100, "random")])

    return shim, img


@pytest.mark.parametrize("err", ["EINVAL", "ESPIPE", "EOPNOTSUPP"])
@pytest.mark.parametrize("threads", [["-n", "1"], ["-n", "3"]], ids=["n1", "n3"])
def test_no_seek_data(lseek_shim, threads, err):
    """Without SEEK_DATA support, the whole file is data and every grain is read."""
    shim, img = lseek_shim
    vmdk = os.path.join(WORK_DIR, "small.vmdk")
    back = os.path.join(WORK_DIR, "small-back.img")

    env = dict(os.environ, LD_PRELOAD=shim, SEEK_DATA_ERRNO=str(getattr(errno, err)))
    subprocess.check_call([VMDK_CONVERT] + threads + [img, vmdk], cwd=WORK_DIR, env=env)
    check_vmdk(img, vmdk, back)


@pytest.mark.parametrize("whence,err", [
    ("SEEK_DATA", "EIO"),
    ("SEEK_HOLE", "EIO"),
    # the file was truncated during the conversion, not the end of the data
    ("SEEK_HOLE", "ENXIO"),
])
@pytest.mark.parametrize("dst", ["small-err.vmdk", "small-err.img"])
def test_seek_error(lseek_shim, whence, err, dst):
    """Other lseek() errors fail the conversion, to VMDK (threads) and to raw (copyDisk)."""
    shim, img = lseek_shim
    dst = os.path.join(WORK_DIR, dst)

    env = dict(os.environ, LD_PRELOAD=shim, **{f"{whence}_ERRNO": str(getattr(errno, err))})
    process = subprocess.run([VMDK_CONVERT, img, dst], cwd=WORK_DIR, env=env)
    assert process.returncode != 0, f"conversion succeeded although {whence} failed with {err}"


@pytest.mark.parametrize("args", [["-n", "1"], ["-n", "3"], [], ["-i"]],
                         ids=["vmdk-n1", "vmdk-n3", "raw", "info"])
def test_empty_data_region(lseek_shim, args):
    """An empty data region from nextData() is an error. It must not be
    accepted, and must not make the raw copy or -i loop forever."""
    shim, _ = lseek_shim
    img = os.path.join(WORK_DIR, "late.img")
    if args == []:
        cmd = [VMDK_CONVERT, img, os.path.join(WORK_DIR, "late-err.img")]
    elif args == ["-i"]:
        cmd = [VMDK_CONVERT, "-i", img]
    else:
        cmd = [VMDK_CONVERT] + args + [img, os.path.join(WORK_DIR, "late-err.vmdk")]

    env = dict(os.environ, LD_PRELOAD=shim, SEEK_HOLE_SAME="1")
    process = subprocess.run(cmd, cwd=WORK_DIR, env=env, timeout=30,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.returncode != 0, "an empty data region was accepted"
    assert b"Invalid data region" in process.stderr
