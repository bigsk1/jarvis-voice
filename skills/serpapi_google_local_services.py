#!/usr/bin/env python3
"""Jarvis Skill: Google Local Services provider discovery through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import get_config_value, load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_LOCAL_SERVICES_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 10
LOCALE_RE = re.compile(r"^[a-z]{2}$")
CID_RE = re.compile(r"^[0-9]+$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "data_cid",
    "hl",
    "job_type",
    "cid",
    "bid",
    "pid",
    "no_cache",
}

# SerpApi's Local Services engine accepts only the provider's documented query
# identifiers, not arbitrary search text. Keep this allowlist in code so the
# public tool schema stays compact while invalid categories fail before using a
# SerpApi search. Source: https://serpapi.com/google-local-services-queries
SUPPORTED_SERVICE_QUERIES = frozenset({
    "acupuncturist",
    "allergist",
    "animal_shelter",
    "appliance_repair",
    "architect",
    "audiologist",
    "auto_body_shop",
    "auto_repair_shop",
    "bankruptcy_lawyer",
    "barber_shop",
    "beauty_school",
    "business_lawyer",
    "car_wash_and_detailing",
    "carpenter",
    "carpet_cleaning",
    "cellphone_and_laptop_repair",
    "child_care",
    "chiropractor",
    "cleaning_service",
    "contract_lawyer",
    "countertop_pro",
    "criminal_lawyer",
    "dance_instructor",
    "dentist",
    "dermatologist",
    "dietitian",
    "disability_lawyer",
    "drain_expert",
    "driving_instructor",
    "dui_lawyer",
    "electrician",
    "estate_lawyer",
    "family_lawyer",
    "fencing_pro",
    "financial_planner",
    "first_aid_trainer",
    "flooring_pro",
    "foundation_pro",
    "funeral_home",
    "garage_door_pro",
    "general_contractor",
    "hair_removal",
    "hair_salon",
    "handyman",
    "home_inspector",
    "home_insulation",
    "home_security",
    "home_theater",
    "hvac",
    "immigration_lawyer",
    "insurance_agency",
    "interior_designer",
    "ip_lawyer",
    "junk_removal",
    "labor_lawyer",
    "landscaper",
    "language_instructor",
    "lawn_care",
    "litigation_lawyer",
    "locksmith",
    "malpractice_lawyer",
    "massage_school",
    "massage_therapist",
    "mover",
    "nail_salon",
    "occupational_therapist",
    "ophthalmologist",
    "optometrist",
    "orthodontist",
    "orthopedic_surgeon",
    "painter",
    "personal_injury_lawyer",
    "personal_trainer",
    "pest_control",
    "pet_adoption",
    "pet_boarding",
    "pet_grooming",
    "pet_trainer",
    "physiotherapist",
    "piercing_studio",
    "plastic_surgeon",
    "plumber",
    "podiatrist",
    "pool_cleaner",
    "pool_contractor",
    "preschool",
    "primary_care",
    "real_estate_agent",
    "real_estate_lawyer",
    "roofer",
    "sewage_pro",
    "siding_pro",
    "snow_removal",
    "solar_energy_contractor",
    "storage",
    "tattoo_studio",
    "tax_lawyer",
    "tax_specialist",
    "tire_shop",
    "towing",
    "traffic_lawyer",
    "tree_service",
    "tutor",
    "veterinarian",
    "water_damage",
    "weight_loss_service",
    "window_cleaner",
    "window_repair",
    "yoga_instructor",
})

# Natural profession/category phrases the model or user is likely to provide
# when they do not know SerpApi's canonical identifier. Most supported phrases
# need no entry because spaces and punctuation normalize directly to
# underscores. Keep these mappings exact and deterministic: this tool accepts a
# profession, not an arbitrary free-form web search.
SERVICE_CATEGORY_ALIASES = {
    "air_conditioner_service": "hvac",
    "air_conditioning_service": "hvac",
    "allergy_doctor": "allergist",
    "allergy_specialist": "allergist",
    "animal_rescue": "animal_shelter",
    "animal_hospital": "veterinarian",
    "appliance_service": "appliance_repair",
    "appliance_technician": "appliance_repair",
    "arborist": "tree_service",
    "attorney_for_bankruptcy": "bankruptcy_lawyer",
    "attorney_for_business": "business_lawyer",
    "attorney_for_contracts": "contract_lawyer",
    "attorney_for_criminal_defense": "criminal_lawyer",
    "attorney_for_disability": "disability_lawyer",
    "attorney_for_divorce": "family_lawyer",
    "attorney_for_dui": "dui_lawyer",
    "attorney_for_employment": "labor_lawyer",
    "attorney_for_estates": "estate_lawyer",
    "attorney_for_family_law": "family_lawyer",
    "attorney_for_immigration": "immigration_lawyer",
    "attorney_for_intellectual_property": "ip_lawyer",
    "attorney_for_lawsuits": "litigation_lawyer",
    "attorney_for_malpractice": "malpractice_lawyer",
    "attorney_for_personal_injury": "personal_injury_lawyer",
    "attorney_for_real_estate": "real_estate_lawyer",
    "attorney_for_taxes": "tax_lawyer",
    "attorney_for_traffic_ticket": "traffic_lawyer",
    "auto_detailing": "car_wash_and_detailing",
    "auto_mechanic": "auto_repair_shop",
    "auto_repair": "auto_repair_shop",
    "automotive_mechanic": "auto_repair_shop",
    "automotive_repair": "auto_repair_shop",
    "body_shop": "auto_body_shop",
    "business_attorney": "business_lawyer",
    "car_body_shop": "auto_body_shop",
    "car_crash_lawyer": "personal_injury_lawyer",
    "car_detailing": "car_wash_and_detailing",
    "car_mechanic": "auto_repair_shop",
    "car_repair": "auto_repair_shop",
    "car_repair_shop": "auto_repair_shop",
    "car_wash": "car_wash_and_detailing",
    "carpet_cleaner": "carpet_cleaning",
    "cat_groomer": "pet_grooming",
    "cell_phone_repair": "cellphone_and_laptop_repair",
    "childcare": "child_care",
    "computer_repair": "cellphone_and_laptop_repair",
    "contract_attorney": "contract_lawyer",
    "criminal_defense_attorney": "criminal_lawyer",
    "day_care": "child_care",
    "daycare": "child_care",
    "deck_builder": "general_contractor",
    "divorce_attorney": "family_lawyer",
    "drain_cleaner": "drain_expert",
    "drain_cleaning": "drain_expert",
    "drain_service": "drain_expert",
    "driving_lessons": "driving_instructor",
    "dui_attorney": "dui_lawyer",
    "electrician_service": "electrician",
    "electrical_service": "electrician",
    "electrical_contractor": "electrician",
    "employment_attorney": "labor_lawyer",
    "estate_planning_attorney": "estate_lawyer",
    "exterminator": "pest_control",
    "family_attorney": "family_lawyer",
    "family_doctor": "primary_care",
    "fence_builder": "fencing_pro",
    "fence_company": "fencing_pro",
    "fence_contractor": "fencing_pro",
    "floor_installer": "flooring_pro",
    "flooring_contractor": "flooring_pro",
    "foundation_contractor": "foundation_pro",
    "foundation_repair": "foundation_pro",
    "garden_care": "lawn_care",
    "garden_maintenance": "lawn_care",
    "general_practitioner": "primary_care",
    "grass_care": "lawn_care",
    "hairdresser": "hair_salon",
    "handyman_service": "handyman",
    "hearing_doctor": "audiologist",
    "hearing_specialist": "audiologist",
    "heating_service": "hvac",
    "heating_and_air_conditioning": "hvac",
    "heating_and_cooling": "hvac",
    "home_alarm": "home_security",
    "home_builder": "general_contractor",
    "home_cleaner": "cleaning_service",
    "home_cleaning": "cleaning_service",
    "home_remodeler": "general_contractor",
    "home_security_system": "home_security",
    "home_stereo_installer": "home_theater",
    "home_theater_installer": "home_theater",
    "house_cleaner": "cleaning_service",
    "house_cleaning": "cleaning_service",
    "house_inspector": "home_inspector",
    "house_mover": "mover",
    "hvac_contractor": "hvac",
    "hvac_repair": "hvac",
    "hvac_service": "hvac",
    "immigration_attorney": "immigration_lawyer",
    "insurance_agent": "insurance_agency",
    "junk_hauling": "junk_removal",
    "labor_attorney": "labor_lawyer",
    "landscape_architect": "landscaper",
    "landscape_contractor": "landscaper",
    "landscape_designer": "landscaper",
    "landscape_service": "landscaper",
    "landscaping": "landscaper",
    "landscaping_service": "landscaper",
    "laptop_repair": "cellphone_and_laptop_repair",
    "lawn_maintenance": "lawn_care",
    "lawn_service": "lawn_care",
    "lawncare": "lawn_care",
    "legal_help_for_bankruptcy": "bankruptcy_lawyer",
    "locksmith_service": "locksmith",
    "maid": "cleaning_service",
    "maid_service": "cleaning_service",
    "massage": "massage_therapist",
    "mechanic": "auto_repair_shop",
    "mechanic_shop": "auto_repair_shop",
    "moving_company": "mover",
    "moving_help": "mover",
    "moving_service": "mover",
    "nanny": "child_care",
    "orthopedic_doctor": "orthopedic_surgeon",
    "orthopedic_specialist": "orthopedic_surgeon",
    "pain_and_suffering_lawyer": "personal_injury_lawyer",
    "personal_injury_attorney": "personal_injury_lawyer",
    "personal_training": "personal_trainer",
    "pest_control_service": "pest_control",
    "pest_exterminator": "pest_control",
    "pet_boarder": "pet_boarding",
    "pet_daycare": "pet_boarding",
    "pet_groomer": "pet_grooming",
    "pet_grooming_service": "pet_grooming",
    "pet_sitter": "pet_boarding",
    "pet_training": "pet_trainer",
    "physical_therapist": "physiotherapist",
    "physical_therapy": "physiotherapist",
    "plumber_service": "plumber",
    "plumbing_contractor": "plumber",
    "plumbing_repair": "plumber",
    "plumbing_service": "plumber",
    "pool_builder": "pool_contractor",
    "pool_cleaning": "pool_cleaner",
    "pool_service": "pool_cleaner",
    "primary_care_doctor": "primary_care",
    "property_inspector": "home_inspector",
    "realtor": "real_estate_agent",
    "remodeling_contractor": "general_contractor",
    "roofing_company": "roofer",
    "roofing_contractor": "roofer",
    "septic_service": "sewage_pro",
    "sewage_cleanup": "sewage_pro",
    "sewer_service": "sewage_pro",
    "siding_contractor": "siding_pro",
    "siding_installation": "siding_pro",
    "solar_company": "solar_energy_contractor",
    "solar_installer": "solar_energy_contractor",
    "tax_accountant": "tax_specialist",
    "tax_attorney": "tax_lawyer",
    "tax_preparation": "tax_specialist",
    "tax_preparer": "tax_specialist",
    "therapeutic_massage": "massage_therapist",
    "tire_center": "tire_shop",
    "tire_repair": "tire_shop",
    "tow_service": "towing",
    "tow_truck": "towing",
    "towing_service": "towing",
    "traffic_attorney": "traffic_lawyer",
    "tree_care": "tree_service",
    "tree_removal_service": "tree_service",
    "tree_trimmer": "tree_service",
    "vet": "veterinarian",
    "veterinary_clinic": "veterinarian",
    "water_damage_restoration": "water_damage",
    "water_remediation": "water_damage",
    "weight_loss_clinic": "weight_loss_service",
    "window_cleaning": "window_cleaner",
    "window_washing": "window_cleaner",
    "window_installer": "window_repair",
    "window_replacement": "window_repair",
    "yard_care": "lawn_care",
    "yard_maintenance": "lawn_care",
    "yard_service": "lawn_care",
    "yoga_classes": "yoga_instructor",
    "yoga_teacher": "yoga_instructor",
}

# Exact task phrases that can safely narrow a supported profession to one of
# SerpApi's documented job_type identifiers. Broad phrases stay in the category
# map above so they do not accidentally exclude suitable providers.
SERVICE_TASK_ALIASES = {
    # Appliance Repair
    "clothes_dryer_repair": ("appliance_repair", "repair_dryer"),
    "dishwasher_repair": ("appliance_repair", "repair_dishwasher"),
    "dryer_repair": ("appliance_repair", "repair_dryer"),
    "dryer_service": ("appliance_repair", "repair_dryer"),
    "freezer_repair": ("appliance_repair", "repair_freezer"),
    "microwave_repair": ("appliance_repair", "repair_microwave"),
    "oven_repair": ("appliance_repair", "repair_oven"),
    "refrigerator_repair": ("appliance_repair", "repair_refrigerator"),
    "stove_repair": ("appliance_repair", "repair_stove_cooktop"),
    "washer_and_dryer_repair": ("appliance_repair", "repair_washer_dryer"),
    "washer_dryer_repair": ("appliance_repair", "repair_washer_dryer"),
    "washing_machine_repair": ("appliance_repair", "repair_washer"),
    # Auto Body and Auto Repair
    "brake_repair": ("auto_repair_shop", "brake_repair"),
    "bumper_repair": ("auto_body_shop", "bumper_repair"),
    "car_dent_repair": ("auto_body_shop", "dents_and_scratches_repair"),
    "car_electrical_repair": ("auto_repair_shop", "electrical_system_repair"),
    "car_engine_repair": ("auto_repair_shop", "engine_repair"),
    "car_exhaust_repair": ("auto_repair_shop", "exhaust_system_repair"),
    "car_maintenance": ("auto_repair_shop", "car_maintenance"),
    "car_scratch_repair": ("auto_body_shop", "dents_and_scratches_repair"),
    "car_transmission_repair": ("auto_repair_shop", "transmission_repair"),
    "vehicle_maintenance": ("auto_repair_shop", "car_maintenance"),
    # Electrical
    "ceiling_fan_installation": ("electrician", "install_fan"),
    "electrical_panel_repair": ("electrician", "repair_panel"),
    "ev_charger_installation": ("electrician", "electric_car_charger"),
    "light_fixture_installation": ("electrician", "install_light_fixtures"),
    "light_fixture_repair": ("electrician", "repair_light_fixtures"),
    "outdoor_lighting_installation": ("electrician", "install_outdoor_lighting"),
    "outlet_installation": ("electrician", "install_outlets_switches"),
    "outlet_repair": ("electrician", "repair_outlets_switches"),
    "power_restoration": ("electrician", "restore_power"),
    # Fencing and Flooring
    "fence_design": ("fencing_pro", "fence_design"),
    "fence_installation": ("fencing_pro", "installation_fencing_pro"),
    "fence_installation_service": ("fencing_pro", "installation_fencing_pro"),
    "fence_repair": ("fencing_pro", "repairs_maintenance_fencing_pro"),
    "fence_repair_service": ("fencing_pro", "repairs_maintenance_fencing_pro"),
    "floor_installation": ("flooring_pro", "installation_flooring_pro"),
    "floor_refinishing": ("flooring_pro", "refinishing"),
    "floor_repair": ("flooring_pro", "repair_maintenance_flooring_pro"),
    "floor_repair_service": ("flooring_pro", "repair_maintenance_flooring_pro"),
    "hardwood_flooring": ("flooring_pro", "hardwood"),
    "tile_flooring": ("flooring_pro", "tile"),
    # Garage Door
    "garage_door_cable_repair": ("garage_door_pro", "repair_cables"),
    "garage_door_installation": ("garage_door_pro", "install_garage_door"),
    "garage_door_opener_replacement": ("garage_door_pro", "replace_opener"),
    "garage_door_repair": ("garage_door_pro", "repair_garage_door"),
    "garage_door_spring_replacement": ("garage_door_pro", "replace_springs"),
    # General Contracting
    "bathroom_remodel": ("general_contractor", "bathroom_remodel"),
    "deck_building": ("general_contractor", "decks_patio"),
    "home_addition": ("general_contractor", "home_addition"),
    "home_construction": ("general_contractor", "home_building"),
    "home_remodel": ("general_contractor", "home_remodel_renovation"),
    "home_renovation": ("general_contractor", "home_remodel_renovation"),
    "kitchen_remodel": ("general_contractor", "kitchen_remodel"),
    "patio_construction": ("general_contractor", "decks_patio"),
    # HVAC
    "ac_installation": ("hvac", "install_ac"),
    "ac_maintenance": ("hvac", "ac_maintenance"),
    "ac_repair": ("hvac", "repair_ac"),
    "air_conditioner_repair": ("hvac", "repair_ac"),
    "air_conditioning_repair": ("hvac", "repair_ac"),
    "air_duct_cleaning": ("hvac", "clean_ducts_vents"),
    "air_duct_installation": ("hvac", "install_ducts_vents"),
    "air_duct_repair": ("hvac", "repair_ducts_vents"),
    "furnace_installation": ("hvac", "install_heating_system"),
    "furnace_maintenance": ("hvac", "heating_maintenance"),
    "furnace_repair": ("hvac", "repair_heating_system"),
    "heating_system_repair": ("hvac", "repair_heating_system"),
    "hvac_maintenance": ("hvac", "hvac_maintenance"),
    "thermostat_repair": ("hvac", "repair_thermostat"),
    # Handyman and House Cleaning
    "drywall_installation": ("handyman", "install_drywall"),
    "drywall_repair": ("handyman", "repair_drywall"),
    "furniture_assembly": ("handyman", "assemble_furniture"),
    "deep_house_cleaning": ("cleaning_service", "deep_clean"),
    "move_out_cleaning": ("cleaning_service", "moving_clean"),
    "moving_cleaning": ("cleaning_service", "moving_clean"),
    "office_cleaning": ("cleaning_service", "office_clean"),
    "regular_house_cleaning": ("cleaning_service", "standard_clean"),
    "standard_house_cleaning": ("cleaning_service", "standard_clean"),
    "tv_mounting": ("handyman", "mount_tv"),
    # Junk Removal
    "appliance_hauling": ("junk_removal", "appliance_removal"),
    "appliance_removal": ("junk_removal", "appliance_removal"),
    "construction_debris_removal": ("junk_removal", "construction_waste_removal"),
    "furniture_hauling": ("junk_removal", "furniture_removal"),
    "furniture_removal": ("junk_removal", "furniture_removal"),
    "yard_waste_removal": ("junk_removal", "yard_waste_removal"),
    # Landscaping and Lawn Care
    "artificial_turf_installation": ("landscaper", "artificial_turf_installation"),
    "driveway_paving": ("landscaper", "paving_driveway_walkway"),
    "garden_design": ("landscaper", "landscape_design"),
    "grass_cutting": ("lawn_care", "lawn_mowing_maintenance"),
    "grass_seeding": ("lawn_care", "seeding"),
    "grading_and_resloping": ("landscaper", "grading_resloping"),
    "hardscape_installation": ("landscaper", "hardscapes"),
    "irrigation_repair": ("lawn_care", "irrigation_system_repair_maintenance"),
    "landscape_design": ("landscaper", "landscape_design"),
    "landscape_installation": ("landscaper", "landscape_installations"),
    "leaf_cleanup": ("lawn_care", "yard_cleanup"),
    "lawn_cutting": ("lawn_care", "lawn_mowing_maintenance"),
    "lawn_mowing": ("lawn_care", "lawn_mowing_maintenance"),
    "lawn_pest_control": ("lawn_care", "lawn_pest_control"),
    "lawn_seeding": ("lawn_care", "seeding"),
    "lawn_sod_installation": ("lawn_care", "sod_installation"),
    "lawn_weeding": ("lawn_care", "weed_control"),
    "mulching": ("lawn_care", "mulching"),
    "outdoor_water_feature": ("landscaper", "outdoor_water_feature"),
    "retaining_wall": ("landscaper", "retaining_walls"),
    "stone_masonry": ("landscaper", "stone_masonry"),
    "sprinkler_repair": ("lawn_care", "irrigation_system_repair_maintenance"),
    "sprinkler_system_repair": ("lawn_care", "irrigation_system_repair_maintenance"),
    "walkway_paving": ("landscaper", "paving_driveway_walkway"),
    "yard_cleanup": ("lawn_care", "yard_cleanup"),
    # Moving and Painting
    "cabinet_painting": ("painter", "cabinet_painting"),
    "house_painting": ("painter", "paint_outdoors_painter"),
    "interior_painting": ("painter", "paint_indoors_painter"),
    "local_moving": ("mover", "local_move"),
    "long_distance_moving": ("mover", "out_of_state_move"),
    "out_of_state_moving": ("mover", "out_of_state_move"),
    "packing_and_unpacking": ("mover", "packing_unpacking"),
    # Pest Control
    "ant_extermination": ("pest_control", "ants"),
    "bed_bug_extermination": ("pest_control", "bed_bugs"),
    "cockroach_extermination": ("pest_control", "cockroaches"),
    "mosquito_control": ("pest_control", "mosquitoes"),
    "rodent_control": ("pest_control", "rodents"),
    "spider_extermination": ("pest_control", "spiders"),
    "termite_control": ("pest_control", "termites"),
    "wasp_removal": ("pest_control", "hornets_or_wasps"),
    # Pet Services
    "cat_boarding": ("pet_boarding", "cat_boarding"),
    "dog_boarding": ("pet_boarding", "dog_boarding"),
    "dog_daycare": ("pet_boarding", "dog_daycare"),
    "dog_training": ("pet_trainer", "dog_training"),
    "puppy_training": ("pet_trainer", "puppy_training"),
    # Plumbing
    "drain_unclogging": ("plumber", "unclog_drain"),
    "faucet_installation": ("plumber", "install_faucet"),
    "faucet_repair": ("plumber", "repair_faucet"),
    "garbage_disposal_installation": ("plumber", "install_garbage_disposal"),
    "garbage_disposal_repair": ("plumber", "repair_garbage_disposal"),
    "leak_detection": ("plumber", "find_leak"),
    "pipe_leak_repair": ("plumber", "repair_pipe"),
    "pipe_repair": ("plumber", "repair_pipe"),
    "shower_installation": ("plumber", "install_shower"),
    "shower_repair": ("plumber", "repair_shower"),
    "toilet_installation": ("plumber", "install_toilet"),
    "toilet_repair": ("plumber", "repair_toilet"),
    "water_heater_installation": ("plumber", "install_water_heater"),
    "water_heater_repair": ("plumber", "repair_water_heater"),
    # Roofing
    "gutter_installation": ("roofer", "gutter_installation"),
    "gutter_repair": ("roofer", "gutter_repair"),
    "roof_inspection": ("roofer", "roof_inspection"),
    "roof_installation": ("roofer", "roof_installation"),
    "roof_repair": ("roofer", "roof_repair"),
    "storm_damage_roof_repair": ("roofer", "storm_wind_damage_roof_repair"),
    # Snow Removal
    "driveway_snow_plowing": ("snow_removal", "residential_plowing"),
    "snow_plowing": ("snow_removal", "residential_plowing"),
    "snow_shoveling": ("snow_removal", "residential_shoveling_blowing"),
    # Tree Services
    "stump_removal": ("tree_service", "stump_removal"),
    "tree_planting": ("tree_service", "tree_planting"),
    "tree_removal": ("tree_service", "tree_removal"),
    "tree_trimming": ("tree_service", "tree_trimming_and_pruning"),
    # Water Damage and Windows
    "fire_damage_restoration": ("water_damage", "fire_damage_cleanup_repair"),
    "mold_remediation": ("water_damage", "water_damage_mold_removal"),
    "mold_removal": ("water_damage", "water_damage_mold_removal"),
    "sewage_damage_cleanup": ("water_damage", "water_damage_sewage_cleanup"),
    "water_damage_cleanup": ("water_damage", "water_damage_cleanup_repair"),
    "water_damage_mold_removal": ("water_damage", "water_damage_mold_removal"),
    "gutter_cleaning": ("window_cleaner", "gutter_cleaning"),
    "door_installation": ("window_repair", "door_installation"),
    "door_repair": ("window_repair", "door_repair"),
    "auto_window_repair": ("auto_body_shop", "window_repair_and_replacement"),
}

SERVICE_QUERY_ALIASES = {
    **SERVICE_CATEGORY_ALIASES,
    **{
        phrase: provider_query
        for phrase, (provider_query, _job_type) in SERVICE_TASK_ALIASES.items()
    },
}

SERVICE_JOB_TYPE_ALIASES = {
    phrase: job_type
    for phrase, (_provider_query, job_type) in SERVICE_TASK_ALIASES.items()
}

# Google Local Services requires a numeric Google city/district CID. These
# aliases avoid a separate Maps lookup for a deliberately small set of common
# locations. All other locations use the bounded resolver below.
COMMON_US_LOCATION_CIDS = {
    "new york": ("14414772292044717666", "New York, New York"),
    "new york city": ("14414772292044717666", "New York, New York"),
    "new york ny": ("14414772292044717666", "New York, New York"),
    "new york new york": ("14414772292044717666", "New York, New York"),
    "nyc": ("14414772292044717666", "New York, New York"),
    "10001": ("14414772292044717666", "New York, New York"),
    "austin": ("6745062158417646970", "Austin, Texas"),
    "austin tx": ("6745062158417646970", "Austin, Texas"),
    "austin texas": ("6745062158417646970", "Austin, Texas"),
    "78701": ("6745062158417646970", "Austin, Texas"),
    "portland": ("2033016683438900625", "Portland, Oregon"),
    "portland or": ("2033016683438900625", "Portland, Oregon"),
    "portland oregon": ("2033016683438900625", "Portland, Oregon"),
    "97201": ("2033016683438900625", "Portland, Oregon"),
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _compact_text(value: Any, maximum: int = 1200) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def _validate_text(value: Any, label: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > maximum:
        raise ValueError(f"'{label}' must be {maximum} characters or fewer.")
    return text


def _numeric_id(value: Any, label: str) -> str:
    identifier = str(value or "").strip()
    if identifier and (len(identifier) > 32 or not CID_RE.fullmatch(identifier)):
        raise ValueError(f"'{label}' must be a numeric identifier.")
    return identifier


def normalize_language(value: Any) -> str:
    language = str(value or "en").strip().lower()
    if not LOCALE_RE.fullmatch(language):
        raise ValueError("'language' must be a two-letter code such as en or es.")
    return language


def _service_query_key(value: str) -> str:
    """Normalize a natural service phrase for alias lookup."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    while normalized.startswith(("a_", "an_", "the_")):
        normalized = normalized.split("_", 1)[1]
    return normalized


