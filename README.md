# DualSPHysics Batch Automation – README

This project provides a Python-based batch runner that automates the setup, execution, and post-processing of sloshing tank simulations in DualSPHysics. The workflow is designed to generate multiple simulation variants (different particle resolutions, excitation motions, and simulation durations) without having to manually edit XML case files or rerun the solver one case at a time.

The script takes a base sloshing case definition (your `*_Def.xml`, for example `Autoslosh_Def.xml`) and builds a full parameter sweep. For each combination of parameters, it (1) generates a clean, isolated case folder, (2) injects the requested simulation settings into the XML, (3) runs GenCase, (4) runs DualSPHysics, and (5) stores all outputs (including VTK snapshots for ParaView) and logs per variant. This enables controlled studies such as mesh resolution sensitivity (changing `dp`) or motion sensitivity (changing amplitude/frequency) without manual, error-prone editing.

## What problem this solves

Normally, to test more than one configuration in DualSPHysics you would:
1. Edit the XML by hand to change `dp` (particle spacing / resolution).
2. Change `TimeMax` to adjust how long the simulation runs.
3. Update the sinusoidal rotation motion block (`<mvrotsinu>`) to change amplitude, units, and frequency.
4. Run GenCase by hand.
5. Run DualSPHysics by hand.
6. Rename/move outputs so they don’t overwrite each other.
7. Repeat for each scenario.

Doing this for many combinations is slow and easy to mess up. The script automates that entire loop and guarantees each run is isolated and labeled.

## High-level workflow

For each requested parameter combination, the script:

1. **Creates a variant folder** named with the parameters, for example:  
   `Autoslosh__dp-0p01__t-3__f-0p5__a-8deg`  
   The folder name encodes:  
   - `dp` = particle spacing  
   - `t` = `TimeMax` (simulation duration)  
   - `f` = excitation frequency in Hz  
   - `a` = oscillation amplitude (deg or rad)

   Decimal points become `p` and negatives become `neg...` so folder names are filesystem-safe.

2. **Copies the base case** into that folder:  
   - It writes a fresh copy of your `*_Def.xml` (e.g. `Autoslosh_Def.xml`).  
   - It copies supporting assets like the `data/` directory (geometry, STL, etc.).  
   - It does **not** blindly copy the original `Autoslosh.xml` from the source folder, because that caused GenCase to ignore edits. Instead, after modification, it generates a new `Autoslosh.xml` for that variant so GenCase sees the updated parameters.

3. **Edits the XML automatically** to match the chosen parameters:

   - **Particle spacing (`dp`):**  
     The script forces custom particle resolution by:  
     - Setting `VResId = -1` in `<execution><parameters>` (tells DualSPHysics to use a user-defined spacing instead of a preset).  
     - Writing both `Dp` and `DP` parameters to the requested value.  
     - Updating `<geometry><definition dp="...">`.  
     - Updating any `<constants><dp v="...">` or stray `<dp>` nodes that the template may still be using.  
     This overrides built-in preset resolution so GenCase actually regenerates particles at your requested `dp`.

   - **Simulation duration (`TimeMax`):**  
     If you supply a non-negative value for `TimeMax`, the script ensures  
     `<parameter key="TimeMax" value="...">` exists in `<execution><parameters>`.  
     This makes DualSPHysics run for exactly that amount of simulated time.  
     You can also enter `-1` to keep the original duration from the template.

   - **Sloshing motion (`mvrotsinu`):**  
     The script rewrites the `<mvrotsinu>` block(s) so that each run can have its own excitation:
     - `anglesunits="degrees"` or `anglesunits="radians"`, depending on what you choose.
     - `duration="..."` is set to the simulation duration if it’s non-negative.
     - It removes any old `<freq>` / `<ampl>` children and inserts fresh ones:
       - `<freq v="...">` with units of 1/s.
       - `<ampl v="...">` in either degrees or radians.
     You can either enter frequency directly in Hz, or provide an angular velocity ω in rad/s. If you provide ω and leave frequency blank, the script converts ω to frequency internally using `f = ω / (2π)`.

   - **Critical execution sections:**  
     The script ensures that sections like `<execution><constants>`, `<execution><special>`, and `<execution><particles>` exist in the generated XML. These sometimes differ depending on how the base XML was exported. Missing them can make DualSPHysics exit immediately, so the script patches them in if required.

   After editing, the script writes:
   - The updated `_Def.xml` back into the variant folder (keeping a `.bak` backup for traceability).
   - A synchronized `<base>.xml` (e.g. `Autoslosh.xml`) in the same folder.  
     This step is critical: GenCase actually reads `<base>.xml`, not `_Def.xml`, so without this step all variants would have ended up identical.

