/*
 * errno.h replacement for building FFmpeg with CeGCC (arm-mingw32ce, __COREDLL__).
 *
 * The toolchain's own errno.h does "#include_next <errno.h>" when __COREDLL__ is
 * defined, but no further errno.h exists, so every file including it fails.
 * Windows CE's COREDLL has no errno at all (no _errno() export), so there is
 * nothing to bind to. This header supplies the usual E* numbers (same values as
 * the mingw runtime's errno.h) and maps errno to a per-translation-unit dummy
 * that is always 0 unless the same file sets it. Nothing in COREDLL ever sets it.
 *
 * Effect: AVERROR(errno) after a failed CRT call yields 0 instead of an error
 * code. That only matters on FFmpeg's file/IO paths, which AutoKit never uses
 * (it calls only the parser and decoder entry points).
 */
#ifndef FFCE_COMPAT_ERRNO_H
#define FFCE_COMPAT_ERRNO_H

#define EPERM        1
#define ENOFILE      2
#define ENOENT       2
#define ESRCH        3
#define EINTR        4
#define EIO          5
#define ENXIO        6
#define E2BIG        7
#define ENOEXEC      8
#define EBADF        9
#define ECHILD      10
#define EAGAIN      11
#define ENOMEM      12
#define EACCES      13
#define EFAULT      14
#define EBUSY       16
#define EEXIST      17
#define EXDEV       18
#define ENODEV      19
#define ENOTDIR     20
#define EISDIR      21
#define EINVAL      22
#define ENFILE      23
#define EMFILE      24
#define ENOTTY      25
#define EFBIG       27
#define ENOSPC      28
#define ESPIPE      29
#define EROFS       30
#define EMLINK      31
#define EPIPE       32
#define EDOM        33
#define ERANGE      34
#define EDEADLOCK   36
#define EDEADLK     36
#define ENAMETOOLONG 38
#define ENOLCK      39
#define ENOSYS      40
#define ENOTEMPTY   41
#define EILSEQ      42

static int ffce_errno_dummy __attribute__((unused));
#define errno ffce_errno_dummy

#endif /* FFCE_COMPAT_ERRNO_H */
