from dataclasses import dataclass
from pathlib import Path
import math

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_TransitionMode,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
)
from OCP.Geom import Geom_CylindricalSurface
from OCP.Geom2d import Geom2d_Line
from OCP.StlAPI import StlAPI_Writer
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Dir2d, gp_Lin2d, gp_Pnt, gp_Pnt2d


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
# Printed external thread on the adjustment rod (see THREAD_* below) cuts its
# own mating groove as it is screwed in. The pilot is sized between the
# minor and major diameter so only part of the thread height compresses
# into the plastic on each turn (full major-to-minor interference would be
# too aggressive and risk cracking the boss in brittle FDM plastic).
THREAD_MAJOR_DIAMETER = 6.00
THREAD_PITCH = 2.00
THREAD_DEPTH = 0.75  # radial height of the triangular thread profile
THREAD_MINOR_DIAMETER = THREAD_MAJOR_DIAMETER - (2 * THREAD_DEPTH)
THREAD_LENGTH = 16.00
M5_COARSE_TAP_PILOT_DIAMETER = THREAD_MAJOR_DIAMETER - 1.00
M5_THREAD_HOLE_OFFSET_FROM_TOP = 22.00

CSI_SLOT_WIDTH = 18.00
CSI_SLOT_HEIGHT = 9.56
CSI_SLOT_BOTTOM = 5.00
CSI_SLOT_FRONT_OFFSET = -4.00

