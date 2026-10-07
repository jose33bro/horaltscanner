from dataclasses import dataclass
from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
)
from OCP.StlAPI import StlAPI_Writer
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
LOWER_RAIL_FRONT_CUT_DEPTH = 3.00

CABLE_PASSAGE_WIDTH = 12.00
CABLE_PASSAGE_HEIGHT = 5.00
CABLE_PASSAGE_Y_OFFSET = 8.00

EAR_PROJECTION = 8.70
EAR_WIDTH = 8.50
EAR_GAP = 5.33
EAR_HEIGHT = 5.99
PIVOT_CLEARANCE_DIAMETER = 3.40
M5_COARSE_TAP_PILOT_DIAMETER = 4.20
M5_THREAD_HOLE_OFFSET_FROM_TOP = 22.00

CSI_SLOT_WIDTH = 18.00
CSI_SLOT_HEIGHT = 9.56
CSI_SLOT_BOTTOM = 5.00
CSI_SLOT_FRONT_OFFSET = -4.00

ROD_LENGTH = 50.00
ROD_DIAMETER = 5.00
BALL_DIAMETER = 6.50
# Ball end is for the camera side; the square end is for the wheel/plate mount.
DRIVE_SQUARE_WIDTH = 5.00
DRIVE_SQUARE_LENGTH = 10.00
M3_CLEARANCE_DIAMETER = 3.20
WHEEL_DIAMETER = 50.00
WHEEL_THICKNESS = 6.00
WHEEL_HUB_WIDTH = 8.00
WHEEL_HUB_LENGTH = 10.00
WHEEL_HUB_M3_CLEARANCE_DIAMETER = 3.20

# Camera carrier: holds the Pi Camera Module 3 (standard or NoIR, same PCB)
# and provides the hinge tab that slots between the base's ears on the M3
# pivot axle. Hole spacing/diameter match the official Camera Module 3
# mechanical drawing (25 x 24mm PCB, 21mm square hole pattern, Ø2.5mm holes).
CAM_PCB_WIDTH = 25.00
CAM_PCB_HEIGHT = 24.00
CAM_MOUNT_HOLE_SPACING = 21.00
CAM_MOUNT_HOLE_DIAMETER = 2.50
CARRIER_THICKNESS = 2.00
# Gap left between the carrier's back face and the main plate's front face,
# so the adjustment rod's ball tip has room to push the carrier and tilt it.
CARRIER_STANDOFF_GAP = 1.00
# Tab width must fit inside EAR_GAP (5.33mm) with clearance to pivot freely.
CARRIER_TAB_WIDTH = 4.80
# Shallow dimple on the back of the carrier so the rod's ball tip seats and
# self-centers instead of sliding off as the carrier tilts.
BALL_SOCKET_CLEARANCE = 0.30
BALL_SOCKET_DEPTH = 1.00

# Front cache (lens-side cover): clips onto the camera through the same 4
# mounting holes instead of screws/nuts. Four printed pins push through the
# PCB holes and into the carrier's holes (friction/press fit); a central
# opening clears the lens.
CAM_PCB_THICKNESS = 1.20
COVER_THICKNESS = 1.60
LENS_HOLE_DIAMETER = 11.00
# Slightly undersized vs. CAM_MOUNT_HOLE_DIAMETER (2.50mm) for a snug push
# fit directly against the PCB's rigid holes.
CLIP_PIN_DIAMETER = 2.30
CLIP_PIN_TIP_DIAMETER = 1.20
CLIP_PIN_TIP_LENGTH = 0.80
# How far short of the carrier's back face the pins stop, so they never
# reach into the 1mm gap in front of the main plate (ball-socket area).
CLIP_PIN_BACK_MARGIN = 0.30


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


@dataclass
class EarGeometry:
    plate_front_y: float
    ear_radius: float
    ear_tip_y: float
    ear_anchor_y: float
    ear_box_depth: float
    ear_body_y: float
    ear_x: float
    ear_z: float
    ear_center_z: float


