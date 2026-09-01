from pathlib import Path

import cadquery as cq

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.StlAPI import StlAPI_Writer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt


OUTPUT_DIR = Path(__file__).parent / "stl"

# Dimensions corrected after printing and measuring the first fit test.
PLATE_WIDTH = 30.45
PLATE_HEIGHT = 38.20
MATERIAL_THICKNESS = 3.20
SHELF_PROJECTION = 24.00

SIDE_SCREW_PILOT_DIAMETER = 2.70
SIDE_SCREW_PILOT_DEPTH = 6.00

SIDE_WALL_THICKNESS = 3.20
SIDE_WALL_HEIGHT = 6.20
LOWER_RAIL_WIDTH = 5.00
LOWER_RAIL_LENGTH = 16.00
LOWER_RAIL_DROP = 5.00
LOWER_RAIL_OVERLAP = 0.50

CAMERA_SUPPORT_HEIGHT_IN_EARS = 34.00
# M5 fine pitch (0.5 mm) requires tap drill Ø4.5-4.7 mm
LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER = 4.60  # tap drill size for M5×0.5
LOWER_ADJUSTMENT_SCREW_MIN_EDGE_MARGIN = 3.00
LOWER_ADJUSTMENT_HOLE_OVERTRAVEL = 1.00
# The lower adjustment hole has been moved up by 5 mm relative to its
# previous calculated position (rear -> front axis through vertical plate).
LOWER_ADJUSTMENT_HOLE_UPSHIFT = 5.00

EAR_PROJECTION = 8.70
EAR_WIDTH = 8.50
EAR_GAP = 5.33
EAR_HEIGHT = 5.99
PIVOT_CLEARANCE_DIAMETER = 3.40

CSI_SLOT_WIDTH_X = 18.00
CSI_SLOT_DEPTH_Y = 9.56

# Ball-end adjustment screw: M5 × 0.5 (fine pitch) × 40 mm with Ø6.5 mm ball at the end.
# The threaded shaft screws into a tapped M5×0.5 hole in the base.
# The ball embeds in a petal snap-fit socket on the camera support plate.
BALL_SCREW_LENGTH = 40.00
BALL_SCREW_SHAFT_DIAMETER = 5.00  # nominal M5 major diameter
BALL_DIAMETER = 6.50
BALL_SOCKET_DIAMETER = 6.90  # slight clearance so the ball can articulate
M5_FINE_PITCH = 0.50  # M5×0.5 fine pitch instead of 0.8mm standard

# Camera support plate (ball-socket side).
CAM_SUPPORT_WIDTH = 28.05
CAM_SUPPORT_DEPTH = 7.00
CAM_SUPPORT_THICKNESS = 1.00
CAM_SUPPORT_M3_DIAMETER = 3.20  # M3 clearance hole
CAM_SUPPORT_M3_OFFSET_X = 8.00  # symmetric M3 holes at ±X from centre

# Petal-style ball retention ring on the support plate.
PETAL_INNER_RADIUS = 3.25   # ≈ ball radius → snug fit once seated
PETAL_WALL = 1.00            # wall thickness of each petal (mm)
PETAL_HEIGHT = 4.00          # petals extend 4 mm above plate surface
PETAL_SLIT_WIDTH = 0.80      # gap between petals (allows flex in PLA)
# Entry chamfer: bore widens outward at the top so the ball can be pressed in.
PETAL_ENTRY_CHAMFER = 0.50   # how much the bore radius increases at the rim



def make_box(
    width: float,
    depth: float,
    height: float,
    x: float = 0,
    y: float = 0,
    z: float = 0,
) -> TopoDS_Shape:
    return BRepPrimAPI_MakeBox(
        gp_Pnt(x - (width / 2), y - (depth / 2), z),
        width,
        depth,
        height,
    ).Shape()


def fuse(*shapes: TopoDS_Shape) -> TopoDS_Shape:
    result = shapes[0]
    for shape in shapes[1:]:
        result = BRepAlgoAPI_Fuse(result, shape).Shape()
    return result


def cut(shape: TopoDS_Shape, tool: TopoDS_Shape) -> TopoDS_Shape:
    return BRepAlgoAPI_Cut(shape, tool).Shape()


