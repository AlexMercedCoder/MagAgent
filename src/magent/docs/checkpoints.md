# Checkpoints

Checkpoints snapshot files before MagAgent writes, edits, or deletes them.

Useful commands:

- `magent checkpoint list`
- `magent checkpoint show <id>`
- `magent checkpoint diff <id>`
- `magent checkpoint restore <id>`
- `magent checkpoint restore-last`

Checkpoints live under:

`~/.config/magent/users/<user>/workbench/checkpoints/`

Each checkpoint stores metadata and a copy of the previous file contents when the file existed. Restoring a checkpoint puts that previous content back. If the checkpoint represents a file that did not exist before creation, restoring removes the created file.
