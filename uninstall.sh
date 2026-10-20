#!/bin/sh
# Remove the per-user Shotwrit install. Screenshots in ~/Pictures/shotwrit are kept.
APPID=io.github.mishajib.Shotwrit
SHARE=${XDG_DATA_HOME:-$HOME/.local/share}
rm -rf "$SHARE/shotwrit" "$SHARE/applications/$APPID.desktop" \
    "$HOME/.local/bin/shotwrit"
K=org.gnome.settings-daemon.plugins.media-keys
P=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/shotwrit/
if command -v gsettings >/dev/null 2>&1; then
    cur=$(gsettings get "$K" custom-keybindings 2>/dev/null)
    new=$(printf '%s' "$cur" | python3 -I -c "
import ast,sys
t=sys.stdin.read().replace('@as ','')
print([p for p in ast.literal_eval(t) if p!='$P'])")
    gsettings set "$K" custom-keybindings "$new" 2>/dev/null
    gsettings reset-recursively "$K.custom-keybinding:$P" 2>/dev/null
fi
echo "Shotwrit removed."