def make_mount() -> TopoDS_Shape:
    plate = make_box(
        PLATE_WIDTH,
        MATERIAL_THICKNESS,
        PLATE_HEIGHT,
    )

    plate_back_y = MATERIAL_THICKNESS / 2
    plate_front_y = -(MATERIAL_THICKNESS / 2)
    shelf_front_y = plate_front_y - SHELF_PROJECTION
    shelf_back_y = plate_front_y + 1.00
    shelf_depth = shelf_back_y - shelf_front_y
    shelf_y = (shelf_back_y + shelf_front_y) / 2
    shelf = make_box(
        PLATE_WIDTH,
        shelf_depth,
        MATERIAL_THICKNESS,
        y=shelf_y,
    )

    wall_x = (PLATE_WIDTH - SIDE_WALL_THICKNESS) / 2
    left_wall = make_box(
        SIDE_WALL_THICKNESS,
        shelf_depth,
        SIDE_WALL_HEIGHT,
        x=-wall_x,
        y=shelf_y,
        z=MATERIAL_THICKNESS,
    )
    right_wall = make_box(
        SIDE_WALL_THICKNESS,
        shelf_depth,
        SIDE_WALL_HEIGHT,
        x=wall_x,
        y=shelf_y,
        z=MATERIAL_THICKNESS,
    )

    rail_x = (PLATE_WIDTH - LOWER_RAIL_WIDTH) / 2
    rail_y = shelf_front_y + (LOWER_RAIL_LENGTH / 2)
    rail_height = LOWER_RAIL_DROP + LOWER_RAIL_OVERLAP
    left_rail = make_box(
        LOWER_RAIL_WIDTH,
        LOWER_RAIL_LENGTH,
        rail_height,
        x=-rail_x,
        y=rail_y,
        z=-LOWER_RAIL_DROP,
    )
    right_rail = make_box(
        LOWER_RAIL_WIDTH,
        LOWER_RAIL_LENGTH,
        rail_height,
        x=rail_x,
        y=rail_y,
        z=-LOWER_RAIL_DROP,
    )

    ear_radius = EAR_HEIGHT / 2
    ear_center_distance = EAR_PROJECTION - ear_radius
    ear_tip_y = plate_front_y - ear_center_distance
    ear_anchor_y = plate_front_y + 1.00
    ear_box_depth = ear_anchor_y - ear_tip_y + 0.20
    ear_body_y = (ear_anchor_y + ear_tip_y - 0.20) / 2
    ear_x = (EAR_GAP + EAR_WIDTH) / 2
    ear_z = PLATE_HEIGHT - EAR_HEIGHT
    ear_center_z = PLATE_HEIGHT - ear_radius
    left_ear_body = make_box(
        EAR_WIDTH,
        ear_box_depth,
        EAR_HEIGHT,
        x=-ear_x,
        y=ear_body_y,
        z=ear_z,
    )
    right_ear_body = make_box(
        EAR_WIDTH,
        ear_box_depth,
        EAR_HEIGHT,
        x=ear_x,
        y=ear_body_y,
        z=ear_z,
    )
    left_ear_round = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-ear_x - (EAR_WIDTH / 2), ear_tip_y, ear_center_z),
            gp_Dir(1, 0, 0),
        ),
        ear_radius,
        EAR_WIDTH,
    ).Shape()
    right_ear_round = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(ear_x - (EAR_WIDTH / 2), ear_tip_y, ear_center_z),
            gp_Dir(1, 0, 0),
        ),
        ear_radius,
        EAR_WIDTH,
    ).Shape()

    mount = fuse(
        plate,
        shelf,
        left_wall,
        right_wall,
        left_rail,
        right_rail,
        left_ear_body,
        right_ear_body,
        left_ear_round,
        right_ear_round,
    )
    left_screw_pilot = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(PLATE_WIDTH / 2) - 1, rail_y, -(LOWER_RAIL_DROP / 2)),
            gp_Dir(1, 0, 0),
        ),
        SIDE_SCREW_PILOT_DIAMETER / 2,
        SIDE_SCREW_PILOT_DEPTH + 1,
    ).Shape()
    right_screw_pilot = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt((PLATE_WIDTH / 2) + 1, rail_y, -(LOWER_RAIL_DROP / 2)),
            gp_Dir(-1, 0, 0),
        ),
        SIDE_SCREW_PILOT_DIAMETER / 2,
        SIDE_SCREW_PILOT_DEPTH + 1,
    ).Shape()
    mount = cut(cut(mount, left_screw_pilot), right_screw_pilot)
    pivot_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(EAR_GAP / 2) - EAR_WIDTH - 1, ear_tip_y, ear_center_z),
            gp_Dir(1, 0, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        (2 * EAR_WIDTH) + EAR_GAP + 2,
    ).Shape()
    lower_adjustment_screw_z = (
        max(
            (LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER / 2)
            + LOWER_ADJUSTMENT_SCREW_MIN_EDGE_MARGIN,
            ear_center_z - CAMERA_SUPPORT_HEIGHT_IN_EARS,
        )
        + LOWER_ADJUSTMENT_HOLE_UPSHIFT
    )
    # Drill the lower adjustment tapped hole (M5×0.5 fine pitch) through the vertical plate
    # (rear -> front), not across the mount width (left -> right).
    lower_adjustment_screw_x = 0.00
    lower_adjustment_screw_y = plate_back_y + LOWER_ADJUSTMENT_HOLE_OVERTRAVEL
    lower_adjustment_hole_depth = MATERIAL_THICKNESS + (2 * LOWER_ADJUSTMENT_HOLE_OVERTRAVEL)
    lower_adjustment_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(lower_adjustment_screw_x, lower_adjustment_screw_y, lower_adjustment_screw_z),
            gp_Dir(0, -1, 0),
        ),
        LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER / 2,  # tap drill for M5×0.5
        lower_adjustment_hole_depth,
    ).Shape()
    csi_slot_height = MATERIAL_THICKNESS + 2
    csi_slot_z = (MATERIAL_THICKNESS - csi_slot_height) / 2
    csi_slot = make_box(
        CSI_SLOT_WIDTH_X,
        CSI_SLOT_DEPTH_Y,
        csi_slot_height,
        y=shelf_y,
        z=csi_slot_z,
    )
    return cut(cut(cut(mount, pivot_hole), lower_adjustment_hole), csi_slot)


