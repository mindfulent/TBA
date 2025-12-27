#!/usr/bin/env python3
"""
MCC CurseForge Compatibility Analyzer
Analyzes your modpack against the CurseForge approved non-CF mods list.

Usage: python check_cf_compatibility.py [path_to_mcc_folder]
"""

import os
import sys
import re
from pathlib import Path

# Approved non-CurseForge mods from the official spreadsheet
# Format: lowercase mod name -> license
APPROVED_NON_CF = {
    # Performance Core
    "sodium": "LGPL v3",
    "lithium": "LGPL-3.0",
    "phosphor": "GNU",
    "indium": "Apache License 2.0",
    "hydrogen": "General Use",
    "nvidium": "GNU",
    "memoryleakfix": "GNU",
    "moreculling": "GNU",
    "servercore": "GNU",
    
    # APIs/Libraries
    "malilib": "LGPL 2.1",
    "mod menu": "MIT",
    "minihud": "General Use",
    "itemscroller": "General Use",
    "tweakeroo": "GNU",
    
    # Building Tools  
    "litematica": "LGPL 2.1",
    "effortless structure": "GNU",
    "reframed": "MIT",
    
    # Visual/Rendering
    "iris": "GPL v3",
    "iris shaders": "GPL v3",
    "effective": "ARR with exception for modpacks",
    "lambdynamiclights": "MIT",
    "presence footsteps": "WTFPL",
    "fabricskyboxes": "MIT",
    "fog looks modern now": "GNU",
    
    # Multiplayer
    "fabricord": "Apache",
    "simple voice chat": None,  # Check - might be on CF
    
    # Misc Approved
    "antique atlas 4": "GNU",
    "fabric seasons": None,  # Needs verification
    "freecam": "MIT",
    "inventorio": "General Use",
    "invmove": "GNU",
    "replay mod": "GPL v3",
    "replaymod": "GPL v3",
    "world host": "MIT",
    "distant horizons": None,  # Check CF
    
    # WATERMeDIA family (by SrRapero720)
    "watermine": "by the owner request",
    "watermedia": "by the owner request",
    
    # Additional from your pack that need checking
    "polymer": None,  # Check license - MIT by Patbox
    "fabric api": None,  # On CurseForge
}

# Mods known to be on CurseForge
KNOWN_ON_CURSEFORGE = {
    "fabric api",
    "fabric language kotlin",
    "architectury api",
    "cloth config",
    "cloth config api",
    "journeymap",
    "bluemap",
    "chipped",
    "handcrafted",
    "macaw's doors",
    "macaw's windows", 
    "macaw's bridges",
    "macaw's roofs",
    "macaw's fences and walls",
    "macaw's trapdoors",
    "macaw's furniture",
    "macaw's lights and lamps",
    "storage drawers",
    "supplementaries",
    "rei",
    "roughly enough items",
    "simple voice chat",
    "controlling",
    "appleskin",
    "mouse tweaks",
    "balm",
    "puzzles lib",
    "moonlight lib",
    "creativecore",
    "farmer's delight",
    "spark",
    "chunky",
    "distant horizons",
    "adorn",
    "ferrite core",
    "ferritecore",
    "modernfix",
    "krypton",
    "resourceful lib",
    "forge config api port",
    "bad packets",
    "searchables",
    "armor statues",
    "little joys",
    "wthit",
    "just zoom",
    "itemswapper",
    "flan",
    "better sleep",
    "advanced backups",
    "simple discord rpc",
    "amendments",
    "universal graves",
    "athena ctm",
    "konkrete",
}


def normalize_name(name: str) -> str:
    """Normalize mod name for comparison."""
    name = name.lower().strip()
    # Remove common prefixes/suffixes
    name = re.sub(r'^\[.*?\]\s*', '', name)  # Remove [Let's Do] etc
    name = re.sub(r'\s*\(.*?\)\s*$', '', name)  # Remove (Fabric) etc
    name = re.sub(r"'s", "s", name)  # Macaw's -> Macaws
    return name


def parse_pw_toml(filepath: Path) -> dict:
    """Parse a .pw.toml file to extract mod info."""
    info = {
        "name": filepath.stem,
        "has_curseforge": False,
        "has_modrinth": False,
        "side": "both",
    }
    
    try:
        content = filepath.read_text(encoding='utf-8')
        
        # Check for CurseForge section
        if "[update.curseforge]" in content:
            info["has_curseforge"] = True
            
        # Check for Modrinth section
        if "[update.modrinth]" in content:
            info["has_modrinth"] = True
            
        # Extract name
        name_match = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
        if name_match:
            info["name"] = name_match.group(1)
            
        # Extract side
        side_match = re.search(r'^side\s*=\s*"([^"]+)"', content, re.MULTILINE)
        if side_match:
            info["side"] = side_match.group(1)
            
    except Exception as e:
        print(f"  Warning: Could not parse {filepath}: {e}")
        
    return info


