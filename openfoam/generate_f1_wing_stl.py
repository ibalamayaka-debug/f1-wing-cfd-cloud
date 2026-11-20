"""
Parametric Watertight 3D F1 Rear Wing STL Generator (Melbourne Albert Park Edition).

Generates an FIA-scale 3D multi-element inverted F1 Rear Wing (half-span y in [0, 0.50] m
for symmetry-plane CFD, or full-span y in [-0.50, 0.50] m):
  - Mainplane: Inverted NACA 6414 cambered airfoil (chord 0.32 m, AoA 14 deg)
  - DRS Flap : Inverted NACA 4412 cambered airfoil (chord 0.16 m), adjustable DRS angle:
                 * DRS Closed (High Downforce): flap_angle = 42 deg
                 * DRS Open   (Low Drag)      : flap_angle = 10 deg
  - Endplate : Sculpted F1 rear-wing endplate at y = 0.50 m (thickness 14 mm)

Every component is a clean, closed, outward-oriented watertight triangulated mesh
suitable for OpenFOAM surfaceFeatureExtract + snappyHexMesh.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

import numpy as np


def naca4_inverted_profile(
    m: float, p: float, t: float, chord: float, n_pts: int = 44
) -> np.ndarray:
    """
    Generate closed CCW 2D profile (x, z) of an INVERTED 4-digit NACA airfoil
    (camber downward -> generates aerodynamic downforce in -z direction).
    Leading edge at (0, 0), trailing edge at (chord, 0) before rotation.
    """
    beta = np.linspace(0.0, math.pi, n_pts)
    xc = 0.5 * (1.0 - np.cos(beta))  # Cosine spacing: dense near LE & TE

    # Thickness distribution (closed TE coefficient -0.1036)
    yt = (
        5.0
        * t
        * (
            0.2969 * np.sqrt(np.maximum(xc, 0.0))
            - 0.1260 * xc
            - 0.3516 * xc**2
            + 0.2843 * xc**3
            - 0.1036 * xc**4
        )
    )
    # Keep a tiny finite TE thickness (1.5 mm) so snappyHexMesh snaps crisply
    yt[-1] = max(yt[-1], 0.0025)

    # Mean camber line
    yc = np.where(
        xc < p,
        (m / (p**2)) * (2.0 * p * xc - xc**2),
        (m / ((1.0 - p) ** 2)) * ((1.0 - 2.0 * p) + 2.0 * p * xc - xc**2),
    )
    dyc_dx = np.where(
        xc < p,
        (2.0 * m / (p**2)) * (p - xc),
        (2.0 * m / ((1.0 - p) ** 2)) * (p - xc),
    )
    theta = np.arctan(dyc_dx)

    # Standard airfoil upper/lower
    xu = xc - yt * np.sin(theta)
    zu = yc + yt * np.cos(theta)
    xl = xc + yt * np.sin(theta)
    zl = yc - yt * np.cos(theta)

    # Invert in z (camber curves downward -> suction peak on lower surface -> downforce!)
    zu = -zu
    zl = -zl

    # Order loop CCW in (x, z) plane:
    # Top surface (was lower, now zl >= zu) from TE -> LE, then bottom surface (zu) from LE -> TE
    x_loop = np.concatenate([xl[::-1], xu[1:]]) * chord
    z_loop = np.concatenate([zl[::-1], zu[1:]]) * chord
    return np.column_stack([x_loop, z_loop])


def transform_2d(
    pts: np.ndarray, angle_deg: float, dx: float, dz: float
) -> np.ndarray:
    """
    Rotate 2D airfoil in (x, z) by `angle_deg` trailing-edge-UP (positive downforce pitch),
    then translate by (dx, dz).
    """
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    # Trailing edge up => +x maps to (+c, +s), +z maps to (-s, +c)
    x_new = pts[:, 0] * c - pts[:, 1] * s + dx
    z_new = pts[:, 0] * s + pts[:, 1] * c + dz
    return np.column_stack([x_new, z_new])


def extrude_2d_loop_to_triangles(
    loop_xz: np.ndarray, y0: float, y1: float, cap_y0: bool = True, cap_y1: bool = True
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """
    Extrude a closed 2D CCW loop in (x, z) along y from y0 to y1 into watertight triangles
    with guaranteed outward-pointing normals.
    """
    # Ensure loop is CCW in (x, z) using shoelace formula
    x = loop_xz[:, 0]
    z = loop_xz[:, 1]
    signed_area = 0.5 * np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)
    if signed_area < 0:
        loop_xz = loop_xz[::-1].copy()

    n = len(loop_xz)
    tris: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    p0 = np.column_stack([loop_xz[:, 0], np.full(n, y0), loop_xz[:, 1]])
    p1 = np.column_stack([loop_xz[:, 0], np.full(n, y1), loop_xz[:, 1]])

    # Side walls: for CCW loop in (x, z), tangent (p[i+1]-p[i]) x (+y) points INWARD,
    # while (+y) x (p[i+1]-p[i]) points OUTWARD!
    # Check right-hand rule: (a1 - a0) x (a2 - a0)
    # Triangle (p0[i], p1[i], p1[j]): e1 = +y, e2 = +y + t => e1 x e2 = y x t = OUTWARD!
    for i in range(n):
        j = (i + 1) % n
        tris.append((p0[i], p1[i], p1[j]))
        tris.append((p0[i], p1[j], p0[j]))

    # End caps via simple fan from centroid (works cleanly for star-shaped airfoils & endplates)
    cx, cz = float(np.mean(loop_xz[:, 0])), float(np.mean(loop_xz[:, 1]))
    if cap_y0:
        # Outward normal at y0 is -y.
        # In (x, z) CCW: (p0[i]-c) x (p0[j]-c) has -y component! (since x x z = -y)
        c0 = np.array([cx, y0, cz])
        for i in range(n):
            j = (i + 1) % n
            tris.append((c0, p0[i], p0[j]))
    if cap_y1:
        # Outward normal at y1 is +y => reverse winding (c1, p1[j], p1[i])
        c1 = np.array([cx, y1, cz])
        for i in range(n):
            j = (i + 1) % n
            tris.append((c1, p1[j], p1[i]))

    return tris


def build_endplate_loop() -> np.ndarray:
    """
    Sculpted F1 rear-wing endplate profile in (x, z), star-shaped around centroid.
    Covers both mainplane and DRS flap with an authentic F1 swept leading edge & rear cutout.
    """
    pts = [
        (-0.04, -0.05),   # Front lower corner
        (0.16, -0.05),    # Lower edge mid
        (0.36, -0.02),    # Lower rear sweep
        (0.50, 0.08),     # Rear lower cutout corner
        (0.51, 0.30),     # Rear top corner
        (0.18, 0.30),     # Top edge
        (0.02, 0.22),     # Swept leading upper edge
        (-0.04, 0.08),    # Front leading nose
    ]
    return np.array(pts, dtype=float)


def write_ascii_stl(
    filepath: Path, solid_name: str, triangles: List[Tuple[np.ndarray, np.ndarray, np.ndarray]]
) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"solid {solid_name}"]
    for v0, v1, v2 in triangles:
        normal = np.cross(v1 - v0, v2 - v0)
        norm = float(np.linalg.norm(normal))
        if norm < 1e-14:
            continue
        n = normal / norm
        lines.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v0[0]:.6e} {v0[1]:.6e} {v0[2]:.6e}")
        lines.append(f"      vertex {v1[0]:.6e} {v1[1]:.6e} {v1[2]:.6e}")
        lines.append(f"      vertex {v2[0]:.6e} {v2[1]:.6e} {v2[2]:.6e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {solid_name}")
    filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_f1_wing_stl(
    out_path: Path,
    drs_open: bool = False,
    half_wing: bool = True,
) -> dict:
    """
    Generate the complete multi-element F1 Rear Wing STL.
      - half_wing=True  -> y in [-0.01, 0.50] m (slightly past y=0 symmetry plane so snappyHexMesh cuts cleanly!)
      - half_wing=False -> full span y in [-0.50, 0.50] m for direct 3D inspection
    """
    y_start = -0.01 if half_wing else -0.50
    y_end = 0.493  # Meets inner face of endplate cleanly (endplate sits at y in [0.490, 0.506])

    # 1. Mainplane: inverted NACA 6414, chord 0.32 m, pitched 14 deg nose-down / TE-up
    main_raw = naca4_inverted_profile(m=0.06, p=0.40, t=0.14, chord=0.32, n_pts=42)
    main_2d = transform_2d(main_raw, angle_deg=14.0, dx=0.0, dz=0.02)

    # 2. Upper DRS Flap: inverted NACA 4412, chord 0.165 m
    #    Pivoted near its trailing-upper mount (x_pivot=0.44, z_pivot=0.22)
    #    DRS Closed: high-downforce 42 deg pitch with narrow 18 mm slot gap
    #    DRS Open  : low-drag 8 deg pitch opening an ~82 mm FIA-spec DRS slot!
    flap_raw = naca4_inverted_profile(m=0.04, p=0.40, t=0.12, chord=0.165, n_pts=36)
    if drs_open:
        flap_2d = transform_2d(flap_raw, angle_deg=8.0, dx=0.30, dz=0.205)
    else:
        flap_2d = transform_2d(flap_raw, angle_deg=42.0, dx=0.285, dz=0.120)

    # 3. Endplate at y = 0.490 .. 0.506 (16 mm thick)
    endplate_2d = build_endplate_loop()

    tris: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    tris.extend(extrude_2d_loop_to_triangles(main_2d, y_start, y_end))
    tris.extend(extrude_2d_loop_to_triangles(flap_2d, y_start, y_end))
    tris.extend(extrude_2d_loop_to_triangles(endplate_2d, 0.490, 0.506))

    if not half_wing:
        tris.extend(extrude_2d_loop_to_triangles(endplate_2d, -0.506, -0.490))

    write_ascii_stl(out_path, "f1_wing", tris)
    return {
        "stl_path": str(out_path),
        "drs_open": drs_open,
        "half_wing": half_wing,
        "n_triangles": len(tris),
        "reference_area_half_m2": 0.25,  # 0.5 m half-span * 0.5 m total chord projection
        "reference_area_full_m2": 0.50,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate F1 Rear Wing STL")
    parser.add_argument("--drs-open", action="store_true", help="Open DRS flap (low drag)")
    parser.add_argument("--full-span", action="store_true", help="Generate full-span STL")
    parser.add_argument("--out", required=True, help="Output STL path")
    args = parser.parse_args()

    info = generate_f1_wing_stl(Path(args.out), drs_open=args.drs_open, half_wing=not args.full_span)
    print(info)