def make_fit_test() -> TopoDS_Shape:
    return make_box(PLATE_WIDTH, MATERIAL_THICKNESS, PLATE_HEIGHT)


def make_ball_screw() -> TopoDS_Shape:
    """M5 × 0.5 (fine pitch) × 40 mm threaded shaft with Ø6.5 mm ball at tip.

    The shaft carries a printable ISO M5 external thread (pitch 0.5 mm fine,
    outer Ø 5.0 mm, core Ø ≈ 4.13 mm).  A right-hand helix profile is swept
    along the full 40 mm length using CadQuery.  The Ø6.5 mm ball is fused at
    the tip and will embed in a petal snap-fit socket on the camera support.
    """
    pitch = M5_FINE_PITCH  # 0.5 mm fine pitch
    major_r = BALL_SCREW_SHAFT_DIAMETER / 2          # 2.5 mm
    minor_r = 2.067      # M5 minor radius (ISO 68-1)
    thread_h = major_r - minor_r  # radial thread depth ≈ 0.433 mm

    # Core shaft (minor diameter)
    core = cq.Workplane("XY").circle(minor_r).extrude(BALL_SCREW_LENGTH)

    # Thread profile: right-hand isosceles triangle with apex at major radius.
    # The profile origin sits at (minor_r, 0) and rides along the helix.
    helix = cq.Wire.makeHelix(
        pitch=pitch,
        height=BALL_SCREW_LENGTH,
        radius=major_r,
        lefthand=False,
    )
    thread_profile = (
        cq.Workplane("XZ")
        .moveTo(minor_r, 0)
        .lineTo(major_r, pitch * 0.5)
        .lineTo(minor_r, pitch)
        .close()
    )
    thread_solid = thread_profile.sweep(helix, multisection=False, isFrenet=True)

    # Fuse core + thread ridge, then add ball at tip
    shaft = core.union(thread_solid)
    ball = cq.Workplane("XY").workplane(offset=BALL_SCREW_LENGTH).sphere(BALL_DIAMETER / 2)
    result = shaft.union(ball)
    # CadQuery's union may return a Compound; collect all solid handles and
    # return the last one, which is the fully-fused result that passes
    # BRepCheck validation.  Use explorer.Value() to get a stable copy of
    # each shape handle rather than the mutable iterator reference from
    # explorer.Current().
    solids: list[TopoDS_Shape] = []
    explorer = TopExp_Explorer(result.val().wrapped, TopAbs_SOLID)
    while explorer.More():
        solids.append(explorer.Value())
        explorer.Next()
    if solids:
        return solids[-1]
    return result.solids().vals()[0].wrapped