def ear_geometry() -> EarGeometry:
    """Shared ear/pivot layout, used by both the base and the camera carrier
    so their hinge tab and ear holes always line up."""
    plate_front_y = -(MATERIAL_THICKNESS / 2)
    ear_radius = EAR_HEIGHT / 2
    ear_center_distance = EAR_PROJECTION - ear_radius
    ear_tip_y = plate_front_y - ear_center_distance
    ear_anchor_y = plate_front_y + 1.00
    ear_box_depth = ear_anchor_y - ear_tip_y + 0.20
    ear_body_y = (ear_anchor_y + ear_tip_y - 0.20) / 2
    ear_x = (EAR_GAP + EAR_WIDTH) / 2
    ear_z = PLATE_HEIGHT - EAR_HEIGHT
    ear_center_z = PLATE_HEIGHT - ear_radius
    return EarGeometry(
        plate_front_y=plate_front_y,
        ear_radius=ear_radius,
        ear_tip_y=ear_tip_y,
        ear_anchor_y=ear_anchor_y,
        ear_box_depth=ear_box_depth,
        ear_body_y=ear_body_y,
        ear_x=ear_x,
        ear_z=ear_z,
        ear_center_z=ear_center_z,
    )


@dataclass
class CameraHoleLayout:
    mount_hole_x: float
    hole_top_z: float
    hole_bottom_z: float
    hole_center_z: float


def camera_hole_layout(ear: EarGeometry) -> CameraHoleLayout:
    """Shared Pi Camera V3 mounting-hole positions (21mm square pattern),
    used by both the carrier and the front cache so pins/screws line up."""
    hole_top_z = ear.ear_z - 1.50
    hole_bottom_z = hole_top_z - CAM_MOUNT_HOLE_SPACING
    return CameraHoleLayout(
        mount_hole_x=CAM_MOUNT_HOLE_SPACING / 2,
        hole_top_z=hole_top_z,
        hole_bottom_z=hole_bottom_z,
        hole_center_z=(hole_top_z + hole_bottom_z) / 2,
    )


def make_mount() -> TopoDS_Shape:
    plate = make_box(
        PLATE_WIDTH,
        MATERIAL_THICKNESS,
        PLATE_HEIGHT,
    )

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
    left_front_cut = make_box(
        LOWER_RAIL_WIDTH,
        LOWER_RAIL_FRONT_CUT_DEPTH,
        rail_height,
        x=-rail_x,
        y=shelf_front_y + (LOWER_RAIL_FRONT_CUT_DEPTH / 2),
        z=-LOWER_RAIL_DROP,
    )
    right_front_cut = make_box(
        LOWER_RAIL_WIDTH,
        LOWER_RAIL_FRONT_CUT_DEPTH,
        rail_height,
        x=rail_x,
        y=shelf_front_y + (LOWER_RAIL_FRONT_CUT_DEPTH / 2),
        z=-LOWER_RAIL_DROP,
    )
    cable_passage = make_box(
        CABLE_PASSAGE_WIDTH,
        shelf_depth + 2,
        CABLE_PASSAGE_HEIGHT,
        y=shelf_front_y + CABLE_PASSAGE_Y_OFFSET,
        z=MATERIAL_THICKNESS / 2,
    )

    ear = ear_geometry()
    ear_radius = ear.ear_radius
    ear_tip_y = ear.ear_tip_y
    ear_anchor_y = ear.ear_anchor_y
    ear_box_depth = ear.ear_box_depth
    ear_body_y = ear.ear_body_y
    ear_x = ear.ear_x
    ear_z = ear.ear_z
    ear_center_z = ear.ear_center_z
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
    mount = cut(cut(cut(mount, left_front_cut), right_front_cut), cable_passage)
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
    m5_thread_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP),
            gp_Dir(0, 1, 0),
        ),
        M5_COARSE_TAP_PILOT_DIAMETER / 2,
        MATERIAL_THICKNESS + 2,
    ).Shape()
    csi_slot = make_box(
        CSI_SLOT_WIDTH,
        MATERIAL_THICKNESS + 2,
        CSI_SLOT_HEIGHT,
        y=CSI_SLOT_FRONT_OFFSET,
        z=CSI_SLOT_BOTTOM + (CSI_SLOT_HEIGHT / 2),
    )
    return cut(cut(cut(mount, pivot_hole), m5_thread_hole), csi_slot)