def check_approved(mod_name: str) -> tuple[bool, str | None]:
    """Check if mod is on approved non-CF list."""
    normalized = normalize_name(mod_name)
    
    for approved_name, license_info in APPROVED_NON_CF.items():
        if normalized == approved_name or approved_name in normalized or normalized in approved_name:
            return True, license_info
            
    return False, None


def check_likely_curseforge(mod_name: str) -> bool:
    """Check if mod is likely on CurseForge."""
    normalized = normalize_name(mod_name)
    
    for cf_name in KNOWN_ON_CURSEFORGE:
        if normalized == cf_name or cf_name in normalized or normalized in cf_name:
            return True
            
    return False


def analyze_modpack(mcc_path: Path):
    """Analyze the modpack for CurseForge compatibility."""
    mods_path = mcc_path / "mods"
    
    if not mods_path.exists():
        print(f"Error: {mods_path} does not exist")
        sys.exit(1)
        
    print("=" * 60)
    print("MCC CurseForge Compatibility Analysis")
    print("=" * 60)
    print()
    
    # Categorize mods
    on_curseforge = []
    on_approved_list = []
    likely_curseforge = []
    needs_verification = []
    potential_blockers = []
    
    pw_toml_files = list(mods_path.glob("*.pw.toml"))
    
    if not pw_toml_files:
        print(f"No .pw.toml files found in {mods_path}")
        print("Run 'packwiz curseforge detect' first to add CF metadata")
        sys.exit(1)
    
    print(f"Analyzing {len(pw_toml_files)} mods...\n")
    
    for toml_file in sorted(pw_toml_files):
        info = parse_pw_toml(toml_file)
        mod_name = info["name"]
        
        if info["has_curseforge"]:
            on_curseforge.append(mod_name)
        elif check_likely_curseforge(mod_name):
            likely_curseforge.append(mod_name)
        else:
            is_approved, license_info = check_approved(mod_name)
            if is_approved:
                on_approved_list.append((mod_name, license_info))
            elif info["has_modrinth"]:
                # Modrinth-only, not on approved list - needs checking
                needs_verification.append(mod_name)
            else:
                potential_blockers.append(mod_name)
    
    # Print results
    print("✅ ON CURSEFORGE (can reference via manifest.json)")
    print("-" * 50)
    for mod in sorted(on_curseforge):
        print(f"  • {mod}")
    print(f"\nTotal: {len(on_curseforge)} mods\n")
    
    print("✅ ON APPROVED NON-CF LIST (can bundle in overrides)")
    print("-" * 50)
    for mod, license_info in sorted(on_approved_list):
        lic = f" [{license_info}]" if license_info else ""
        print(f"  • {mod}{lic}")
    print(f"\nTotal: {len(on_approved_list)} mods\n")
    
    print("📋 LIKELY ON CURSEFORGE (verify and run detect again)")
    print("-" * 50)
    for mod in sorted(likely_curseforge):
        print(f"  • {mod}")
    print(f"\nTotal: {len(likely_curseforge)} mods\n")
    
    if needs_verification:
        print("⚠️  NEEDS VERIFICATION (check CF + approved list)")
        print("-" * 50)
        for mod in sorted(needs_verification):
            print(f"  • {mod}")
        print(f"\nTotal: {len(needs_verification)} mods\n")
    
    if potential_blockers:
        print("❌ POTENTIAL BLOCKERS (may need alternatives)")
        print("-" * 50)
        for mod in sorted(potential_blockers):
            print(f"  • {mod}")
        print(f"\nTotal: {len(potential_blockers)} mods\n")
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = len(pw_toml_files)
    ready = len(on_curseforge) + len(on_approved_list)
    print(f"Ready for CurseForge:  {ready}/{total} ({ready*100//total}%)")
    print(f"Need verification:     {len(likely_curseforge) + len(needs_verification)}")
    print(f"Potential blockers:    {len(potential_blockers)}")
    print()
    
    print("NEXT STEPS:")
    print("-" * 50)
    print("1. Run: packwiz curseforge detect")
    print("2. Verify mods in 'LIKELY ON CURSEFORGE' category")
    print("3. Check 'NEEDS VERIFICATION' against:")
    print("   https://docs.google.com/spreadsheets/d/176Wv-PZUo0hFxy6oC6N8tWdquBLPRtSuLbNK-r0_byM")
    print("4. For blockers, check license and submit approval request or find alternative")
    print("5. Export: packwiz curseforge export -o MCC-curseforge.zip")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mcc_path = Path(sys.argv[1])
    else:
        mcc_path = Path(".")
        
    if not (mcc_path / "pack.toml").exists():
        print("Error: pack.toml not found. Run from your MCC directory or specify path.")
        print("Usage: python check_cf_compatibility.py [path_to_mcc_folder]")
        sys.exit(1)
        
    analyze_modpack(mcc_path)
