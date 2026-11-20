"""
OpenFOAM v2512 Wind-Tunnel CFD Pipeline for 3D F1 Rear Wing (DRS Closed vs DRS Open).

Runs:
  1. Generate watertight 3D multi-element F1 Rear Wing STL (Mainplane + DRS Flap + Endplate)
  2. blockMesh (half-span virtual wind tunnel with y=0 symmetry plane)
  3. surfaceFeatureExtract + snappyHexMesh -overwrite (3D body-fitted hex mesh)
  4. potentialFoam initialization
  5. 4-core parallel simpleFoam (k-omega SST RANS @ 252 km/h = 70 m/s) with forceCoeffs
  6. reconstructPar -latestTime + foamToVTK -latestTime
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from generate_f1_wing_stl import generate_f1_wing_stl

OPENFOAM_BASHRC = "/usr/lib/openfoam/openfoam2512/etc/bashrc"
U_INF = 70.0        # 70 m/s = 252 km/h (Albert Park fast section / main straight)
RHO = 1.225         # Air density [kg/m^3]
NU = 1.5e-5         # Air kinematic viscosity [m^2/s]
A_REF_HALF = 0.25   # Half-wing reference area [m^2] (full span = 0.50 m^2)
L_REF = 0.50        # Reference chord [m]
N_PROCS = min(4, os.cpu_count() or 1)


def run_foam(case_dir: Path, cmd: str, timeout: int = 300) -> str:
    full_cmd = f"source '{OPENFOAM_BASHRC}' >/dev/null 2>&1 || true; {cmd}"
    proc = subprocess.run(
        ["bash", "-lc", full_cmd],
        cwd=str(case_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-50:])
        raise RuntimeError(f"Command failed ({cmd}):\n{tail}")
    return proc.stdout


def setup_case(case_dir: Path, drs_open: bool) -> dict:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for sub in ("0", "constant/triSurface", "system"):
        (case_dir / sub).mkdir(parents=True, exist_ok=True)

    stl_info = generate_f1_wing_stl(
        case_dir / "constant" / "triSurface" / "f1_wing.stl",
        drs_open=drs_open,
        half_wing=True,
    )

    # Estimate inlet turbulence for wind tunnel (TI = 1.5%, length scale = 0.05 m)
    ti = 0.015
    k_in = 1.5 * (U_INF * ti) ** 2
    omega_in = math.sqrt(k_in) / (0.09 ** 0.25 * 0.05)

    # system/blockMeshDict: x in [-2.0, 4.5], y in [0.0, 2.0], z in [-1.2, 1.8]
    (case_dir / "system" / "blockMeshDict").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}

scale 1;

vertices
(
    (-2.0 0.0 -1.2) // 0
    ( 4.5 0.0 -1.2) // 1
    ( 4.5 2.0 -1.2) // 2
    (-2.0 2.0 -1.2) // 3
    (-2.0 0.0  1.8) // 4
    ( 4.5 0.0  1.8) // 5
    ( 4.5 2.0  1.8) // 6
    (-2.0 2.0  1.8) // 7
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (44 14 20) simpleGrading (1 1 1)
);

edges ();

boundary
(
    inlet
    {
        type patch;
        faces ((0 4 7 3));
    }
    outlet
    {
        type patch;
        faces ((1 2 6 5));
    }
    symmetry
    {
        type symmetryPlane;
        faces ((0 1 5 4));
    }
    outerWall
    {
        type patch;
        faces
        (
            (3 7 6 2)
            (0 3 2 1)
            (4 5 6 7)
        );
    }
);

mergePatchPairs ();
""")

    # system/surfaceFeatureExtractDict
    (case_dir / "system" / "surfaceFeatureExtractDict").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      surfaceFeatureExtractDict;
}

