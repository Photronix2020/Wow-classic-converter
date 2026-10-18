"""What the converter knows about retail-only APIs and Classic clients.

Shimmed APIs are not listed here: they are read straight from shim.lua so
the two can't drift apart. This file covers the client targets and the
things that can't be shimmed, which go into the report.

Availability across Classic flavors is a best-effort guess. Values say
which targets are expected to lack the API:
  "all"     - missing in every Classic flavor
  "vanilla" - missing in Classic Era / Anniversary / SoD / Hardcore,
              possibly present in later progression flavors (TBC, Mists)
"""

# name -> (TOC suffix, default ## Interface value)
# Interface numbers change with every client patch. A TOC may list several,
# so a few recent ones are included. Check yours in game with
#   /dump select(4, GetBuildInfo())
# and pass --interface to override.
TARGETS = {
    "vanilla": ("_Vanilla", "11507, 11508"),
    "tbc": ("_TBC", "20505"),
    "mists": ("_Mists", "50500, 50501"),
}

# Other TOC suffixes an addon author may already use for each target. If an
# addon ships one, it already supports that client and its TOC is kept.
TARGET_TOC_ALIASES = {
    "vanilla": ("_Vanilla", "-Vanilla", "_Classic", "-Classic"),
    "tbc": ("_TBC", "-TBC", "_BCC", "-BCC"),
    "mists": ("_Mists", "-Mists"),
}


RETAIL_NAMESPACES = {
    "C_AdventureMap": "all",
    "C_ArtifactUI": "all",
    "C_AzeriteEmpoweredItem": "all",
    "C_AzeriteEssence": "all",
    "C_AzeriteItem": "all",
    "C_ChallengeMode": "vanilla",
    "C_ClassTalents": "all",
    "C_ContributionCollector": "all",
    "C_CovenantCallings": "all",
    "C_Covenants": "all",
    "C_CovenantSanctumUI": "all",
    "C_CraftingOrders": "all",
    "C_DelvesUI": "all",
    "C_EditMode": "all",
    "C_EncounterJournal": "vanilla",
    "C_Garrison": "all",
    "C_Heirloom": "vanilla",
    "C_Housing": "all",
    "C_IslandsQueue": "all",
    "C_ItemInteraction": "all",
    "C_ItemUpgrade": "all",
    "C_LegendaryCrafting": "all",
    "C_MajorFactions": "all",
    "C_MountJournal": "vanilla",
    "C_MythicPlus": "all",
    "C_PerksActivities": "all",
    "C_PerksProgram": "all",
    "C_PetBattles": "vanilla",
    "C_PetJournal": "vanilla",
    "C_PlayerChoice": "all",
    "C_ProfSpecs": "all",
    "C_Scenario": "vanilla",
    "C_Soulbinds": "all",
    "C_SpecializationInfo": "vanilla",
    "C_SpellBook": "vanilla",
    "C_TaskQuest": "all",
    "C_TooltipInfo": "vanilla",
    "C_ToyBox": "vanilla",
    "C_TradeSkillUI": "vanilla",
    "C_Traits": "all",
    "C_Transmog": "vanilla",
    "C_TransmogCollection": "all",
    "C_TransmogSets": "all",
    "C_WeeklyRewards": "all",
    "C_ZoneAbility": "all",
    "EditModeManagerFrame": "all",
    "Menu": "vanilla",
    "MenuUtil": "vanilla",
}

RETAIL_GLOBALS = {
    "GetAverageItemLevel": "vanilla",
    "GetLootSpecialization": "vanilla",
    "GetSpecializationInfoByID": "vanilla",
    "IsInJailersTower": "all",
    "IsLevelAtEffectiveMaxLevel": "all",
    "UnitIsWildBattlePet": "vanilla",
    "UnitTreatAsPlayerForDisplay": "all",
    "C_PlayerInfo.GetPlayerMythicPlusRatingSummary": "all",
}

# Registering these on a client that lacks them is made safe at runtime by
# the shim; they are reported so you know the feature will be inactive.
RETAIL_EVENTS = {
    "ACTIVE_DELVE_DATA_UPDATE": "all",
    "ACTIVE_TALENT_GROUP_CHANGED": "vanilla",
    "AZERITE_EMPOWERED_ITEM_SELECTION_UPDATED": "all",
    "AZERITE_ITEM_EXPERIENCE_CHANGED": "all",
    "CHALLENGE_MODE_COMPLETED": "vanilla",
    "CHALLENGE_MODE_RESET": "vanilla",
    "CHALLENGE_MODE_START": "vanilla",
    "COVENANT_CHOSEN": "all",
    "CRAFTINGORDERS_UPDATE_ORDER_COUNT": "all",
    "EDIT_MODE_LAYOUTS_UPDATED": "all",
    "GARRISON_UPDATE": "all",
    "MYTHIC_PLUS_CURRENT_AFFIX_UPDATE": "all",
    "PET_BATTLE_CLOSE": "vanilla",
    "PET_BATTLE_OPENING_START": "vanilla",
    "PLAYER_SOFT_INTERACT_CHANGED": "vanilla",
    "PLAYER_SPECIALIZATION_CHANGED": "vanilla",
    "SCENARIO_UPDATE": "vanilla",
    "SOULBIND_ACTIVATED": "all",
    "TRAIT_CONFIG_UPDATED": "all",
    "TRANSMOG_COLLECTION_UPDATED": "all",
    "UNIT_ABSORB_AMOUNT_CHANGED": "vanilla",
    "UNIT_HEAL_ABSORB_AMOUNT_CHANGED": "vanilla",
    "WEEKLY_REWARDS_UPDATE": "all",
}

RETAIL_XML_TEMPLATES = {
    "EditModeSystemTemplate": "all",
    "SettingsCheckboxControlTemplate": "all",
    "SettingsListTemplate": "all",
    "SettingsSliderControlTemplate": "all",
    "WowStyle1DropdownTemplate": "vanilla",
    "WowStyle1FilterDropdownTemplate": "vanilla",
    "DropdownButton": "vanilla",
}


def missing_in(availability, target):
    return availability == "all" or availability == target
