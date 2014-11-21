/*================================================================================
Copyright (c) 2014 VMware, Inc.  All Rights Reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of VMware, Inc. nor the names of its contributors may be used
  to endorse or promote products derived from this software without specific prior
  written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL VMWARE, INC. OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
================================================================================*/

#define _GNU_SOURCE

#include "diskinfo.h"

#include <sys/stat.h>
#include <stdlib.h>
#include <fcntl.h>
#include <errno.h>

typedef struct {
	DiskInfo hdr;
	int fd;
	uint64_t capacity;
} FlatDiskInfo;

static inline FlatDiskInfo *
getFDI(DiskInfo *self)
{
	return (FlatDiskInfo *)self;
}

static off_t
FlatGetCapacity(DiskInfo *self)
{
	FlatDiskInfo *fdi = getFDI(self);

	return fdi->capacity;
}

static ssize_t
FlatPread(DiskInfo *self,
          void *buf,
          size_t len,
          off_t pos)
{
	FlatDiskInfo *fdi = getFDI(self);
	return pread(fdi->fd, buf, len, pos);
}

static ssize_t
FlatPwrite(DiskInfo *self,
           const void *buf,
           size_t len,
           off_t pos)
{
	FlatDiskInfo *fdi = getFDI(self);

	/*
         * Should we do some zero detection here to generate sparse file?
         */
	return pwrite(fdi->fd, buf, len, pos);
}

static int
FlatClose(DiskInfo *self)
{
	FlatDiskInfo *fdi = getFDI(self);
	int fd = fdi->fd;

	free(fdi);
	return close(fd);
}

static int
FlatNextData(DiskInfo *self,
	     off_t *pos,
             off_t *end)
{
	FlatDiskInfo *fdi = getFDI(self);
	off_t dataOff = lseek(fdi->fd, *end, SEEK_DATA);
	off_t holeOff;

	if (dataOff == -1) {
		if (errno == ENXIO) {
			return -1;
		}
		dataOff = *end;
		holeOff = fdi->capacity;
		if (dataOff >= holeOff) {
			errno = ENXIO;
			return -1;
		}
	} else {
		holeOff = lseek(fdi->fd, dataOff, SEEK_HOLE);
		if (holeOff == -1) {
			holeOff = fdi->capacity;
		}
	}
	*pos = dataOff;
	*end = holeOff;
	return 0;
	
}

static DiskInfoVMT flatDiskInfoVMT = {
	.getCapacity = FlatGetCapacity,
	.pread = FlatPread,
	.pwrite = FlatPwrite,
	.nextData = FlatNextData,
	.close = FlatClose,
	.abort = FlatClose
};

DiskInfo *
Flat_Open(const char *fileName)
{
	int fd = open(fileName, O_RDONLY);
	struct stat stb;
	FlatDiskInfo *fdi;

	if (fd == -1) {
		return NULL;
	}
	if (fstat(fd, &stb)) {
		goto errClose;
	}
	fdi = malloc(sizeof *fdi);
	if (!fdi) {
		goto errClose;
	}
	fdi->hdr.vmt = &flatDiskInfoVMT;
	fdi->fd = fd;
	fdi->capacity = stb.st_size;
	return &fdi->hdr;
errClose:
	close(fd);
	return NULL;
}

DiskInfo *
Flat_Create(const char *fileName,
            off_t capacity)
{
	int fd = open(fileName, O_RDWR | O_CREAT | O_TRUNC, 0666);
	FlatDiskInfo *fdi;

	if (fd == -1) {
		return NULL;
	}
	if (ftruncate(fd, capacity)) {
		goto errClose;
	}
	fdi = malloc(sizeof *fdi);
	if (!fdi) {
		goto errClose;
	}
	fdi->hdr.vmt = &flatDiskInfoVMT;
	fdi->fd = fd;
	fdi->capacity = capacity;
	return &fdi->hdr;
errClose:
	close(fd);
	return NULL;
}