def _service_query_candidates(value: str) -> list[str]:
    """Return exact lookup candidates after removing generic request framing."""
    normalized = _service_query_key(value)
    generic_suffixes = (
        "_near_me",
        "_companies",
        "_company",
        "_contractors",
        "_contractor",
        "_professionals",
        "_professional",
        "_providers",
        "_provider",
        "_services",
        "_service",
    )
    candidates: list[str] = []
    pending = [normalized]
    while pending:
        candidate = pending.pop(0)
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)
        if candidate.startswith("local_"):
            pending.append(candidate.removeprefix("local_"))
        for suffix in generic_suffixes:
            if candidate.endswith(suffix):
                pending.append(candidate[: -len(suffix)])
                break
    return candidates


def normalize_service_query(value: Any) -> tuple[str, str]:
    """Return the requested phrase and SerpApi's supported query identifier."""
    requested = _validate_text(value, "query", 300)
    if not requested:
        raise ValueError("'query' is required.")

    provider_query = ""
    for candidate in _service_query_candidates(requested):
        mapped = SERVICE_QUERY_ALIASES.get(candidate, candidate)
        if mapped in SUPPORTED_SERVICE_QUERIES:
            provider_query = mapped
            break
        if mapped.endswith("s"):
            singular = mapped[:-1]
            mapped = SERVICE_QUERY_ALIASES.get(singular, singular)
            if mapped in SUPPORTED_SERVICE_QUERIES:
                provider_query = mapped
                break
    if not provider_query:
        raise ValueError(
            f"Unsupported Google Local Services query '{requested}'. Use a supported "
            "profession such as appliance repair, plumber, electrician, auto repair "
            "shop, cleaning service, roofer, or locksmith; use "
            "serpapi_google_local for general business searches."
        )
    return requested, provider_query


