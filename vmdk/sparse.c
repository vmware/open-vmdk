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

#define _GNU_SOURCE

#include "vmware_vmdk.h"
#include "diskinfo.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#include <zlib.h>

#define CEILING(x, y) (((x) + (y) - 1) / (y))

#define VMDK_SECTOR_SIZE	512ULL

static uint16_t
getUnalignedLE16(const __le16 *src)
{
	const uint8_t *b = (const uint8_t *)src;

	return (b[1] << 8) | b[0];
}

static uint64_t
getUnalignedLE64(const __le64 *src)
{
	__le64 b;

	memcpy(&b, src, sizeof b);
	return __le64_to_cpu(b);
}

static void
setUnalignedLE16(__le16 *dst, uint16_t src)
{
	uint8_t *b = (uint8_t *)dst;

	b[0] = src;
	b[1] = src >> 8;
}

static void
setUnalignedLE64(__le64 *dst, uint64_t src)
{
	uint64_t tmp = __cpu_to_le64(src);
	memcpy(dst, &tmp, sizeof *dst);
}

static bool
checkSparseExtentHeader(const SparseExtentHeaderOnDisk *src)
{
	return src->magicNumber == __cpu_to_le32(SPARSE_MAGICNUMBER);
}

static bool
getSparseExtentHeader(SparseExtentHeader *dst,
                      const SparseExtentHeaderOnDisk *src)
{
	if (src->magicNumber != __cpu_to_le32(SPARSE_MAGICNUMBER)) {
		return false;
	}
	dst->version = __le32_to_cpu(src->version);
	if (dst->version > SPARSE_VERSION_INCOMPAT_FLAGS) {
		return false;
	}
	dst->flags = __le32_to_cpu(src->flags);
	if (dst->flags & (SPARSEFLAG_INCOMPAT_FLAGS & ~SPARSEFLAG_COMPRESSED & ~SPARSEFLAG_EMBEDDED_LBA)) {
		return false;
	}
	if (dst->flags & SPARSEFLAG_VALID_NEWLINE_DETECTOR) {
		if (src->singleEndLineChar != SPARSE_SINGLE_END_LINE_CHAR ||
		    src->nonEndLineChar != SPARSE_NON_END_LINE_CHAR ||
		    src->doubleEndLineChar1 != SPARSE_DOUBLE_END_LINE_CHAR1 ||
		    src->doubleEndLineChar2 != SPARSE_DOUBLE_END_LINE_CHAR2) {
			return false;
		}
	}
	/* Embedded LBA is allowed with compressed flag only. */
	if (dst->flags & SPARSEFLAG_EMBEDDED_LBA) {
		if (!(dst->flags & SPARSEFLAG_COMPRESSED)) {
			return false;
		}
	}
	dst->compressAlgorithm = getUnalignedLE16(&src->compressAlgorithm);
	dst->uncleanShutdown = src->uncleanShutdown;
	dst->reserved = 0;
	dst->capacity = getUnalignedLE64(&src->capacity);
	dst->grainSize = getUnalignedLE64(&src->grainSize);
	dst->descriptorOffset = getUnalignedLE64(&src->descriptorOffset);
	dst->descriptorSize = getUnalignedLE64(&src->descriptorSize);
	dst->numGTEsPerGT = __le32_to_cpu(src->numGTEsPerGT);
	dst->rgdOffset = __le64_to_cpu(src->rgdOffset);
	dst->gdOffset = __le64_to_cpu(src->gdOffset);
	dst->overHead = __le64_to_cpu(src->overHead);
	return true;
}

