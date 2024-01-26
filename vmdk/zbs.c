#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <zbs/libzbs.h>

#include "block.h"

typedef struct zbs {
    void* zbs_client;
    const char* zbs_volume_id;
    off_t seek;
    int flags;
} zbs;

zbs* zbs_open(const char* hosts, const char* volume_id, int flags) {
    char* err = NULL;
    zbs* z = (zbs*)malloc(sizeof(zbs));
    z->zbs_client = zbs_create_external(hosts, &err);
    if (!z->zbs_client) {
        printf("[%s] create zbs client with host '%s' error.\n", err, hosts);
        zbs_free_err_str(err);
        return NULL;
    }

    z->zbs_volume_id = volume_id;
    z->seek = 0;
    z->flags = flags;

    return z;
}

off_t zbs_seek(zbs* z, off_t offset, int whence) {
    switch (whence) {
        case SEEK_SET:
            z->seek = offset;
            break;
        case SEEK_CUR:
            z->seek += offset;
            break;
        default:
            return -1;
    }

    return z->seek;
}

ssize_t zbs_pread_volume(zbs* z, void* buf, size_t n_bytes, off_t offset) {
    int read_ret;
    read_ret = zbs_read(z->zbs_client, z->zbs_volume_id, buf, (uint32_t)n_bytes, (uint64_t)offset);
    if (read_ret < 0) {
        printf("read volume '%s' at '%ld' error.\n", z->zbs_volume_id, z->seek);
        return read_ret;
    }

    return n_bytes;
}

ssize_t zbs_read_volume(zbs* z, void* buf, size_t n_bytes) {
    int read_ret = zbs_pread_volume(z, buf, n_bytes, z->seek);
    if (read_ret < 0) {
        return read_ret;
    }

    z->seek += (off_t)n_bytes;

    return n_bytes;
}

ssize_t zbs_pwrite_volume(zbs* z, void* buf, size_t n_bytes, off_t offset) {
    int write_ret;
    if (z->flags & O_RDONLY) {
        printf("cannot write a read-only volume '%s'.\n", z->zbs_volume_id);
        return -1;
    }

    write_ret = zbs_write(z->zbs_client, z->zbs_volume_id, buf, (uint32_t)n_bytes, (uint64_t)offset);
    if (write_ret < 0) {
        printf("write volume '%s' at '%ld' error.\n", z->zbs_volume_id, offset);
        return write_ret;
    }

    return n_bytes;
}

ssize_t zbs_write_volume(zbs* z, void* buf, size_t n_bytes) {
    int write_ret = zbs_pwrite_volume(z, buf, n_bytes, z->seek);
    if (write_ret < 0) {
        return write_ret;
    }

    z->seek += (off_t)n_bytes;

    return n_bytes;
}

ssize_t zbs_get_size(zbs* z) {
    return z->seek;
}

int zbs_close(zbs* z) {
    zbs_destroy(z->zbs_client);
    free(z);

    return 0;
}

block* new_zbs_block(const char* hosts, const char* volume_id, int flags) {
    block* b = (block*)malloc(sizeof(block));

    b->opaque = zbs_open(hosts, volume_id, flags);
    if (!b->opaque) {
        free(b);
        return NULL;
    }

    b->seek = zbs_seek;
    b->pread = zbs_pread_volume;
    b->read = zbs_read_volume;
    b->pwrite = zbs_pwrite_volume;
    b->write = zbs_write_volume;
    b->get_size = zbs_get_size;
    b->close = zbs_close;

    return b;
}
