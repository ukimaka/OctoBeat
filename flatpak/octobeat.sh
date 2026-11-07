#!/bin/sh
# OctoBeat Flatpak launcher.
#
# main.py lives in /app/lib/octobeat together with themes/ and icons/.
# Python adds the script directory to sys.path, so all local modules import
# normally; PyQt5 comes from the PyQt BaseApp in /app/lib/python3.13.
exec python3 /app/lib/octobeat/main.py "$@"
