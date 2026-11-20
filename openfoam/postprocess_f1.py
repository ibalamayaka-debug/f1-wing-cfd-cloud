"""
Post-process OpenFOAM 3D F1 Rear Wing CFD (DRS Closed vs DRS Open):
  1. Computes true 3D aerodynamic streamlines & swirling wingtip vortices using VTK RK45 vtkStreamTracer
  2. Mirrors the half-wing + streamlines across y=0 symmetry plane for full-span 3D geometry
  3. Exports compact .vtp files (wing surface Cp, 3D streamlines, centerline slice) for ParaView / Web VTK.js
  4. Renders a high-resolution dark-theme F1 Telemetry & CFD Dashboard PNG
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Tuple

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib_f1")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

RHO = 1.225
U_INF = 70.0
Q_INF = 0.5 * RHO * U_INF**2  # 3001.25 Pa


def load_case_vtk(case_dir: Path) -> Tuple[vtk.vtkUnstructuredGrid, vtk.vtkPolyData]:
    vtk_root = case_dir / "VTK"
    internal_files = sorted(vtk_root.glob("*.vtk"), key=lambda p: p.stat().st_mtime)
    if not internal_files:
        internal_files = sorted(vtk_root.rglob("internal.vtu"), key=lambda p: p.stat().st_mtime)
    internal_path = internal_files[-1]

    if internal_path.suffix == ".vtu":
        r_int = vtk.vtkXMLUnstructuredGridReader()
    else:
        r_int = vtk.vtkUnstructuredGridReader()
        r_int.ReadAllScalarsOn()
        r_int.ReadAllVectorsOn()
    r_int.SetFileName(str(internal_path))
    r_int.Update()
    ug = r_int.GetOutput()

    # Load f1_wing boundary surface patch (.vtp in OpenFOAM v2512 or legacy .vtk)
    wing_vtp = sorted(vtk_root.rglob("f1_wing.vtp"), key=lambda p: p.stat().st_mtime)
    if wing_vtp:
        r_wing = vtk.vtkXMLPolyDataReader()
        r_wing.SetFileName(str(wing_vtp[-1]))
    else:
        wing_files = sorted((vtk_root / "f1_wing").glob("*.vtk"), key=lambda p: p.stat().st_mtime)
        r_wing = vtk.vtkPolyDataReader()
        r_wing.SetFileName(str(wing_files[-1]))
        r_wing.ReadAllScalarsOn()
        r_wing.ReadAllVectorsOn()
    r_wing.Update()
    wing_raw = r_wing.GetOutput()

    # Convert cell data -> point data for smooth shading & streamline integration
    c2p_int = vtk.vtkCellDataToPointData()
    c2p_int.SetInputData(ug)
    c2p_int.Update()
    ug_pt = c2p_int.GetOutput()

    c2p_wing = vtk.vtkCellDataToPointData()
    c2p_wing.SetInputData(wing_raw)
    c2p_wing.Update()
    wing_pt = c2p_wing.GetOutput()

    # Add Cp and U_mag arrays
    for ds in (ug_pt, wing_pt):
        pd = ds.GetPointData()
        p_arr = pd.GetArray("p")
        if p_arr is not None:
            p_pa = vtk_to_numpy(p_arr) * RHO
            cp = (p_pa / Q_INF).astype(np.float32)
            cp_vtk = numpy_to_vtk(cp, deep=True)
            cp_vtk.SetName("Cp")
            pd.AddArray(cp_vtk)
        u_arr = pd.GetArray("U")
        if u_arr is not None:
            u_np = vtk_to_numpy(u_arr)
            umag = np.linalg.norm(u_np, axis=1).astype(np.float32)
            umag_vtk = numpy_to_vtk(umag, deep=True)
            umag_vtk.SetName("U_mag")
            pd.AddArray(umag_vtk)
            pd.SetActiveVectors("U")

    return ug_pt, wing_pt


def mirror_polydata_y(poly: vtk.vtkPolyData) -> vtk.vtkPolyData:
    """Combine half-span polydata (y >= 0) with its mirror across y=0 for full-span 3D wing."""
    t = vtk.vtkTransform()
    t.Scale(1.0, -1.0, 1.0)
    tf = vtk.vtkTransformPolyDataFilter()
    tf.SetTransform(t)
    tf.SetInputData(poly)
    tf.Update()

    rev = vtk.vtkReverseSense()
    rev.SetInputConnection(tf.GetOutputPort())
    rev.ReverseCellsOn()
    rev.ReverseNormalsOn()
    rev.Update()

    append = vtk.vtkAppendPolyData()
    append.AddInputData(poly)
    append.AddInputData(rev.GetOutput())
    append.Update()
    return append.GetOutput()


def compute_3d_streamlines(ug_pt: vtk.vtkUnstructuredGrid) -> vtk.vtkPolyData:
    """
    Resample the snappyHexMesh polyhedral velocity field onto a fine 3D structured
    vtkImageData volume so vtkStreamTracer never terminates prematurely on VTK_POLYHEDRON
    refinement-level faces, yielding 50+ smooth, unbroken 3D streamlines & wingtip vortices!
    """
    resampler = vtk.vtkResampleToImage()
    resampler.SetInputDataObject(ug_pt)
    resampler.UseInputBoundsOff()
    resampler.SetSamplingBounds(-0.48, 1.70, 0.005, 0.80, -0.32, 0.60)
    resampler.SetSamplingDimensions(115, 50, 58)
    resampler.Update()
    img = resampler.GetOutput()
    img.GetPointData().SetActiveVectors("U")

    seed_pts = vtk.vtkPoints()
    # 1) Spanwise rake upstream of mainplane & slot (captures upwash & suction acceleration)
    for y in np.linspace(0.04, 0.44, 6):
        for z in (0.01, 0.11, 0.22):
            seed_pts.InsertNextPoint(-0.42, float(y), float(z))
    # 2) Tight cluster around the endplate tip (y ~ 0.45..0.55) to capture swirling wingtip vortices!
    for y in np.linspace(0.45, 0.56, 4):
        for z in np.linspace(0.02, 0.28, 4):
            seed_pts.InsertNextPoint(-0.22, float(y), float(z))

    seed_poly = vtk.vtkPolyData()
    seed_poly.SetPoints(seed_pts)

    tracer = vtk.vtkStreamTracer()
    tracer.SetInputData(img)
    tracer.SetSourceData(seed_poly)
    tracer.SetMaximumPropagation(2.3)
    tracer.SetInitialIntegrationStep(0.015)
    tracer.SetMaximumIntegrationStep(0.03)
    tracer.SetIntegrationDirectionToForward()
    tracer.SetIntegratorTypeToRungeKutta45()
    tracer.SetInputArrayToProcess(0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "U")
    tracer.Update()

    # Subsample points along each streamline slightly so VTP stays super compact (~250 KB)
    raw = tracer.GetOutput()
    sub_pts = vtk.vtkPoints()
    sub_lines = vtk.vtkCellArray()
    raw_pts = vtk_to_numpy(raw.GetPoints().GetData())
    raw_umag = vtk_to_numpy(raw.GetPointData().GetArray("U_mag"))
    out_umag = []

    lines = raw.GetLines()
    lines.InitTraversal()
    id_list = vtk.vtkIdList()
    while lines.GetNextCell(id_list):
        n_ids = id_list.GetNumberOfIds()
        if n_ids < 8:
            continue
        sampled_ids = list(range(0, n_ids, 2))
        if sampled_ids[-1] != n_ids - 1:
            sampled_ids.append(n_ids - 1)
        new_ids = []
        for k in sampled_ids:
            orig_id = id_list.GetId(k)
            p = raw_pts[orig_id]
            new_ids.append(sub_pts.InsertNextPoint(float(p[0]), float(p[1]), float(p[2])))
            out_umag.append(float(raw_umag[orig_id]))
        sub_lines.InsertNextCell(len(new_ids))
        for nid in new_ids:
            sub_lines.InsertCellPoint(nid)

    half_streams = vtk.vtkPolyData()
    half_streams.SetPoints(sub_pts)
    half_streams.SetLines(sub_lines)
    if out_umag:
        arr = numpy_to_vtk(np.array(out_umag, dtype=np.float32), deep=True)
        arr.SetName("U_mag")
        half_streams.GetPointData().SetScalars(arr)

    # Mirror streamlines across y=0 for twin counter-rotating wingtip vortices
    t = vtk.vtkTransform()
    t.Scale(1.0, -1.0, 1.0)
    tf = vtk.vtkTransformPolyDataFilter()
    tf.SetTransform(t)
    tf.SetInputData(half_streams)
    tf.Update()

    append = vtk.vtkAppendPolyData()
    append.AddInputData(half_streams)
    append.AddInputData(tf.GetOutput())
    append.Update()
    return append.GetOutput()


def extract_center_slice(ug_pt: vtk.vtkUnstructuredGrid) -> vtk.vtkPolyData:
    plane = vtk.vtkPlane()
    plane.SetOrigin(0.0, 0.02, 0.0)  # Just inside symmetry plane for clean triangles
    plane.SetNormal(0.0, 1.0, 0.0)

    cutter = vtk.vtkCutter()
    cutter.SetCutFunction(plane)
    cutter.SetInputData(ug_pt)
    cutter.Update()

    tri = vtk.vtkTriangleFilter()
    tri.SetInputConnection(cutter.GetOutputPort())
    tri.Update()
    return tri.GetOutput()


def _keep_only_arrays(poly: vtk.vtkPolyData, keep: tuple[str, ...]) -> vtk.vtkPolyData:
    """Strip unused OpenFOAM arrays (k, omega, nut, etc.) to keep web .vtp files compact."""
    out = vtk.vtkPolyData()
    out.DeepCopy(poly)
    out.GetCellData().Initialize()
    out.GetFieldData().Initialize()
    pd = out.GetPointData()
    names = [pd.GetArrayName(i) for i in range(pd.GetNumberOfArrays())]
    for n in names:
        if n not in keep:
            pd.RemoveArray(n)
    if keep and pd.GetArray(keep[0]) is not None:
        pd.SetActiveScalars(keep[0])
    return out


def _crop_polydata_box(poly: vtk.vtkPolyData, bounds: tuple[float, float, float, float, float, float]) -> vtk.vtkPolyData:
    box = vtk.vtkBox()
    box.SetBounds(*bounds)
    clip = vtk.vtkExtractPolyDataGeometry()
    clip.SetImplicitFunction(box)
    clip.SetInputData(poly)
    clip.ExtractInsideOn()
    clip.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(clip.GetOutputPort())
    clean.Update()
    return clean.GetOutput()


def write_vtp(poly: vtk.vtkPolyData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    w = vtk.vtkXMLPolyDataWriter()
    w.SetFileName(str(path))
    w.SetInputData(poly)
    w.SetDataModeToAscii()
    w.Write()


def plot_2d_slice(ax, slice_poly: vtk.vtkPolyData, title: str, drs_open: bool):
    from matplotlib.path import Path as MplPath
    from scipy.interpolate import griddata
    from generate_f1_wing_stl import naca4_inverted_profile, transform_2d

    pts = vtk_to_numpy(slice_poly.GetPoints().GetData())
    u_vec = vtk_to_numpy(slice_poly.GetPointData().GetArray("U"))
    u_mag = vtk_to_numpy(slice_poly.GetPointData().GetArray("U_mag"))

    mask = (
        (pts[:, 0] >= -0.60)
        & (pts[:, 0] <= 1.50)
        & (pts[:, 2] >= -0.45)
        & (pts[:, 2] <= 0.68)
    )
    xz = np.column_stack([pts[mask, 0], pts[mask, 2]])
    gx = np.linspace(-0.42, 1.30, 220)
    gz = np.linspace(-0.30, 0.54, 150)
    GX, GZ = np.meshgrid(gx, gz)

    UM = griddata(xz, u_mag[mask], (GX, GZ), method="linear")
    UX = griddata(xz, u_vec[mask, 0], (GX, GZ), method="linear")
    UZ = griddata(xz, u_vec[mask, 2], (GX, GZ), method="linear")

    # Exact analytic F1 mainplane & DRS flap silhouettes (razor sharp, zero checkerboard!)
    main_2d = transform_2d(naca4_inverted_profile(0.06, 0.40, 0.14, 0.32, 60), 14.0, 0.0, 0.02)
    flap_raw = naca4_inverted_profile(0.04, 0.40, 0.12, 0.165, 50)
    flap_2d = transform_2d(flap_raw, 8.0, 0.30, 0.205) if drs_open else transform_2d(flap_raw, 42.0, 0.285, 0.120)

    grid_pts = np.column_stack([GX.ravel(), GZ.ravel()])
    inside_wing = (
        MplPath(main_2d).contains_points(grid_pts)
        | MplPath(flap_2d).contains_points(grid_pts)
    ).reshape(GX.shape)

    levels = np.linspace(0.0, 115.0, 30)
    cf = ax.contourf(GX, GZ, np.ma.array(UM, mask=inside_wing), levels=levels, cmap="turbo", extend="max")

    ax.streamplot(
        gx, gz,
        np.where(inside_wing, 0.0, np.nan_to_num(UX, nan=0.0)),
        np.where(inside_wing, 0.0, np.nan_to_num(UZ, nan=0.0)),
        color=(1.0, 1.0, 1.0, 0.62),
        density=1.45,
        linewidth=0.78,
        arrowsize=0.75,
    )
    ax.fill(main_2d[:, 0], main_2d[:, 1], facecolor="#0b1120", edgecolor="#e2e8f0", linewidth=1.0, zorder=6)
    ax.fill(flap_2d[:, 0], flap_2d[:, 1], facecolor="#0b1120", edgecolor="#38bdf8" if not drs_open else "#fb923c", linewidth=1.2, zorder=6)

    ax.set_xlim(-0.42, 1.30)
    ax.set_ylim(-0.30, 0.54)
    ax.set_aspect("equal")
    ax.set_facecolor("#0b1120")
    ax.set_title(title, color="#f8fafc", fontsize=10.5, fontweight="bold", pad=8)
    ax.set_xlabel("x [m] (Flow Direction →)", color="#94a3b8", fontsize=9)
    ax.set_ylabel("z [m]", color="#94a3b8", fontsize=9)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#334155")
    return cf


def plot_3d_wing_and_streamlines(ax, wing_full: vtk.vtkPolyData, streams_full: vtk.vtkPolyData):
    # Triangulate wing surface for 3D rendering
    tri_f = vtk.vtkTriangleFilter()
    tri_f.SetInputData(wing_full)
    tri_f.Update()
    wpoly = tri_f.GetOutput()

    pts = vtk_to_numpy(wpoly.GetPoints().GetData())
    cp = vtk_to_numpy(wpoly.GetPointData().GetArray("Cp"))
    cells = vtk_to_numpy(wpoly.GetPolys().GetData()).reshape(wpoly.GetNumberOfPolys(), 4)[:, 1:4]

    # Subsample slightly if very dense so matplotlib 3D stays fast & sharp
    stride = max(1, len(cells) // 6000)
    cells_sub = cells[::stride]
    verts = pts[cells_sub]
    tri_cp = np.mean(cp[cells_sub], axis=1)

    norm_cp = plt.Normalize(vmin=-2.0, vmax=1.0)
    cmap_cp = plt.cm.coolwarm
    facecolors = cmap_cp(norm_cp(tri_cp))

    poly3d = Poly3DCollection(verts, facecolors=facecolors, edgecolors="none", alpha=0.96)
    ax.add_collection3d(poly3d)

    # Plot 3D streamlines colored by velocity magnitude
    s_pts = vtk_to_numpy(streams_full.GetPoints().GetData())
    s_umag = vtk_to_numpy(streams_full.GetPointData().GetArray("U_mag"))
    lines = streams_full.GetLines()
    lines.InitTraversal()
    id_list = vtk.vtkIdList()

    norm_u = plt.Normalize(vmin=25.0, vmax=105.0)
    cmap_u = plt.cm.turbo

    segments = []
    seg_colors = []
    line_idx = 0
    while lines.GetNextCell(id_list):
        n_ids = id_list.GetNumberOfIds()
        line_idx += 1
        if n_ids < 4:
            continue
        ids = [id_list.GetId(k) for k in range(0, n_ids, 2)]
        coords = s_pts[ids]
        # Clip streamline display region near wing + near wake
        mask = (coords[:, 0] >= -0.45) & (coords[:, 0] <= 1.65)
        coords = coords[mask]
        mags = s_umag[ids][mask]
        if len(coords) < 2:
            continue
        for k in range(len(coords) - 1):
            segments.append([coords[k], coords[k + 1]])
            seg_colors.append(cmap_u(norm_u(0.5 * (mags[k] + mags[k + 1]))))

    if segments:
        lc = Line3DCollection(segments, colors=seg_colors, linewidths=0.85, alpha=0.72)
        ax.add_collection3d(lc)

    ax.set_xlim(-0.35, 1.45)
    ax.set_ylim(-0.72, 0.72)
    ax.set_zlim(-0.28, 0.58)
    ax.set_box_aspect((1.8, 1.44, 0.86))
    ax.view_init(elev=24, azim=-132)
    ax.set_facecolor("#0b1120")
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.fill = False
        axis.pane.set_edgecolor("#1e293b")
        axis._axinfo["grid"]["color"] = (0.2, 0.25, 0.35, 0.35)
    ax.tick_params(colors="#94a3b8", labelsize=7.5)
    ax.set_xlabel("x [m]", color="#94a3b8", fontsize=8.5)
    ax.set_ylabel("y [m]", color="#94a3b8", fontsize=8.5)
    ax.set_zlabel("z [m]", color="#94a3b8", fontsize=8.5)
    ax.set_title(
        "3D F1 Rear Wing (DRS Closed) — Surface Cp & Wingtip Vortex Streamlines",
        color="#f8fafc", fontsize=11, fontweight="bold", pad=6,
    )


def main():
    root = Path("/home/ymxl/openfoam_playground/04_f1_rear_wing")
    summary = json.loads((root / "aero_summary.json").read_text())
    export_dir = root / "vtk_exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # Load both OpenFOAM cases
    ug_closed, wing_closed = load_case_vtk(root / "drs_closed")
    ug_open, wing_open = load_case_vtk(root / "drs_open")

    slice_closed = extract_center_slice(ug_closed)
    slice_open = extract_center_slice(ug_open)
    wing_closed_full = mirror_polydata_y(wing_closed)
    streams_closed_full = compute_3d_streamlines(ug_closed)

    wing_open_full = mirror_polydata_y(wing_open)
    streams_open_full = compute_3d_streamlines(ug_open)

    # Export compact ParaView / VTK.js ready .vtp files (decimate wing ~75% for fast 1.8 MB web load)
    web_box = (-0.50, 1.75, -0.85, 0.85, -0.35, 0.62)

    def _decimate_wing(poly: vtk.vtkPolyData) -> vtk.vtkPolyData:
        tri = vtk.vtkTriangleFilter()
        tri.SetInputData(poly)
        tri.Update()
        clean = vtk.vtkCleanPolyData()
        clean.SetInputConnection(tri.GetOutputPort())
        clean.Update()
        dec = vtk.vtkQuadricDecimation()
        dec.SetInputConnection(clean.GetOutputPort())
        dec.SetTargetReduction(0.75)
        dec.AttributeErrorMetricOn()
        dec.ScalarsAttributeOn()
        dec.Update()
        return _keep_only_arrays(dec.GetOutput(), ("Cp",))

    write_vtp(_decimate_wing(wing_closed_full), export_dir / "drs_closed_wing.vtp")
    write_vtp(_keep_only_arrays(streams_closed_full, ("U_mag",)), export_dir / "drs_closed_streamlines.vtp")
    write_vtp(_keep_only_arrays(_crop_polydata_box(slice_closed, web_box), ("U_mag", "Cp")), export_dir / "drs_closed_slice.vtp")

    write_vtp(_decimate_wing(wing_open_full), export_dir / "drs_open_wing.vtp")
    write_vtp(_keep_only_arrays(streams_open_full, ("U_mag",)), export_dir / "drs_open_streamlines.vtp")
    write_vtp(_keep_only_arrays(_crop_polydata_box(slice_open, web_box), ("U_mag", "Cp")), export_dir / "drs_open_slice.vtp")

    # Build 2x2 F1 CFD Telemetry Dashboard
    fig = plt.figure(figsize=(16, 10.5), facecolor="#070b14")
    fig.suptitle(
        "Melbourne Albert Park F1 Rear Wing Aerodynamics — OpenFOAM v2512 (simpleFoam, k-ω SST @ 252 km/h)",
        color="#f8fafc", fontsize=14.5, fontweight="bold", y=0.975,
    )

    ax1 = fig.add_subplot(2, 2, 1)
    cf1 = plot_2d_slice(
        ax1, slice_closed,
        f"DRS CLOSED — Centerline |U| & Streamlines (Downforce = {summary['drs_closed']['downforce_kgf']} kgf)",
        drs_open=False,
    )
    cbar1 = fig.colorbar(cf1, ax=ax1, fraction=0.036, pad=0.02)
    cbar1.set_label("|U| [m/s]", color="#cbd5e1", fontsize=8.5)
    cbar1.ax.tick_params(colors="#94a3b8", labelsize=8)

    ax2 = fig.add_subplot(2, 2, 2)
    cf2 = plot_2d_slice(
        ax2, slice_open,
        f"DRS OPEN — Centerline |U| & Streamlines (Drag -{summary['drs_effect']['drag_reduction_pct']}%)",
        drs_open=True,
    )
    cbar2 = fig.colorbar(cf2, ax=ax2, fraction=0.036, pad=0.02)
    cbar2.set_label("|U| [m/s]", color="#cbd5e1", fontsize=8.5)
    cbar2.ax.tick_params(colors="#94a3b8", labelsize=8)

    ax3 = fig.add_subplot(2, 2, 3, projection="3d")
    plot_3d_wing_and_streamlines(ax3, wing_closed_full, streams_closed_full)

    # Panel 4: Aero Telemetry Bar Comparison
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.set_facecolor("#0b1120")
    c = summary["drs_closed"]
    o = summary["drs_open"]
    eff = summary["drs_effect"]

    metrics = ["Downforce\n[N]", "Drag\n[N]", "Downforce\n[kgf]"]
    closed_vals = [c["downforce_N"], c["drag_N"], c["downforce_kgf"]]
    open_vals = [o["downforce_N"], o["drag_N"], o["downforce_kgf"]]
    x_pos = np.arange(len(metrics))
    w = 0.34

    b1 = ax4.bar(x_pos - w / 2, closed_vals, w, label=f"DRS Closed (CL={c['Cl_downforce']:.2f}, CD={c['Cd_drag']:.2f}, L/D={c['L_over_D']:.2f})", color="#38bdf8", edgecolor="#0ea5e9")
    b2 = ax4.bar(x_pos + w / 2, open_vals, w, label=f"DRS Open   (CL={o['Cl_downforce']:.2f}, CD={o['Cd_drag']:.2f}, L/D={o['L_over_D']:.2f})", color="#fb923c", edgecolor="#f97316")

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax4.text(
                bar.get_x() + bar.get_width() / 2, h + max(closed_vals) * 0.02,
                f"{h:.0f}", ha="center", va="bottom", color="#f8fafc", fontsize=9.5, fontweight="bold",
            )

    ax4.set_xticks(x_pos)
    ax4.set_xticklabels(metrics, color="#e2e8f0", fontsize=10, fontweight="bold")
    ax4.set_ylim(0, max(closed_vals) * 1.28)
    ax4.set_ylabel("Force [N / kgf] @ 252 km/h (Full 1.0 m Span)", color="#94a3b8", fontsize=9.5)
    ax4.set_title("Albert Park Aero Telemetry — DRS Closed vs DRS Open", color="#f8fafc", fontsize=11.5, fontweight="bold", pad=8)
    ax4.tick_params(colors="#94a3b8", labelsize=9)
    ax4.grid(axis="y", color="#1e293b", linestyle="--", alpha=0.6)
    for sp in ax4.spines.values():
        sp.set_color("#334155")
    ax4.legend(facecolor="#0f172a", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=9, loc="upper right")

    callout = (
        f"DRS Overtaking Gain @ 252 km/h:\n"
        f"  • Drag Reduction : -{eff['drag_reduction_pct']:.1f}% (-{eff['drag_saved_N']:.0f} N)\n"
        f"  • Downforce Drop : -{eff['downforce_reduction_pct']:.1f}%\n"
        f"  • Mesh (Half-Wing): {c['n_cells']:,} hex cells (snappyHexMesh)"
    )
    ax4.text(
        0.97, 0.62, callout, transform=ax4.transAxes,
        ha="right", va="top", color="#e2e8f0", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.6", facecolor="#131c31", edgecolor="#38bdf8", alpha=0.92),
    )

    plt.tight_layout(rect=[0, 0.01, 1, 0.945])
    out_png = Path("/home/ymxl/openfoam_playground/results/04_f1_rear_wing_cfd.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved dashboard PNG: {out_png} ({out_png.stat().st_size / 1024:.1f} KB)")
    print(f"Exported VTP files in: {export_dir}")


if __name__ == "__main__":
    main()
