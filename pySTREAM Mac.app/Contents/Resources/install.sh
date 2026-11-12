#!/bin/bash
# Installs what pySTREAM needs: a Python environment in the .venv folder of the pySTREAM folder with the packages
# in requirements.txt. "pySTREAM Mac" runs this in a Terminal window the first time, then starts pySTREAM.
# Arguments: the pySTREAM folder, the app, and the temporary file that started this (deleted).
DIR="$1"
APP="$2"
[ -n "$3" ] && rm -f "$3"
cd "$DIR" || exit 1

fail() {
    echo
    echo "$1"
    echo
    read -r -p "Press Enter to close this window."
    exit 1
}

# Python 3.12 or newer (pandas 3 and numpy 2.5 need it). /usr/bin/python3 is left out: it is too old,
# and without Apple's developer tools, using it asks to install them.
find_python() {
    local candidates=() version path
    for version in 14 13 12 15; do
        path="$(command -v "python3.$version")" && candidates+=("$path")
        candidates+=("/Library/Frameworks/Python.framework/Versions/3.$version/bin/python3"
                     "/opt/homebrew/bin/python3.$version" "/usr/local/bin/python3.$version")
    done
    path="$(command -v python3)" && [ "$path" != /usr/bin/python3 ] && candidates+=("$path")
    candidates+=(/opt/homebrew/bin/python3 /usr/local/bin/python3)
    for path in "${candidates[@]}"; do
        if [ -x "$path" ] && "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

echo "Installing pySTREAM. This is only needed the first time and takes a few minutes..."
echo

PYTHON="$(find_python)" || {
    open "https://www.python.org/downloads/"
    fail "pySTREAM needs Python 3.12 or newer, which was not found on this Mac.
The Python download page is now open in your browser: install Python from there,
then double-click \"pySTREAM Mac\" again."
}
echo "Using $("$PYTHON" --version) ($PYTHON)"
echo

"$PYTHON" -m venv --clear .venv || fail "Could not create the Python environment (the .venv folder); see the messages above."
.venv/bin/python -m pip install --upgrade pip || fail "The installation failed; check your internet connection and try again."
.venv/bin/python -m pip install -r requirements.txt || fail "The installation failed; check your internet connection and try again."

echo
echo "pySTREAM is installed. It opens in your web browser now; you can close this window."
open "$APP"