def infer_service_job_type(query: str) -> str:
    """Infer a supported provider subcategory from a natural service phrase."""
    return next(
        (
            SERVICE_JOB_TYPE_ALIASES[candidate]
            for candidate in _service_query_candidates(query)
            if candidate in SERVICE_JOB_TYPE_ALIASES
        ),
        "",
    )


def resolve_location_input(explicit_location: Any) -> tuple[str, str]:
    location = _validate_text(explicit_location, "location", 200)
    if location:
        return location, "explicit"

    default_location = _validate_text(
        get_config_value("JARVIS_DEFAULT_LOCATION", ""),
        "JARVIS_DEFAULT_LOCATION",
        200,
    )
    if default_location:
        return default_location, "jarvis_default_location"

    default_postal_code = _validate_text(
        get_config_value("JARVIS_DEFAULT_POSTAL_CODE", ""),
        "JARVIS_DEFAULT_POSTAL_CODE",
        40,
    )
    if default_postal_code:
        return default_postal_code, "jarvis_default_postal_code"

    raise ValueError(
        "Provide 'data_cid' or 'location', or set JARVIS_DEFAULT_LOCATION or "
        "JARVIS_DEFAULT_POSTAL_CODE in the active mode env file."
    )


def _location_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    words = normalized.split()
    while words and words[-1] in {"usa", "us", "united", "states"}:
        words.pop()
    return " ".join(words)


