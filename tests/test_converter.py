"""Tests: unit checks on the rewriter, plus an end-to-end run of a converted
addon inside a fake Classic client (needs `lua5.1` on PATH for that part)."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wowconv import converter  # noqa: E402
from wowconv.__main__ import main  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "RetailDemo"
LUA = shutil.which("lua5.1") or shutil.which("lua")

# A stand-in for a Classic Era client: old-style globals only, no C_Spell,
# C_AddOns, Settings, etc., and RegisterEvent errors on unknown events.
FAKE_CLASSIC = r"""
local KNOWN_EVENTS = { PLAYER_LOGIN = true, PLAYER_ENTERING_WORLD = true, UNIT_AURA = true }
local frames = {}
local Frame = {}
Frame.__index = Frame
function Frame:RegisterEvent(e)
  if not KNOWN_EVENTS[e] then error("Attempt to register unknown event \"" .. tostring(e) .. "\"") end
  self.events[e] = true
end
function Frame:UnregisterEvent(e)
  if not KNOWN_EVENTS[e] then error("unknown event " .. tostring(e)) end
  self.events[e] = nil
end
function Frame:SetScript(k, fn) self.scripts[k] = fn end
function CreateFrame() local f = setmetatable({ events = {}, scripts = {} }, Frame); frames[#frames + 1] = f; return f end

function GetSpellInfo(id) if id == 133 then return "Fireball", nil, 135812, 3500, 0, 35, 133, 135812 end end
function GetSpellCooldown(id) return 0, 0, 1, 1 end
function GetAddOnMetadata(name, field) if field == "Version" then return "1.2.3" end end
function UnitAura(unit, i, filter) if i == 1 then return "Arcane Intellect", 135932, 3, nil, 1800, 100, "player" end end
function GetMouseFocus() return "WorldFrame" end
function GetCVar(name) return "1" end
function GetItemInfo(id) if id == 6948 then return "Hearthstone" end end
local added = {}
function InterfaceOptions_AddCategory(frame) added[#added + 1] = frame.name end

local function fire(event)
  for _, f in ipairs(frames) do
    if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event) end
  end
end

local ns = {}
local ADDON = "RetailDemo"
for _, file in ipairs(FILES) do
  if file.lua then
    local chunk = assert(loadstring(file.lua, file.name))
    chunk(ADDON, ns)
  end
end
fire("PLAYER_LOGIN")
ns.results.optionsAdded = added[1]
ns.results.xmlOk = XML_SELF and XML_SELF.ok

local function encode(v)
  if type(v) == "string" then return string.format("%q", v) end
  if v == nil then return "null" end
  return tostring(v)
end
local keys = {}
for k in pairs(ns.results) do keys[#keys + 1] = k end
table.sort(keys)
local out = {}
for _, k in ipairs(keys) do out[#out + 1] = string.format("%q", k) .. ":" .. encode(ns.results[k]) end
print("{" .. table.concat(out, ",") .. "}")
"""


def run_in_fake_classic(addon_dir, toc_name):
    """Load the addon's files in TOC order inside the fake client; return results."""
    toc = (addon_dir / toc_name).read_text()
    files = []
    for entry in converter.toc_file_entries(toc):
        path = addon_dir / entry.replace("\\", "/")
        if path.suffix == ".lua":
            files.append((entry, path.read_text()))
        elif path.suffix == ".xml":
            # Run each OnLoad handler as a chunk with `self` bound to a fake frame.
            for body in re.findall(r"<OnLoad>(.*?)</OnLoad>", path.read_text(), re.S):
                files.append((entry, "XML_SELF = CreateFrame(); local self = XML_SELF\n" + body))
    lua_files = "FILES = {" + ",".join(
        "{name=%s, lua=%s}" % (lua_str(name), lua_str(src)) for name, src in files) + "}\n"
    proc = subprocess.run([LUA, "-"], input=lua_files + FAKE_CLASSIC, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError("Lua error:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().replace("\\\n", "\\n"))


def lua_str(s):
    level = 0
    while "]" + "=" * level + "]" in s:
        level += 1
    eq = "=" * level
    return f"[{eq}[\n{s}]{eq}]"


class RewriteTests(unittest.TestCase):
    def rw(self, src):
        return converter.rewrite_lua(src, "SHIM")[0]

    def test_strings_and_comments_untouched(self):
        src = 'local s = "C_Spell.GetSpellInfo" -- C_Spell.GetSpellInfo\n--[[ C_Item ]] x = [[C_Item]]'
        self.assertEqual(self.rw(src), src)

    def test_namespace_and_global_rewritten(self):
        out = self.rw("local i = C_Spell.GetSpellInfo(1)\nlocal f = GetMouseFoci()")
        self.assertIn("SHIM.C_Spell.GetSpellInfo(1)", out)
        self.assertIn("SHIM.GetMouseFoci()", out)

    def test_alias_keeps_local_name(self):
        out = self.rw("local C_Spell = C_Spell\nlocal a, C_Item = 1, _G.C_Item\nC_Spell.X()")
        self.assertIn("local C_Spell = SHIM.C_Spell", out)
        self.assertIn("local a, C_Item = 1, SHIM.C_Item", out)
        self.assertNotIn("local SHIM", out)

    def test_shadowed_name_left_alone(self):
        src = "local Settings = {}\nSettings.x = 1\nlocal c = _G.Settings.RegisterAddOnCategory"
        out = self.rw(src)
        self.assertIn("Settings.x = 1", out)
        self.assertIn("SHIM.Settings.RegisterAddOnCategory", out)
        self.assertNotIn("local SHIM", out)

    def test_parameter_shadow(self):
        src = "local function f(C_Item) return C_Item.x end"
        self.assertEqual(self.rw(src), src)

    def test_member_access_not_rewritten(self):
        src = "foo.C_Spell.x = 1; bar:GetMouseFoci()"
        self.assertEqual(self.rw(src), src)

    def test_event_calls(self):
        out = self.rw('f:RegisterEvent("A")\nself.frame : UnregisterEvent ( "B" )\nx:RegisterEvent()')
        self.assertIn('SHIM.RegisterEvent(f, "A")', out)
        self.assertIn('SHIM.UnregisterEvent(self.frame, "B" )', out)
        self.assertIn("SHIM.RegisterEvent(x)", out)

    def test_method_definition_untouched(self):
        src = "function Addon:RegisterEvent(e) end"
        self.assertEqual(self.rw(src), src)

    def test_toc_retarget(self):
        toc = "## Interface: 110200\n## AllowLoadGameType: mainline\n## Title: X\n\nCore.lua\n"
        out, notes = converter.build_flavor_toc(converter.add_shim_to_toc(toc), "11507")
        self.assertIn("## Interface: 11507", out)
        self.assertNotIn("AllowLoadGameType", out)
        self.assertLess(out.index(converter.SHIM_FILENAME), out.index("Core.lua"))
        self.assertTrue(notes)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def convert(self):
        out = self.tmp / "out"
        self.assertEqual(main([str(FIXTURE), "-o", str(out)]), 0)
        return out / "RetailDemo"

    def test_output_layout(self):
        addon = self.convert()
        for toc in ("RetailDemo_Vanilla.toc", "RetailDemo_TBC.toc", "RetailDemo_Mists.toc"):
            self.assertTrue((addon / toc).exists(), toc)
        self.assertTrue((addon / converter.SHIM_FILENAME).exists())
        lib = (addon / "Libs/LibFake/LibFake.lua").read_text()
        self.assertEqual(lib, (FIXTURE / "Libs/LibFake/LibFake.lua").read_text())
        report = (self.tmp / "out" / "CONVERSION_REPORT.md").read_text()
        self.assertIn("C_MythicPlus", report)
        self.assertIn("WowStyle1DropdownTemplate", report)
        self.assertIn("PLAYER_SPECIALIZATION_CHANGED", report)

    def forever_copy(self, keep_mainline):
        """The fixture repackaged as a WoW Forever addon (RetailDemo_Camelot.toc)."""
        src = self.tmp / "src" / "RetailDemo"
        shutil.copytree(FIXTURE, src)
        mainline = src / "RetailDemo_Mainline.toc"
        (src / "RetailDemo_Camelot.toc").write_text(mainline.read_text().replace("120001", "16001"))
        if keep_mainline:
            # A retail TOC that loads a different file list; the Forever one should win.
            mainline.write_text("## Interface: 120001\n## Title: Retail Demo\n\nRetailOnly.lua\n")
        else:
            mainline.unlink()
        return src

    @unittest.skipUnless(LUA, "lua5.1 not installed")
    def test_forever_only_addon(self):
        src = self.forever_copy(keep_mainline=False)
        out = self.tmp / "out"
        self.assertEqual(main([str(src), "-o", str(out)]), 0)
        addon = out / "RetailDemo"
        self.assertTrue((addon / "RetailDemo_Vanilla.toc").exists())
        r = run_in_fake_classic(addon, "RetailDemo_Vanilla.toc")
        self.assertEqual(r["spellName"], "Fireball")

    def test_forever_toc_preferred_over_mainline(self):
        src = self.forever_copy(keep_mainline=True)
        out = self.tmp / "out"
        self.assertEqual(main([str(src), "-o", str(out), "-t", "vanilla"]), 0)
        toc = (out / "RetailDemo" / "RetailDemo_Vanilla.toc").read_text()
        self.assertIn("Core.lua", toc)
        self.assertNotIn("RetailOnly.lua", toc)

    def test_zip_round_trip(self):
        src_zip = self.tmp / "RetailDemo.zip"
        with zipfile.ZipFile(src_zip, "w") as zf:
            for p in FIXTURE.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(FIXTURE.parent).as_posix())
        out_zip = self.tmp / "RetailDemo-classic.zip"
        self.assertEqual(main([str(src_zip), "-o", str(out_zip), "-t", "vanilla"]), 0)
        with zipfile.ZipFile(out_zip) as zf:
            names = zf.namelist()
        self.assertIn("RetailDemo/RetailDemo_Vanilla.toc", names)
        self.assertIn("RetailDemo/" + converter.SHIM_FILENAME, names)
        self.assertTrue((self.tmp / "RetailDemo-classic-report.md").exists())

    @unittest.skipUnless(LUA, "lua5.1 not installed")
    def test_original_fails_on_classic(self):
        with self.assertRaises(AssertionError):
            run_in_fake_classic(FIXTURE, "RetailDemo_Mainline.toc")

    @unittest.skipUnless(LUA, "lua5.1 not installed")
    def test_converted_runs_on_classic(self):
        addon = self.convert()
        r = run_in_fake_classic(addon, "RetailDemo_Vanilla.toc")
        self.assertEqual(r["events"], "PLAYER_LOGIN;")
        self.assertEqual(r["spellName"], "Fireball")
        self.assertEqual(r["spellIcon"], 135812)
        self.assertEqual(r["cdEnabled"], True)
        self.assertEqual(r["version"], "1.2.3")
        self.assertEqual(r["auraName"], "Arcane Intellect")
        self.assertEqual(r["auraStacks"], 3)
        self.assertEqual(r["foci"], 1)
        self.assertIsNone(r.get("spec"))
        self.assertEqual(r["absorb"], 0)
        self.assertEqual(r["cvar"], "1")
        self.assertIsNone(r.get("mplus"))
        # Ace-style objects: valid events pass through, retail-only ones are dropped.
        self.assertEqual(r["customRegister"], "PLAYER_ENTERING_WORLD;")
        self.assertEqual(r["tableKey"], "key not rewritten")
        self.assertEqual(r["note"], "uses C_Item.GetItemInfo")
        self.assertEqual(r["localSettings"], 2)
        self.assertEqual(r["categoryID"], "Retail Demo")
        self.assertEqual(r["optionsAdded"], "Retail Demo")
        self.assertEqual(r["xmlOk"], "Hearthstone")

    @unittest.skipUnless(LUA, "lua5.1 not installed")
    def test_shim_prefers_real_apis(self):
        """On a client that has the modern API, the shim must use it."""
        shim = converter.SHIM_TEMPLATE.replace("__SHIM__", "S")
        script = ('C_Spell = { GetSpellInfo = function() return "real" end }\n'
                  'GetMouseFoci = function() return "realfoci" end\n'
                  'function CreateFrame() return {} end\n'
                  + shim +
                  '\nprint(S.C_Spell.GetSpellInfo(1), S.GetMouseFoci(), type(S.C_Spell.GetSpellCooldown))')
        proc = subprocess.run([LUA, "-"], input=script, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.split(), ["real", "realfoci", "function"])


if __name__ == "__main__":
    unittest.main()