ROD_LENGTH = 50.00
ROD_DIAMETER = THREAD_MINOR_DIAMETER
BALL_DIAMETER = 6.50
# How far the ball sphere is sunk into the rod so the fuse creates a real
# overlapping solid neck instead of a single tangent point (which boolean
# fuse cannot merge into one watertight body).
BALL_OVERLAP = 1.00
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
# Official Camera Module 3 mechanical drawing: the CSI FPC connector is on
# the PCB's back face (the side that sits flush against the carrier's board
# plate), centered in X, with its centerline 2.10mm from the PCB's bottom
# edge. With nothing removed there, the carrier's board plate is solid right
# behind the connector, so the flat ribbon has no room to lie flush and
# route down toward the base -- it would be pinched between the PCB and the
# carrier. CARRIER_CABLE_CHANNEL below is a shallow groove in the carrier's
# front face (PCB side only, well clear of the ball-socket pocket cut into
# the opposite/back face) sized to let the ribbon lie flat from the
# connector down to the carrier's bottom edge, where it continues into the
# shelf's CABLE_PASSAGE below.
FPC_CONNECTOR_OFFSET_FROM_PCB_BOTTOM = 2.10
CARRIER_CABLE_CHANNEL_WIDTH = 16.00
CARRIER_CABLE_CHANNEL_DEPTH = 0.60
CARRIER_CABLE_CHANNEL_MARGIN_ABOVE_CONNECTOR = 3.00
# How far below the ball-socket pocket's lower edge the full through-slot
# (see CARRIER_CABLE_CHANNEL_* below) must stop, leaving solid wall so the
# socket's flat contact pad is never pierced.
CARRIER_CABLE_CHANNEL_CLEAR_MARGIN = 1.00
# Gap left between the carrier's back face and the main plate's front face,
# so the adjustment rod's ball tip has room to push the carrier and tilt it.
# Sized (not just an arbitrary assembly clearance) so the carrier's bottom
# edge -- the point farthest from the M3 pivot axle, so it sweeps the widest
# arc -- clears the plate's front face across the full +/-15deg working tilt
# range with margin, instead of jamming into the plate after a fraction of
# a degree like the old 1.00mm gap did.
CARRIER_STANDOFF_GAP = 9.00
# Target working tilt range (both directions from the rest/0deg position)
# used to size the shelf relief pocket below and to validate rod travel.
CARRIER_TILT_RANGE_DEG = 15.00
# Tab width must fit inside EAR_GAP (5.33mm) with clearance to pivot freely.
CARRIER_TAB_WIDTH = 4.80
# Radial clearance between the shelf's side walls and the carrier's PCB
# width (25.00mm) so the carrier can sit/pivot without rubbing the walls;
# see CARRIER_WALL_CLEARANCE note near make_mount()'s wall notch.
CARRIER_WALL_CLEARANCE = 0.30
# Shallow flat-bottomed pocket on the back of the carrier where the rod's
# ball tip bears. Radius sized so the contact point's lateral travel across
# the real tilt range (see BALL_SOCKET_PAD_RADIUS derivation note near
# make_camera_carrier) stays on the pad instead of riding onto the rim.
BALL_SOCKET_PAD_RADIUS = 6.00
BALL_SOCKET_DEPTH = 0.60

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

    # Relief notch on each wall's inner face where it would otherwise clash
    # with the camera carrier's PCB (25.00mm wide): the walls' clear inner
    # gap (PLATE_WIDTH - 2*SIDE_WALL_THICKNESS = 24.05mm) is narrower than
    # the carrier board, so without this the carrier's bottom edge jams
    # against the wall tops even at zero tilt.
    wall_inner_x = wall_x - (SIDE_WALL_THICKNESS / 2)
    notch_outer_x = (CAM_PCB_WIDTH / 2) + CARRIER_WALL_CLEARANCE
    if notch_outer_x > wall_inner_x:
        notch_width = notch_outer_x - wall_inner_x
        notch_center_x = (notch_outer_x + wall_inner_x) / 2
        left_wall_notch = make_box(
            notch_width,
            shelf_depth,
            SIDE_WALL_HEIGHT,
            x=-notch_center_x,
            y=shelf_y,
            z=MATERIAL_THICKNESS,
        )
        right_wall_notch = make_box(
            notch_width,
            shelf_depth,
            SIDE_WALL_HEIGHT,
            x=notch_center_x,
            y=shelf_y,
            z=MATERIAL_THICKNESS,
        )
        mount = cut(cut(mount, left_wall_notch), right_wall_notch)

    # Relief pocket in the shelf's top face under the carrier's bottom edge
    # sweep. At rest (0deg) the carrier's board plate sits flush on the
    # shelf (z = MATERIAL_THICKNESS). Because the M3 pivot axle sits ~32mm
    # above that edge, rotating the carrier in either direction swings it
    # along a circular arc whose chord dips below the z=0deg endpoints
    # before rising clear again -- without relief, the carrier's bottom
    # edge jams into the shelf after a fraction of a degree in the
    # direction that isn't simply lifting straight up off the shelf.
    # Depth/extent are derived from the same pivot geometry used to place
    # the carrier, scanned over the full CARRIER_TILT_RANGE_DEG so the
    # pocket is only as deep/wide as the real sweep needs.
    carrier_back_y = ear.plate_front_y - CARRIER_STANDOFF_GAP
    carrier_front_y = carrier_back_y - CARRIER_THICKNESS
    dz0 = MATERIAL_THICKNESS - ear_center_z
    relief_dip = 0.0
    relief_y_min = min(carrier_front_y, carrier_back_y)
    relief_y_max = max(carrier_front_y, carrier_back_y)
    sweep_steps = 60
    for edge_y in (carrier_front_y, carrier_back_y):
        dy = edge_y - ear_tip_y
        for i in range(-sweep_steps, sweep_steps + 1):
            theta = math.radians(CARRIER_TILT_RANGE_DEG) * i / sweep_steps
            s, c = math.sin(theta), math.cos(theta)
            nz = ear_center_z + dy * s + dz0 * c
            ny = ear_tip_y + dy * c - dz0 * s
            relief_dip = max(relief_dip, MATERIAL_THICKNESS - nz)
            relief_y_min = min(relief_y_min, ny)
            relief_y_max = max(relief_y_max, ny)
    relief_margin = 0.30
    relief_depth = relief_dip + relief_margin
    relief_y_center = (relief_y_min + relief_y_max) / 2
    relief_y_span = (relief_y_max - relief_y_min) + 1.00
    shelf_relief = make_box(
        CAM_PCB_WIDTH,
        relief_y_span,
        relief_depth,
        y=relief_y_center,
        z=MATERIAL_THICKNESS - relief_depth,
    )
    mount = cut(mount, shelf_relief)

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
            gp_Pnt(0, plate_front_y - 1, PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP),
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
    carrier_front_y = carrier_back_y - CARRIER_THICKNESS
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
    #
    # Depth must NOT reuse ear.ear_box_depth/ear.ear_body_y: those size the
    # base's ears to anchor (overlap) deep into the main plate for a
    # permanent fuse, since the ears are part of the same printed piece as
    # the plate. The carrier is a separate, free-pivoting part, so its tab
    # must stop well short of the plate instead, overlapping only into the
    # carrier's own board plate for its fuse. Anchoring at the board plate's
    # mid-thickness gives a solid 1mm fuse overlap while leaving a clear
    # ~2mm gap before the main plate's front face at any mount tilt angle.
    tab_anchor_y = carrier_center_y
    tab_box_depth = tab_anchor_y - ear.ear_tip_y + 0.20
    tab_body_y = (tab_anchor_y + ear.ear_tip_y - 0.20) / 2
    tab_body = make_box(
        CARRIER_TAB_WIDTH,
        tab_box_depth,
        EAR_HEIGHT,
        y=tab_body_y,
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

    # Shallow flat-bottomed pocket on the back face, aligned with the base's
    # adjustment boss, where the rod's ball tip bears.
    #
    # A deep socket shaped to closely match the ball's own radius (as a
    # mating sphere) only keeps contact for a tiny fraction of a degree of
    # tilt: as the carrier pivots about the ears' M3 axle, the pocket swings
    # through an arc and its height (Z) relative to the ball axis (which only
    # translates straight along Y, fixed at the base's hole height) drifts
    # away fast relative to the old BALL_SOCKET_CLEARANCE=0.30mm match-up.
    # A flat pad instead keeps a valid single-point contact at any carrier
    # angle (a sphere touching a plane always has a solution), so the pocket
    # only needs to be wide enough that the contact point's lateral travel
    # across the real working tilt range stays on the pad instead of running
    # off the rim into the surrounding full-thickness wall.
    adjustment_boss_z = PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP
    ball_socket = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, carrier_back_y, adjustment_boss_z),
            gp_Dir(0, -1, 0),
        ),
        BALL_SOCKET_PAD_RADIUS,
        BALL_SOCKET_DEPTH,
    ).Shape()

    # CSI ribbon clearance opening, shaped like an "L" in side view:
    #   - a full through-slot for the lower leg, from the carrier's bottom
    #     edge (flush with the shelf top, where it continues into the
    #     shelf's CABLE_PASSAGE) up to just below the ball-socket pocket, so
    #     the ribbon's path is an actual visible opening, not just a shallow
    #     cosmetic recess;
    #   - a shallow groove for the short upper leg, cut only into the board
    #     plate's front face (PCB side) from there up past the FPC
    #     connector's height, kept on the opposite face from ball_socket so
    #     the two pockets never meet even where their Z ranges overlap.
    pcb_bottom_z = hole_bottom_z - ((CAM_PCB_HEIGHT - CAM_MOUNT_HOLE_SPACING) / 2)
    connector_center_z = pcb_bottom_z + FPC_CONNECTOR_OFFSET_FROM_PCB_BOTTOM
    channel_top_z = connector_center_z + CARRIER_CABLE_CHANNEL_MARGIN_ABOVE_CONNECTOR
    ball_socket_bottom_z = adjustment_boss_z - BALL_SOCKET_PAD_RADIUS
    channel_through_top_z = ball_socket_bottom_z - CARRIER_CABLE_CHANNEL_CLEAR_MARGIN
    cable_channel_through = make_box(
        CARRIER_CABLE_CHANNEL_WIDTH,
        CARRIER_THICKNESS + 2,
        channel_through_top_z - MATERIAL_THICKNESS,
        y=carrier_center_y,
        z=MATERIAL_THICKNESS,
    )
    cable_channel_groove = make_box(
        CARRIER_CABLE_CHANNEL_WIDTH,
        CARRIER_CABLE_CHANNEL_DEPTH,
        channel_top_z - channel_through_top_z,
        y=carrier_front_y + (CARRIER_CABLE_CHANNEL_DEPTH / 2),
        z=channel_through_top_z,
    )

    carrier = cut(carrier, pivot_hole)
    carrier = cut(cut(carrier, top_left_hole), top_right_hole)
    carrier = cut(cut(carrier, bottom_left_hole), bottom_right_hole)
    carrier = cut(carrier, ball_socket)
    carrier = cut(carrier, cable_channel_through)
    return cut(carrier, cable_channel_groove)


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