def common_location_cid(location: str) -> tuple[str, str] | None:
    return COMMON_US_LOCATION_CIDS.get(_location_key(location))


def _serpapi_request(params: dict[str, Any]) -> dict[str, Any]:
    # The code stays proxy-capable while proxy_policy=off keeps Jarvis calls direct.
    return request_serpapi(
        params,
        timeout=GOOGLE_LOCAL_SERVICES_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def resolve_data_cid(
    location: str,
    *,
    language: str,
    no_cache: bool,
) -> tuple[str, str, str, dict[str, Any]]:
    """Resolve a US city/district CID, using a static alias before Google Maps."""
    common = common_location_cid(location)
    if common:
        cid, label = common
        return cid, label, "common_location", {}

    payload = _serpapi_request({
        "engine": "google_maps",
        "type": "search",
        "q": location,
        "hl": language,
        "no_cache": "true" if no_cache else "false",
    })
    place = payload.get("place_results")
    place = place if isinstance(place, dict) else {}
    data_cid = str(place.get("data_cid") or "").strip()
    if not CID_RE.fullmatch(data_cid):
        local_results = payload.get("local_results")
        first = (
            local_results[0]
            if isinstance(local_results, list)
            and local_results
            and isinstance(local_results[0], dict)
            else {}
        )
        data_cid = str(first.get("data_cid") or "").strip()
        if not place:
            place = first
    if not CID_RE.fullmatch(data_cid):
        raise ValueError(
            f"Could not resolve a Google city/district CID for '{location}'. "
            "Provide data_cid explicitly."
        )

    country = str(place.get("country") or "").strip()
    if country and country.lower() not in {"us", "usa", "united states"}:
        raise ValueError(
            "Google Local Services returns results only in the United States; "
            f"the resolved location was in {country}."
        )
    label = _compact_text(place.get("title") or place.get("address"), 300) or location
    resolver_metadata = _search_metadata(payload)
    return data_cid, label, "google_maps_resolver", resolver_metadata


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_string_list(value: Any, limit: int, maximum: int = 500) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value[:limit]
        if (text := _compact_text(item, maximum))
    ]


