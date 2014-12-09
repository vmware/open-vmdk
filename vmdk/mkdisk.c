/*================================================================================
Copyright (c) 2014 VMware, Inc.  All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the “License”); you may not
use this file except in compliance with the License.  You may obtain a copy of
the License at:

            http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an “AS IS” BASIS, without warranties or
conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
specific language governing permissions and limitations under the License.
================================================================================*/

#define _GNU_SOURCE

#include "diskinfo.h"

#include <sys/time.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <getopt.h>

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
copyDisk(DiskInfo *src, const char *fileName)
{
	off_t capacity;
	DiskInfo *dst;
	off_t end;
	off_t pos;

	capacity = src->vmt->getCapacity(src);
	dst = StreamOptimized_Create(fileName, capacity);
	if (!dst) {
		return false;
	}
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

int
main(int argc,
     char *argv[])
{
	struct timeval tv;
	DiskInfo *di;
	const char *src;
	int opt;
	int doInfo = 0;

	gettimeofday(&tv, NULL);
	srand48(tv.tv_sec ^ tv.tv_usec);

	while ((opt = getopt(argc, argv, "i")) != -1) {
		switch (opt) {
		case 'i':
			doInfo = 1;
			break;
		}
	}
	if (optind >= argc) {
		src = "src.vmdk";
	} else {
		src = argv[optind++];
	}
	di = Sparse_Open(src);
	if (di == NULL) {
		di = Flat_Open(src);
	}
	if (di == NULL) {
		fprintf(stderr, "Cannot open source disk: %s\n", strerror(errno));
	} else {
		if (doInfo) {
			off_t capacity = di->vmt->getCapacity(di);
			off_t end = 0;
			off_t pos;
			off_t usedSpace = 0;
			while (di->vmt->nextData(di, &pos, &end) == 0) {
				usedSpace += end - pos;
			}
			printf("{ \"capacity\": %llu, \"used\": %llu }\n",
			       (unsigned long long)capacity, (unsigned long long)usedSpace);
		} else {
			const char *tgt;

			if (optind >= argc) {
				tgt = "dst.vmdk";
			} else {
				tgt = argv[optind++];
			}
			if (copyDisk(di, tgt)) {
				printf("Success\n");
			} else {
				fprintf(stderr, "Failure!\n");
			}
		}
		di->vmt->close(di);
	}
	return 0;
}