def make_camera_carrier() -> TopoDS_Shape:
    """Carries the Pi Camera Module 3 PCB (25 x 24mm, 21mm square hole
    pattern) and provides the hinge tab that slots between the base's ears
    on the M3 pivot axle, plus a dimple on the back where the adjustment
    rod's ball tip seats to tilt it."""
    ear = ear_geometry()

    carrier_back_y = ear.plate_front_y - CARRIER_STANDOFF_GAP
    carrier_center_y = carrier_back_y - (CARRIER_THICKNESS / 2)
    carrier_height = ear.ear_z - MATERIAL_THICKNESS
    board_plate = make_box(
        CAM_PCB_WIDTH,
        CARRIER_THICKNESS,
        carrier_height,
        y=carrier_center_y,
        z=MATERIAL_THICKNESS,
    )

    # Hinge tab: same rounded-tip profile as the base's ears, centered and
    # narrow enough to slot into EAR_GAP, stacked directly on top of the
    # board plate so it reaches the ears' pivot axis.
    tab_body = make_box(
        CARRIER_TAB_WIDTH,
        ear.ear_box_depth,
        EAR_HEIGHT,
        y=ear.ear_body_y,
        z=ear.ear_z,
    )
    tab_round = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(CARRIER_TAB_WIDTH / 2), ear.ear_tip_y, ear.ear_center_z),
            gp_Dir(1, 0, 0),
        ),
        ear.ear_radius,
        CARRIER_TAB_WIDTH,
    ).Shape()

    carrier = fuse(board_plate, tab_body, tab_round)

    pivot_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(CARRIER_TAB_WIDTH / 2) - 1, ear.ear_tip_y, ear.ear_center_z),
            gp_Dir(1, 0, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        CARRIER_TAB_WIDTH + 2,
    ).Shape()

    holes = camera_hole_layout(ear)
    hole_top_z = holes.hole_top_z
    hole_bottom_z = holes.hole_bottom_z
    mount_hole_x = holes.mount_hole_x
    top_left_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_top_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 2,
    ).Shape()
    top_right_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_top_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 2,
    ).Shape()
    bottom_left_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_bottom_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 2,
    ).Shape()
    bottom_right_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_bottom_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 2,
    ).Shape()

    # Shallow ball-socket dimple on the back face, aligned with the base's
    # adjustment boss, so the rod's ball tip seats and self-centers instead
    # of sliding off as the carrier tilts.
    adjustment_boss_z = PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP
    ball_socket_radius = (BALL_DIAMETER / 2) + BALL_SOCKET_CLEARANCE
    ball_socket_center_y = carrier_back_y + (ball_socket_radius - BALL_SOCKET_DEPTH)
    ball_socket = BRepPrimAPI_MakeSphere(
        gp_Pnt(0, ball_socket_center_y, adjustment_boss_z),
        ball_socket_radius,
    ).Shape()

    carrier = cut(carrier, pivot_hole)
    carrier = cut(cut(carrier, top_left_hole), top_right_hole)
    carrier = cut(cut(carrier, bottom_left_hole), bottom_right_hole)
    return cut(carrier, ball_socket)