static void
setSparseExtentHeader(SparseExtentHeaderOnDisk *dst,
                      const SparseExtentHeader *src,
                      bool temporary)
{
	memset(dst, 0, sizeof *dst);
	/* Use lowercase 'vmdk' signature for temporary stuff. */
	if (temporary) {
		dst->magicNumber = __cpu_to_le32(SPARSE_MAGICNUMBER ^ 0x20202020);
	} else {
		dst->magicNumber = __cpu_to_le32(SPARSE_MAGICNUMBER);
	}
	dst->version = __cpu_to_le32(src->version);
	dst->flags = __cpu_to_le32(src->flags);
	dst->singleEndLineChar = SPARSE_SINGLE_END_LINE_CHAR;
	dst->nonEndLineChar = SPARSE_NON_END_LINE_CHAR;
	dst->doubleEndLineChar1 = SPARSE_DOUBLE_END_LINE_CHAR1;
	dst->doubleEndLineChar2 = SPARSE_DOUBLE_END_LINE_CHAR2;
	setUnalignedLE16(&dst->compressAlgorithm, src->compressAlgorithm);
	dst->uncleanShutdown = src->uncleanShutdown;
	setUnalignedLE64(&dst->capacity, src->capacity);
	setUnalignedLE64(&dst->grainSize, src->grainSize);
	setUnalignedLE64(&dst->descriptorOffset, src->descriptorOffset);
	setUnalignedLE64(&dst->descriptorSize, src->descriptorSize);
	dst->numGTEsPerGT = __cpu_to_le32(src->numGTEsPerGT);
	dst->rgdOffset = __cpu_to_le64(src->rgdOffset);
	dst->gdOffset = __cpu_to_le64(src->gdOffset);
	dst->overHead = __cpu_to_le64(src->overHead);
}

static char *
makeDiskDescriptorFile(const char *fileName,
                       uint64_t capacity,
                       uint32_t cid)
{
	static const char ddfTemplate[] =
"# Disk DescriptorFile\n"
"version=1\n"
"encoding=\"UTF-8\"\n"
"CID=%08x\n"
"parentCID=ffffffff\n"
"createType=\"streamOptimized\"\n"
"\n"
"# Extent description\n"
"RW %llu SPARSE \"%s\"\n"
"\n"
"# The Disk Data Base\n"
"#DDB\n"
"\n"
"ddb.longContentID = \"%08x%08x%08x%08x\"\n"
"ddb.virtualHWVersion = \"4\"\n" /* This field is obsolete, used by ESX3.x and older only. */
"ddb.geometry.cylinders = \"%u\"\n"
"ddb.geometry.heads = \"255\"\n" /* 255/63 is good for anything bigger than 4GB. */
"ddb.geometry.sectors = \"63\"\n"
"ddb.adapterType = \"lsilogic\"\n"
"ddb.toolsInstallType = \"4\"\n" /* unmanaged (open-vm-tools) */
"ddb.toolsVersion = \"%s\""; /* open-vm-tools version */

	unsigned int cylinders;
	char *ret;

	if (capacity > 65535 * 255 * 63) {
		cylinders = 65535;
	} else {
		cylinders = CEILING(capacity, 255 * 63);
	}
	if (asprintf(&ret, ddfTemplate, cid, (long long int)capacity, fileName, (uint32_t)mrand48(), (uint32_t)mrand48(), (uint32_t)mrand48(), cid, cylinders, toolsVersion) == -1) {
		return NULL;
	}
	return ret;
}

typedef union {
	SparseGrainLBAHeaderOnDisk *grainHdr;
	SparseSpecialLBAHeaderOnDisk *specialHdr;
	uint8_t *data;
} ZLibBuffer;

typedef struct {
	uint64_t GTEs;
	uint32_t GTs;
	uint32_t GDsectors;
	uint32_t GTsectors;
	uint64_t lastGrainNr;
	uint32_t lastGrainSize;
	__le32 *gd;
	__le32 *gt;
} SparseGTInfo;

typedef struct {
	SparseGTInfo gtInfo;
	off_t gdOffset;
	off_t gtOffset;
	off_t rgdOffset;
	off_t rgtOffset;
	uint32_t curSP;
	ZLibBuffer zlibBuffer;
	size_t zlibBufferSize;
	z_stream zstream;
	int fd;
	char *fileName;
	uint8_t *grainBuffer;
	uint64_t grainBufferNr;
	uint32_t grainBufferValidStart;
	uint32_t grainBufferValidEnd;
} SparseVmdkWriter;

typedef struct {
	DiskInfo hdr;
	SparseVmdkWriter writer;
	SparseExtentHeader diskHdr;
} StreamOptimizedDiskInfo;

static StreamOptimizedDiskInfo *
getSODI(DiskInfo *self)
{
	return (StreamOptimizedDiskInfo *)self;
}

static bool
isPow2(uint64_t val)
{
	return (val & (val - 1)) == 0;
}