4. **Runs GenCase for that variant.**  
   The script calls GenCase inside the variant folder. It passes `-save:all` and also forces `-dp <value>` on the command line. This guarantees that the requested particle spacing is honored, even if the original case tried to impose a preset.  
   After GenCase runs, the script can check the console output (e.g. `Distance between points (Dp): ...`) to confirm that the generated particle spacing matches what you asked for.

   GenCase generates:
   - The `.bi4` particle file.  
   - Initial geometry/particle VTKs (`*_Bound.vtk`, `*_Fluid.vtk`, etc.).  
   - The solver-ready XML that DualSPHysics will advance in time.

5. **Runs DualSPHysics (optional, per user input).**  
   If you choose to run the solver:
   - The script creates an `out/` directory inside the variant to hold results.
   - It also creates `logs/dualsphysics.log` and “tees” solver output there while also printing it live to the terminal.  
     This solves the “silent crash” problem: if a run produces no VTKs because the solver instantly quit (bad `dp`, invalid motion duration, missing constants), you just open `logs/dualsphysics.log` to see why.
   - The solver is launched with `-sv:binx,vtk -svdomainvtk:1 -svnormals:1 -svres`, so `.vtk` snapshots are written directly into `out/`. Those can be inspected in ParaView immediately.

   The script also tries to detect the actual case name DualSPHysics expects (because GenCase sometimes outputs or expects a slightly different base name). That avoids the classic `Case configuration was not found` error.

6. **VTK fallback with PartVTK.**  
   After DualSPHysics finishes, the script checks the `out/` folder.  
   - If `.vtk` exists, you’re done.  
   - If only `.binx` exists, the script runs PartVTK automatically to convert BINX → VTK.  
   - If neither exists, the solver failed very early and you can read `logs/dualsphysics.log` in that variant to see the exact reason.

7. **Progress/timing info.**  
   After each variant finishes, the script prints:
   - How long that variant took.
   - How many variants are completed.
   - The average runtime per variant and a rough “remaining” estimate.
   
   This gives you a sanity check on how long a batch will take.

## Inputs and parameter sweep

When you run the script, you will be prompted for:

- **Base case XML**  
  Path to the base `*_Def.xml` (e.g. `D:\...\Autoslosh_Def.xml`).

- **dp list**  
  Comma-separated particle spacing values, e.g.  
  `0.01, 0.02, 0.05`  
  Smaller `dp` = more particles = higher resolution and higher cost.

- **TimeMax list**  
  Comma-separated total simulation durations in seconds, e.g.  
  `2, 3, 5`  
  Use `-1` to keep the original duration from the template.

- **Amplitude units**  
  `degrees` or `radians`.  
  The script does *not* silently convert amplitude units for you. Whatever you say here is what gets written into `<mvrotsinu>` (and into the folder name as `a-...deg` or `a-...rad`).

- **Excitation frequency / angular velocity**  
  You can provide:
  - A list of frequencies `f` in Hz, OR
  - A list of angular velocities `ω` in rad/s.  
    If you provide `ω` but not `f`, the script converts ω → f using `f = ω / (2π)`.

- **Amplitude list**  
  Rotation amplitudes in the chosen units, e.g. `6, 8, 10`.

All lists are combined using a Cartesian product.  
Example:
- `dp = [0.01, 0.05]`
- `TimeMax = [2]`
- `f = [0.5]`
- `amplitude(deg) = [8]`

