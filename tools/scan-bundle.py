#!/usr/bin/env python3
"""Portability scan for a built bundle. Exit 1 if it would not work on someone else's machine.

Two checks, both of which caught real defects when this was written:

  1. MACHINE-SPECIFIC PATHS. A bundle carrying an absolute path from the build box works there and
     nowhere else, silently - the file it names simply is not present.
  2. MISSING UNIX EXEC BIT on .sh files. zipfile records the source mode, and on Windows that is
     0o666 for everything, so hooks extracted on macOS or Linux cannot be run by the harness.

Run: python tools/scan-bundle.py dist/*.zip
"""
import sys
import zipfile

# Windows-absolute paths only. `/Users/...` and `/home/...` were in the first version and produced
# three false positives on the first real run: they were example paths inside upstream skill
# documentation ("Worktree ready at /Users/jesse/myproject/..."), which nothing reads and which
# break nothing. A scanner that cries wolf on prose gets ignored, and then it misses the real one.
NEEDLES = [b"D:/Omincom", b"D:\\Omincom", b"E:/omni", b"E:\\omni",
           b"C:/Users", b"C:\\Users", b"/c/Users"]


def scan(path):
    zf = zipfile.ZipFile(path)
    problems = []

    for name in zf.namelist():
        try:
            blob = zf.read(name)
        except Exception:
            continue
        for needle in NEEDLES:
            if needle in blob:
                problems.append("machine-specific path in %s (%s)" % (name, needle.decode()))
                break

    for info in zf.infolist():
        if not info.filename.endswith(".sh"):
            continue
        mode = (info.external_attr >> 16) & 0o777
        if not mode & 0o111:
            problems.append("not executable: %s (mode %s)" % (info.filename, oct(mode)))

    label = path.replace("\\", "/").split("/")[-1]
    if problems:
        print("%s - %d PROBLEM(S):" % (label, len(problems)))
        for p in problems:
            print("    " + p)
        return 1
    print("%s - portable: no machine-specific paths, all .sh executable" % label)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    return max(scan(p) for p in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