static bool
getGDGT(SparseGTInfo *gtInfo,
        const SparseExtentHeader *hdr)
{
	if (hdr->grainSize < 1 || hdr->grainSize > 128 || !isPow2(hdr->grainSize)) {
		return false;
	}
	/* disklib supports only 512 GTEs per GT (=> 4KB GT size).  Streaming is more flexible. */
	if (hdr->numGTEsPerGT < VMDK_SECTOR_SIZE / sizeof(uint32_t) || !isPow2(hdr->numGTEsPerGT)) {
		return false;
	}
	gtInfo->lastGrainNr = hdr->capacity / hdr->grainSize;
	gtInfo->lastGrainSize = (hdr->capacity & (hdr->grainSize - 1)) * VMDK_SECTOR_SIZE;

	{
		uint64_t GTEs = gtInfo->lastGrainNr + (gtInfo->lastGrainSize != 0);
		/* Number of GTEs must be less than 2^32.  Actually capacity must be less than 2^32 (2TB) for everything except streamOptimized format... */
		uint32_t GTs = CEILING(GTEs, hdr->numGTEsPerGT);
		uint32_t GDsectors = CEILING(GTs * sizeof(uint32_t), VMDK_SECTOR_SIZE);
		uint32_t GTsectors = CEILING(hdr->numGTEsPerGT * sizeof(uint32_t), VMDK_SECTOR_SIZE);
		uint32_t *gd = calloc(GDsectors + GTsectors * GTs, VMDK_SECTOR_SIZE);
		uint32_t *gt;

		if (!gd) {
			return false;
		}
		gt = gd + GDsectors * VMDK_SECTOR_SIZE / sizeof(uint32_t);
		gtInfo->GTEs = GTEs;
		gtInfo->GTs = GTs;
		gtInfo->GDsectors = GDsectors;
		gtInfo->gd = gd;
		gtInfo->GTsectors = GTsectors;
		gtInfo->gt = gt;
	}
	return true;
}

static SectorType
prefillGD(SparseGTInfo *gtInfo,
          SectorType gtBase)
{
	uint32_t i;

	for (i = 0; i < gtInfo->GTs; i++) {
		gtInfo->gd[i] = __cpu_to_le32(gtBase);
		gtBase += gtInfo->GTsectors;
	}
	return gtBase;
}

static bool
safeWrite(int fd,
          const void *buf,
          size_t len)
{
	ssize_t written = write(fd, buf, len);

	if (written == -1) {
		fprintf(stderr, "Write failed: %s\n", strerror(errno));
		return false;
	}
	if ((size_t)written != len) {
		fprintf(stderr, "Short write.  Disk full?\n");
		return false;
	}
	return true;
}

static bool
safePread(int fd,
          void *buf,
          size_t len,
          off_t pos)
{
	ssize_t rd = pread(fd, buf, len, pos);

	if (rd == -1) {
		fprintf(stderr, "Read failed: %s\n", strerror(errno));
		return false;
	}
	if ((size_t)rd != len) {
		fprintf(stderr, "Short read, %zu instead of %zu\n", rd, len);
		return false;
	}
	return true;
}

static bool
isZeroed(const void *data,
         size_t len)
{
	const uint64_t *data64 = data;
	len = len >> 3;

	while (len--) {
		if (*data64++ != 0) {
			return false;
		}
	}
	return true;
}

static int
fillGrain(StreamOptimizedDiskInfo *sodi)
{
	size_t lenBytes;

	if (sodi->writer.grainBufferNr < sodi->writer.gtInfo.lastGrainNr) {
		lenBytes = sodi->diskHdr.grainSize * VMDK_SECTOR_SIZE;
	} else if (sodi->writer.grainBufferNr == sodi->writer.gtInfo.lastGrainNr) {
		lenBytes = sodi->writer.gtInfo.lastGrainSize;
	} else {
		lenBytes = 0;
	}
	if (sodi->writer.grainBufferValidStart == 0 &&
	    sodi->writer.grainBufferValidEnd >= lenBytes) {
		return 0;
	}
	if (sodi->writer.gtInfo.gt[sodi->writer.grainBufferNr] != __cpu_to_le32(0)) {
		fprintf(stderr, "Unimplemented read-modify-write.\n");
		return -1;
	}
	if (sodi->writer.grainBufferValidStart != 0) {
		memset(sodi->writer.grainBuffer, 0, sodi->writer.grainBufferValidStart);
		sodi->writer.grainBufferValidStart = 0;
	}
	if (sodi->writer.grainBufferValidEnd < lenBytes) {
		memset(sodi->writer.grainBuffer + sodi->writer.grainBufferValidEnd, 0, lenBytes - sodi->writer.grainBufferValidEnd);
		sodi->writer.grainBufferValidEnd = lenBytes;
	}
	return 0;
}