def make_camera_front_cover() -> TopoDS_Shape:
    """Lens-side cache that clips onto the Pi Camera V3 through the same 4
    mounting holes used by the carrier, instead of screws/nuts. Four pins
    push through the PCB's holes and into the carrier's holes (press/
    friction fit); a central opening clears the lens."""
    ear = ear_geometry()
    holes = camera_hole_layout(ear)

    carrier_back_y = ear.plate_front_y - CARRIER_STANDOFF_GAP
    carrier_front_y = carrier_back_y - CARRIER_THICKNESS
    pcb_front_y = carrier_front_y - CAM_PCB_THICKNESS
    cover_back_y = pcb_front_y
    cover_center_y = cover_back_y - (COVER_THICKNESS / 2)
    cover_bottom_z = ear.ear_z - CAM_PCB_HEIGHT

    cover_plate = make_box(
        CAM_PCB_WIDTH,
        COVER_THICKNESS,
        CAM_PCB_HEIGHT,
        y=cover_center_y,
        z=cover_bottom_z,
    )

    cover_front_y = cover_back_y - COVER_THICKNESS
    lens_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, cover_front_y - 1, holes.hole_center_z),
            gp_Dir(0, 1, 0),
        ),
        LENS_HOLE_DIAMETER / 2,
        COVER_THICKNESS + 2,
    ).Shape()

    # Pins span the PCB thickness plus most of the carrier thickness,
    # stopping short of the carrier's back face (ball-socket side).
    engagement_length = (
        CAM_PCB_THICKNESS + CARRIER_THICKNESS - CLIP_PIN_BACK_MARGIN
    )
    shaft_length = engagement_length - CLIP_PIN_TIP_LENGTH

    def clip_pin(x: float, z: float) -> TopoDS_Shape:
        shaft = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(x, cover_back_y, z), gp_Dir(0, 1, 0)),
            CLIP_PIN_DIAMETER / 2,
            shaft_length,
        ).Shape()
        tip = BRepPrimAPI_MakeCone(
            gp_Ax2(gp_Pnt(x, cover_back_y + shaft_length, z), gp_Dir(0, 1, 0)),
            CLIP_PIN_DIAMETER / 2,
            CLIP_PIN_TIP_DIAMETER / 2,
            CLIP_PIN_TIP_LENGTH,
        ).Shape()
        return fuse(shaft, tip)

    pins = [
        clip_pin(-holes.mount_hole_x, holes.hole_top_z),
        clip_pin(holes.mount_hole_x, holes.hole_top_z),
        clip_pin(-holes.mount_hole_x, holes.hole_bottom_z),
        clip_pin(holes.mount_hole_x, holes.hole_bottom_z),
    ]

    cover = fuse(cover_plate, *pins)
    return cut(cover, lens_hole)


def make_adjustment_rod() -> TopoDS_Shape:
    rod_radius = ROD_DIAMETER / 2
    rod = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, -(ROD_LENGTH / 2)),
            gp_Dir(0, 0, 1),
        ),
        rod_radius,
        ROD_LENGTH,
    ).Shape()
    ball = BRepPrimAPI_MakeSphere(
        gp_Pnt(0, 0, (ROD_LENGTH / 2) + (BALL_DIAMETER / 2)),
        BALL_DIAMETER / 2,
    ).Shape()
    drive_square = make_box(
        DRIVE_SQUARE_WIDTH,
        DRIVE_SQUARE_WIDTH,
        DRIVE_SQUARE_LENGTH,
        z=-(ROD_LENGTH / 2) - (DRIVE_SQUARE_LENGTH / 2),
    )
    drive_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, -(ROD_LENGTH / 2) - (DRIVE_SQUARE_LENGTH / 2)),
            gp_Dir(0, 0, 1),
        ),
        M3_CLEARANCE_DIAMETER / 2,
        DRIVE_SQUARE_LENGTH + 2,
    ).Shape()
    return cut(fuse(rod, ball, drive_square), drive_hole)


def make_wheel_crank() -> TopoDS_Shape:
    wheel = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, 0),
            gp_Dir(0, 0, 1),
        ),
        WHEEL_DIAMETER / 2,
        WHEEL_THICKNESS,
    ).Shape()
    hub = make_box(
        WHEEL_HUB_WIDTH,
        WHEEL_HUB_WIDTH,
        WHEEL_HUB_LENGTH,
        z=-(WHEEL_HUB_LENGTH / 2),
    )
    hub_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, -(WHEEL_HUB_LENGTH / 2)),
            gp_Dir(0, 0, 1),
        ),
        WHEEL_HUB_M3_CLEARANCE_DIAMETER / 2,
        WHEEL_HUB_LENGTH + 2,
    ).Shape()
    return cut(fuse(wheel, hub), hub_hole)


def make_fit_test() -> TopoDS_Shape:
    return make_box(PLATE_WIDTH, MATERIAL_THICKNESS, PLATE_HEIGHT)


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
    export_model(make_adjustment_rod(), "adjustment_rod_M5x50_ball6.5_square_m3.stl")
    export_model(make_wheel_crank(), "wheel_crank_50mm_square_m3.stl")
    export_model(make_camera_carrier(), "camera_carrier_v3_25x24_tab4.8.stl")
    export_model(make_camera_front_cover(), "camera_front_cover_v3_clip.stl")
