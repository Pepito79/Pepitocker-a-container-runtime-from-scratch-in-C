#define _GNU_SOURCE
#include <sched.h>
#include <sys/mount.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define CGROUP_DIR "/sys/fs/cgroup/pepitocker"
#define CGROUP_SUBTREE "/sys/fs/cgroup/pepitocker/cgroup.subtree_control"

unsigned long long parse_memory_size(const char *str)
{
    if (strcmp(str, "max") == 0)
    {
        return 0; // Indique qu'il faut écrire "max" directement
    }

    char *endptr;
    unsigned long long val = strtoull(str, &endptr, 10);

    if (*endptr != '\0')
    {
        switch (*endptr)
        {
        case 'k':
        case 'K':
            val *= 1024ULL;
            break;
        case 'm':
        case 'M':
            val *= 1024ULL * 1024ULL;
            break;
        case 'g':
        case 'G':
            val *= 1024ULL * 1024ULL * 1024ULL;
            break;
        }
    }
    return val;
}
int pivot_root(const char *new_root, const char *old_root)
{
    return syscall(SYS_pivot_root, new_root, old_root);
}

FILE *open_file(const char *path, const char *mode)
{
    FILE *f = fopen(path, mode);
    if (!f)
    {
        perror("[ERROR] Cannot open a file");
        return NULL;
    }

    return f;
}

int configure_cgroup(const char *memory_size, const char *container_name)
{
    // Create the cgroup directory
    if (mkdir(CGROUP_DIR, 0755) == -1 && errno != EEXIST)
    {
        perror("[ERROR]  Create CGROUP_DIR= /sys/fs/cgroup/pepitocker failed");
        exit(EXIT_FAILURE);
    }

    // Add to subtree the capcity to control the memory and cpu
    FILE *f = open_file(CGROUP_SUBTREE, "w");
    if (!f)
    {
        exit(EXIT_FAILURE);
    }

    if (fprintf(f, "%s", "+cpu +memory +pids +io") == -1)
    {
        perror("[ERROR] Failed to modify cgroup.subtree_control");
        fclose(f);
        exit(EXIT_FAILURE);
    }

    fclose(f);

    // Create the <container-name> folder
    char final_folder[256];
    snprintf(final_folder, sizeof(final_folder), "%s/%s", CGROUP_DIR, container_name);

    if (mkdir(final_folder, 0755) == -1 && errno != EEXIST)
    {
        perror("[ERROR]  Create CGROUP_DIR= /sys/fs/cgroup/pepitocker/<container-name> failed\n");
        exit(EXIT_FAILURE);
    }

    // Parse the memory value
    char memory_buffer[64];
    if (strcmp(memory_size, "max") == 0)
    {
        snprintf(memory_buffer, sizeof(memory_buffer), "max");
    }
    else
    {
        unsigned long long bytes = parse_memory_size(memory_size);
        snprintf(memory_buffer, sizeof(memory_buffer), "%llu", bytes);
    }

    // Open the memory.max file to write the max memory usable
    char mem_max_file[256];
    int r = snprintf(mem_max_file, sizeof(mem_max_file), "%s/%s", final_folder, "memory.max");
    if (r < 0 || (size_t)r >= sizeof(mem_max_file))
    {
        perror("[ERROR] snprintf memory.max");
        exit(EXIT_FAILURE);
    }

    FILE *container_mem_file = open_file(mem_max_file, "w");
    if (!container_mem_file)
    {
        exit(EXIT_FAILURE);
    }

    if (fprintf(container_mem_file, "%s", memory_buffer) == -1)
    {
        perror("[ERROR] Failed to modify the container max memory");
        fclose(container_mem_file);
        exit(EXIT_FAILURE);
    }

    fclose(container_mem_file);

    // Add the PID to the cgroup.pid
    char proc_path[256];
    snprintf(proc_path, sizeof(proc_path), "%s/%s/cgroup.procs", CGROUP_DIR, container_name);
    FILE *cgroup_procs_file = open_file(proc_path, "w");
    if (!cgroup_procs_file)
    {
        exit(EXIT_FAILURE);
    }
    if (fprintf(cgroup_procs_file, "0") == -1)
    {
        perror("[ERROR] Add the container PID to cgroup.procs failed");
        fclose(cgroup_procs_file);
        exit(EXIT_FAILURE);
    }
    fclose(cgroup_procs_file);
    return 0;
}