static int
flushGrain(StreamOptimizedDiskInfo *sodi)
{
	int ret;
	uint32_t oldLoc;

	if (sodi->writer.grainBufferNr == ~0ULL) {
		return 0;
	}
	if (sodi->writer.grainBufferValidEnd == 0) {
		return 0;
	}
	ret = fillGrain(sodi);
	if (ret) {
		return ret;
	}

	oldLoc = __le32_to_cpu(sodi->writer.gtInfo.gt[sodi->writer.grainBufferNr]);
	if (oldLoc != 0) {
		fprintf(stderr, "Cannot update already written grain\n");
		return -1;
	}

	if (!isZeroed(sodi->writer.grainBuffer, sodi->writer.grainBufferValidEnd)) {
		size_t dataLen;
		uint32_t rem;
		SparseGrainLBAHeaderOnDisk *grainHdr = sodi->writer.zlibBuffer.grainHdr;

		sodi->writer.gtInfo.gt[sodi->writer.grainBufferNr] = __cpu_to_le32(sodi->writer.curSP);
		if (deflateReset(&sodi->writer.zstream) != Z_OK) {
			fprintf(stderr, "DeflateReset failed\n");
			return -1;
		}
		sodi->writer.zstream.next_in = sodi->writer.grainBuffer;
		sodi->writer.zstream.avail_in = sodi->writer.grainBufferValidEnd;
		sodi->writer.zstream.next_out = sodi->writer.zlibBuffer.data + sizeof *grainHdr;
		sodi->writer.zstream.avail_out = sodi->writer.zlibBufferSize - sizeof *grainHdr;
		if (deflate(&sodi->writer.zstream, Z_FINISH) != Z_STREAM_END) {
			fprintf(stderr, "Deflate failed\n");
			return -1;
		}
		dataLen = sodi->writer.zstream.next_out - sodi->writer.zlibBuffer.data;
		grainHdr->lba = sodi->writer.grainBufferNr * sodi->diskHdr.grainSize;
		grainHdr->cmpSize = __cpu_to_le32(dataLen - sizeof *grainHdr);
		rem = dataLen & (VMDK_SECTOR_SIZE - 1);
		if (rem != 0) {
			rem = VMDK_SECTOR_SIZE - rem;
			memset(sodi->writer.zstream.next_out, 0, rem);
			dataLen += rem;
		}
		if (!safeWrite(sodi->writer.fd, grainHdr, dataLen)) {
			return -1;
		}
		sodi->writer.curSP += dataLen / VMDK_SECTOR_SIZE;
	}
	return 0;
}

static int
prepareGrain(StreamOptimizedDiskInfo *sodi,
             uint64_t grainNr)
{
	if (grainNr != sodi->writer.grainBufferNr) {
		int ret;

		ret = flushGrain(sodi);
		if (ret < 0) {
			return ret;
		}
		sodi->writer.grainBufferNr = grainNr;
		sodi->writer.grainBufferValidStart = 0;
		sodi->writer.grainBufferValidEnd = 0;
	}
	return 0;
}

static ssize_t
StreamOptimizedPwrite(DiskInfo *self,
                      const void *buf,
                      size_t length,
                      off_t pos)
{
	const uint8_t *buf8 = buf;
	StreamOptimizedDiskInfo *sodi = getSODI(self);
	SparseVmdkWriter *writer = &sodi->writer;
	SparseExtentHeader *hdr = &sodi->diskHdr;
	uint64_t grainNr = pos / (hdr->grainSize * VMDK_SECTOR_SIZE);
	uint32_t updateStart = pos & (hdr->grainSize * VMDK_SECTOR_SIZE - 1);

	while (length > 0) {
		uint32_t updateLen;
		uint32_t updateEnd;

		if (prepareGrain(sodi, grainNr)) {
			return -1;
		}
		updateLen = hdr->grainSize * VMDK_SECTOR_SIZE - updateStart;
		if (length < updateLen) {
			updateLen = length;
			length = 0;
		} else {
			length -= updateLen;
		}
		updateEnd = updateStart + updateLen;
		if (writer->grainBufferValidEnd == 0) {
			;
		} else if (updateEnd < writer->grainBufferValidStart ||
		           updateStart > writer->grainBufferValidEnd) {
			if (fillGrain(sodi)) {
				return -1;
			}
		}
		memcpy(writer->grainBuffer + updateStart, buf8, updateLen);
		if (updateStart < writer->grainBufferValidStart || writer->grainBufferValidEnd == 0) {
			writer->grainBufferValidStart = updateStart;
		}
		if (updateEnd > writer->grainBufferValidEnd) {
			writer->grainBufferValidEnd = updateEnd;
		}
		buf8 += updateLen;
		grainNr++;
		updateStart = 0;
	}
	return buf8 - (const uint8_t *)buf;
}

