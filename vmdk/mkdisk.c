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

#include "diskinfo.h"

#include <sys/time.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <getopt.h>

/* toolsVersion in metadata -
   default is 2^31-1 (unknown) */
char *toolsVersion = "2147483647";

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
copyDisk(DiskInfo *src, DiskInfo *dst)
{
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

/* Displays the usage message. */
static int
printUsage(char *cmd)
{
	printf("Usage:\n");
	printf("%s -i src.vmdk: displays information for specified virtual disk\n", cmd);
	printf("%s [-t toolsVersion] src.vmdk dst.vmdk: converts source disk to destination disk with given tools version\n\n", cmd);

	return 1;
}

/* Check a string is number */
static bool
isNumber(char *text)
{
	int j;
	j = strlen(text);
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
	bool doConvert = false;

	gettimeofday(&tv, NULL);
	srand48(tv.tv_sec ^ tv.tv_usec);

	while ((opt = getopt(argc, argv, "it:")) != -1) {
		switch (opt) {
		case 'i':
			doInfo = true;
			break;
		case 't':
			doConvert = true;
			toolsVersion = optarg;
			if (!isNumber(toolsVersion)){
				fprintf(stderr, "Invalid tools version: %s\n", toolsVersion);
				exit(1);
			}
			break;
		case '?':
			printUsage(argv[0]);
			exit(1);
		}
	}

	if (doInfo && doConvert) {
		printUsage(argv[0]);
		exit(1);
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
		fprintf(stderr, "Cannot open source disk %s: %s\n", src, strerror(errno));
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
				tgt = StreamOptimized_Create(filename, capacity);
			else
				tgt = Flat_Create(filename, capacity);

			if (tgt == NULL) {
				fprintf(stderr, "Cannot open target disk %s: %s\n", filename, strerror(errno));
			} else {
				printf("Starting to convert %s to %s...\n", src, filename);
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
