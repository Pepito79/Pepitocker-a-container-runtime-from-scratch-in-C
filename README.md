# pepitocker

A minimal container runtime written from scratch in C for learning purposes.

## Goal

The goal of this project is to build a simple container runtime from scratch to better understand how Linux containers work under the hood.

It is an evolving educational project focused on exploring and reimplementing core container concepts step by step, such as:

- **Process isolation** with Linux namespaces
- **Resource control** with cgroups
- **Filesystem isolation** (root filesystem, mounts, `pivot_root`)
- Other container runtime fundamentals over time

## Build

```bash
gcc -Wall -Wextra -o pepitocker pepitocker.c
```

## Usage

> This project is a work in progress; the interface and behavior may change as it evolves.

Example (requires root and a prepared root filesystem):

```bash
sudo ./pepitocker <rootfs_dir>
```

## Notes

This is a learning project, not a production-ready container runtime.