static bool
writeSpecial(SparseVmdkWriter *writer,
             uint32_t marker,
             SectorType length)
{
	SparseSpecialLBAHeaderOnDisk *specialHdr = writer->zlibBuffer.specialHdr;

	memset(writer->zlibBuffer.data, 0, VMDK_SECTOR_SIZE);
	specialHdr->lba = __cpu_to_le64(length);
	specialHdr->type = __cpu_to_le32(marker);
	return safeWrite(writer->fd, specialHdr, VMDK_SECTOR_SIZE);
}

static bool
writeEOS(SparseVmdkWriter *writer)
{
	return writeSpecial(writer, GRAIN_MARKER_EOS, 0);
}

static int
StreamOptimizedFinalize(StreamOptimizedDiskInfo *sodi)
{
	int ret;

	ret = close(sodi->writer.fd);
	deflateEnd(&sodi->writer.zstream);
	free(sodi->writer.gtInfo.gd);
	free(sodi->writer.grainBuffer);
	free(sodi->writer.zlibBuffer.data);
	free(sodi->writer.fileName);
	free(sodi);
	return ret;
}

static int
StreamOptimizedAbort(DiskInfo *self)
{
	StreamOptimizedDiskInfo *sodi = getSODI(self);

	return StreamOptimizedFinalize(sodi);
}

static int
StreamOptimizedClose(DiskInfo *self)
{
	StreamOptimizedDiskInfo *sodi = getSODI(self);
	uint32_t cid;
	char *descFile;
	SparseExtentHeaderOnDisk onDisk;

	if (flushGrain(sodi)) {
		goto failAll;
	}
	writeEOS(&sodi->writer);
	if (lseek(sodi->writer.fd, sodi->writer.gdOffset * VMDK_SECTOR_SIZE, SEEK_SET) == -1) {
		goto failAll;
	}
	if (!safeWrite(sodi->writer.fd, sodi->writer.gtInfo.gd, (sodi->writer.gtInfo.GDsectors + sodi->writer.gtInfo.GTsectors * sodi->writer.gtInfo.GTs) * VMDK_SECTOR_SIZE)) {
		goto failAll;
	}
	do {
		cid = mrand48();
		/*
		 * Do not accept 0xFFFFFFFF and 0xFFFFFFFE.  They may be interpreted by
		 * some software as no parent, or disk full of zeroes.
		 */
	} while (cid == 0xFFFFFFFFU || cid == 0xFFFFFFFEU);
	descFile = makeDiskDescriptorFile(sodi->writer.fileName, sodi->diskHdr.capacity, cid);
	if (pwrite(sodi->writer.fd, descFile, strlen(descFile), sodi->diskHdr.descriptorOffset * VMDK_SECTOR_SIZE) != (ssize_t)strlen(descFile)) {
		free(descFile);
		goto failAll;
	}
	free(descFile);

	/*
	 * Write everything out as it should be, except that file signature is
	 * vmdk, rather than VMDK.  Then flush everything to the media, and finally
	 * rewrite header with proper VMDK signature.
	 */
	setSparseExtentHeader(&onDisk, &sodi->diskHdr, true);
	if (pwrite(sodi->writer.fd, &onDisk, sizeof onDisk, 0) != sizeof onDisk) {
		goto failAll;
	}
	if (fsync(sodi->writer.fd) != 0) {
		goto failAll;
	}
	setSparseExtentHeader(&onDisk, &sodi->diskHdr, false);
	if (pwrite(sodi->writer.fd, &onDisk, sizeof onDisk, 0) != sizeof onDisk) {
		goto failAll;
	}
	if (fsync(sodi->writer.fd) != 0) {
		goto failAll;
	}
	return StreamOptimizedFinalize(sodi);

failAll:
	StreamOptimizedAbort(&sodi->hdr);
	return -1;
}

static DiskInfoVMT streamOptimizedVMT = {
	.pwrite = StreamOptimizedPwrite,
	.close = StreamOptimizedClose,
	.abort = StreamOptimizedAbort
};