def _normalize_hours(value: Any) -> tuple[str | None, list[dict[str, str]]]:
    hours = value if isinstance(value, dict) else {}
    week: list[dict[str, str]] = []
    for item in _dict_list(hours.get("week"))[:7]:
        compact = {
            str(day): text
            for day, raw in list(item.items())[:1]
            if (text := _compact_text(raw, 100))
        }
        if compact:
            week.append(compact)
    return _compact_text(hours.get("currently"), 100), week


def normalize_provider(
    item: dict[str, Any],
    *,
    position: int,
    focused_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    hours_current, hours_week = _normalize_hours(item.get("hours"))
    images = _compact_string_list(item.get("images"), 8, 2000)
    provider = {
        "position": position,
        "title": _compact_text(item.get("title"), 500),
        "url": str(item.get("link") or item.get("website") or "").strip() or None,
        "website": str(item.get("website") or "").strip() or None,
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "rating_stars": _dict_list(item.get("rating_stars"))[:5] or None,
        "phone": _compact_text(item.get("phone"), 100),
        "badge": _compact_text(item.get("badge"), 100),
        "type": _compact_text(item.get("type"), 200),
        "address": _compact_text(item.get("address"), 500),
        "service_area": _compact_text(item.get("service_area"), 500),
        "years_in_business": item.get("years_in_business"),
        "bookings_nearby": item.get("bookings_nearby"),
        "thumbnail": item.get("thumbnail") or (images[0] if images else None),
        "images": images or None,
        "hours_current": hours_current,
        "hours_week": hours_week or None,
        "checks": _compact_string_list(item.get("checks"), 12),
        "description": _compact_string_list(item.get("description"), 12),
        "services": _compact_string_list(item.get("services"), 30),
        "covid_measures": _compact_string_list(item.get("covid_measures"), 12),
        "at_this_place": _dict_list(item.get("at_this_place"))[:8] or None,
        "cid": _numeric_id(item.get("cid"), "provider cid") or None,
        "bid": _numeric_id(item.get("bid"), "provider bid") or None,
        "pid": _numeric_id(item.get("pid"), "provider pid") or None,
    }
    if focused_ids:
        for key, value in focused_ids.items():
            provider[key] = value
    return {
        key: field
        for key, field in provider.items()
        if field not in (None, "", [], {})
    }


def normalize_providers(
    value: Any,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    raw = _dict_list(value)
    providers = [
        normalize_provider(item, position=index)
        for index, item in enumerate(raw[:limit], 1)
    ]
    providers = [item for item in providers if item.get("title") or item.get("url")]
    return providers, len(raw)


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
        )
        if metadata.get(key) not in (None, "")
    }


