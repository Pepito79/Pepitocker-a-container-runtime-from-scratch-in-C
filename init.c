#define _DEFAULT_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#define PEPITOCKER_ROOT "/var/lib/pepitocker"

/* Create a single directory if it does not already exist. Returns 0 on success, -1 on error. */
static int ensure_dir(const char *path, mode_t mode)
{
    if (mkdir(path, mode) == 0)
    {
        return 0;
    }

    if (errno == EEXIST)
    {
        struct stat st;
        if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
        {
            return 0;
        }
        fprintf(stderr, "[ERROR] '%s' exists but is not a directory\n", path);
        return -1;
    }

    fprintf(stderr, "[ERROR] Failed to create '%s': %s\n", path, strerror(errno));
    return -1;
}

/* Recursively create parent directories as needed (similar to `mkdir -p`). */
static int ensure_dir_p(const char *path, mode_t mode)
{
    char buf[PATH_MAX];
    size_t len = strlen(path);

    if (len == 0 || len >= sizeof(buf))
    {
        fprintf(stderr, "[ERROR] Invalid or too-long path: %s\n", path);
        return -1;
    }

    strcpy(buf, path);
    /* Strip trailing slashes except for the root path "/" */
    while (len > 1 && buf[len - 1] == '/')
    {
        buf[--len] = '\0';
    }

    for (char *p = buf + 1; *p; p++)
    {
        if (*p == '/')
        {
            *p = '\0';
            if (ensure_dir(buf, mode) != 0)
            {
                return -1;
            }
            *p = '/';
        }
    }

    return ensure_dir(buf, mode);
}

/* Initialize base directories for pepitocker storage. */
int init_storage(const char *base_dir)
{
    const char *root = (base_dir && *base_dir) ? base_dir : PEPITOCKER_ROOT;

    if (ensure_dir_p(root, 0755) != 0)
    {
        return -1;
    }

    const char *dirs[] = {"layers", "rootfs", "images"};
    for (size_t i = 0; i < 3; i++)
    {
        char path[PATH_MAX];
        int n = snprintf(path, sizeof(path), "%s/%s", root, dirs[i]);
        if (n < 0 || (size_t)n >= sizeof(path))
        {
            fprintf(stderr, "[ERROR] Path too long for '%s'\n", dirs[i]);
            return -1;
        }
        if (ensure_dir(path, 0755) != 0)
        {
            return -1;
        }
    }

    return 0;
}

#ifdef INIT_TEST
int main(void)
{
    if (init_storage(PEPITOCKER_ROOT) != 0)
    {
        return EXIT_FAILURE;
    }
    printf("[OK] Directories ready in %s (layers, rootfs,images)\n", PEPITOCKER_ROOT);
    return EXIT_SUCCESS;
}
#endif