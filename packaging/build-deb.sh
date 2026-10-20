#!/bin/sh
# Build shotwrit_<version>_all.deb into ./dist
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:-$(sed -n 's/^## \[\([0-9][^]]*\)\].*/\1/p' "$HERE/CHANGELOG.md" | head -1)}
APPID=io.github.mishajib.Shotwrit
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

install -Dm 644 "$HERE/shotwrit.py" "$T/usr/share/shotwrit/shotwrit.py"
install -Dm 644 "$HERE/data/$APPID.desktop" "$T/usr/share/applications/$APPID.desktop"
install -Dm 644 "$HERE/LICENSE" "$T/usr/share/doc/shotwrit/copyright"
mkdir -p "$T/usr/bin"
printf '#!/bin/sh\nexec python3 /usr/share/shotwrit/shotwrit.py "$@"\n' > "$T/usr/bin/shotwrit"
chmod 755 "$T/usr/bin/shotwrit"

mkdir -p "$T/DEBIAN" "$HERE/dist"
cat > "$T/DEBIAN/control" <<CTL
Package: shotwrit
Version: $VERSION
Section: graphics
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0 (>= 4.12), xdg-desktop-portal
Maintainer: mishajib <mishajib222@gmail.com>
Homepage: https://github.com/mishajib/shotwrit
Description: Screenshot tool with drawing, boxes, arrows, text and blur
 Capture an area or window, mark it up with pen, box, arrow, text,
 highlight and blur, then copy or save. The Ctrl+Alt+S shortcut is
 set up the first time the app runs (GNOME).
CTL
dpkg-deb --root-owner-group --build "$T" "$HERE/dist/shotwrit_${VERSION}_all.deb"