f1_wing.stl
{
    extractionMethod    extractFromSurface;
    extractFromSurfaceCoeffs
    {
        includedAngle   150;
    }
    writeObj            no;
}
""")

    # system/snappyHexMeshDict
    (case_dir / "system" / "snappyHexMeshDict").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}

castellatedMesh true;
snap            true;
addLayers       false;

geometry
{
    f1_wing.stl
    {
        type triSurfaceMesh;
        name f1_wing;
    }
    wakeBox
    {
        type searchableBox;
        min (-0.40 0.0 -0.30);
        max ( 1.65 0.80  0.60);
    }
    nearWingBox
    {
        type searchableBox;
        min (-0.15 0.0 -0.15);
        max ( 0.75 0.62  0.42);
    }
}

castellatedMeshControls
{
    maxLocalCells       500000;
    maxGlobalCells      1500000;
    minRefinementCells  5;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 2;

    features
    (
        {
            file "f1_wing.eMesh";
            level 5;
        }
    );

    refinementSurfaces
    {
        f1_wing
        {
            level (4 5);
            patchInfo
            {
                type wall;
            }
        }
    }

    resolveFeatureAngle 30;

    refinementRegions
    {
        wakeBox
        {
            mode inside;
            levels ((1E15 2));
        }
        nearWingBox
        {
            mode inside;
            levels ((1E15 3));
        }
    }

    locationInMesh (-1.5 1.5 1.0);
    allowFreeStandingZoneFaces true;
}

snapControls
{
    nSmoothPatch    3;
    tolerance       2.0;
    nSolveIter      30;
    nRelaxIter      5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap false;
}

addLayersControls
{
    relativeSizes true;
    layers {}
    expansionRatio 1.2;
    finalLayerThickness 0.3;
    minThickness 0.1;
    nGrow 0;
    featureAngle 60;
    nRelaxIter 3;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}

meshQualityControls
{
    maxNonOrtho         65;
    maxBoundarySkewness 20;
    maxInternalSkewness 4;
    maxConcave          80;
    minVol              1e-13;
    minTetQuality       -1e30;
    minArea             -1;
    minTwist            0.02;
    minDeterminant      0.001;
    minFaceWeight       0.02;
    minVolRatio         0.01;
    minTriangleTwist    -1;
    nSmoothScale        4;
    errorReduction      0.75;
}

mergeTolerance 1e-6;
""")

    # system/decomposeParDict
    (case_dir / "system" / "decomposeParDict").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}}

numberOfSubdomains {N_PROCS};
method          scotch;
""")

    # system/controlDict
    (case_dir / "system" / "controlDict").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}

application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         220;
deltaT          1;
writeControl    timeStep;
writeInterval   220;
purgeWrite      1;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    wingForceCoeffs
    {{
        type            forceCoeffs;
        libs            (forces);
        writeControl    timeStep;
        writeInterval   5;
        patches         (f1_wing);
        rho             rhoInf;
        rhoInf          {RHO};
        liftDir         (0 0 -1);   // Positive Cl == Downforce (-z direction)
        dragDir         (1 0 0);
        CofR            (0.20 0 0.10);
        pitchAxis       (0 1 0);
        magUInf         {U_INF};
        lRef            {L_REF};
        Aref            {A_REF_HALF};
    }}

    wingForces
    {{
        type            forces;
        libs            (forces);
        writeControl    timeStep;
        writeInterval   5;
        patches         (f1_wing);
        rho             rhoInf;
        rhoInf          {RHO};
        CofR            (0.20 0 0.10);
    }}
}}
""")

    # system/fvSchemes
    (case_dir / "system" / "fvSchemes").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}

ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
}

divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwindV grad(U);
    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear limited corrected 0.5;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         limited corrected 0.5;
}

wallDist
{
    method          meshWave;
}
""")

    # system/fvSolution
    (case_dir / "system" / "fvSolution").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}

solvers
{
    p
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-6;
        relTol          0.05;
    }

    Phi
    {
        $p;
    }

    "(U|k|omega)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-6;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent      yes;
    residualControl
    {
        p               1e-4;
        U               1e-4;
        "(k|omega)"     1e-4;
    }
}

potentialFlow
{
    nNonOrthogonalCorrectors 4;
}

relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
        k               0.6;
        omega           0.6;
    }
}
""")

    # constant/transportProperties & turbulenceProperties
    (case_dir / "constant" / "transportProperties").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}}

transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {NU:.6e};
""")

    (case_dir / "constant" / "turbulenceProperties").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}

simulationType  RAS;

RAS
{
    RASModel        kOmegaSST;
    turbulence      on;
    printCoeffs     off;
}
""")

    # Initial fields: 0/U, 0/p, 0/k, 0/omega, 0/nut
    (case_dir / "0" / "U").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}

dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({U_INF} 0 0);

boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform ({U_INF} 0 0);
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform (0 0 0);
        value           uniform ({U_INF} 0 0);
    }}
    symmetry
    {{
        type            symmetryPlane;
    }}
    outerWall
    {{
        type            slip;
    }}
    f1_wing
    {{
        type            noSlip;
    }}
}}
""")

    (case_dir / "0" / "p").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}

dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;

boundaryField
{
    inlet
    {
        type            zeroGradient;
    }
    outlet
    {
        type            fixedValue;
        value           uniform 0;
    }
    symmetry
    {
        type            symmetryPlane;
    }
    outerWall
    {
        type            zeroGradient;
    }
    f1_wing
    {
        type            zeroGradient;
    }
}
""")

    (case_dir / "0" / "k").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      k;
}}

dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_in:.6e};

boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform {k_in:.6e};
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform {k_in:.6e};
        value           uniform {k_in:.6e};
    }}
    symmetry
    {{
        type            symmetryPlane;
    }}
    outerWall
    {{
        type            slip;
    }}
    f1_wing
    {{
        type            kqRWallFunction;
        value           uniform {k_in:.6e};
    }}
}}
""")

    (case_dir / "0" / "omega").write_text(f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      omega;
}}

dimensions      [0 0 -1 0 0 0 0];
internalField   uniform {omega_in:.6e};

boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform {omega_in:.6e};
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform {omega_in:.6e};
        value           uniform {omega_in:.6e};
    }}
    symmetry
    {{
        type            symmetryPlane;
    }}
    outerWall
    {{
        type            slip;
    }}
    f1_wing
    {{
        type            omegaWallFunction;
        value           uniform {omega_in:.6e};
    }}
}}
""")

    (case_dir / "0" / "nut").write_text("""FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}

dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;

boundaryField
{
    inlet
    {
        type            calculated;
        value           uniform 0;
    }
    outlet
    {
        type            calculated;
        value           uniform 0;
    }
    symmetry
    {
        type            symmetryPlane;
    }
    outerWall
    {
        type            calculated;
        value           uniform 0;
    }
    f1_wing
    {
        type            nutkWallFunction;
        value           uniform 0;
    }
}
""")
    return stl_info


def parse_force_coeffs(case_dir: Path) -> dict:
    dat_files = sorted((case_dir / "postProcessing" / "wingForceCoeffs").rglob("*.dat"))
    if not dat_files:
        raise RuntimeError(f"No forceCoeffs .dat found in {case_dir}")

    # Average over the last 8 recorded samples for smooth steady-state aero telemetry
    rows = []
    for line in dat_files[-1].read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) >= 4:
            # OpenFOAM v2512 coefficient.dat columns: Time Cd Cs Cl CmRoll CmPitch CmYaw ...
            rows.append([float(x) for x in parts[:6]])

    tail = rows[-8:] if len(rows) >= 8 else rows
    # Note: verify column headers!
    headers = []
    for line in dat_files[-1].read_text().splitlines():
        if line.strip().startswith("# Time"):
            headers = line.strip().lstrip("#").split()
            break

    cd_idx = headers.index("Cd") if "Cd" in headers else 1
    cl_idx = headers.index("Cl") if "Cl" in headers else 3

    cd_vals = [r[cd_idx] for r in tail]
    cl_vals = [r[cl_idx] for r in tail]
    cd = sum(cd_vals) / len(cd_vals)
    cl = sum(cl_vals) / len(cl_vals)

    q_inf = 0.5 * RHO * U_INF**2
    full_area = 2.0 * A_REF_HALF  # 0.50 m^2 full-span reference area
    downforce_n = cl * q_inf * full_area
    drag_n = cd * q_inf * full_area

    return {
        "Cl_downforce": round(cl, 4),
        "Cd_drag": round(cd, 4),
        "L_over_D": round(cl / cd, 3) if abs(cd) > 1e-6 else 0.0,
        "downforce_N": round(downforce_n, 1),
        "downforce_kgf": round(downforce_n / 9.81, 1),
        "drag_N": round(drag_n, 1),
        "speed_kmh": round(U_INF * 3.6, 1),
        "iterations": int(rows[-1][0]) if rows else 0,
    }


