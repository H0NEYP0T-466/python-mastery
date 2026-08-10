# File I/O

## What it is
Python's file I/O layer — `open()`, file objects, buffering modes, text vs binary mode, path handling (`os.path`, `pathlib`), and memory-mapped files (`mmap`) — is the interface between your program and the filesystem. The mechanics matter: how buffering affects when data is actually written, why text mode has encoding implications, how seeking works differently in text vs binary mode, and when memory-mapped files outperform sequential reading. This file covers both the everyday patterns (reading/writing files correctly) and the advanced techniques that matter for large-scale data processing.

## Why it matters
File I/O bugs are insidious — data loss from unflushed buffers, encoding errors from implicit text-mode assumptions, performance issues from small reads, and resource leaks from unclosed files. In ML and data work (which you do constantly), reading a 10GB dataset efficiently is the difference between a training pipeline that runs in minutes and one that runs for hours. The `with open()` pattern is well-known, but the underlying mechanics — buffering, encoding, flush behavior — are what separate correct I/O from data corruption. And in interviews, questions about file I/O test whether you understand the system-level behavior, not just the Python syntax.

## Core example

### Text mode vs binary mode — the encoding trap

```python
# Text mode (default) — decodes bytes to str using a default encoding
with open("file.txt", "w") as f:
    f.write("hello")  # str → encoded to bytes using system default encoding

with open("file.txt", "r") as f:
    content = f.read()  # bytes → decoded to str using system default encoding

# The default encoding is platform-dependent: usually UTF-8 on Linux/macOS,
# but cp1252 on Windows. This is a common source of "works on my machine" bugs.

# Always specify encoding explicitly:
with open("file.txt", "w", encoding="utf-8") as f:
    f.write("hello")

with open("file.txt", "r", encoding="utf-8") as f:
    content = f.read()

# Binary mode — no encoding/decoding, raw bytes
with open("file.png", "rb") as f:
    data = f.read()  # bytes, not str

with open("file.png", "wb") as f:
    f.write(data)  # bytes, not str

# Mixing text and binary is a common error:
# f.write(b"hello") in text mode → TypeError
# f.write("hello") in binary mode → TypeError

# For ML work: model weights, images, and serialized data should ALWAYS
# be handled in binary mode. Text mode with implicit encoding can corrupt
# binary data (e.g., newline translation on Windows: \n → \r\n).
```

### Buffering — when data actually hits the disk

```python
# File I/O is buffered by default — writes go to an in-memory buffer
# and are flushed to disk periodically, not immediately.

# Buffering modes:
# - buffering=0: unbuffered (binary mode only) — every write hits disk immediately
# - buffering=1: line buffered — flush on each newline (text mode only)
# - buffering=N: buffer of N bytes — flush when buffer is full
# - buffering=-1 (default): system default buffer size (usually 8KB)

with open("log.txt", "w") as f:
    f.write("first line\n")
    f.write("second line\n")
    # Data may still be in the buffer here — not necessarily on disk!

# Flush explicitly when you need data on disk:
with open("log.txt", "w") as f:
    f.write("critical data\n")
    f.flush()  # Force buffer to OS — but OS may still cache it
    os.fsync(f.fileno())  # Force OS to write to disk — guaranteed

# The with statement closes the file on exit, which implicitly flushes.
# But if your program crashes before the with block exits, buffered data is lost.
# For critical data (checkpoints, logs, financial records), call fsync.

# For reading: buffering affects performance, not correctness.
# Reading line by line with default buffering is efficient — Python reads
# large chunks internally and yields lines from the buffer.
with open("large.txt") as f:
    for line in f:  # Efficient — buffered reading, one line at a time
        process(line)
```

### `pathlib` — the modern approach to paths

```python
from pathlib import Path

# Old way — os.path with string manipulation:
import os
path = os.path.join("data", "subdir", "file.txt")
if os.path.exists(path):
    with open(path, "r") as f:
        content = f.read()

# New way — pathlib with object-oriented paths:
path = Path("data") / "subdir" / "file.txt"
if path.exists():
    content = path.read_text(encoding="utf-8")

# pathlib.Path is a path object with methods for everything:
p = Path("/home/user/data/file.txt")
print(p.parent)        # /home/user/data
print(p.name)          # file.txt
print(p.stem)          # file
print(p.suffix)        # .txt
print(p.suffixes)      # [.tar.gz] for file.tar.gz

p.with_suffix(".csv")  # /home/user/data/file.csv (returns new Path)
p.parent / "other.txt" # /home/user/data/other.txt

# Globbing:
for py_file in Path(".").glob("*.py"):
    print(py_file)

# Recursive glob:
for py_file in Path(".").rglob("*.py"):  # **/*.py
    print(py_file)

# Reading/writing:
text = Path("file.txt").read_text(encoding="utf-8")
Path("file.txt").write_text("hello", encoding="utf-8")
data = Path("image.png").read_bytes()
Path("image.png").write_bytes(data)

# pathlib is now the recommended approach (PEP 428). It handles cross-platform
# path separators automatically and provides a cleaner API than os.path.
# The only caveat: some older libraries still expect string paths —
# use str(path) to convert when needed.
```