def make_external_thread(
    root_radius: float,
    pitch: float,
    depth: float,
    length: float,
    start_z: float,
) -> TopoDS_Shape:
    """Sweep a triangular V-profile along a helix to cut a real printable
    external thread on a rod, starting at z=start_z and running +Z for
    `length` along a cylinder of the given root (minor) radius."""
    n_turns = length / pitch
    axis = gp_Ax3(gp_Pnt(0, 0, start_z), gp_Dir(0, 0, 1))
    cylinder = Geom_CylindricalSurface(axis, root_radius)
    # Cylindrical surface param space is (u=angle radians, v=height). The 2D
    # line's direction must be (angle_per_turn, height_per_turn) = (2*pi,
    # pitch) so one full turn (u += 2*pi) advances height by exactly one
    # pitch. gp_Dir2d normalizes the direction, so the edge's own parameter
    # "t" is arc-length, not u directly: solve for t_end so u(t_end) hits
    # the desired total angle.
    norm = math.hypot(2 * math.pi, pitch)
    t_end = n_turns * norm
    line2d = Geom2d_Line(gp_Lin2d(gp_Pnt2d(0.0, 0.0), gp_Dir2d(2 * math.pi, pitch)))
    helix_edge = BRepBuilderAPI_MakeEdge(line2d, cylinder, 0, t_end).Edge()
    BRepLib.BuildCurves3d_s(helix_edge)
    helix_wire = BRepBuilderAPI_MakeWire(helix_edge).Wire()

    half_width = (pitch / 2) - 0.05
    profile = BRepBuilderAPI_MakePolygon()
    profile.Add(gp_Pnt(root_radius, 0, start_z - half_width))
    profile.Add(gp_Pnt(root_radius + depth, 0, start_z))
    profile.Add(gp_Pnt(root_radius, 0, start_z + half_width))
    profile.Close()

    pipe = BRepOffsetAPI_MakePipeShell(helix_wire)
    pipe.Add(profile.Wire(), True, True)
    pipe.SetTransitionMode(BRepBuilderAPI_TransitionMode.BRepBuilderAPI_Transformed)
    pipe.Build()
    pipe.MakeSolid()
    return pipe.Shape()


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
    # Thread sits in the front part of the shaft (toward the ball/camera
    # end), spanning the plate's tapped hole across the adjustment travel
    # range; the rest of the shaft toward the drive-square stays a plain
    # shank that only needs clearance, not engagement.
    thread_start_z = (ROD_LENGTH / 2) - THREAD_LENGTH
    thread = make_external_thread(
        rod_radius,
        THREAD_PITCH,
        THREAD_DEPTH,
        THREAD_LENGTH,
        thread_start_z,
    )
    rod = fuse(rod, thread)
    ball = BRepPrimAPI_MakeSphere(
        gp_Pnt(0, 0, (ROD_LENGTH / 2) + (BALL_DIAMETER / 2) - BALL_OVERLAP),
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
    # Fine linear deflection (was 0.05) avoids tessellation gaps on swept
    # helical thread geometry that otherwise show up as non-watertight STL.
    BRepMesh_IncrementalMesh(model, 0.01, False, 0.1, True)
    writer = StlAPI_Writer()
    writer.Write(model, str(OUTPUT_DIR / filename))


if __name__ == "__main__":
    export_model(make_mount(), "pi_camera_tilt_base.stl")
    export_model(make_fit_test(), "fit_test_rear_cavity_30.45x38.2.stl")
    export_model(make_adjustment_rod(), "adjustment_rod_M5x50_ball6.5_square_m3.stl")
    export_model(make_wheel_crank(), "wheel_crank_50mm_square_m3.stl")
    export_model(make_camera_carrier(), "camera_carrier_v3_25x24_tab4.8.stl")
    export_model(make_camera_front_cover(), "camera_front_cover_v3_clip.stl")
