/* ********************************************************************************
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

#ifndef _DISKINFO_H_
#define _DISKINFO_H_

#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>

typedef struct DiskInfo DiskInfo;

typedef struct {
    off_t (*getCapacity)(DiskInfo *self);
    ssize_t (*pread)(DiskInfo *self, void *buf, size_t len, off_t pos);
    ssize_t (*pwrite)(DiskInfo *self, const void *buf, size_t len, off_t pos);
    int (*nextData)(DiskInfo *self, off_t *pos, off_t *end);
    int (*close)(DiskInfo *self);
    int (*abort)(DiskInfo *self);
    ssize_t (*copyDisk)(DiskInfo *self, DiskInfo *src, int numThreads);
} DiskInfoVMT;

struct DiskInfo {
    const DiskInfoVMT *vmt;
};

extern char *toolsVersion; /* toolsVersion in metadata */

DiskInfo *Flat_Open(const char *fileName);
DiskInfo *Flat_Create(const char *fileName, off_t capacity);
DiskInfo *Sparse_Open(const char *fileName);
DiskInfo *StreamOptimized_Create(const char *fileName, off_t capacity, int compressionLevel);

#endif /* _DISKINFO_H_ */
