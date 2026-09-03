#!/usr/bin/env python3
"""List (and optionally delete) files in instance/uploads/ that no material row names.

Two kinds of file collect at the root of the upload folder, and both look identical
to `ls`:

  1. Originals left behind by migrate_057, which copied each material into its
     topic's folder and deliberately kept the flat copy as the only undo path.
  2. True orphans -- files whose material row was deleted long ago, or that were
     never referenced at all. Nothing has pointed at these for months.

Both are safe to remove once the new layout has been used in anger; neither is safe
to remove by filename pattern. migrate_057 inner-joins material to task, so a
material row whose topic was deleted never got repointed and STILL holds a flat
path. Deleting by glob would take that file with it. This script asks the database
instead: a root-level file goes only if no material.pfad names it.

Scope is the root of the upload folder. Files inside a topic folder are the import's
business (import_task._prune_orphaned_files cleans those on re-import), and
artefakte/ holds student uploads under their own naming.

Dry run by default. --delete archives everything it removes to data/ first, so the
operation is reversible; delete that tarball yourself once the materials load.
"""
import argparse
import datetime
import os
import sqlite3
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE, UPLOAD_FOLDER


def find_orphans():
    """Root-level upload files that no material row references, sorted by name."""
    with sqlite3.connect(DATABASE) as conn:
        referenced = {
            row[0] for row in
            conn.execute("SELECT pfad FROM material WHERE pfad IS NOT NULL")
        }
    entries = sorted(os.listdir(UPLOAD_FOLDER))
    files = [n for n in entries if os.path.isfile(os.path.join(UPLOAD_FOLDER, n))]
    return files, [n for n in files if n not in referenced]


def archive(names):
    """Tar the doomed files into data/ and return the archive path."""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(os.path.dirname(DATABASE), f'uploads_orphans_{stamp}.tar.gz')
    with tarfile.open(path, 'w:gz') as tar:
        for name in names:
            tar.add(os.path.join(UPLOAD_FOLDER, name), arcname=name)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--delete', action='store_true',
                        help='archive to data/ and then remove (default: list only)')
    args = parser.parse_args()

    for path, label in ((DATABASE, 'Database'), (UPLOAD_FOLDER, 'Upload folder')):
        if not os.path.exists(path):
            print(f"{label} not found: {path}")
            return 1

    files, orphans = find_orphans()
    for name in orphans:
        print(f"  {name}")
    total = sum(os.path.getsize(os.path.join(UPLOAD_FOLDER, name)) for name in orphans)
    print(f"\n{len(files)} file(s) at the upload root, {len(orphans)} unreferenced, "
          f"{total / 1e6:.1f} MB")

    if not orphans:
        return 0
    if not args.delete:
        print("Dry run. Pass --delete to archive and remove them.")
        return 0

    path = archive(orphans)
    for name in orphans:
        os.remove(os.path.join(UPLOAD_FOLDER, name))
    print(f"Archived to {path} and removed {len(orphans)} file(s).")
    print("The archive is the undo. Delete it once the materials load.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
