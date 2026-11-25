"""Size limits for author-facing text diffs."""

from difflib import unified_diff

MAX_PREVIEW_BYTES = 32 * 1024
MAX_DIFF_LINES = 2000


def file_diffs(files):
    """Bound each side across the preview; callers retain the original blobs for publication."""
    old_bytes = new_bytes = lines = 0
    parts = []
    for path, old, new, heading in files:
        old_bytes += len(old)
        new_bytes += len(new)
        if max(old_bytes, new_bytes) > MAX_PREVIEW_BYTES:
            return f"Diff omitted: saved or draft files exceed the {MAX_PREVIEW_BYTES // 1024} KiB preview limit."
        before = old.decode(errors="replace").splitlines(keepends=True)
        after = new.decode(errors="replace").splitlines(keepends=True)
        lines += len(before) + len(after)
        if lines > MAX_DIFF_LINES:
            return f"Diff omitted: saved and draft files exceed {MAX_DIFF_LINES:,} combined lines."
        if heading:
            parts.append(heading + "\n")
        diff = unified_diff(before, after, fromfile=f"saved/{path}", tofile=f"draft/{path}")
        parts.extend(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in diff)
    return "".join(parts)
