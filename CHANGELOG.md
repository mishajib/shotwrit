# Changelog

## [0.1.1] - 2026-10-20
- Ctrl+Alt+S now opens GNOME's own screenshot selector (area, screen or window) first, then the editor
  on just the captured part.
- `shotwrit --update` installs the latest release (`.deb` installs use `sudo apt`); `shotwrit --version` prints the version.
- After a Ctrl+Alt+S capture, Copy and Save close the editor automatically.

## [0.1.0] - 2026-10-20
- Initial release: area/window capture with optional delay, multi-monitor chooser, pen, box, arrow,
  text, highlight, blur, move/select, undo/redo, copy (also saves), save to `~/Pictures/shotwrit`,
  Ctrl+Alt+S shortcut set up automatically on first run (`shotwrit --setup` to redo).
- `shotwrit --uninstall-user` removes the shortcut, permission and settings before `apt remove`.
