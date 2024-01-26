#include <unistd.h>

typedef struct block {
    void* opaque;
    off_t (*seek)(void* opaque, off_t offset, int whence);
    ssize_t (*read)(void* opaque, void* buf, size_t n_bytes);
    ssize_t (*pread)(void* opaque, void* buf, size_t n_bytes, off_t offset);
    ssize_t (*write)(void* opaque, const void* buf, size_t n_bytes);
    ssize_t (*pwrite)(void* opaque, void* buf, size_t n_bytes, off_t offset);
    ssize_t (*get_size)(void* opaque);
    int (*close)(void* opaque);
} block;

block* new_zbs_block(const char* hosts, const char* volume_id, int flags);
