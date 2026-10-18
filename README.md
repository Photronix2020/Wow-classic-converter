# WoW Classic Addon Converter

Takes an addon written for current retail World of Warcraft and makes it load
and run on WoW Classic clients wherever that's possible. Anything it can't fix
automatically goes into a report with file and line numbers.

## Download (Windows)

Get `WoWClassicConverter.exe` from the [Releases](../../releases) page. No install needed.

1. Double-click `WoWClassicConverter.exe`.
2. Click **Choose zip…** and pick the addon zip as you downloaded it from CurseForge, Wago or similar.
   You can also use **Choose folder…** to pick an addon folder.
3. Tick which Classic versions you play and press **Convert**.
4. Unzip the resulting `<name>-classic.zip` into your Classic AddOns folder, for example
   `World of Warcraft\_classic_era_\Interface\AddOns\`.

The first time you run it, Windows may say *"Windows protected your PC"*. That happens because
the exe isn't code-signed, which costs money. Click **More info** → **Run anyway**.
The exe is built automatically from this repository's source code by GitHub Actions; see
`.github/workflows/build.yml`.

If the game lists the addon as out of date, tick **Load out of date AddOns** in the
in-game AddOns menu.

## Command line

The exe also works from a terminal (`WoWClassicConverter.exe MyAddon.zip -o out.zip`), or run
from source with Python 3.9+ and no other dependencies.

### Usage

```sh
# a folder (the addon folder itself, a folder of addons, or a GitHub checkout)
python3 -m wowconv path/to/MyAddon -o out/

# a zip as downloaded from CurseForge / Wago / GitHub, straight to a zip
python3 -m wowconv MyAddon-1.2.zip -o MyAddon-classic.zip

# only Classic Era, with your client's exact interface number
python3 -m wowconv MyAddon -o out/ -t vanilla --interface vanilla=11508
```

Copy the folder(s) in the output to `World of Warcraft/_classic_era_/Interface/AddOns/`
(or `_classic_` / `_anniversary_` for the other Classic clients) and read
`CONVERSION_REPORT.md`.

| Option | Meaning |
|---|---|
| `-t, --target` | `vanilla` (Classic Era, Hardcore, SoD, Anniversary), `tbc`, `mists`. Repeatable; default is all three. |
| `--interface TARGET=N` | TOC `## Interface` number. Defaults are in `wowconv/apidb.py`; check yours in game with `/dump select(4, GetBuildInfo())`. |
| `--rewrite-libs` | Also rewrite embedded libraries under `Libs/`. Off by default since Ace3, LibStub and similar already support Classic. |

## What it does

1. **TOC files.** Writes `<Addon>_Vanilla.toc`, `_TBC.toc`, `_Mists.toc` from the
   retail TOC with the right `## Interface`, and drops `## AllowLoadGameType`
   lines that would stop it loading. If the addon already ships a Classic TOC,
   that one is kept, since the author already supports that client.
2. **API shim.** Adds `ClassicCompat.lua` (loaded first) with versions of modern
   APIs built on the older ones Classic still has, and points the addon's code at
   them. Covered:
   - `C_Spell` (`GetSpellInfo`, `GetSpellCooldown`, `GetSpellCharges`, `IsSpellInRange`, …, returning the retail table shapes)
   - `C_Item`, `C_Container`, `C_AddOns`, `C_CVar`
   - `C_UnitAuras` (`GetAuraDataByIndex`, `GetBuffDataByIndex`, `GetPlayerAuraBySpellID`, …, returning `AuraData` tables)
   - `C_Reputation`, `C_QuestLog`, `C_ChatInfo`, `C_ClassColor`
   - `Settings` (canvas categories mapped onto the old Interface Options panel)
   - `TooltipDataProcessor.AddTooltipPostCall` (mapped onto `OnTooltipSetItem/Spell/Unit`)
   - `GetMouseFoci`, plus safe defaults for spec and absorb functions and `issecretvalue`
3. **Events.** Classic clients raise an error when an addon registers an event they
   don't know. Every `obj:RegisterEvent(...)`, `RegisterUnitEvent` and
   `UnregisterEvent` call is routed through a check that skips unknown events.
   This also covers Ace-style `self:RegisterEvent("X")`.
4. **Report.** Lists retail-only features the addon uses that have no Classic
   equivalent (Mythic+, garrisons, talents/traits, transmog collection, Edit Mode,
   retail-only XML templates, …) and anything the shim doesn't cover.

### Safety

- Strings and comments are never modified.
- Nothing leaks to other addons. The shim lives in one uniquely named global,
  `ClassicCompat_<AddonName>`, and doesn't create or change any real API
  globals.
- The real API always wins. Each fill only applies when the client lacks that
  function, so the converted addon still works on retail.
- If a file declares its own local with the same name as an API (for example
  `local Settings = {}`), that name is left alone in that file and noted in the
  report.

## Limits

This isn't magic. It can't create game systems Classic doesn't have.
An addon built around Mythic+, Delves, or the retail talent tree has nothing to
run against. The tool makes the *rest* of the addon load and tells you where
those features are. Interface numbers and the "missing in" data are best-effort
and should be checked against your client. Output from a converted addon should
be tested in game.

## Tests

```sh
python3 -m unittest discover tests
```

The end-to-end tests run the converted sample addon inside a fake Classic client
(`lua5.1` required; those tests are skipped without it). They check that the
original addon crashes there and the converted one runs correctly.

## Building the exe yourself

On Windows with Python 3.12:

```sh
pip install pyinstaller==6.16.0
pyinstaller WoWClassicConverter.spec
```

The result is `dist/WoWClassicConverter.exe`.

## Publishing a new version

Change `__version__` in `wowconv/__init__.py` (for example to `1.0.1`), commit, and push
to `main`. GitHub Actions runs the tests, builds the exe on Windows, and creates release
`v1.0.1` with the exe attached. Pushes that don't change the version only build a test
copy, available under the run's "Artifacts".

The permanent link to the newest exe is
https://github.com/Photronix2020/Wow-classic-converter/releases/latest/download/WoWClassicConverter.exe
