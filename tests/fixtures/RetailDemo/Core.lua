local addonName, ns = ...
local C_Spell = C_Spell
local pairs, C_Timer = pairs, C_Timer

ns.results = {}
local R = ns.results

-- A string mentioning C_Item.GetItemInfo must not be touched.
R.note = "uses C_Item.GetItemInfo"
--[[ C_AddOns.GetAddOnMetadata in a comment ]]

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("PLAYER_SPECIALIZATION_CHANGED")
f:RegisterUnitEvent("UNIT_ABSORB_AMOUNT_CHANGED", "player")
f:SetScript("OnEvent", function(self, event, ...)
	R.events = (R.events or "") .. event .. ";"
	if event == "PLAYER_LOGIN" then
		local info = C_Spell.GetSpellInfo(133)
		R.spellName = info and info.name
		R.spellIcon = info and info.iconID
		local cd = C_Spell.GetSpellCooldown(133)
		R.cdEnabled = cd and cd.isEnabled
		R.version = C_AddOns.GetAddOnMetadata(addonName, "Version")
		local aura = C_UnitAuras.GetBuffDataByIndex("player", 1)
		R.auraName = aura and aura.name
		R.auraStacks = aura and aura.applications
		R.foci = #GetMouseFoci()
		R.spec = GetSpecialization()
		R.absorb = UnitGetTotalAbsorbs("player")
		R.cvar = C_CVar.GetCVar("autoLootDefault")
		if C_MythicPlus then R.mplus = true end
	end
end)

local Addon = {}
function Addon:RegisterEvent(e) R.customRegister = (R.customRegister or "") .. e .. ";" end
Addon:RegisterEvent("GARRISON_UPDATE")
Addon:RegisterEvent("PLAYER_ENTERING_WORLD")

local t = { C_Spell = "key not rewritten" }
R.tableKey = t.C_Spell