def run_single_mode(root_dir: Path, name: str, drs_open: bool) -> dict:
    case_dir = root_dir / name
    t0 = time.perf_counter()
    print(f"\n=== [{name}] Setting up F1 Rear Wing (DRS {'OPEN' if drs_open else 'CLOSED'}) ===", flush=True)
    setup_case(case_dir, drs_open=drs_open)

    print(f"[{name}] blockMesh + surfaceFeatureExtract + snappyHexMesh...", flush=True)
    run_foam(case_dir, "blockMesh")
    run_foam(case_dir, "surfaceFeatureExtract")
    snappy_log = run_foam(case_dir, "snappyHexMesh -overwrite", timeout=240)
    n_cells = 0
    for line in snappy_log.splitlines():
        if "cells:" in line and "faces:" in line:
            try:
                n_cells = int(line.split("cells:")[1].split()[0])
            except Exception:
                pass
    t_mesh = time.perf_counter() - t0
    print(f"[{name}] Mesh ready: {n_cells:,} cells in {t_mesh:.1f}s", flush=True)

    print(f"[{name}] potentialFoam + {N_PROCS}-core simpleFoam (k-omega SST @ 252 km/h)...", flush=True)
    t_solve0 = time.perf_counter()
    run_foam(case_dir, "potentialFoam -noFunctionObjects")
    if N_PROCS > 1:
        run_foam(case_dir, "decomposePar -force")
        run_foam(case_dir, f"mpirun --oversubscribe -np {N_PROCS} simpleFoam -parallel", timeout=600)
        run_foam(case_dir, "reconstructPar -latestTime")
        # Clean processor folders to save disk space
        for pdir in case_dir.glob("processor*"):
            shutil.rmtree(pdir, ignore_errors=True)
    else:
        run_foam(case_dir, "simpleFoam", timeout=600)
    t_solve = time.perf_counter() - t_solve0

    print(f"[{name}] foamToVTK -latestTime...", flush=True)
    run_foam(case_dir, "foamToVTK -latestTime -noFaceZones", timeout=120)

    aero = parse_force_coeffs(case_dir)
    aero["n_cells"] = n_cells
    aero["mesh_sec"] = round(t_mesh, 1)
    aero["solve_sec"] = round(t_solve, 1)
    aero["total_sec"] = round(time.perf_counter() - t0, 1)
    print(
        f"[{name}] DONE in {aero['total_sec']}s | Downforce = {aero['downforce_N']} N "
        f"({aero['downforce_kgf']} kgf, Cl={aero['Cl_downforce']}) | "
        f"Drag = {aero['drag_N']} N (Cd={aero['Cd_drag']}) | L/D = {aero['L_over_D']}",
        flush=True,
    )
    return aero


def main():
    root_dir = Path("/home/ymxl/openfoam_playground/04_f1_rear_wing")
    summary = {}
    summary["drs_closed"] = run_single_mode(root_dir, "drs_closed", drs_open=False)
    summary["drs_open"] = run_single_mode(root_dir, "drs_open", drs_open=True)

    df_closed = summary["drs_closed"]["downforce_N"]
    df_open = summary["drs_open"]["downforce_N"]
    drag_closed = summary["drs_closed"]["drag_N"]
    drag_open = summary["drs_open"]["drag_N"]

    summary["drs_effect"] = {
        "drag_reduction_pct": round((1.0 - drag_open / drag_closed) * 100.0, 1) if drag_closed > 0 else 0.0,
        "downforce_reduction_pct": round((1.0 - df_open / df_closed) * 100.0, 1) if df_closed > 0 else 0.0,
        "drag_saved_N": round(drag_closed - drag_open, 1),
    }

    (root_dir / "aero_summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== ALBERT PARK F1 REAR WING SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
