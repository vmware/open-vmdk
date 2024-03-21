/*
  FUSE: Filesystem in Userspace
  Copyright (C) 2001-2007  Miklos Szeredi <miklos@szeredi.hu>
  Copyright (C) 2014 Broadcom

  This program can be distributed under the terms of the GNU GPLv2.
  See the file COPYING.
*/

/** @file
 *
 * This "filesystem" provides only a single file. The mountpoint
 * needs to be a file rather than a directory.
 */


#define FUSE_USE_VERSION 31

#include <fuse.h>
#include <fuse_lowlevel.h>

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>

#include "diskinfo.h"

char *toolsVersion = "2147483647";

struct options {
    char *vmdk_path;
};

#define OPTION(t, p) { t, offsetof(struct options, p), 1 }
static const struct fuse_opt option_spec[] = {
                OPTION("--file=%s", vmdk_path),
                FUSE_OPT_END
};

struct vmdk_data {
    struct options options;
    off_t capacity;
};

static int vmdk_getattr(const char *path, struct stat *stbuf,
                        struct fuse_file_info *fi)
{
	(void) fi;
    struct stat st;
    struct vmdk_data *data = (struct vmdk_data *)fuse_get_context()->private_data;
    char *vmdk_path = data->options.vmdk_path;

    if(strcmp(path, "/") != 0)
        return -ENOENT;

    stat(vmdk_path, &st);

    stbuf->st_mode = st.st_mode;
    stbuf->st_nlink = 1;
    stbuf->st_uid = getuid();
    stbuf->st_gid = getgid();
    stbuf->st_size = data->capacity;
    stbuf->st_blocks = 0;
    stbuf->st_atime = st.st_atime;
    stbuf->st_mtime = st.st_mtime;
    stbuf->st_ctime = st.st_ctime;

	return 0;
}

static int vmdk_truncate(const char *path, off_t size,
                         struct fuse_file_info *fi)
{
    (void) size;
    (void) fi;

    if(strcmp(path, "/") != 0)
        return -ENOENT;

    return -EROFS;
}

static int vmdk_open(const char *path, struct fuse_file_info *fi)
{
    (void) fi;

    if(strcmp(path, "/") != 0)
        return -ENOENT;

    struct vmdk_data *data = (struct vmdk_data *)fuse_get_context()->private_data;
    DiskInfo *di = Sparse_Open(data->options.vmdk_path);
    if (di == NULL) {
        fprintf(stderr, "could not read %s\n", data->options.vmdk_path);
        return -EIO;
    }

    fi->fh = (uint64_t)di;

	return 0;
}

static int vmdk_release(const char *path, struct fuse_file_info *fi)
{
    if(strcmp(path, "/") != 0)
        return -ENOENT;

    DiskInfo *di = (DiskInfo *)(fi->fh);
    if (di == NULL)
        return -EIO;

    di->vmt->close(di);

    return 0;
}

static int vmdk_read(const char *path, char *buf, size_t size,
		             off_t offset, struct fuse_file_info *fi)
{
    if(strcmp(path, "/") != 0)
        return -ENOENT;

    DiskInfo *di = (DiskInfo *)(fi->fh);
    if (di == NULL)
        return -EIO;

    if (di->vmt->pread(di, (void *)buf, size, offset) != (ssize_t)size) {
        return -EIO;
    }

    return size;
}

static int vmdk_write(const char *path, const char *buf, size_t size,
		      off_t offset, struct fuse_file_info *fi)
{
    (void) buf;
    (void) offset;
    (void) fi;
    (void) size;

    if(strcmp(path, "/") != 0)
        return -ENOENT;

    return -EROFS;
}

static const struct fuse_operations vmdk_oper = {
    .getattr	= vmdk_getattr,
    .truncate	= vmdk_truncate,
    .open		= vmdk_open,
    .release    = vmdk_release,
    .read		= vmdk_read,
    .write		= vmdk_write,
};

int vmdk_init(struct vmdk_data *data)
{
    DiskInfo *di;

    di = Sparse_Open(data->options.vmdk_path);
    if (di == NULL) {
        fprintf(stderr, "could not read %s\n", data->options.vmdk_path);
        return 1;
    }
    data->capacity = di->vmt->getCapacity(di);
    di->vmt->close(di);

    return 0;
}

int main(int argc, char *argv[])
{
	struct fuse_args args = FUSE_ARGS_INIT(argc, argv);
	struct stat stbuf;
    struct vmdk_data data = {0};
    int argc_saved;
    char **argv_saved;

    if (fuse_opt_parse(&args, &data.options, option_spec, NULL) == -1)
            return 1;

    if (!data.options.vmdk_path) {
        fprintf(stderr, "missing vmdk file parameter (file=)\n");
        return 1;        
    } else {
        char *tmp = data.options.vmdk_path;
        data.options.vmdk_path = realpath(data.options.vmdk_path, NULL);
        free(tmp);
    }

    if (stat(data.options.vmdk_path, &stbuf) == -1) {
        fprintf(stderr ,"failed to access vmdk file %s: %s\n",
            data.options.vmdk_path, strerror(errno));
        free(data.options.vmdk_path);
        return 1;
    }
    if (!S_ISREG(stbuf.st_mode)) {
        fprintf(stderr, "vmdk file %s is not a regular file\n", data.options.vmdk_path);
        return 1;
    }

    argc_saved = args.argc;
    argv_saved = args.argv;

    if (vmdk_init(&data) != 0) {
        return 1;
    }

    printf("before fuse_main\n");
    return fuse_main(argc_saved, argv_saved, &vmdk_oper, (void *)&data);
}