def make_camera_support_plate() -> TopoDS_Shape:
    """Rectangular camera support plate: 28.05 × 7 × 1 mm.

    Contains:
    - a centred Ø6.9 mm ball socket pocket (shallow hemisphere) in the plate.
    - a 4-petal snap-fit retention ring (4 mm tall, 1 mm wall, 0.8 mm slits)
      so the Ø6.5 mm ball can be pressed in and locked.  The entry bore is
      chamfered so the ball spreads the PLA petals on insertion.
    - two M3 clearance holes (Ø3.2 mm) symmetrically at ±8 mm along X.
    """
    # Base plate
    plate = cq.Workplane("XY").box(CAM_SUPPORT_WIDTH, CAM_SUPPORT_DEPTH, CAM_SUPPORT_THICKNESS)

    # Ball-socket pocket: hemisphere centred on the top face of the plate.
    # The socket centre sits at z = CAM_SUPPORT_THICKNESS + BALL_DIAMETER/2 so
    # that only the lower cap (≈ 0.75 mm) is subtracted from the 1 mm plate.
    socket_center_z = CAM_SUPPORT_THICKNESS + BALL_DIAMETER / 2
    socket = (
        cq.Workplane("XY")
        .workplane(offset=socket_center_z)
        .sphere(BALL_SOCKET_DIAMETER / 2)
    )
    plate = plate.cut(socket)

    # Petal ring: hollow cylinder with 4 axial slits for snap-fit retention.
    petal_outer_r = PETAL_INNER_RADIUS + PETAL_WALL
    petal_ring = (
        cq.Workplane("XY")
        .workplane(offset=CAM_SUPPORT_THICKNESS)
        .circle(petal_outer_r)
        .circle(PETAL_INNER_RADIUS)
        .extrude(PETAL_HEIGHT)
    )
    # Cut X-slit and Y-slit (cross pattern → 4 equal petals)
    slit_len = (petal_outer_r + 1) * 2
    slit_x = (
        cq.Workplane("XY")
        .box(PETAL_SLIT_WIDTH, slit_len, PETAL_HEIGHT)
        .translate((0, 0, CAM_SUPPORT_THICKNESS + PETAL_HEIGHT / 2))
    )
    slit_y = (
        cq.Workplane("XY")
        .box(slit_len, PETAL_SLIT_WIDTH, PETAL_HEIGHT)
        .translate((0, 0, CAM_SUPPORT_THICKNESS + PETAL_HEIGHT / 2))
    )
    petal_ring = petal_ring.cut(slit_x).cut(slit_y)

    # Entry chamfer: truncated cone at the rim widens the bore opening so the
    # ball can spread the petals on entry.  Only cut the inner taper (cone),
    # keeping the outer wall intact.
    # The chamfer sits at the very top of the petal ring.
    chamfer_z = CAM_SUPPORT_THICKNESS + PETAL_HEIGHT - PETAL_ENTRY_CHAMFER
    chamfer_cone_shape = BRepPrimAPI_MakeCone(
        gp_Ax2(gp_Pnt(0, 0, chamfer_z), gp_Dir(0, 0, 1)),
        PETAL_INNER_RADIUS,                        # r1 at base of chamfer
        PETAL_INNER_RADIUS + PETAL_ENTRY_CHAMFER,  # r2 at rim
        PETAL_ENTRY_CHAMFER,                       # height of chamfer band
    ).Shape()
    petal_ring = petal_ring.cut(
        cq.Workplane("XY").add(cq.Shape.cast(chamfer_cone_shape))
    )

    result = plate.union(petal_ring)

    # Two symmetric M3 clearance holes through the plate thickness
    for sign in (+1, -1):
        m3 = (
            cq.Workplane("XY")
            .circle(CAM_SUPPORT_M3_DIAMETER / 2)
            .extrude(CAM_SUPPORT_THICKNESS + 1.0)
            .translate((sign * CAM_SUPPORT_M3_OFFSET_X, 0, -0.5))
        )
        result = result.cut(m3)

    return result.solids().vals()[0].wrapped



def export_model(model: TopoDS_Shape, filename: str) -> None:
    if not BRepCheck_Analyzer(model).IsValid():
        raise ValueError(f"Invalid solid: {filename}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BRepMesh_IncrementalMesh(model, 0.05, False, 0.1, True)
    writer = StlAPI_Writer()
    writer.Write(model, str(OUTPUT_DIR / filename))


if __name__ == "__main__":
    export_model(make_mount(), "pi_camera_tilt_base.stl")
    export_model(make_fit_test(), "fit_test_rear_cavity_30.45x38.2.stl")
<<<<<<< HEAD
=======
    export_model(make_ball_screw(), "ball_screw_M5x40_ball6.5.stl")
    export_model(make_camera_support_plate(), "camera_support_plate_28.05x7x1.stl")
>>>>>>> origin/main
