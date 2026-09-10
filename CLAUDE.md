# Repo notes for Claude

## Roadmap maintenance

`roadmap.html` at the repo root is the living project roadmap. Whenever a
status pill or phase flips to Done:

1. Add the completion date (`YYYY-MM-DD`) next to the pill, using a
   `<span class="done-date">`.
2. Wrap the item as `<details class="status-item">` (grid items) or
   `<details class="phase">` (soft-sequencing phases), closed by default
   (no `open` attribute), with the name/pill/date in the `<summary>` so
   completed items collapse out of the way instead of the page growing
   forever. Follow the markup pattern of the existing Done items in the
   file rather than inventing a new one.
3. Update the "Last written" date in the `.meta-line` in the header.

This convention is also noted as an HTML comment directly above
`<div class="page">` in `roadmap.html` itself.