### Memory-mapped files — random access to large files

```python
import mmap

# For reading large files with random access, mmap maps the file into
# virtual memory — you can access any part without loading the whole file.

with open("large.bin", "rb") as f:
    # Map the entire file into memory
    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        # mm behaves like a bytes object
        print(mm[:100])        # First 100 bytes — not read from disk yet
        print(mm[1000:1100])   # Bytes 1000-1100 — lazy, only accessed when read
        # The OS handles paging — only accessed parts are loaded into RAM

# For writing:
with open("large.bin", "r+b") as f:
    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_WRITE) as mm:
        mm[100:110] = b"newdata"  # Modify in place — writes to file
        # Changes are flushed when the mmap is closed

# Use cases:
# - Large binary files where you need random access
# - Log files where you want to read from the end
# - Memory-efficient file sharing between processes (mmap is shared memory)

# Don't use mmap for:
# - Text files with variable-length encoding (UTF-8) — byte offsets don't
#   map cleanly to character positions
# - Sequential reading — regular buffered I/O is simpler and just as fast
# - Files that change size while mapped — mmap has a fixed size

# For your DINOv2 work: mmap is useful for large binary datasets where
# you need to seek to specific offsets without loading everything.
```

### Reading large files — strategies

```python
# Strategy 1: Read entire file — only for small files
with open("small.txt") as f:
    content = f.read()  # Loads entire file into memory

# Strategy 2: Read line by line — for text files, memory-efficient
with open("large.txt") as f:
    for line in f:  # One line in memory at a time
        process(line)

# Strategy 3: Read in chunks — for binary files or when line boundaries don't exist
CHUNK_SIZE = 8192  # 8KB — matches typical filesystem block size
with open("large.bin", "rb") as f:
    while True:
        chunk = f.read(CHUNK_SIZE)
        if not chunk:
            break
        process(chunk)

# Strategy 4: Read from the end — for log tailing
def tail(f, n=10):
    """Read last n lines from a file"""
    f.seek(0, 2)  # Seek to end
    position = f.tell()
    block_size = 1024
    blocks = []
    while n > 0 and position > 0:
        position = max(0, position - block_size)
        f.seek(position)
        block = f.read(block_size if position == 0 else position + block_size - position)
        blocks.extend(block.decode().splitlines(keepends=True))
        n -= block.count(b"\n") - (1 if position == 0 else 0)
    return "".join(reversed(blocks[-n:]))

# Strategy 5: Memory-mapped — for random access to large binary files
# (see mmap example above)

# The right strategy depends on your access pattern:
# - Sequential, full file → read() or line iteration
# - Sequential, large file → chunked reading
# - Random access → mmap
# - End of file only → seek to end and read backwards
```

### Atomic file writes — preventing partial writes

```python
import os
import tempfile

def atomic_write(path, content, encoding="utf-8"):
    """Write to a temp file, then atomically rename to target"""
    dir_path = os.path.dirname(path) or "."
    # Write to a temp file in the same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename — on POSIX, rename is atomic
        # On Windows, may need os.replace for same behavior
        os.replace(tmp_path, path)
    except Exception:
        os.remove(tmp_path)
        raise

# Why this matters: if your program crashes mid-write, the original file
# is intact (you wrote to a temp file, not the target). When the write
# completes successfully, the rename is atomic — there's no intermediate
# state where the file is partially written.
#
# For ML checkpoints: always write atomically. A partial checkpoint file
# is worse than no checkpoint — it can corrupt your training state.
```

## Common mistakes / gotchas

- **Not specifying encoding** — relying on system default encoding causes cross-platform bugs. Always use `encoding="utf-8"` for text files.
- **Assuming data is on disk after `write()`** — writes are buffered. Use `flush()` + `os.fsync()` for critical data. The `with` statement flushes on close but doesn't fsync.
- **Reading binary files in text mode** — can corrupt data due to newline translation and encoding errors. Use `"rb"`/`"wb"` for non-text data.
- **Not closing files** — relying on garbage collection to close files is unreliable. Always use `with open()`. If you must manage manually, use `try/finally` or `contextlib.closing`.
- **`seek()` in text mode** — in text mode, `seek()` only accepts offsets returned by `tell()`. Arbitrary byte offsets don't work because of encoding (a character may be multiple bytes). Use binary mode for arbitrary seeking.
- **Opening files in the wrong mode** — `"w"` truncates the file. `"a"` appends. `"r+"` opens for reading and writing without truncating. `"w+"` truncates and opens for both. The difference matters.
- **Path joining with string concatenation** — `path + "/" + file` is error-prone. Use `Path /` or `os.path.join()` which handles separators correctly across platforms.
- **Ignoring file permissions** — newly created files have default permissions (usually 644). If you're writing sensitive data (API keys, credentials), explicitly set restrictive permissions with `os.chmod()`.

