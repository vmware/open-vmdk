/* *******************************************************************************
 * Copyright (c) 2014-2023 VMware, Inc.  All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License.  You may obtain a copy of
 * the License at:
 *
 *            http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed
 * under the License is distributed on an "AS IS" BASIS, without warranties or
 * conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
 * specific language governing permissions and limitations under the License.
 * *********************************************************************************/

#define _GNU_SOURCE

#include "diskinfo.h"
#include "vmware_vmdk.h"

#include <sys/sysinfo.h>
#include <sys/time.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <getopt.h>
#include <zlib.h>

/* toolsVersion in metadata -
   default is 2^31-1 (unknown) */
char *toolsVersion = "2147483647";

// Forward declaration for sparse disk structure
typedef struct {
    DiskInfo hdr;
    SparseExtentHeader diskHdr;
    void *gtInfo;  // We don't need the full structure, just the header
    int fd;
} SparseDiskInfo;

static int
copyData(DiskInfo *dst,
         off_t dstOffset,
         DiskInfo *src,
         off_t srcOffset,
         uint64_t length)
{
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

static bool
copyDisk(DiskInfo *src, DiskInfo *dst, int numThreads)
{
    if (dst->vmt->copyDisk) {
        ssize_t ret;

        ret = dst->vmt->copyDisk(src, dst, numThreads);
        if (ret < 0) {
            return false;
        }
    } else {
        off_t end = 0;
        off_t pos;

        while (src->vmt->nextData(src, &pos, &end) == 0) {
            if (copyData(dst, pos, src, pos, end - pos)) {
                goto failAll;
            }
        }
        if (errno != ENXIO) {
            goto failAll;
        }
    }
    if (dst->vmt->close(dst)) {
        return false;
    }
    return true;

failAll:
    dst->vmt->abort(dst);
    return false;
}

/* Displays the usage message. */
static int
printUsage(char *cmd, int compressionLevel, int numThreads)
{
    printf("Usage:\n");
    printf("%s -i [--detailed] src.vmdk: displays information for specified virtual disk\n", cmd);
    printf("%s [-c compressionlevel] [-n threads] [-t toolsVersion] src.vmdk dst.vmdk: converts source disk to destination disk with given tools version\n\n", cmd);
    printf("-c <level> sets the compression level. Valid values are 1 (fastest) to 9 (best). Only when writing to VMDK. Current is %d.\n", compressionLevel);
    printf("-n <threads> sets the number of threads used for compression level. Only when writing to VMDK. Current is (%d).\n", numThreads);
    printf("--detailed shows detailed sparse extent header information (only with -i)\n");

    return 1;
}

/* Check if string is a number */
static bool
isNumber(const char *text)
{
    int j;
    j = strlen(text);

    /* an empty string is not a number */
    if (j <= 0)
        return false;

    while(j--)
    {
        if(text[j] >= '0' && text[j] <= '9')
            continue;

        return false;
    }
    return true;
}

int
main(int argc,
     char *argv[])
{
    struct timeval tv;
    DiskInfo *di;
    const char *src;
    int opt;
    bool doInfo = false;
    bool doDetailed = false;
    bool doConvert = false;
    int compressionLevel = Z_BEST_COMPRESSION;
    int numThreads = get_nprocs();
    const char *env;

    static struct option long_options[] = {
        {"detailed", no_argument, 0, 'd'},
        {"help", no_argument, 0, 'h'},
        {0, 0, 0, 0}
    };

    gettimeofday(&tv, NULL);
    srand48(tv.tv_sec ^ tv.tv_usec);

    /* use environment values, but only if sanity checked */
    if ((env = getenv("VMDKCONVERT_COMPRESSION_LEVEL")) != NULL) {
        if (isNumber(env)) {
            int n = atoi(env);
            if (n > 0 && n <= 9)
                compressionLevel = atoi(env);
        }
    }
    if ((env = getenv("VMDKCONVERT_NUM_THREADS")) != NULL) {
        if (isNumber(env)) {
            int n = atoi(env);
            if (n > 0)
                numThreads = atoi(env);
        }
    }

    while ((opt = getopt_long(argc, argv, "c:hin:t:", long_options, NULL)) != -1) {
        switch (opt) {
        case 'c':
            if (!isNumber(optarg)){
                fprintf(stderr, "invalid compression level: %s\n", optarg);
                exit(1);
            }
            compressionLevel = atoi(optarg);
            break;
        case 'i':
            doInfo = true;
            break;
        case 'd':
            doDetailed = true;
            break;
        case 'n':
            if (!isNumber(optarg)) {
                fprintf(stderr, "invalid threads value: %s\n", optarg);
                exit(1);
            }
            numThreads = atoi(optarg);
            break;
        case 't':
            doConvert = true;
            toolsVersion = optarg;
            if (!isNumber(toolsVersion)){
                fprintf(stderr, "invalid tools version: %s\n", toolsVersion);
                exit(1);
            }
            break;
        case '?':
        case 'h':
            printUsage(argv[0], compressionLevel, numThreads);
            exit(1);
        }
    }

    if (numThreads <= 0) {
        fprintf(stderr, "number of threads must be > 0: %d\n", numThreads);
        exit(1);
    }

    if (compressionLevel <= 0 || compressionLevel > 9) {
        fprintf(stderr, "compression level must be > 0 and <= 9: %d\n", compressionLevel);
        exit(1);
    }

    if (doInfo && doConvert) {
        printUsage(argv[0], compressionLevel, numThreads);
        exit(1);
    }

    if (doDetailed && !doInfo) {
        fprintf(stderr, "--detailed can only be used with -i option\n");
        exit(1);
    }

    if (optind >= argc) {
        src = "src.vmdk";
    } else {
        src = argv[optind++];
    }
    bool isSparse = false;
    di = Sparse_Open(src);
    if (di != NULL) {
        isSparse = true;
    } else {
        di = Flat_Open(src);
    }
    if (di == NULL) {
        fprintf(stderr, "Cannot open source disk %s: %s\n", src, strerror(errno));
        exit(1);
    } else {
        if (doInfo) {
            off_t capacity = di->vmt->getCapacity(di);
            off_t end = 0;
            off_t pos;
            off_t usedSpace = 0;
            while (di->vmt->nextData(di, &pos, &end) == 0) {
                usedSpace += end - pos;
            }
            printf("{ \"capacity\": %llu, \"used\": %llu",
                    (unsigned long long)capacity, (unsigned long long)usedSpace);

            if (doDetailed) {
                if (isSparse) {
                    // Cast to SparseDiskInfo to access the header
                    SparseDiskInfo *sdi = (SparseDiskInfo *)di;
                    printf(", \"sparseHeader\": {");
                    printf("\"version\": %u, ", sdi->diskHdr.version);
                    printf("\"flags\": %u, ", sdi->diskHdr.flags);
                    printf("\"flagsDecoded\": {");
                    printf("\"validNewlineDetector\": %s, ", (sdi->diskHdr.flags & SPARSEFLAG_VALID_NEWLINE_DETECTOR) ? "true" : "false");
                    printf("\"useRedundant\": %s, ", (sdi->diskHdr.flags & SPARSEFLAG_USE_REDUNDANT) ? "true" : "false");
                    printf("\"compressed\": %s, ", (sdi->diskHdr.flags & SPARSEFLAG_COMPRESSED) ? "true" : "false");
                    printf("\"embeddedLBA\": %s", (sdi->diskHdr.flags & SPARSEFLAG_EMBEDDED_LBA) ? "true" : "false");
                    printf("}, ");
                    printf("\"numGTEsPerGT\": %u, ", sdi->diskHdr.numGTEsPerGT);
                    printf("\"compressAlgorithm\": %u, ", sdi->diskHdr.compressAlgorithm);
                    printf("\"compressAlgorithmName\": \"%s\", ",
                           sdi->diskHdr.compressAlgorithm == SPARSE_COMPRESSALGORITHM_NONE ? "none" :
                           sdi->diskHdr.compressAlgorithm == SPARSE_COMPRESSALGORITHM_DEFLATE ? "deflate" : "unknown");
                    printf("\"uncleanShutdown\": %u, ", sdi->diskHdr.uncleanShutdown);
                    printf("\"grainSize\": %llu, ", (unsigned long long)sdi->diskHdr.grainSize);
                    printf("\"grainSizeBytes\": %llu, ", (unsigned long long)(sdi->diskHdr.grainSize * 512));
                    printf("\"descriptorOffset\": %llu, ", (unsigned long long)sdi->diskHdr.descriptorOffset);
                    printf("\"descriptorSize\": %llu, ", (unsigned long long)sdi->diskHdr.descriptorSize);
                    printf("\"rgdOffset\": %llu, ", (unsigned long long)sdi->diskHdr.rgdOffset);
                    printf("\"gdOffset\": %llu, ", (unsigned long long)sdi->diskHdr.gdOffset);
                    printf("\"overHead\": %llu", (unsigned long long)sdi->diskHdr.overHead);
                    printf("}");
                } else {
                    printf(", \"error\": \"detailed information only available for sparse VMDK files\"");
                }
            }

            printf(" }\n");
        } else {
            const char *filename;
            DiskInfo *tgt;
            off_t capacity;

            if (optind >= argc) {
                filename = "dst.vmdk";
            } else {
                filename = argv[optind++];
            }
            capacity = di->vmt->getCapacity(di);

            if (strcmp(&(filename[strlen(filename) - 5]), ".vmdk") == 0)
                tgt = StreamOptimized_Create(filename, capacity, compressionLevel);
            else
                tgt = Flat_Create(filename, capacity);

            if (tgt == NULL) {
                fprintf(stderr, "Cannot open target disk %s: %s\n", filename, strerror(errno));
                di->vmt->close(di);
                exit(1);
            } else {
                printf("Starting to convert %s to %s using compression level %d and %d threads\n", src, filename, compressionLevel, numThreads);
                if (copyDisk(di, tgt, numThreads)) {
                    printf("Success\n");
                } else {
                    fprintf(stderr, "Failure!\n");
                    exit(1);
                }
            }
        }
        di->vmt->close(di);
    }
    return 0;
}