int create_container(const char *rootfs)
{

    // Prevent mounting operation of the namespace to be diffused to the host and vice-versa
    if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) == -1)
    {
        perror("[ERROR] Making mounting event private opertion failed");
        exit(EXIT_FAILURE);
    }

    // Make the rootfs as a mounting point
    if (mount(rootfs, rootfs, NULL, MS_BIND | MS_REC, NULL) == -1)
    {
        perror("[ERROR] Mount bind operation failed");
        exit(EXIT_FAILURE);
    }

    char old_root_path[512];
    snprintf(old_root_path, sizeof(old_root_path), "%s/old_root", rootfs);

    if (mkdir(old_root_path, 0755) == -1 && errno != EEXIST)
    {
        perror("[ERROR] mkdir old_root");
        return -1;
    }

    // Change the the root directory for the processus
    if (pivot_root(rootfs, old_root_path) == -1)
    {
        perror("[ERROR] Pivot root operation failed");
        return -1;
    }

    // Go the the new root
    if (chdir("/") == -1)
    {
        perror("[ERROR] chdir /");
        return -1;
    }

    if (mkdir("/proc", 0555) == -1 && errno != EEXIST)
    {
        perror("[WARN] mkdir /proc");
    }

    // Mount the filesystem proc
    if (mount("proc", "/proc", "proc", 0, NULL) == -1)
    {
        perror("[ERROR] mount /proc");
        return -1;
    }

    // Unmount the old root and delete it
    if (umount2("/old_root", MNT_DETACH) == -1)
    {
        perror("[ERROR] umount2 old_root");
        return -1;
    }

    if (rmdir("/old_root") == -1)
    {
        perror("[ERROR] rmdir old_root");
        return -1;
    }

    return 0;
}

int main(int argc, char *argv[])
{

    if (argc < 2)
    {
        fprintf(stderr, "Usage: %s <dir_rootfs> <container-name> -memory=<container memory max> (optional)\n", argv[0]);
        exit(EXIT_FAILURE);
    }

    const char *memory_size = "max";
    const char *container_name = "pepito_container";
    for (int i = 1; i < argc; i++)
    {
        if (strncmp(argv[i], "-memory=", 8) == 0)
        {
            memory_size = argv[i] + 8;
        }
        if (strncmp(argv[i], "-name=", 6) == 0)
        {
            container_name = argv[i] + 6;
        }
    }
    printf("%s will be allocated to this container\n", memory_size);

    // Unshare the child processus from the current namespaces
    if (unshare(CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWUTS) == -1)
    {
        perror("[ERROR] Unshare operation failed");
        return -1;
    }

    pid_t pid = fork();

    if (pid < 0)
    {
        perror("[ERROR] Fork operation failed");
        exit(EXIT_FAILURE);
    }

    if (pid == 0)
    {
        if (sethostname("container", strlen("container")) == -1)
        {
            perror("[WARN] sethostname");
        }
        if (configure_cgroup(memory_size, container_name) != 0)
        {
            fprintf(stderr, "[ERROR] Failed to configure cgroup for the container\n");
            exit(EXIT_FAILURE);
        }
        if (create_container(argv[1]) == -1)
        {
            exit(EXIT_FAILURE);
        }

        char *const args[] = {"/bin/sh", NULL};
        char *const envp[] = {
            "PATH=/bin:/sbin:/usr/bin:/usr/sbin",
            "HOME=/root",
            "TERM=xterm",
            NULL};
        execve(args[0], args, envp);
        perror("[ERROR] execve /bin/sh");
        exit(EXIT_FAILURE);
    }

    int status = 0;
    if (waitpid(pid, &status, 0) == -1)
    {
        perror("[ERROR] waitpid");
        return EXIT_FAILURE;
    }

    // Delete the cgroup container directory
    char cg_path[512];
    int n = snprintf(cg_path, sizeof(cg_path), "%s/%s", CGROUP_DIR, container_name);
    if (n < 0 || (size_t)n >= sizeof(cg_path))
    {
        fprintf(stderr, "[WARN] Cgroup very big cannot be deleted\n");
    }
    else if (rmdir(cg_path) == -1)
    {
        fprintf(stderr, "[WARN] rmdir %s: %s\n", cg_path, strerror(errno));
    }
    else
    {
        printf("Cgroup deleted: %s and container shutted down\n", cg_path);
    }

    return WIFEXITED(status) ? WEXITSTATUS(status) : EXIT_FAILURE;
}