DiskInfo *
StreamOptimized_Create(const char *fileName, off_t capacity)
{
	StreamOptimizedDiskInfo *sodi;
	size_t maxOutSize;

	sodi = malloc(sizeof *sodi);
	if (!sodi) {
		goto fail;
	}
	memset(sodi, 0, sizeof *sodi);
	sodi->writer.fileName = strdup(fileName);
	if (!sodi->writer.fileName) {
		goto failSODI;
	}
	sodi->hdr.vmt = &streamOptimizedVMT;
	sodi->diskHdr.version = SPARSE_VERSION_INCOMPAT_FLAGS;
	sodi->diskHdr.flags = SPARSEFLAG_VALID_NEWLINE_DETECTOR | SPARSEFLAG_COMPRESSED | SPARSEFLAG_EMBEDDED_LBA;
	sodi->diskHdr.numGTEsPerGT = 512;
	sodi->diskHdr.compressAlgorithm = SPARSE_COMPRESSALGORITHM_DEFLATE;
	sodi->diskHdr.grainSize = 128;
	sodi->diskHdr.overHead = 1;
	sodi->diskHdr.capacity = CEILING(capacity, VMDK_SECTOR_SIZE);
	if (!getGDGT(&sodi->writer.gtInfo, &sodi->diskHdr)) {
		goto failFileName;
	}
	sodi->writer.fd = open(fileName, O_RDWR | O_CREAT | O_TRUNC, 0666);
	if (sodi->writer.fd == -1) {
		goto failGDGT;
	}
	sodi->diskHdr.descriptorOffset = sodi->diskHdr.overHead;
	sodi->diskHdr.descriptorSize = 20;
	sodi->diskHdr.overHead = sodi->diskHdr.overHead + sodi->diskHdr.descriptorSize;
	sodi->writer.gdOffset = sodi->diskHdr.overHead;
	sodi->diskHdr.gdOffset = sodi->writer.gdOffset;
	sodi->diskHdr.overHead += sodi->writer.gtInfo.GDsectors;
	sodi->writer.gtOffset = sodi->diskHdr.overHead;
	sodi->diskHdr.overHead = prefillGD(&sodi->writer.gtInfo, sodi->diskHdr.overHead);
	sodi->writer.curSP = sodi->diskHdr.overHead;
	sodi->writer.grainBuffer = malloc(sodi->diskHdr.grainSize * VMDK_SECTOR_SIZE);
	if (!sodi->writer.grainBuffer) {
		goto failFD;
	}
	sodi->writer.grainBufferNr = ~0ULL;
	sodi->writer.zstream.zalloc = NULL;
	sodi->writer.zstream.zfree = NULL;
	sodi->writer.zstream.opaque = &sodi->writer;
	if (deflateInit(&sodi->writer.zstream, Z_BEST_COMPRESSION) != Z_OK) {
		goto failGrainBuffer;
	}
	maxOutSize = deflateBound(&sodi->writer.zstream, sodi->diskHdr.grainSize * VMDK_SECTOR_SIZE) + sizeof(SparseGrainLBAHeaderOnDisk);
	maxOutSize = (maxOutSize + VMDK_SECTOR_SIZE - 1) & ~(VMDK_SECTOR_SIZE - 1);
	sodi->writer.zlibBufferSize = maxOutSize;
	sodi->writer.zlibBuffer.data = malloc(maxOutSize);
	if (!sodi->writer.zlibBuffer.data) {
		goto failDeflate;
	}
	if (lseek(sodi->writer.fd, sodi->writer.curSP * VMDK_SECTOR_SIZE, SEEK_SET) == -1) {
		goto failAll;
	}
	return &sodi->hdr;

failAll:
	free(sodi->writer.zlibBuffer.data);
failDeflate:
	deflateEnd(&sodi->writer.zstream);
failGrainBuffer:
	free(sodi->writer.grainBuffer);
failFD:
	close(sodi->writer.fd);
failGDGT:
	free(sodi->writer.gtInfo.gd);
failFileName:
	free(sodi->writer.fileName);
failSODI:
	free(sodi);
fail:
	return NULL;
}

typedef struct {
	DiskInfo hdr;
	SparseExtentHeader diskHdr;
	SparseGTInfo gtInfo;
	size_t readBufferSize;
	z_stream zstream;
	int fd;
} SparseDiskInfo;

typedef struct {
	off_t pos;
	uint8_t *buf;
	size_t len;
	int fd;
} CoalescedPreader;

