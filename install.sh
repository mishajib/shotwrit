#!/bin/sh
# Install Shotwrit for the current user (no root needed).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
APPID=io.github.mishajib.Shotwrit
SHARE=${XDG_DATA_HOME:-$HOME/.local/share}
BIN=$HOME/.local/bin

mkdir -p "$SHARE/shotwrit" "$SHARE/applications" "$BIN"
install -m 644 "$HERE/shotwrit.py" "$SHARE/shotwrit/shotwrit.py"
printf '#!/bin/sh\nexec python3 "%s/shotwrit/shotwrit.py" "$@"\n' "$SHARE" > "$BIN/shotwrit"
chmod 755 "$BIN/shotwrit"
sed "s|^Exec=shotwrit|Exec=$BIN/shotwrit|" "$HERE/data/$APPID.desktop" > "$SHARE/applications/$APPID.desktop"
update-desktop-database "$SHARE/applications" 2>/dev/null || true

"$BIN/shotwrit" --setup
echo "Installed. Press Ctrl+Alt+S or find Shotwrit in the app menu."
