local addonName, ns = ...
-- This file has its own local named Settings; it must not be rewritten.
local Settings = { scale = 2 }
ns.results.localSettings = Settings.scale

local panel = CreateFrame("Frame")
local category = _G.Settings.RegisterCanvasLayoutCategory(panel, "Retail Demo")
_G.Settings.RegisterAddOnCategory(category)
ns.results.categoryID = category:GetID()