## Practice

> [!question]- Q1. You need to write a 50GB training log file. The application may crash at any point. Design a write strategy that guarantees no data loss and minimal performance overhead.
**Answer:** Use a combination of chunked writing with periodic fsync and atomic rotation. Write to a temporary file in chunks (e.g., 8MB), calling `fsync()` after each chunk to ensure durability. For the active log, append to a rotating set of files: write to `log.current`, and when it reaches a size threshold, `os.replace` it to `log.1` (atomic) and start a new `log.current`. Use `O_DIRECT` or disable OS buffering if write ordering is critical. The key trade-off: fsync after every write is safe but slow (each fsync is a disk sync, ~1-10ms). fsync every 8MB balances durability with performance — you lose at most 8MB on crash. For ML training checkpoints, fsync after every checkpoint is non-negotiable — a corrupted checkpoint is worse than no checkpoint.

> [!question]- Q2. Explain why `with open(file, "rb") as f: for line in f:` doesn't work as expected for binary files, and what the correct approach is.
**Answer:** In binary mode, `for line in f` splits on `\n` bytes, but there's no decoding to str. The "lines" are bytes objects ending with `\n`. This works but is rarely what you want for binary data — binary files don't have "lines" in the semantic sense. If you're processing a binary format with record boundaries, you should read fixed-size records or use a struct-based parser. If you need to split binary data on a delimiter, use `f.read()` and `split(b"\n")` or iterate with `f.readline()` which returns bytes. The key insight: line iteration is a text-mode concept — it assumes the file has lines separated by newline characters. Binary files have bytes, and you impose structure on them based on the format, not on newlines.

> [!question]- Q3. What's the difference between `f.flush()` and `os.fsync(f.fileno())`? When do you need each, and when do you need both?
**Answer:** `f.flush()` flushes Python's internal buffer — it writes data from the Python file object's buffer to the OS kernel buffer. But the OS may still cache the data in memory and delay writing to disk. `os.fsync(f.fileno())` forces the OS to write the data to physical storage — it blocks until the disk confirms the write. You need `flush()` when you want data to leave Python's buffer (e.g., so another process reading the file can see it). You need `fsync()` when you need data guaranteed on disk (e.g., after writing a checkpoint or transaction log). You need both: `flush()` first (to get data from Python to OS), then `fsync()` (to get data from OS to disk). Calling `fsync()` without `flush()` may not flush Python's buffer, so some data never reaches the OS to be synced.

> [!question]- Q4. You have a directory with 100,000 files and need to find all `.jpg` files modified in the last 7 days. Compare `os.walk`, `Path.rglob`, and `os.scandir` approaches in terms of performance and memory.
**Answer:** `os.scandir` is the most efficient — it returns directory entries with cached stat info (like `st_mtime`), avoiding a separate `stat()` call per file. `os.walk` uses `os.scandir` internally under the hood (Python 3.5+), so it's also efficient. `Path.rglob` is the cleanest syntactically but slightly slower because it creates Path objects for every entry. For 100,000 files, the difference is measurable but not catastrophic. The best approach: `os.scandir` with recursive iteration, filtering by `entry.suffix == ".jpg"` and `entry.stat().st_mtime > cutoff`. This avoids creating Path objects and reuses the cached stat from `scandir`. Memory: all three approaches are streaming — they don't load all files into memory at once. The difference is in per-entry overhead.

> [!question]- Q5. Design a function `read_last_n_lines(path, n)` that efficiently reads the last n lines of a large file without loading the entire file into memory. Explain the algorithm.
**Answer:** Seek to the end of the file, then read backwards in blocks, counting newlines until you've found n+1 newlines. Then read forward from that position to get the last n lines:
```python
def read_last_n_lines(path, n, block_size=8192):
    with open(path, "rb") as f:
        f.seek(0, 2)  # End of file
        size = f.tell()
        offset = 0
        newlines = 0
        blocks = []
        
        while offset < size and newlines <= n:
            read_size = min(block_size, size - offset)
            offset += read_size
            f.seek(size - offset)
            block = f.read(read_size)
            blocks.append(block)
            newlines += block.count(b"\n")
        
        # If we have more newlines than needed, find the cutoff
        data = b"".join(reversed(blocks))
        lines = data.split(b"\n")
        # Return last n lines (decode if needed)
        return [line.decode() for line in lines[-n:] if line]
```
The algorithm reads backwards from the end in chunks, counting newlines. Once it has enough, it assembles the blocks and extracts the last n lines. Memory usage is proportional to the number of blocks needed to find n lines — typically much less than the full file size. For files with very long lines (e.g., a single 10GB line), it degrades to reading the whole file, but that's an edge case.

## Related
[[context-managers]]
[[exception-handling]]
[[generators-and-iterators]]
[[data-structures-and-complexity]]

#status/new