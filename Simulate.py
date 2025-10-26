import sys
import shutil
import subprocess
import re
from pathlib import Path
from math import pi
import itertools
import xml.etree.ElementTree as ET
import glob
import time

GENCASE_EXE     = r"C:\Users\chakraag\Downloads\DualSPHysics_v5.4.3\DualSPHysics_v5.4\bin\windows\GenCase_win64.exe"
DUAL_CPU_EXE    = r"C:\Users\chakraag\Downloads\DualSPHysics_v5.4.3\DualSPHysics_v5.4\bin\windows\DualSPHysics5.4CPU_win64.exe"
DUAL_GPU_EXE    = r"C:\Users\chakraag\Downloads\DualSPHysics_v5.4.3\DualSPHysics_v5.4\bin\windows\DualSPHysics5.4GPU_win64.exe"
PARTVTK_EXE     = r"C:\Users\chakraag\Downloads\DualSPHysics_v5.4.3\DualSPHysics_v5.4\bin\windows\PartVTK_win64.exe"
def stream_run(cmd, cwd=None):
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.stdout.close()
    return proc.wait()

def parse_list_or_single(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if raw == "":
        raw = str(default)
    vals = [v.strip() for v in raw.split(",") if v.strip() != ""]
    out = []
    for v in vals:
        v = v.replace(",", ".")
        out.append(float(v))
    return out

def get_choice(prompt, default, choices=("degrees", "radians")):
    s = (input(f"{prompt} [{default}]: ").strip().lower() or default).lower()
    return s if s in choices else default

def load_xml_with_sanitize(xml_path: Path):
    try:
        tree = ET.parse(xml_path)
        return tree, False, None
    except ET.ParseError:
        raw = xml_path.read_text(encoding="utf-8-sig", errors="ignore")
        first_lt = raw.find("<")
        cleaned = raw[first_lt:] if first_lt > 0 else raw.lstrip("\ufeff")
        root = ET.fromstring(cleaned)
        preclean_bak = xml_path.with_suffix(xml_path.suffix + ".preclean.bak")
        shutil.copy2(xml_path, preclean_bak)
        xml_path.write_text(cleaned, encoding="utf-8", newline="\n")
        return ET.ElementTree(root), True, preclean_bak

def write_tree_with_backup(tree: ET.ElementTree, xml_path: Path):
    backup = xml_path.with_suffix(xml_path.suffix + ".bak")
    if xml_path.exists():
        shutil.copy2(xml_path, backup)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return backup

def clone_tree(tree: ET.ElementTree) -> ET.ElementTree:
    return ET.ElementTree(ET.fromstring(ET.tostring(tree.getroot())))

def safe_val_tag(prefix: str, val: float, unit_suffix=""):
    if val < 0:
        core = f"neg{abs(val):g}".replace(".", "p")
    else:
        core = f"{val:g}".replace(".", "p")
    return f"{prefix}-{core}{unit_suffix}"

def ensure_case_assets_without_xml(case_dir: Path, variant_dir: Path):
    data_src = case_dir / "data"
    if data_src.exists() and data_src.is_dir():
        shutil.copytree(data_src, variant_dir / "data", dirs_exist_ok=True)
    return True

def preserve_critical_xml_sections(target_tree: ET.ElementTree, source_tree: ET.ElementTree):
    target_root = target_tree.getroot()
    source_root = source_tree.getroot()
    target_exec = target_root.find(".//execution")
    if target_exec is None:
        target_exec = ET.SubElement(target_root, "execution")
    target_constants = target_exec.find("./constants")
    source_constants = source_root.find(".//execution/constants")
    if source_constants is None:
        source_constantsdef = source_root.find(".//casedef/constantsdef")
        if source_constantsdef is not None:
            print("  ! Found <constantsdef> in source, converting to <constants> format")
            if target_constants is None:
                target_constants = ET.SubElement(target_exec, "constants")
            for child in source_constantsdef:
                if child.tag != "dp":  
                    new_child = ET.fromstring(ET.tostring(child))
                    target_constants.append(new_child)
        else:
            if target_constants is None:
                _ensure_constants_block(target_root)
                print("  ! Created empty <constants> section (none in original)")
    elif target_constants is None and source_constants is not None:
        
        new_constants = ET.fromstring(ET.tostring(source_constants))
        target_exec.append(new_constants)
        print("  ! Copied <constants> section from original XML")
    if target_exec.find("./special") is None:
        source_special = source_root.find(".//execution/special")
        if source_special is not None:
            new_special = ET.fromstring(ET.tostring(source_special))
            target_exec.append(new_special)
            print("  ! Copied <special> section from original XML")
        else:
            special = ET.SubElement(target_exec, "special")
            print("  ! Created minimal <special> section")
    if target_exec.find("./particles") is None:
        source_particles = source_root.find(".//execution/particles")
        if source_particles is not None:
            new_particles = ET.fromstring(ET.tostring(source_particles))
            target_exec.append(new_particles)
            print("  ! Copied <particles> section from original XML")

def _ensure_params_block(root):
    exec_node = root.find(".//execution")
    if exec_node is None:
        exec_node = ET.SubElement(root, "execution")
    params = exec_node.find("./parameters")
    if params is None:
        params = ET.SubElement(exec_node, "parameters")
    return params

def _ensure_constants_block(root):
    exec_node = root.find(".//execution")
    if exec_node is None:
        exec_node = ET.SubElement(root, "execution")
    constants = exec_node.find("./constants")
    if constants is None:
        constants = ET.SubElement(exec_node, "constants")
        print("  ! Creating missing <constants> section with defaults")
    return constants

def update_dp(tree: ET.ElementTree, dp: float):
    root = tree.getroot()
    params = _ensure_params_block(root)
    constants = _ensure_constants_block(root)  
    updated = False
    changes_log = []
    def ensure_param(key, value):
        nonlocal updated
        node = None
        for p in params.findall("./parameter"):
            if p.attrib.get("key", "").lower() == key.lower():
                node = p
                break
        if node is None:
            node = ET.SubElement(params, "parameter")
            node.set("key", key)
            node.set("value", f"{value:g}")
            node.set("comment", f"Custom value from batch script")
            updated = True
            changes_log.append(f"  + Created parameter {key}={value:g}")
            return node        
        new_val = f"{value:g}"
        old_val = node.attrib.get("value")
        if old_val != new_val:
            node.set("value", new_val)
            node.set("comment", f"Updated from batch script (was {old_val})")
            updated = True
            changes_log.append(f"  * Updated parameter {key}: {old_val} -> {new_val}")
        return node
    ensure_param("VResId", -1)
    ensure_param("Dp", dp)
    ensure_param("DP", dp)  
    for node in root.findall(".//geometry/definition"):
        old_dp = node.attrib.get("dp")
        new_dp = f"{dp:g}"
        if old_dp != new_dp:
            node.set("dp", new_dp)
            node.set("comment", f"Custom dp from batch (was {old_dp})")
            updated = True
            changes_log.append(f"  * Updated geometry/definition dp: {old_dp} -> {new_dp}")
    geom_def = root.find(".//geometry/definition")
    if geom_def is not None:
        dp_node = geom_def.find("./lattice_dp")
        if dp_node is None:
            dp_node = geom_def.find("./dp")
        if dp_node is None:
            dp_node = ET.SubElement(geom_def, "dp")
        old_val = dp_node.attrib.get("v", dp_node.text or "")
        new_val = f"{dp:g}"
        if old_val != new_val:
            dp_node.set("v", new_val)
            dp_node.text = new_val
            updated = True
            changes_log.append(f"  * Updated geometry/definition/dp: {old_val} -> {new_val}")
    constants = root.find(".//constants")
    if constants is not None:
        dp_const = constants.find("./dp")
        if dp_const is None:
            dp_const = ET.SubElement(constants, "dp")
        old_val = dp_const.attrib.get("v", dp_const.text or "")
        new_val = f"{dp:g}"
        if old_val != new_val:
            dp_const.set("v", new_val)
            dp_const.text = new_val
            updated = True
            changes_log.append(f"  * Updated constants/dp: {old_val} -> {new_val}")    
    for xp in [".//dp", ".//kernel//dp", ".//*[@name='dp']", ".//*[@Name='dp']"]:
        for n in root.findall(xp):
            parent = n
            in_params = False
            for _ in range(5):  
                parent = list(root.iter())  
                if parent and any(p.tag == "parameters" for p in root.iter() if n in list(p.iter())):
                    in_params = True
                    break
            if in_params:
                continue
                
            if "v" in n.attrib:
                old_val = n.attrib.get("v")
                new_val = f"{dp:g}"
                if old_val != new_val:
                    n.set("v", new_val)
                    updated = True
                    changes_log.append(f"  * Updated {xp} v attribute: {old_val} -> {new_val}")
            elif not list(n):  
                old_val = (n.text or "").strip()
                new_val = f"{dp:g}"
                if old_val != new_val:
                    n.text = new_val
                    updated = True
                    changes_log.append(f"  * Updated {xp} text: {old_val} -> {new_val}")
    if changes_log:
        print(f"\n  Dp update changes made:")
        for log_line in changes_log:
            print(log_line)
    else:
        print(f"\n  WARNING: No Dp changes were needed - XML might already have dp={dp:g}")
        print(f"           or the XML structure doesn't match expected patterns!")

    return updated

def update_time_max(tree: ET.ElementTree, t_end: float):
    root = tree.getroot()
    params = _ensure_params_block(root)

    node = None
    for p in params.findall("./parameter"):
        if p.attrib.get("key", "").lower() == "timemax":
            node = p
            break
    if node is None:
        node = ET.SubElement(params, "parameter")
        node.set("key", "TimeMax")
    
    old_val = node.attrib.get("value")
    node.set("value", f"{t_end:g}")
    node.set("comment", f"Set by batch script (was {old_val})")
    print(f"  * Updated TimeMax: {old_val} -> {t_end:g}")
    return True

def update_mvrotsinu(tree: ET.ElementTree, freq_hz: float, ampl_val: float, unit: str, duration: float):
    root = tree.getroot()
    nodes = root.findall(".//mvrotsinu")
    if not nodes:
        return 0
    updated = 0
    for mv in nodes:
        mv.set("anglesunits", unit)
        if duration is not None and duration >= 0:
            mv.set("duration", f"{duration:g}")
        for child in list(mv):
            if child.tag in ("freq", "ampl"):
                mv.remove(child)
        f = ET.SubElement(mv, "freq")
        a = ET.SubElement(mv, "ampl")
        f.set("v", f"{freq_hz:g}")
        a.set("v", f"{ampl_val:g}")
        f.set("units_comment", "1/s")
        a.set("units_comment", unit)
        updated += 1
    print(f"  * Updated {updated} mvrotsinu block(s): freq={freq_hz:g} Hz, ampl={ampl_val:g} {unit}")
    return updated

def run_gencase(case_dir: Path, base: str, dp: float = None):
    exe = Path(GENCASE_EXE)
    if not exe.exists():
        print(f"ERROR: GenCase not found at: {exe}")
        return False
    
    cmd = [str(exe), base, "-save:all"]
    
    if dp is not None:
        cmd.extend(["-dp", f"{dp:g}"])
        print(f"  >> Forcing dp={dp:g} via command line argument")
    
    print("\n> Running GenCase (streaming):\n", " ".join([f'"{c}"' if " " in c else c for c in cmd]))
    rc = stream_run(cmd, cwd=case_dir)
    print("\nGenCase return code:", rc)
    if rc == 0:
        verify_gencase_output(case_dir, base, dp)
    
    return rc == 0
def verify_gencase_output(case_dir: Path, base: str, expected_dp: float):
    """
    Verify that GenCase actually used the dp we specified.
    Checks Run.out log for actual dp used.
    """
    print("\n  === POST-GENCASE VERIFICATION ===")
    log_candidates = [
        case_dir / "Run.out",
        case_dir / f"{base}_Run.out",
        case_dir / "log.out"
    ]    
    log_file = None
    for candidate in log_candidates:
        if candidate.exists():
            log_file = candidate
            break   
    if log_file and log_file.exists():
        log_text = log_file.read_text(errors='ignore')
        dp_patterns = [
            r'Dp:\s*([0-9.eE+-]+)',
            r'dp=([0-9.eE+-]+)',
            r'Distance between particles:\s*([0-9.eE+-]+)',
            r'Particle spacing:\s*([0-9.eE+-]+)'
        ]
        
        found_dp = None
        for pattern in dp_patterns:
            match = re.search(pattern, log_text, re.IGNORECASE)
            if match:
                found_dp = float(match.group(1))
                break        
        if found_dp:
            print(f"  GenCase log shows dp = {found_dp:g}")
            if abs(found_dp - expected_dp) < 1e-10:
                print(f"  ✓ VERIFIED: dp matches expected value ({expected_dp:g})")
            else:
                print(f"  ✗ WARNING: dp MISMATCH! Expected {expected_dp:g}, got {found_dp:g}")
                print(f"  This means GenCase ignored your dp setting!")
        else:
            print(f"  Could not find dp value in {log_file.name}")
    else:
        print(f"  No GenCase log found in {case_dir}")  
    bi4_files = list(case_dir.glob("*.bi4"))
    xml_files = list(case_dir.glob(f"{base}_Actual.xml"))
    
    print(f"  Generated BI4 files: {len(bi4_files)}")
    if xml_files:
        print(f"  Found {base}_Actual.xml (GenCase output)")
    
    print("  =================================\n")

def run_dual(case_dir: Path, case_base: str, mode: str = "cpu") -> Path:
    out_dir = case_dir / "out"
    out_dir.mkdir(exist_ok=True)
    logs_dir = case_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    dual_log = logs_dir / "dualsphysics.log"
    mode = mode.lower().strip()
    dual_exe = Path(DUAL_GPU_EXE if mode.startswith("g") else DUAL_CPU_EXE)
    if not dual_exe.exists():
        print(f"WARNING: DualSPHysics exe not found at {dual_exe}. Skipping solver.")
        return out_dir
    gencase_xml_candidates = sorted(case_dir.glob("*.xml"), key=lambda p: p.stat().st_mtime, reverse=True)
    gencase_output_xml = None
    for xml_file in gencase_xml_candidates:
        if xml_file.stem not in [f"{case_base}_Def", case_base, f"{case_base}_Actual"]:
            gencase_output_xml = xml_file
            print(f"  >> Using GenCase output XML: {xml_file.name}")
            break  
    if gencase_output_xml is None:
        print(f"  !! WARNING: Could not find GenCase output XML (e.g., '0.01.xml')")
        print(f"     Available XML files: {[x.name for x in case_dir.glob('*.xml')]}")
        print(f"     Trying to use {case_base}.xml anyway...")
        gencase_output_xml = case_dir / f"{case_base}.xml"
    dual_case_name = gencase_output_xml.stem
    cmd = [
        str(dual_exe),
        dual_case_name,              
        str(case_dir),               
        "-sv:binx,vtk",
        "-svdomainvtk:1",
        "-svnormals:1",
        "-svres",
        "-dirout", str(out_dir)
    ]
    print("\n> Running DualSPHysics (VTK on):\n", " ".join([f'"{c}"' if " " in c else c for c in cmd]))
    with dual_log.open("w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(case_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lf.write(line)
        proc.stdout.close()
        rc = proc.wait()
        lf.write(f"\n[Return code: {rc}]\n")

    print(f"\nDualSPHysics return code: {rc}")
    if rc != 0:
        print(f"!! Solver failed for {case_dir.name}. Check {dual_log} for details.")
    return out_dir
def ensure_vtk_with_partvtk(out_dir: Path, case_base: str):
    """
    If the solver produced BINX but no VTK, run PartVTK to convert BINX->VTK.
    """
    vtks = glob.glob(str(out_dir / "*.vtk"))
    if vtks:
        print(f"VTK check: found {len(vtks)} file(s).")
        return
    binx = sorted(glob.glob(str(out_dir / "*.binx")))
    if not binx:
        print("No VTKs and no BINX found to convert. Skipping PartVTK.")
        return
    exe = Path(PARTVTK_EXE)
    if not exe.exists():
        print(f"PartVTK not found at {exe}. Cannot convert BINX->VTK.")
        return
    cmd = [str(exe), str(out_dir), case_base, str(out_dir), "-savevtk"]
    print("\n> Converting BINX->VTK with PartVTK (streaming):\n", " ".join([f'"{c}"' if " " in c else c for c in cmd]))
    rc = stream_run(cmd, cwd=out_dir)
    print("\nPartVTK return code:", rc)
    after_vtks = glob.glob(str(out_dir / "*.vtk"))
    print(f"PartVTK VTK files: {len(after_vtks)}")
def main():
    print("=== SPH batch runner ===")
    print("Changes:")
    print("  - Enhanced XML dp injection at multiple locations")
    print("  - Explicit -dp flag passed to GenCase command line")
    print("  - Post-GenCase verification of actual dp used")
    print("=" * 60)
    xml_path_in = input("\nPath to *_Def.xml (e.g., C:\\Users\\you\\Autoslosh_Def.xml): ").strip('" ').strip()
    if not xml_path_in:
        print("No XML path provided.")
        sys.exit(1)
    xml_path = Path(xml_path_in)
    if not xml_path.exists():
        print(f"XML not found: {xml_path}")
        sys.exit(1)    
    try:
        tree_orig, cleaned, preclean_bak = load_xml_with_sanitize(xml_path)
        if cleaned:
            print(f"Note: XML had leading junk; cleaned and saved. Backup at: {preclean_bak}")                
        root_check = tree_orig.getroot()
        constants_check = root_check.find(".//execution/constants")
        if constants_check is None:
            print("\n⚠ WARNING: Your original XML is missing <execution><constants> section!")
            print("  This will cause DualSPHysics to fail.")
            print("  The script will attempt to create a minimal constants section.")
            print("  You may need to add proper constants manually to your original XML.")
            response = input("\n  Continue anyway? (yes/no) [no]: ").strip().lower()
            if not response.startswith('y'):
                print("Aborting.")
                sys.exit(0)        
    except ET.ParseError as e:
        print("ERROR: Cannot parse XML even after sanitize attempt:", e)
        sys.exit(2)  
    print("\n--- Parameter Sweep Configuration ---")
    dp_list = parse_list_or_single("Dp (m) list (comma-separated)", 0.01)
    t_list  = parse_list_or_single("Simulation duration TimeMax (s) list (-1 keeps case default)", -1)
    unit    = get_choice("Amplitude units (degrees/radians)", "degrees")

    freq_list  = parse_list_or_single("Frequency (Hz) list (leave blank to use ω)", "")
    if len(freq_list) == 1 and freq_list[0] == 0.0:
        freq_list = []
    omega_list = parse_list_or_single("Angular velocity ω (rad/s) list (leave blank to use f)", "")
    if len(omega_list) == 1 and omega_list[0] == 0.0:
        omega_list = []
    ampl_list  = parse_list_or_single(f"Amplitude values list ({unit})", 8.0)
    if omega_list and not freq_list:
        freq_list = [w/(2*pi) for w in omega_list]
    if not freq_list:
        freq_list = [0.5]  
    combos = list(itertools.product(dp_list, t_list, freq_list, ampl_list))
    print(f"\nPlanned runs: {len(combos)} combination(s).")
    print(f"Total variants to generate: {len(combos)}")
    base = xml_path.stem
    case_dir = xml_path.parent
    if base.endswith("_Def"):
        base = base[:-4]
    print(f"Base case name: {base}")
    print(f"Case directory: {case_dir}")
    run_solver = (input("\nRun DualSPHysics automatically for each variant? (yes/no) [yes]: ").strip().lower() or "yes").startswith("y")
    mode       = (input("Run mode: cpu/gpu [cpu]: ").strip().lower() or "cpu")
    print("\n" + "="*60)
    print("Starting batch generation...")
    print("="*60 + "\n")
    completed, total = 0, 0.0
    for (dp, t_end, f_in, ampl_val) in combos:
        start_t = time.time()
        tag_dp = safe_val_tag("dp", dp)
        tag_t  = safe_val_tag("t", t_end)
        tag_f  = safe_val_tag("f", f_in)
        tag_a  = safe_val_tag("a", ampl_val, "deg" if unit == "degrees" else "rad")
        variant_name = "__".join([tag_dp, tag_t, tag_f, tag_a])
        variant_dir = case_dir / f"{base}__{variant_name}"
        variant_dir.mkdir(exist_ok=True)
        print(f"\n{'='*60}")
        print(f"Processing: {variant_name}")
        print(f"{'='*60}")
        xml_variant_def = variant_dir / f"{base}_Def.xml"
        clone = clone_tree(tree_orig)
        clone.write(xml_variant_def, encoding="utf-8", xml_declaration=True)
        ensure_case_assets_without_xml(case_dir, variant_dir)
        upd_tree, _, _ = load_xml_with_sanitize(xml_variant_def)
        preserve_critical_xml_sections(upd_tree, tree_orig)
        print(f"\nApplying parameter updates for {variant_name}:")
        dp_set = update_dp(upd_tree, dp)
        if t_end >= 0:
            update_time_max(upd_tree, t_end)
        else:
            print(f"  * Keeping default TimeMax (user specified {t_end})")
            
        mvupd = update_mvrotsinu(
            upd_tree,
            freq_hz   = f_in,
            ampl_val  = ampl_val,
            unit      = unit,
            duration  = t_end if t_end >= 0 else -1
        )
        backup = write_tree_with_backup(upd_tree, xml_variant_def)
        print(f"  Saved {xml_variant_def.name} (backup: {backup.name})")
        xml_for_gencase = variant_dir / f"{base}.xml"
        upd_tree.write(xml_for_gencase, encoding="utf-8", xml_declaration=True)
        print(f"  Saved {xml_for_gencase.name} (for GenCase)")
        rt_check = upd_tree.getroot()
        constants_check = rt_check.find(".//execution/constants")
        if constants_check is None:
            print("  ⚠ WARNING: <execution><constants> section is MISSING!")
            print("             DualSPHysics will fail. Check your original XML.")
        else:
            print(f"  ✓ Constants section exists with {len(list(constants_check))} child elements")
        rt = upd_tree.getroot()

        def _first(root, xps, attr=None):
            for xp in xps:
                node = root.find(xp)
                if node is None:
                    continue
                if attr:
                    if attr in node.attrib:
                        return node.attrib[attr]
                else:
                    if "v" in node.attrib:
                        return node.attrib["v"]
                    val = (node.text or "").strip()
                    if val:
                        return val
            return None
        dp_echo = None
        gdef = rt.find(".//geometry/definition")
        if gdef is not None:
            dp_echo = gdef.attrib.get("dp")
        if dp_echo is None:
            p_dp = rt.find(".//execution/parameters/parameter[@key='Dp']") \
                or rt.find(".//execution/parameters/parameter[@key='dp']")
            if p_dp is not None:
                dp_echo = p_dp.attrib.get("value")
        tmax_echo = None
        tm_node = rt.find(".//execution/parameters/parameter[@key='TimeMax']") \
            or rt.find(".//execution/parameters/parameter[@key='timemax']")
        if tm_node is not None:
            tmax_echo = tm_node.attrib.get("value")
        if tmax_echo is None:
            tmax_echo = _first(rt, [".//tmax", ".//time//tmax", ".//simulation//tmax"])
        vres_echo = None
        vres_node = rt.find(".//execution/parameters/parameter[@key='VResId']") \
            or rt.find(".//execution/parameters/parameter[@key='vresid']")
        if vres_node is not None:
            vres_echo = vres_node.attrib.get("value")
        mv_node   = rt.find(".//mvrotsinu")
        unit_echo = mv_node.attrib.get("anglesunits") if mv_node is not None else None
        freq_echo = _first(rt, [".//mvrotsinu/freq"])
        ampl_echo = _first(rt, [".//mvrotsinu/ampl"])
        print(f"\n  XML Verification:")
        print(f"    Dp: {dp_echo}")
        print(f"    TimeMax: {tmax_echo}")
        print(f"    VResId: {vres_echo}")
        print(f"    Motion unit: {unit_echo}")
        print(f"    Frequency: {freq_echo} Hz")
        print(f"    Amplitude: {ampl_echo} {unit_echo}")
        ok = run_gencase(variant_dir, base, dp=dp)
        if not ok:
            print(f"\n[{variant_name}] GenCase FAILED, skipping solver for this combo.")
            elapsed = time.time() - start_t
            completed += 1
            total += elapsed
            avg = total / completed
            remaining = len(combos) - completed
            print(f"[{variant_name}] Elapsed {elapsed:.1f}s • Done {completed}/{len(combos)} • Avg ~{avg:.1f}s • Remaining ~{avg*remaining:.1f}s")
            continue
        if run_solver:
            out_folder = run_dual(variant_dir, base, mode=mode)
            ensure_vtk_with_partvtk(out_folder, base)
        elapsed = time.time() - start_t
        completed += 1
        total += elapsed
        avg = total / completed
        remaining = len(combos) - completed
        print(f"\n[{variant_name}] ✓ COMPLETE")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Progress: {completed}/{len(combos)}")
        print(f"  Average time per variant: {avg:.1f}s")
        print(f"  Estimated remaining: {avg*remaining:.1f}s")
    print("\n" + "="*60)
    print("ALL VARIANTS COMPLETE!")
    print("="*60)
    print(f"Total variants processed: {completed}")
    print(f"Total time: {total:.1f}s ({total/60:.1f} minutes)")
    print(f"Average per variant: {total/completed:.1f}s")
    print("\nNext steps:")
    print("  1. Check the logs/ folder in each variant for solver output")
    print("  2. Open ParaView and load the .vtk files from out/ folders")
    print("  3. Compare particle spacing visually between different dp values")
    print("  4. If dp still doesn't change, check Run.out files for warnings")
if __name__ == "__main__":
    main()