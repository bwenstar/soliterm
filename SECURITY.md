# Security policy

## Supported versions

Fixes go into the latest release. Soliterm is small enough that there are no
long-lived branches, so if you're on an older version, upgrading is the fix.

## What Soliterm touches

Soliterm makes no network connections and never runs other programs. It
reads and writes three things, all in your home directory:

- its settings, statistics, history and saved games, under
  `~/.config/soliterm` and `~/.local/share/soliterm` (or the
  `XDG_CONFIG_HOME` and `XDG_DATA_HOME` you set);
- GNOME AisleRiot's keyfile, `~/.config/gnome-games/aisleriot`, when
  statistics sharing is on and AisleRiot is installed;
- the old aisle-cli folders, which it reads once to copy your settings
  and statistics across, and never writes.

So the things worth reporting are ones like a crafted settings, stats or
keyfile making Soliterm write outside those paths, lose data it shouldn't,
or print escape sequences that take over your terminal.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead:
go to the [Security tab](https://github.com/bwenstar/soliterm/security),
choose **Report a vulnerability**, and describe what you found and how to
reproduce it. Include what `soliterm --debug-info` prints, which has the
version, your OS and your Python version in it.

You should hear back within a week. Once a fix is out, the report is made
public along with a note in the changelog, with credit to you unless you'd
rather stay anonymous.