def _build_speech(
    query: str,
    location: str | None,
    providers: list[dict[str, Any]],
    *,
    focused: bool,
) -> str:
    where = f" near {location}" if location else ""
    if not providers:
        return (
            f"Google Local Services returned no provider details for '{query}'{where}."
            if focused
            else f"Google Local Services returned no providers for '{query}'{where}."
        )
    top = providers[0]
    details = []
    if top.get("rating") is not None:
        details.append(f"rated {top['rating']}")
    if top.get("badge"):
        details.append(str(top["badge"]).title())
    suffix = f", {', '.join(details)}" if details else ""
    if focused:
        return f"Retrieved Google Local Services details for {top.get('title') or query}{suffix}."
    return (
        f"Found {len(providers)} Google Local Services provider(s) for '{query}'{where}. "
        f"Top result: {top.get('title') or 'local provider'}{suffix}."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query, provider_query = normalize_service_query(input_data.get("query"))
        language = normalize_language(input_data.get("language"))
        job_type = _validate_text(input_data.get("job_type"), "job_type", 200)
        if not job_type:
            job_type = infer_service_job_type(query)
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        max_results = _bounded_int(
            input_data.get("max_results"),
            "max_results",
            default=DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=20,
        )
        data_cid = _numeric_id(input_data.get("data_cid"), "data_cid")
        cid = _numeric_id(input_data.get("cid"), "cid")
        bid = _numeric_id(input_data.get("bid"), "bid")
        pid = _numeric_id(input_data.get("pid"), "pid")
        focused_values = [cid, bid, pid]
        if any(focused_values) and not all(focused_values):
            raise ValueError("'cid', 'bid', and 'pid' must be supplied together.")
        focused = all(focused_values)

        explicit_location = _validate_text(input_data.get("location"), "location", 200)
        location: str | None = explicit_location or None
        location_source: str | None = "explicit" if explicit_location else None
        resolved_location: str | None = None
        data_cid_source = "explicit" if data_cid else ""
        resolver_metadata: dict[str, Any] = {}
        searches_used = 1
        if not data_cid:
            location, location_source = resolve_location_input(explicit_location)
            data_cid, resolved_location, data_cid_source, resolver_metadata = resolve_data_cid(
                location,
                language=language,
                no_cache=no_cache,
            )
            if data_cid_source == "google_maps_resolver":
                searches_used += 1

        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_local_services",
            "q": provider_query,
            "data_cid": data_cid,
            "hl": language,
            "no_cache": "true" if no_cache else "false",
        }
        for key, field in (
            ("job_type", job_type),
            ("cid", cid),
            ("bid", bid),
            ("pid", pid),
        ):
            if field:
                params[key] = field
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _serpapi_request(params)
        if focused:
            local_place = payload.get("local_place")
            local_place = local_place if isinstance(local_place, dict) else {}
            provider = normalize_provider(
                local_place,
                position=1,
                focused_ids={"cid": cid, "bid": bid, "pid": pid},
            ) if local_place else {}
            providers = [provider] if provider else []
            provider_results_count = 1 if local_place else 0
        else:
            providers, provider_results_count = normalize_providers(
                payload.get("local_ads"), limit=max_results
            )

        metadata = _search_metadata(payload)
        search_information = payload.get("search_information")
        search_information = search_information if isinstance(search_information, dict) else {}
        public_results_url = str(
            search_information.get("google_local_services_url") or ""
        ).strip()
        location_label = resolved_location or location
        data: dict[str, Any] = {
            "engine": "google_local_services",
            "mode": "provider_details" if focused else "search",
            "query": query,
            "provider_query": provider_query,
            "location": location,
            "location_source": location_source,
            "resolved_location": resolved_location,
            "data_cid": data_cid,
            "data_cid_source": data_cid_source,
            "language": language,
            "job_type": job_type or None,
            "cid": cid or None,
            "bid": bid or None,
            "pid": pid or None,
            "max_results": max_results,
            "results_count": len(providers),
            "provider_results_count": provider_results_count,
            "results": providers,
            "top_results": providers[:5],
            "detail": providers[0] if focused and providers else None,
            "top_url": providers[0].get("url") if providers else None,
            "google_local_services_url": public_results_url or None,
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "resolver_search_metadata": resolver_metadata or None,
            "serpapi_searches_used": searches_used,
            "us_only": True,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Local Services",
        }
        data = {
            key: field
            for key, field in data.items()
            if field not in (None, "", [], {})
        }
        if include_raw:
            data["raw"] = payload

        return_success(
            _build_speech(query, location_label, providers, focused=focused),
            data,
        )
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Local Services request timed out.")
            return 1
        return_error(f"SerpApi Google Local Services error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