static void
CoalescedPreaderInit(CoalescedPreader *p,
                     int fd)
{
	p->fd = fd;
	p->len = 0;
}

static int
CoalescedPreaderExec(CoalescedPreader *p)
{
	return p->len ? safePread(p->fd, p->buf, p->len, p->pos) ? 0 : -1 : 0;
}

static int
CoalescedPreaderPread(CoalescedPreader *p,
                      void *buf,
                      size_t len,
                      off_t pos)
{
	if (len != 0) {
		if (0 == p->pos + p->len - pos &&
                    buf == p->buf + p->len) {
			p->len += len;
			return 0;
		}
		if (CoalescedPreaderExec(p)) {
			return -1;
		}
	}
	p->buf = buf;
	p->len = len;
	p->pos = pos;
	return 0;
}

static SparseDiskInfo *
getSDI(DiskInfo *self)
{
	return (SparseDiskInfo *)self;
}

static off_t
SparseGetCapacity(DiskInfo *self)
{
	SparseDiskInfo *sdi = getSDI(self);

	return sdi->diskHdr.capacity * VMDK_SECTOR_SIZE;
}

static int
SparseNextData(DiskInfo *self,
               off_t *pos,
               off_t *end)
{
	SparseDiskInfo *sdi = getSDI(self);
	off_t p = *end;
	uint32_t grainNr = p / (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE);
	uint32_t skip = p & (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE - 1);
	bool want = false;

	while (grainNr < sdi->gtInfo.GTEs) {
		bool empty = sdi->gtInfo.gt[grainNr] == __cpu_to_le32(0);

		if (empty == want) {
			if (want) {
				*end = grainNr * (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE);
				return 0;
			}
			*pos = grainNr * (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE) | skip;
			want = true;
		}
		skip = 0;
		grainNr++;
	}
	if (want) {
		*end = sdi->gtInfo.lastGrainNr * (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE) + sdi->gtInfo.lastGrainSize;
		return 0;
	}
	errno = ENXIO;
	return -1;
}

static ssize_t
SparsePread(DiskInfo *self,
            void *buf,
            size_t len,
            off_t pos)
{
	SparseDiskInfo *sdi = getSDI(self);
	uint8_t *buf8 = buf;
	uint8_t grainBuf[sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE];
	uint8_t readBuf[(sdi->diskHdr.grainSize + 1) * VMDK_SECTOR_SIZE];
	z_stream zstream = {0};
	uint32_t grainNr = pos / (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE);
	uint32_t readSkip = pos & (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE - 1);

	if (inflateInit(&zstream) != Z_OK) {
		return -1;
	}

	while (len > 0) {
		uint32_t readLen;
		uint32_t sect;
		uint32_t grainSize;

		if (grainNr < sdi->gtInfo.lastGrainNr) {
			grainSize = sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE;
		} else if (grainNr == sdi->gtInfo.lastGrainNr) {
			grainSize = sdi->gtInfo.lastGrainSize;
		} else {
			grainSize = 0;
		}
		if (readSkip >= grainSize) {
			break;
		}
		readLen = grainSize - readSkip;
		if (len < readLen)
			readLen = len;

		sect = __le32_to_cpu(sdi->gtInfo.gt[grainNr]);
		if (sect == 0) {
			/* Read from parent... No parent for us... */
			memset(buf8, 0, readLen);
		} else if (sect == 1) {
			memset(buf8, 0, readLen);
		} else {
			if (sdi->diskHdr.flags & SPARSEFLAG_COMPRESSED) {
				uint32_t hdrlen;
				uint32_t cmpSize;

				if (!safePread(sdi->fd, readBuf, VMDK_SECTOR_SIZE, sect * VMDK_SECTOR_SIZE)) {
					return -1;
				}
				if (sdi->diskHdr.flags & SPARSEFLAG_EMBEDDED_LBA) {
					SparseGrainLBAHeaderOnDisk *hdr = (SparseGrainLBAHeaderOnDisk *)readBuf;

					if (__le64_to_cpu(hdr->lba) != grainNr * sdi->diskHdr.grainSize) {
						return -1;
					}
					cmpSize = __le32_to_cpu(hdr->cmpSize);
					hdrlen = 12;
				} else {
					cmpSize = __le32_to_cpu(*(__le32*)readBuf);
					hdrlen = 4;
				}
				if (cmpSize > sizeof readBuf - hdrlen) {
					return -1;
				}
				if (cmpSize + hdrlen > VMDK_SECTOR_SIZE) {
					size_t remainingLength = (cmpSize + hdrlen - VMDK_SECTOR_SIZE + VMDK_SECTOR_SIZE - 1) & ~(VMDK_SECTOR_SIZE - 1);

					if (!safePread(sdi->fd, readBuf + VMDK_SECTOR_SIZE, remainingLength, (sect + 1) * VMDK_SECTOR_SIZE)) {
						return -1;
					}
				}
				zstream.next_in = readBuf + hdrlen;
				zstream.avail_in = cmpSize;
				zstream.next_out = grainBuf;
				zstream.avail_out = sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE;
				if (inflate(&zstream, Z_FINISH) != Z_STREAM_END) {
					return -1;
				}
				if (sdi->diskHdr.grainSize * VMDK_SECTOR_SIZE - zstream.avail_out < grainSize) {
					return -1;
				}
				memcpy(buf8, grainBuf + readSkip, readLen);
			} else {
				if (!safePread(sdi->fd, buf8, readLen, sect * VMDK_SECTOR_SIZE + readSkip)) {
					return -1;
				}
			}
		}
		buf8 += readLen;
		len -= readLen;
		grainNr++;
		readSkip = 0;
		if (len > 0) {
			if (inflateReset(&zstream) != Z_OK) {
				return -1;
			}
		}
	}
	return buf8 - (uint8_t *)buf;
}

