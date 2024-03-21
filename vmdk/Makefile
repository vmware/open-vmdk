# ================================================================================
# Copyright (c) 2014-2023 VMware, Inc.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the “License”); you may not
# use this file except in compliance with the License.  You may obtain a copy of
# the License at:
#
#              http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an “AS IS” BASIS, without warranties or
# conditions of any kind, EITHER EXPRESS OR IMPLIED.  See the License for the
# specific language governing permissions and limitations under the License.
# ================================================================================

SRC := flat.c sparse.c mkdisk.c
SRC_FUSE := sparse.c vmdk-fuse.c

OUTPUTDIR := ../build/vmdk
EXE := $(OUTPUTDIR)/vmdk-convert
EXE_FUSE := $(OUTPUTDIR)/vmdk-fuse

PREFIX ?= /usr

CC := gcc
CFLAGS := -W -Wall -O2 -g $(CFLAGS)
LDFLAGS := -g -lz $(LDFLAGS)
LDFLAGS_FUSE := $(LDFLAGS) $$(pkg-config fuse3 --libs)

OBJS := $(addprefix $(OUTPUTDIR)/, $(SRC:%.c=%.o))
OBJS_FUSE := $(addprefix $(OUTPUTDIR)/, $(SRC_FUSE:%.c=%.o))

default: all

all: $(EXE) $(EXE_FUSE)

$(EXE): $(OBJS) $(OUTPUTDIR)
	$(CC) -o $@ $(OBJS) $(LDFLAGS)

$(EXE_FUSE): $(OBJS_FUSE) $(OUTPUTDIR)
	$(CC) -o $@ $(OBJS_FUSE) $(LDFLAGS_FUSE)

$(OUTPUTDIR)/%.o: %.c | $(OUTPUTDIR)
	$(CC) $(CFLAGS) -c -o $@ $<

$(OUTPUTDIR)/vmdk-fuse.o: vmdk-fuse.c | $(OUTPUTDIR)
	$(CC) $(CFLAGS) $$(pkg-config fuse3 --cflags) -c -o $@ $<

$(OUTPUTDIR):
	mkdir -p $(OUTPUTDIR)

$(addprefix $(OUTPUTDIR)/,mkdisk.o flat.o sparse.o): diskinfo.h

$(addprefix $(OUTPUTDIR)/,sparse.o): vmware_vmdk.h

check:
	sparse -Wsparse-all -I/usr/include/x86_64-linux-gnu $(SRC)

install:
	mkdir -p $(DESTDIR)/$(PREFIX)/bin && cp $(EXE) $(EXE_FUSE) $(DESTDIR)/$(PREFIX)/bin/

clean:
	rm -rf $(OUTPUTDIR)
