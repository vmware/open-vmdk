/* *******************************************************************************
 * Copyright (c) 2014-2023 VMware, Inc.  All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the “License”); you may not
 * use this file except in compliance with the License.  You may obtain a copy of
 * the License at:
 *
 *            http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed
 * under the License is distributed on an “AS IS” BASIS, without warranties or
 * conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
 * specific language governing permissions and limitations under the License.
 * *********************************************************************************/

#define _GNU_SOURCE

#include <errno.h>
#include <getopt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#include "diskinfo.h"
#include "parse_cmd.h"

static int copyData(DiskInfo *dst, off_t dstOffset, DiskInfo *src, off_t srcOffset, uint64_t length) {
    char buf[65536];

    while (length > 0) {
        size_t readLen;

        readLen = sizeof buf;
        if (length < readLen) {
            readLen = length;
            length = 0;
        } else {
            length -= readLen;
        }
        if (src->vmt->pread(src, buf, readLen, srcOffset) != (ssize_t)readLen) {
            return -1;
        }
        if (dst->vmt->pwrite(dst, buf, readLen, dstOffset) != (ssize_t)readLen) {
            return -1;
        }
        srcOffset += readLen;
        dstOffset += readLen;
    }
    return 0;
}

static bool copyDisk(DiskInfo *src, DiskInfo *dst) {
    off_t end;
    off_t pos;

    end = 0;
    while (src->vmt->nextData(src, &pos, &end) == 0) {
        if (copyData(dst, pos, src, pos, end - pos)) {
            goto failAll;
        }
    }
    if (errno != ENXIO) {
        goto failAll;
    }
    if (dst->vmt->close(dst)) {
        return false;
    }
    return true;

failAll:
    dst->vmt->abort(dst);
    return false;
}

int main(int argc, char *argv[]) {
    CommandLineArgs args = {
        .tools_version = "2147483647",  // default is 2^31-1 (unknown)
        .do_convert_zbs = false,
        .do_convert_local = false,
        .do_info = false,
        .dest_file_path = "dest.vmdk",
        .src_file_path = "",
        .dest_ip = "",
        .dest_volume_uuid = "",
        .src_ip = "",
        .src_volume_uuid = "",
    };
    struct timeval tv;
    DiskInfo *di;

    gettimeofday(&tv, NULL);
    srand48(tv.tv_sec ^ tv.tv_usec);

    if (parse_args(argc, argv, args) != 0) {
        exit(1);
    }

    di = Sparse_Open(args.src_file_path);
    if (di == NULL) {
        di = Flat_Open(args.src_file_path);
    }
    if (di == NULL) {
        fprintf(stderr, "Cannot open source disk %s: %s\n", args.src_file_path, strerror(errno));
    } else {
        if (args.do_info) {
            off_t capacity = di->vmt->getCapacity(di);
            off_t end = 0;
            off_t pos;
            off_t usedSpace = 0;
            while (di->vmt->nextData(di, &pos, &end) == 0) {
                usedSpace += end - pos;
            }
            printf("{ \"capacity\": %llu, \"used\": %llu }\n", (unsigned long long)capacity,
                   (unsigned long long)usedSpace);
        } else {
            DiskInfo *tgt;
            off_t capacity;

            capacity = di->vmt->getCapacity(di);

            if (strcmp(&(args.dest_file_path[strlen(args.dest_file_path) - 5]), ".vmdk") == 0)
                tgt = StreamOptimized_Create(args.dest_file_path, capacity);
            else
                tgt = Flat_Create(args.dest_file_path, capacity);

            if (tgt == NULL) {
                fprintf(stderr, "Cannot open target disk %s: %s\n", args.dest_file_path, strerror(errno));
            } else {
                printf("Starting to convert %s to %s...\n", args.src_file_path, args.dest_file_path);
                if (copyDisk(di, tgt)) {
                    printf("Success\n");
                } else {
                    fprintf(stderr, "Failure!\n");
                }
            }
        }
        di->vmt->close(di);
    }
    return 0;
}