static int
SparseClose(DiskInfo *self)
{
	SparseDiskInfo *sdi = getSDI(self);
	int fd;

	free(sdi->gtInfo.gd);
	fd = sdi->fd;
	free(sdi);
	return close(fd);
}


static DiskInfoVMT sparseVMT = {
	.getCapacity = SparseGetCapacity,
	.nextData = SparseNextData,
	.pread = SparsePread,
	.close = SparseClose,
	.abort = SparseClose,
};

DiskInfo *
Sparse_Open(const char *fileName)
{
	SparseDiskInfo *sdi;
	int fd;
	SparseExtentHeaderOnDisk onDisk;
	uint32_t i;
	uint32_t *gt;
	CoalescedPreader cp = {0};

	fd = open(fileName, O_RDONLY);
	if (fd == -1) {
		goto fail;
	}
	if (read(fd, &onDisk, sizeof onDisk) != sizeof onDisk) {
		goto failFd;
	}
	if (!checkSparseExtentHeader(&onDisk)) {
		goto failFd;
	}
	sdi = malloc(sizeof *sdi);
	if (!sdi) {
		goto failFd;
	}
	memset(sdi, 0, sizeof *sdi);
	sdi->fd = fd;
	if (!getSparseExtentHeader(&sdi->diskHdr, &onDisk)) {
		goto failSdi;
	}
	sdi->hdr.vmt = &sparseVMT;
	if (!getGDGT(&sdi->gtInfo, &sdi->diskHdr)) {
		goto failSdi;
	}
	if (sdi->diskHdr.flags & SPARSEFLAG_COMPRESSED) {
		sdi->readBufferSize = (sdi->diskHdr.grainSize + 1) * VMDK_SECTOR_SIZE;
		sdi->zstream.zalloc = NULL;
		sdi->zstream.zfree = NULL;
		sdi->zstream.opaque = sdi;
		if (inflateInit(&sdi->zstream) != Z_OK) {
			goto failRB;
		}
	}
	if (!safePread(fd, sdi->gtInfo.gd, sdi->gtInfo.GDsectors * VMDK_SECTOR_SIZE, sdi->diskHdr.gdOffset * VMDK_SECTOR_SIZE)) {
		goto failDF;
	}
	CoalescedPreaderInit(&cp, fd);
	gt = sdi->gtInfo.gt;
	for (i = 0; i < sdi->gtInfo.GTs; i++) {
		uint32_t loc = __le32_to_cpu(sdi->gtInfo.gd[i]);

		if (loc != 0) {
			if (CoalescedPreaderPread(&cp, gt, sdi->gtInfo.GTsectors * VMDK_SECTOR_SIZE, loc * VMDK_SECTOR_SIZE)) {
				goto failDF;
			}
		}
		gt += sdi->diskHdr.numGTEsPerGT;
	}
	if (CoalescedPreaderExec(&cp)) {
		goto failDF;
	}
	return &sdi->hdr;

failDF:
failRB:
failSdi:
	free(sdi);
failFd:
	close(fd);
fail:
	return NULL;
}

