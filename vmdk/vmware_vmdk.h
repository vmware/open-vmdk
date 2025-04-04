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

#ifndef _VMWARE_VMDK_H_
#define _VMWARE_VMDK_H_

#include <asm/byteorder.h>
#include <stdint.h>
#include <stdbool.h>

#pragma pack(push, 1)
typedef struct {
    __le32  magicNumber;
    __le32  version;
    __le32  flags;
    __le64  capacity; /* UA */
    __le64  grainSize; /* UA */
    __le64  descriptorOffset; /* UA */
    __le64  descriptorSize; /* UA */
    __le32  numGTEsPerGT;
    __le64  rgdOffset;
    __le64  gdOffset;
    __le64  overHead;
    uint8_t uncleanShutdown;
    char    singleEndLineChar;
    char    nonEndLineChar;
    char    doubleEndLineChar1;
    char    doubleEndLineChar2;
    __le16  compressAlgorithm; /* UA */
    uint8_t pad[433];
} SparseExtentHeaderOnDisk;
#pragma pack(pop)

#define SPARSE_MAGICNUMBER                  0x564d444b /* VMDK */
#define SPARSE_VERSION_INCOMPAT_FLAGS       3
#define SPARSE_GTE_EMPTY                    0x00000000
#define SPARSE_GD_AT_END                    0xFFFFFFFFFFFFFFFFULL
#define SPARSE_SINGLE_END_LINE_CHAR         '\n'
#define SPARSE_NON_END_LINE_CHAR            ' '
#define SPARSE_DOUBLE_END_LINE_CHAR1        '\r'
#define SPARSE_DOUBLE_END_LINE_CHAR2        '\n'
#define SPARSEFLAG_COMPAT_FLAGS             0x0000FFFFU
#define SPARSEFLAG_VALID_NEWLINE_DETECTOR   (1 << 0)
#define SPARSEFLAG_USE_REDUNDANT            (1 << 1)
#define SPARSEFLAG_MAGIC_GTE                (1 << 2)
#define SPARSEFLAG_INCOMPAT_FLAGS           0xFFFF0000U
#define SPARSEFLAG_COMPRESSED               (1 << 16)
#define SPARSEFLAG_EMBEDDED_LBA             (1 << 17)
#define SPARSE_COMPRESSALGORITHM_NONE       0x0000
#define SPARSE_COMPRESSALGORITHM_DEFLATE    0x0001

#pragma pack(push, 1)
typedef struct {
    __le64  lba;
    __le32  cmpSize;
} SparseGrainLBAHeaderOnDisk;
#pragma pack(pop)

#pragma pack(push, 1)
typedef struct {
    __le64  lba;
    __le32  cmpSize;
    __le32  type;
} SparseSpecialLBAHeaderOnDisk;
#pragma pack(pop)

#define GRAIN_MARKER_EOS                0
#define GRAIN_MARKER_GRAIN_TABLE        1
#define GRAIN_MARKER_GRAIN_DIRECTORY    2
#define GRAIN_MARKER_FOOTER             3
#define GRAIN_MARKER_PROGRESS           4

typedef uint64_t SectorType;

typedef struct {
    uint32_t    version;
    uint32_t    flags;
    uint32_t    numGTEsPerGT;
    uint16_t    compressAlgorithm;
    uint8_t     uncleanShutdown;
    uint8_t     reserved;
    SectorType  capacity;
    SectorType  grainSize;
    SectorType  descriptorOffset;
    SectorType  descriptorSize;
    SectorType  rgdOffset;
    SectorType  gdOffset;
    SectorType  overHead;
} SparseExtentHeader;

#endif /* _VMWARE_VMDK_H_ */