This will generate two variant folders:
- `...dp-0p01__t-2__f-0p5__a-8deg`
- `...dp-0p05__t-2__f-0p5__a-8deg`

Each one will get its own XML, logs, and `out/` data.

## Outputs per variant

Each generated variant directory looks like:
`Autoslosh__dp-0p01__t-3__f-0p5__a-8deg/`

Inside you’ll find:
- `Autoslosh_Def.xml` – the edited case definition for this variant.
- `Autoslosh_Def.xml.bak` – backup of the pre-edit state for traceability.
- `Autoslosh.xml` – the synchronized version that GenCase actually reads.
- `data/` – copied reference data from the base case.
- `out/` – DualSPHysics time snapshots (`.vtk` and/or `.binx`).
- `logs/dualsphysics.log` – full solver output, including crash reasons if any.

This structure guarantees:
- You can drag `out/*.vtk` directly into ParaView to visualize each run.
- You can diff the XMLs between two variant folders to see exactly what changed.
- You can diagnose solver failures after the fact just by checking the log.

## Key technical safeguards

- **Custom `dp` is actually enforced.**  
  DualSPHysics templates sometimes keep an internal preset resolution that overrides whatever `dp` you think you set. The script:  
  - Forces `VResId = -1` ("custom") in `<execution><parameters>`.  
  - Writes `Dp`/`DP` with your requested value.  
  - Writes the same `dp` into `<geometry><definition dp="...">` and other known `dp` locations.  
  - Calls GenCase with `-dp <value>` explicitly.  
  Together this makes GenCase *really* generate a new particle layout for each requested `dp`.

- **`TimeMax` and motion stay consistent.**  
  The script keeps the global simulation duration and the sinusoidal motion (`mvrotsinu`) aligned. That prevents situations where you define a 10-second oscillation but only simulate 2 seconds, or where a missing/negative duration crashes the solver.

- **Missing critical XML blocks are patched.**  
  Some exported cases keep `<constants>`, `<special>`, or particle definitions in slightly different subtrees, or omit them. The script re-injects these under `<execution>` if needed, so DualSPHysics doesn’t crash at startup.

- **Per-run logging.**  
  Solver output for each run is saved into `logs/dualsphysics.log`.  
  If a run’s `out/` folder is empty (no `.vtk`, no `.binx`), you just read that log to see the exact error (for example: `dp` too coarse → not enough particles to initialize the fluid domain, or invalid motion settings).

## Typical usage example (resolution study)

1. Run the script.  
2. When prompted:
   - `dp list`: `0.01, 0.05`  
   - `TimeMax list`: `2`  
   - amplitude units: `degrees`  
   - frequency (Hz): `0.5`  
   - amplitude list (deg): `8`  
   - run solver: `yes`  
   - mode: `cpu`
3. The script will generate:
   - `...dp-0p01__t-2__f-0p5__a-8deg`
   - `...dp-0p05__t-2__f-0p5__a-8deg`
4. Each folder will have:
   - An edited XML with the correct custom `dp`, `TimeMax`, and motion.  
   - A `logs/dualsphysics.log` file.  
   - An `out/` directory with `.vtk` snapshots for ParaView (or `.binx` that then gets converted to VTK automatically).

Now you can open both `out/*.vtk` sequences in ParaView and compare the splash height, interface sharpness, damping, etc. between coarse and fine resolutions.

## Summary

This script is an end-to-end parametric study tool for DualSPHysics sloshing simulations. It:
- Sweeps `dp`, run time, excitation frequency/ω, amplitude, and units.
- Automatically rewrites the XML for each variant so you don’t touch it by hand.
- Forces DualSPHysics / GenCase to actually respect your requested `dp` across runs (no silent reuse of the same mesh).
- Runs GenCase and DualSPHysics, captures solver logs, and writes VTK output into clean per-variant folders.
- Makes it straightforward to perform resolution studies, amplitude sweeps, frequency response studies, and duration studies — all reproducibly, without manual XML editing between runs.

Remember that the dp values be kept as low as possible, for bigger dp values , you would need to change the dimensions of the box in xml base definition file.
