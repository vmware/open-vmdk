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

#ifndef _VMWARE_VMDK_H_
#define _VMWARE_VMDK_H_

#include <asm/byteorder.h>
#include <stdint.h>
#include <stdbool.h>

#pragma pack(push, 1)
typedef struct {
	__le32	magicNumber;
	__le32	version;
	__le32	flags;
	__le64	capacity; /* UA */
	__le64	grainSize; /* UA */
	__le64	descriptorOffset; /* UA */
	__le64	descriptorSize; /* UA */
	__le32	numGTEsPerGT;
	__le64	rgdOffset;
	__le64	gdOffset;
	__le64	overHead;
	uint8_t	uncleanShutdown;
	char	singleEndLineChar;
	char	nonEndLineChar;
	char	doubleEndLineChar1;
	char	doubleEndLineChar2;
	__le16	compressAlgorithm; /* UA */
	uint8_t	pad[433];
} SparseExtentHeaderOnDisk;
#pragma pack(pop)

#define SPARSE_MAGICNUMBER			0x564d444b /* VMDK */
#define SPARSE_VERSION_INCOMPAT_FLAGS		3
#define SPARSE_GTE_EMPTY			0x00000000
#define SPARSE_GD_AT_END			0xFFFFFFFFFFFFFFFFULL
#define SPARSE_SINGLE_END_LINE_CHAR		'\n'
#define SPARSE_NON_END_LINE_CHAR		' '
#define SPARSE_DOUBLE_END_LINE_CHAR1		'\r'
#define SPARSE_DOUBLE_END_LINE_CHAR2		'\n'
#define SPARSEFLAG_COMPAT_FLAGS			0x0000FFFFU
#define SPARSEFLAG_VALID_NEWLINE_DETECTOR	(1 << 0)
#define SPARSEFLAG_USE_REDUNDANT		(1 << 1)
#define SPARSEFLAG_MAGIC_GTE			(1 << 2)
#define SPARSEFLAG_INCOMPAT_FLAGS		0xFFFF0000U
#define SPARSEFLAG_COMPRESSED			(1 << 16)
#define SPARSEFLAG_EMBEDDED_LBA			(1 << 17)
#define SPARSE_COMPRESSALGORITHM_NONE		0x0000
#define SPARSE_COMPRESSALGORITHM_DEFLATE	0x0001

#pragma pack(push, 1)
typedef struct {
	__le64	lba;
	__le32	cmpSize;
} SparseGrainLBAHeaderOnDisk;
#pragma pack(pop)

#pragma pack(push, 1)
typedef struct {
	__le64	lba;
	__le32	cmpSize;
	__le32	type;
} SparseSpecialLBAHeaderOnDisk;
#pragma pack(pop)

#define GRAIN_MARKER_EOS		0
#define GRAIN_MARKER_GRAIN_TABLE	1
#define GRAIN_MARKER_GRAIN_DIRECTORY	2
#define GRAIN_MARKER_FOOTER		3
#define GRAIN_MARKER_PROGRESS		4

typedef uint64_t SectorType;

typedef struct {
	uint32_t	version;
	uint32_t	flags;
	uint32_t	numGTEsPerGT;
	uint16_t	compressAlgorithm;
	uint8_t		uncleanShutdown;
	uint8_t		reserved;
	SectorType	capacity;
	SectorType	grainSize;
	SectorType	descriptorOffset;
	SectorType	descriptorSize;
	SectorType	rgdOffset;
	SectorType	gdOffset;
	SectorType	overHead;
} SparseExtentHeader;

#endif /* _VMWARE_VMDK_H_ */
