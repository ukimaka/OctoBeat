# Arch Linux package

Build a native pacman package from the release tarball:

```sh
packaging/linux/build-tarball.sh
packaging/arch/build-package.sh
sudo pacman -U dist/octobeat-bin-1.0.0-1-x86_64.pkg.tar.zst
```

The package installs:

- `/usr/bin/octobeat`
- `/usr/share/octobeat/` (themes, icons, translations and bundled tools)
- desktop entry, AppStream metadata and hicolor icon

Dependencies: `qt6-base`, `qt6-svg`, `alsa-lib`, `hicolor-icon-theme`,
`xdg-utils`. yt-dlp, Deno, ffmpeg and SomeDL are bundled.
