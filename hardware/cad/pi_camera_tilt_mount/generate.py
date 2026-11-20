from dataclasses import dataclass
from pathlib import Path
import math
import struct
from collections import Counter

import numpy as np
from verify_stl import DEGENERATE_AREA_MM2, analyse, load_stl

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
    BRepBuilderAPI_Transform,
    BRepBuilderAPI_TransitionMode,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
)
from OCP.Geom import Geom_CylindricalSurface
from OCP.Geom2d import Geom2d_Line
from OCP.StlAPI import StlAPI_Writer
from OCP.TopoDS import TopoDS_Shape, TopoDS_Wire
from OCP.gp import (
    gp_Ax1,
    gp_Ax2,
    gp_Ax3,
    gp_Dir,
    gp_Dir2d,
    gp_Lin2d,
    gp_Pnt,
    gp_Pnt2d,
    gp_Trsf,
    gp_Vec,
)


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

# Must be >= CARRIER_CABLE_CHANNEL_WIDTH (defined below, in the carrier's
# constants) so the CSI ribbon continues straight down through the shelf at
# its full width right under the carrier's through-slot, instead of necking
# down to a narrower opening and getting pinched/bent off-axis.
# Ribbon/connector span measured with the caliper (20.72 mm) + 0.30 mm clearance;
# the shelf passage was 16.00 (printed 15.85), too narrow for the connector.
CAM_FFC_SPAN = 20.72
CAM_FFC_SPAN_CLEARANCE = 0.30
CABLE_PASSAGE_WIDTH = CAM_FFC_SPAN + CAM_FFC_SPAN_CLEARANCE  # 21.02
CABLE_PASSAGE_HEIGHT = 5.00
CABLE_PASSAGE_Y_OFFSET = 8.00

EAR_PROJECTION = 8.70
EAR_WIDTH = 8.50
EAR_GAP = 5.33
EAR_HEIGHT = 5.99
PIVOT_CLEARANCE_DIAMETER = 3.40
# Adjustment rod and base hole: true ISO M5 x 0.8 (same thread as the ball
# screw). The base carries a modelled internal thread; the printed hole is
# sized for FDM: minor diameter 4.20 (nominal 4.13), bored to a 5.50 major
# diameter so the rod's 5.00 crest has 0.25 mm radial clearance.
THREAD_MAJOR_DIAMETER = 5.00
THREAD_PITCH = 0.80
THREAD_DEPTH = 0.50  # radial height of the triangular thread profile
THREAD_MINOR_DIAMETER = THREAD_MAJOR_DIAMETER - (2 * THREAD_DEPTH)
THREAD_LENGTH = 20.00
M5_HOLE_MINOR_DIAMETER = 4.20
M5_HOLE_MAJOR_DIAMETER = 5.50
M5_HOLE_RIDGE_DEPTH = 0.65  # ridge tip radius 2.75 - 0.65 = 2.10
M3_TAP_PILOT_DIAMETER = 2.70  # self-tapping M3 pilot in PLA
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
WHEEL_HUB_WIDTH = 10.00
WHEEL_HUB_LENGTH = 10.00
WHEEL_SOCKET_WIDTH = DRIVE_SQUARE_WIDTH + 0.20
WHEEL_SOCKET_DEPTH = 6.00  # 5 mm of protruding square + 1 mm slack
WHEEL_HUB_M3_CLEARANCE_DIAMETER = 3.20

# Camera carrier: holds the Pi Camera Module 3 (standard or NoIR, same PCB)
# and provides the hinge tab that slots between the base's ears on the M3
# pivot axle. Hole spacing/diameter match the official Camera Module 3
# mechanical drawing (25 x 24mm PCB, 21mm square hole pattern, ÃƒËœ2.5mm holes).
# Camera Module 3 NoIR Wide, measured with calipers by the user.
CAM_PCB_WIDTH = 25.16
CAM_PCB_HEIGHT = 24.16
CAM_TOTAL_THICKNESS = 10.86  # PCB + lens, measured
CAM_FIT_CLEARANCE_PER_SIDE = 0.17  # PLA clearance (0.15-0.20); housing = PCB + 2x
CAM_HOUSING_WIDTH = CAM_PCB_WIDTH + 2 * CAM_FIT_CLEARANCE_PER_SIDE  # 25.50
CAM_HOUSING_HEIGHT = CAM_PCB_HEIGHT + 2 * CAM_FIT_CLEARANCE_PER_SIDE  # 24.50

# Hole pitch X x Z: official Camera Module 3 drawing values (user decision:
# the datasheet is more precise than the caliper readings 20.87 / ~12.33).
CAM_MOUNT_HOLE_SPACING_X = 21.00
# The model used 21.00 along Z before, which was wrong.
CAM_MOUNT_HOLE_SPACING = 12.50
# Caliper reading 20.87 mm on the board back (connector width, interpretation
# unconfirmed); the carrier slot stays CARRIER_CABLE_CHANNEL_WIDTH since
# 20.87 + 0.30 would run into the M3 holes.
CAM_FFC_CONNECTOR_WIDTH = 20.87
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
# Measured on the strip next to the lens (user's photo; read as the FFC
# tongue, interpretation not confirmed).
CAM_FFC_WIDTH = 7.43
CAM_FFC_THICKNESS = 0.82
CAM_FFC_LENGTH = 8.88
# FFC connector height on the component side (user: "epaisseur nappe 2,45").
CAM_FFC_CONNECTOR_HEIGHT = 2.45
CAM_FFC_CONNECTOR_RELIEF = CAM_FFC_CONNECTOR_HEIGHT + 0.30  # 2.75 needed
CAM_FFC_LENGTH_CLEARANCE = 0.30
CAM_FFC_WIDTH_CLEARANCE = 0.30
CAM_FFC_THICKNESS_CLEARANCE = 0.20
# 16 mm stays: it must match the shelf's CABLE_PASSAGE_WIDTH and is
# far above the required 7.43 + 0.30 = 7.73 mm.
# Narrow section (between the upper mounting holes); the lower, wide section
# (CARRIER_CABLE_WIDE_WIDTH) sits below the lower mounting holes.
CARRIER_CABLE_CHANNEL_WIDTH = 16.00
CARRIER_CABLE_WIDE_WIDTH = CAM_FFC_SPAN + CAM_FFC_SPAN_CLEARANCE  # 21.02
CARRIER_CABLE_WIDE_HOLE_MARGIN = 0.50  # solid left under the lower holes
# Rear component relief pocket (front face of the carrier, PCB side).
# Through window (no blind pocket => no bridge/support needed printing face down):
# the back-face components (4.25 mm incl. PCB) sink into the open 9 mm gap behind.
CARRIER_COMPONENT_POCKET_WALL_X = 0.80  # solid left around the M3 holes
# Thicker rims (bosses) around the 4 camera mounting holes, on the carrier back
# face (away from the PCB/components, so no clash with them, the ribbon or lens).
# The 2.5 mm holes take the cover pins / M2 self-tapping screws.
CARRIER_REAR_HOOD_WALL = 1.20  # rear hood walls/skin closing the component pocket
CARRIER_HOLE_BOSS_DIAMETER = 4.50  # max: 25.5 mm carrier width limits it
CARRIER_HOLE_BOSS_HEIGHT = 3.00  # extra thickness behind the 2.00 mm carrier
CARRIER_HOLE_BOSS_END_WALL = 0.80  # blind hole: closed end, no support needed
assert CARRIER_CABLE_CHANNEL_WIDTH >= CAM_FFC_WIDTH + CAM_FFC_WIDTH_CLEARANCE
CARRIER_CABLE_CHANNEL_DEPTH = CAM_FFC_THICKNESS + CAM_FFC_THICKNESS_CLEARANCE  # 1.02
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
# Measured: bare PCB 1.06, board with components (connector side) 4.25,
# total with lens 10.86 (CAM_TOTAL_THICKNESS).
CAM_PCB_BARE_THICKNESS = 1.06
CAM_PCB_SLOT_CLEARANCE = 0.20
CAM_PCB_THICKNESS = CAM_PCB_BARE_THICKNESS + CAM_PCB_SLOT_CLEARANCE  # 1.26 slot
CAM_COMPONENT_HEIGHT = 4.25  # board + components, connector side (measured)
CAM_COMPONENT_CLEARANCE_DEPTH = CAM_COMPONENT_HEIGHT + 0.3  # rear relief budget
# Part 4 is a solid plate 5.36 mm thick (user), with 4 blind pin holes.
COVER_THICKNESS = 5.36
# Skirt (rim) on the cover's rear side wrapping the carrier board so 3+5 and 4 nest:
# inner opening = board + 2 x 0.15 mm, wall 1.2 mm, no supports (vertical walls).
COVER_SKIRT_CLEARANCE = 0.15
COVER_SKIRT_WALL = 1.20
COVER_RAIL_MIN_Z = 9.70  # above the base shelf lip (top at z 9.4)
# Camera pins now live on the carrier (3+5); the cover only has blind holes.
COVER_PIN_HOLE_DIAMETER = 2.25  # carrier pin 2.00 + 0.25: 0.125 mm/side insertion clearance
COVER_PIN_ENGAGEMENT = 1.20  # pin length inside the cover
COVER_PIN_HOLE_DEPTH = COVER_PIN_ENGAGEMENT + 0.20
# Lens window of the cover (part 4). Barrel ~8.5 mm is a VISUAL estimate (not
# measured); window = barrel + 2 x 0.45 clearance. Offsets are relative to the
# hole-pattern centre (+X right, +Z up; +Z = side away from the FPC connector).
# Single reference: official Camera Module 3 mechanical drawing (PDF vector
# data): holes 21 x 12.5, lens axis centred in X and 14.5 mm from the connector
# edge = on the far hole row, i.e. 12.5/2 - 0.1 = 6.15 mm above pattern centre.
# Which PCB edge is 'up' in the print is an assumption (connector at bottom).
LENS_BARREL_SIZE = 8.50
LENS_CLEARANCE_PER_SIDE = 0.45
LENS_HOLE_DIAMETER = LENS_BARREL_SIZE + 2 * LENS_CLEARANCE_PER_SIDE  # 9.40
# X: user observation - lens square and optic are centred between the two holes
# on the ribbon (connector) side, i.e. on the pattern centre line (x = 0).
LENS_OFFSET_X = 0.0
assert LENS_OFFSET_X == 0.0
# User caliper: lens square sits 4.11 mm from the connector-side PCB edge and
# 6.86 mm from the opposite (hole-side) edge => square = 24.16 - 4.11 - 6.86
# = 13.19 mm along Z, centred in X between the connector-side holes.
# Near hole row is assumed 2.0 mm from the connector edge (drawing, not
# certain). The earlier drawing reading (14.5 mm) CONTRADICTS this.
LENS_SQUARE_EDGE_FROM_CONNECTOR = 4.11
LENS_SQUARE_EDGE_FROM_HOLE_SIDE = 6.86
LENS_SQUARE_SIZE = (CAM_PCB_HEIGHT - LENS_SQUARE_EDGE_FROM_CONNECTOR
                    - LENS_SQUARE_EDGE_FROM_HOLE_SIDE)
CAM_HOLE_ROW_FROM_CONNECTOR_EDGE = 2.00
LENS_OFFSET_Z = (LENS_SQUARE_EDGE_FROM_CONNECTOR + LENS_SQUARE_SIZE / 2
                 - CAM_HOLE_ROW_FROM_CONNECTOR_EDGE - CAM_MOUNT_HOLE_SPACING / 2)
# Square recess on the cover's back face for the lens housing. The housing is
# the user's caliper square (13.19 mm along Z, see below); the recess adds a
# clearance per side so the housing edges stay at 4.11 / 6.86 mm from the PCB
# edges (measured and checked on the STL by verify_stl.py). Depth is capped by
# the front wall (>= 1.2 mm around the round window).
LENS_HOUSING_SIZE = LENS_SQUARE_SIZE
LENS_HOUSING_CLEARANCE = 0.20
LENS_RECESS_SIZE = LENS_HOUSING_SIZE + 2 * LENS_HOUSING_CLEARANCE  # 13.59
LENS_RECESS_FRONT_WALL = 1.20
# Cover redesign (user): square recess 11 mm along Z, its connector-side edge
# 4.69 mm from the cover's connector-side (bottom) edge; the round window is
# centred on it. Pin holes unchanged. Cover length 29.13 mm (was 24.50).
COVER_RECESS_Z = 11.00
COVER_RECESS_BOTTOM_FROM_EDGE = 4.69
COVER_LENGTH_Z = 29.13
LENS_RECESS_WIDTH_X = 14.00  # user: 13.59 'voir 14' mm across X (room for the lens connector)
LENS_RECESS_DEPTH = COVER_THICKNESS - LENS_RECESS_FRONT_WALL  # 4.16

# Barn doors (part 4 hood). The doors must sit IN FRONT of the lens glass, so
# a hollow standoff lifts the door frame above the barrel; the frame holds two
# guide layers (X doors behind, Z doors in front). Doors are flat plates that
# slide in slots open on the sides (friction fit, no screws).
LENS_PROTRUSION = (
    CAM_TOTAL_THICKNESS - CAM_PCB_BARE_THICKNESS - CAM_PCB_SLOT_CLEARANCE - COVER_THICKNESS
)  # lens glass above the cover front face (~8.0)
HOOD_LENS_GAP = 0.50
HOOD_STANDOFF_DEPTH = LENS_PROTRUSION + HOOD_LENS_GAP
HOOD_WALL = 1.60  # standoff wall thickness
DOOR_THICKNESS = 0.90
DOOR_SLOT_CLEARANCE = 0.20  # total, added to the slot thickness
DOOR_SLOT_MARGIN = 0.40  # total, added to the slot's other dimension
DOOR_RIB = 0.80  # solid layer between/in front of slots
DOOR_LENGTH = 10.0  # sliding direction
# Open aperture of the frame at the fully-open position. Sized so the
# 102 x 67 deg field of view is not clipped by the frame itself.
FRAME_BORE_WIDTH = 18.0
FRAME_BORE_HEIGHT = 17.0
DOOR_X_HEIGHT = FRAME_BORE_HEIGHT + 2.0  # left/right doors, Z extent
DOOR_Z_WIDTH = FRAME_BORE_WIDTH + 2.0  # top/bottom doors, X extent
DOOR_SLOT_DEPTH = DOOR_THICKNESS + DOOR_SLOT_CLEARANCE
DOOR_STACK_DEPTH = 2 * DOOR_SLOT_DEPTH + 2 * DOOR_RIB
# Closing travel: from fully open (door edge at the bore edge) to the axis.
DOOR_TRAVEL_X = FRAME_BORE_WIDTH / 2
DOOR_TRAVEL_Z = FRAME_BORE_HEIGHT / 2

# Turntable framing (user measurements, approximate)
TURNTABLE_DIAMETER_MM = 200.0
TURNTABLE_NEAR_EDGE_MM = (125.0, 135.0)   # camera -> nearest turntable edge
TURNTABLE_FAR_POINT_MM = (320.0, 520.0)   # farthest point, front..rear position
FOV_MARGIN = 1.10
DOOR_PLANE_AHEAD_OF_LENS_MM = 3.0         # assumed, not measured


def required_full_fov_deg(center_distance_mm):
    r = TURNTABLE_DIAMETER_MM / 2 * FOV_MARGIN
    return 2 * math.degrees(math.asin(r / center_distance_mm))


FOV_NEAR_DEG = required_full_fov_deg(TURNTABLE_NEAR_EDGE_MM[0] + TURNTABLE_DIAMETER_MM / 2)
FOV_FAR_DEG = required_full_fov_deg(TURNTABLE_FAR_POINT_MM[1] - TURNTABLE_DIAMETER_MM / 2)
# Door edge offset from the optical axis for each case
DOOR_EDGE_NEAR_MM = DOOR_PLANE_AHEAD_OF_LENS_MM * math.tan(math.radians(FOV_NEAR_DEG / 2))
DOOR_EDGE_FAR_MM = DOOR_PLANE_AHEAD_OF_LENS_MM * math.tan(math.radians(FOV_FAR_DEG / 2))
assert DOOR_TRAVEL_X >= FRAME_BORE_WIDTH / 2 - DOOR_EDGE_FAR_MM
assert DOOR_TRAVEL_Z >= FRAME_BORE_HEIGHT / 2 - DOOR_EDGE_FAR_MM
# Slightly undersized vs. CAM_MOUNT_HOLE_DIAMETER (2.50mm) for a snug push
# fit directly against the PCB's rigid holes.
# Pins on the carrier front face (3+5), exactly at the official 21 x 12.5 mm
# hole pattern: thin (2.0 vs ~2.2-2.5 mm camera holes), through the PCB slot
# then into the cover's blind holes.
CARRIER_PIN_DIAMETER = 2.00
CARRIER_PIN_TIP_DIAMETER = 1.20
CARRIER_PIN_TIP_LENGTH = 0.60  # ~45 deg lead-in
CARRIER_PIN_LENGTH = CAM_PCB_THICKNESS + COVER_PIN_ENGAGEMENT  # 2.46

# Camera support plate (28.05 x 7 x 1 mm, hardware/mechanical_specs.md) and the
# M5 x 0.8 ball screw that snaps into its 4-petal socket.
SUPPORT_LENGTH = 28.05
SUPPORT_WIDTH = 7.00
SUPPORT_THICKNESS = 1.00
SUPPORT_HOLE_SPACING = 14.00  # M3 holes on 14 mm centres (spec)
SUPPORT_SCREW_PILOT_DIAMETER = 2.70  # blind pilot in the carrier for the M3 screws
SUPPORT_SCREW_PILOT_DEPTH = 1.40  # carrier is 2 mm thick: stays closed on the PCB side
SUPPORT_SOCKET_DIAMETER = BALL_DIAMETER + 0.40  # 6.90 mm (spec)
SUPPORT_LIP_DIAMETER = BALL_DIAMETER - 0.50  # rim narrower than the ball: snap
SUPPORT_SHAFT_HOLE_DIAMETER = 5.30
PETAL_WALL = 1.20  # petal wall thickness (was 0.80, a petal snapped/curled)
SUPPORT_COLLAR_RADIUS = (SUPPORT_SOCKET_DIAMETER / 2) + PETAL_WALL
PETAL_HEIGHT = 4.00
PETAL_LIP_HEIGHT = 0.60
PETAL_CHAMFER = 0.50
PETAL_SLIT_WIDTH = 1.00
# 45 deg chamfer under the lip so the socket prints with no flat overhang.
PETAL_LIP_UNDERCUT = (SUPPORT_SOCKET_DIAMETER - SUPPORT_LIP_DIAMETER) / 2  # 0.45
BALL_SCREW_LENGTH = 40.00
BALL_SCREW_PITCH = 0.80  # ISO M5 coarse
BALL_SCREW_THREAD_DEPTH = 0.50
BALL_SCREW_ROOT_RADIUS = 2.50 - BALL_SCREW_THREAD_DEPTH
BALL_SCREW_THREAD_START = 1.50
BALL_SCREW_THREAD_LENGTH = 32.00
BALL_SCREW_BALL_RECESS = (BALL_DIAMETER - 5.00) / 2
BALL_SCREW_SLOT_LENGTH = 5.00
BALL_SCREW_SLOT_WIDTH = 0.80
BALL_SCREW_SLOT_DEPTH = 1.50

# Gauge for the support plate: pocket = plate + 0.2 mm per side.
PLATE_SLOT_WIDTH = SUPPORT_LENGTH + 0.40
PLATE_SLOT_DEPTH = SUPPORT_WIDTH + 0.40
SLOT_TEST_WALL = 3.00
SLOT_TEST_HEIGHT = 8.00
SLOT_TEST_FLOOR = 2.00
MERGED_BALL_POCKET_RADIUS = 3.50  # > 2.65 mm shaft-hole radius that lets the ball dip in


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
    """Shared Pi Camera V3 mounting-hole positions (21.00 x 12.50 mm
    pattern), used by both the carrier and the front cache so pins/screws
    line up. The pattern centre stays where the old 21 mm square sat, so the
    PCB outline, cover and ribbon geometry do not move."""
    hole_center_z = ear.ear_z - 1.50 - 10.50
    hole_top_z = hole_center_z + CAM_MOUNT_HOLE_SPACING / 2
    hole_bottom_z = hole_center_z - CAM_MOUNT_HOLE_SPACING / 2
    return CameraHoleLayout(
        mount_hole_x=CAM_MOUNT_HOLE_SPACING_X / 2,
        hole_top_z=hole_top_z,
        hole_bottom_z=hole_bottom_z,
        hole_center_z=hole_center_z,
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
    # z starts at 0 (the shelf's own bottom face), not MATERIAL_THICKNESS/2:
    # starting mid-thickness left a solid 1.6mm floor under the ribbon,
    # turning this into a shallow top-side groove instead of an actual
    # through-slot. Starting at the shelf's bottom guarantees a clean cut
    # through its full MATERIAL_THICKNESS, flush with the carrier's own
    # through-slot which starts right above at z=MATERIAL_THICKNESS.
    cable_passage = make_box(
        CABLE_PASSAGE_WIDTH,
        shelf_depth + 2,
        CABLE_PASSAGE_HEIGHT,
        y=shelf_front_y + CABLE_PASSAGE_Y_OFFSET,
        z=0,
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
    notch_outer_x = (CAM_HOUSING_WIDTH / 2) + CARRIER_WALL_CLEARANCE
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
        CAM_HOUSING_WIDTH,
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
        M5_HOLE_MAJOR_DIAMETER / 2,
        MATERIAL_THICKNESS + 2,
    ).Shape()
    # Internal M5 x 0.8 thread: the hole is bored to the major diameter and a
    # helical ridge (same helix as the rod's external thread, pointing
    # inward) is fused back into the wall. A swept solid used as a cutting
    # tool made the OCC boolean return an unchanged plate, so it is added.
    ridge = make_external_thread(
        M5_HOLE_MAJOR_DIAMETER / 2,
        THREAD_PITCH,
        M5_HOLE_RIDGE_DEPTH,
        MATERIAL_THICKNESS,
        0.0,
        inward=True,
    )
    to_hole = gp_Trsf()
    to_hole.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
    ridge = BRepBuilderAPI_Transform(ridge, to_hole, True).Shape()
    move = gp_Trsf()
    move.SetTranslation(
        gp_Vec(0, plate_front_y, PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP)
    )
    m5_thread_ridge = BRepBuilderAPI_Transform(ridge, move, True).Shape()
    csi_slot = make_box(
        CSI_SLOT_WIDTH,
        MATERIAL_THICKNESS + 2,
        CSI_SLOT_HEIGHT,
        y=CSI_SLOT_FRONT_OFFSET,
        z=CSI_SLOT_BOTTOM + (CSI_SLOT_HEIGHT / 2),
    )
    return fuse(cut(cut(cut(mount, pivot_hole), m5_thread_hole), csi_slot), m5_thread_ridge)


def make_camera_carrier(ball_pad_radius: float = BALL_SOCKET_PAD_RADIUS,
                        screw_pilots: bool = True) -> TopoDS_Shape:
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
        CAM_HOUSING_WIDTH,
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
        CARRIER_THICKNESS + 1 + CARRIER_HOLE_BOSS_HEIGHT - CARRIER_HOLE_BOSS_END_WALL,
    ).Shape()
    top_right_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_top_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 1 + CARRIER_HOLE_BOSS_HEIGHT - CARRIER_HOLE_BOSS_END_WALL,
    ).Shape()
    bottom_left_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_bottom_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 1 + CARRIER_HOLE_BOSS_HEIGHT - CARRIER_HOLE_BOSS_END_WALL,
    ).Shape()
    bottom_right_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(mount_hole_x, carrier_center_y - (CARRIER_THICKNESS / 2) - 1, hole_bottom_z),
            gp_Dir(0, 1, 0),
        ),
        CAM_MOUNT_HOLE_DIAMETER / 2,
        CARRIER_THICKNESS + 1 + CARRIER_HOLE_BOSS_HEIGHT - CARRIER_HOLE_BOSS_END_WALL,
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
        ball_pad_radius,
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
    # The 8.88 mm tongue is centred on the connector: keep half its length
    # (plus clearance) open above it, never less than the existing margin.
    channel_top_z = connector_center_z + max(
        CARRIER_CABLE_CHANNEL_MARGIN_ABOVE_CONNECTOR,
        (CAM_FFC_LENGTH + CAM_FFC_LENGTH_CLEARANCE) / 2,
    )
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
    # Connector window: through the carrier plate (limited by its 2 mm
    # thickness, less than CAM_FFC_CONNECTOR_RELIEF), stopping short of the
    # ball pocket on the back face.
    window_top_z = min(
        channel_top_z,
        adjustment_boss_z - ball_pad_radius - CARRIER_CABLE_CHANNEL_CLEAR_MARGIN,
    )
    connector_window = make_box(
        CAM_FFC_WIDTH + CAM_FFC_WIDTH_CLEARANCE,
        CARRIER_THICKNESS + 2,
        window_top_z - channel_through_top_z,
        y=carrier_center_y,
        z=channel_through_top_z,
    )

    # Wide through-slot under the lower mounting holes: passes the 20.72 mm
    # connector/ribbon span (the narrow 16 mm slot above stays between holes).
    wide_top_z = (
        hole_bottom_z - CAM_MOUNT_HOLE_DIAMETER / 2 - CARRIER_CABLE_WIDE_HOLE_MARGIN
    )
    cable_channel_wide = make_box(
        CARRIER_CABLE_WIDE_WIDTH,
        CARRIER_THICKNESS + 2,
        wide_top_z - MATERIAL_THICKNESS,
        y=carrier_center_y,
        z=MATERIAL_THICKNESS,
    )
    # Component relief: board back components (up to 4.25 mm) cannot fit in a
    # 2 mm carrier, so recess the PCB side between the holes as far as the
    # wall allows (the carrier front is already pressed against the PCB).
    pocket_half_x = mount_hole_x - CAM_MOUNT_HOLE_DIAMETER / 2 - CARRIER_COMPONENT_POCKET_WALL_X
    pocket_bottom_z = wide_top_z
    pocket_top_z = hole_top_z - CAM_MOUNT_HOLE_DIAMETER / 2 - CARRIER_COMPONENT_POCKET_WALL_X
    component_pocket = make_box(
        2 * pocket_half_x,
        CARRIER_THICKNESS + 2,
        pocket_top_z - pocket_bottom_z + 0.01,
        y=carrier_center_y,
        z=pocket_bottom_z - 0.01,
    )

    # Rear hood closing the upper part of the component pocket (above the
    # fused support plate): walls rise from the carrier back, a skin closes
    # the cavity at the full component depth. Printed back-down, so the
    # cavity opens upward: no overhang, no supports.
    hood_bottom_z = adjustment_boss_z + BALL_DIAMETER / 2 + 0.5  # clears the rod
    hood_top_z = pocket_top_z + CARRIER_REAR_HOOD_WALL
    hood_half_x = pocket_half_x + CARRIER_REAR_HOOD_WALL
    cavity_depth = CAM_COMPONENT_CLEARANCE_DEPTH - CAM_PCB_THICKNESS
    skin_back_y = carrier_front_y + cavity_depth + CARRIER_REAR_HOOD_WALL
    hood_outer = make_box(
        2 * hood_half_x,
        skin_back_y - carrier_back_y + 0.1,
        hood_top_z - hood_bottom_z,
        y=(skin_back_y + carrier_back_y - 0.1) / 2,
        z=hood_bottom_z,
    )
    hood_cavity = make_box(
        2 * pocket_half_x,
        cavity_depth + 1.0,
        pocket_top_z - hood_bottom_z + 1.0,
        y=carrier_front_y + (cavity_depth - 1.0) / 2,
        z=hood_bottom_z - 1.0,
    )
    carrier = fuse(carrier, cut(hood_outer, hood_cavity))

    for bx in (-mount_hole_x, mount_hole_x):
        for bz in (hole_top_z, hole_bottom_z):
            carrier = fuse(
                carrier,
                BRepPrimAPI_MakeCylinder(
                    gp_Ax2(gp_Pnt(bx, carrier_back_y - 0.5, bz), gp_Dir(0, 1, 0)),
                    CARRIER_HOLE_BOSS_DIAMETER / 2,
                    CARRIER_HOLE_BOSS_HEIGHT + 0.5,
                ).Shape(),
            )

    carrier = cut(carrier, pivot_hole)
    carrier = cut(carrier, ball_socket)
    # Two M3 pilot holes (self-tapping in PLA) on the 14 mm centres of the
    # camera support plate, fixing it flat on the carrier back face.
    for sign in ((-1, 1) if screw_pilots else ()):
        carrier = cut(
            carrier,
            BRepPrimAPI_MakeCylinder(
                gp_Ax2(
                    gp_Pnt(sign * SUPPORT_HOLE_SPACING / 2, carrier_back_y + 1, adjustment_boss_z),
                    gp_Dir(0, -1, 0),
                ),
                SUPPORT_SCREW_PILOT_DIAMETER / 2,
                SUPPORT_SCREW_PILOT_DEPTH + 1,
            ).Shape(),
        )
    carrier = cut(carrier, cable_channel_through)
    carrier = cut(carrier, cable_channel_wide)
    carrier = cut(carrier, component_pocket)
    carrier = cut(carrier, connector_window)
    carrier = cut(carrier, cable_channel_groove)
    return fuse(carrier, *camera_pins(holes, carrier_center_y - CARRIER_THICKNESS / 2))


def camera_pins(holes, front_y: float) -> list[TopoDS_Shape]:
    """4 thin pins on the carrier front face (-Y), on the 21 x 12.5 pattern."""
    shaft_length = CARRIER_PIN_LENGTH - CARRIER_PIN_TIP_LENGTH
    pins = []
    for x in (-holes.mount_hole_x, holes.mount_hole_x):
        for z in (holes.hole_top_z, holes.hole_bottom_z):
            shaft = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(x, front_y + 0.2, z), gp_Dir(0, -1, 0)),
                CARRIER_PIN_DIAMETER / 2,
                shaft_length + 0.2,
            ).Shape()
            tip = BRepPrimAPI_MakeCone(
                gp_Ax2(gp_Pnt(x, front_y - shaft_length, z), gp_Dir(0, -1, 0)),
                CARRIER_PIN_DIAMETER / 2,
                CARRIER_PIN_TIP_DIAMETER / 2,
                CARRIER_PIN_TIP_LENGTH,
            ).Shape()
            pins.append(fuse(shaft, tip))
    return pins


def make_camera_front_cover(with_frame: bool = True) -> TopoDS_Shape:
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
    cover_bottom_z = ear.ear_z - CAM_HOUSING_HEIGHT

    cover_plate = make_box(
        CAM_HOUSING_WIDTH,
        COVER_THICKNESS,
        CAM_HOUSING_HEIGHT,
        y=cover_center_y,
        z=cover_bottom_z,
    )
    # Side rails (left/right) wrap the carrier board edges; they start above
    # the base shelf lip (COVER_RAIL_MIN_Z) and the carrier is wider than the
    # camera at the bottom/top, so no top/bottom rails.
    rail_z0 = COVER_RAIL_MIN_Z
    rail_h = cover_bottom_z + CAM_HOUSING_HEIGHT - rail_z0
    skirt_depth = CAM_PCB_THICKNESS + 1.50
    rails = []
    for sign in (-1, 1):
        x_in = CAM_HOUSING_WIDTH / 2 + COVER_SKIRT_CLEARANCE
        x_out = x_in + COVER_SKIRT_WALL
        wing_in = CAM_HOUSING_WIDTH / 2 - 0.2
        rails.append(
            make_box(
                x_out - x_in,
                skirt_depth + 0.1,
                rail_h,
                x=sign * (x_in + x_out) / 2,
                y=cover_back_y + (skirt_depth - 0.1) / 2,
                z=rail_z0,
            )
        )
        rails.append(
            make_box(
                x_out - wing_in,
                COVER_THICKNESS,
                rail_h,
                x=sign * (wing_in + x_out) / 2,
                y=cover_center_y,
                z=rail_z0,
            )
        )
    cover_plate = fuse(cover_plate, *rails)
    cover_plate = fuse(
        cover_plate,
        make_box(
            CAM_HOUSING_WIDTH,
            COVER_THICKNESS,
            COVER_LENGTH_Z - CAM_HOUSING_HEIGHT,
            y=cover_center_y,
            z=cover_bottom_z + CAM_HOUSING_HEIGHT,
        ),
    )

    cover_front_y = cover_back_y - COVER_THICKNESS
    lens_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(LENS_OFFSET_X, cover_front_y - 1, cover_bottom_z + COVER_RECESS_BOTTOM_FROM_EDGE + COVER_RECESS_Z / 2),
            gp_Dir(0, 1, 0),
        ),
        LENS_HOLE_DIAMETER / 2,
        COVER_THICKNESS + 2,
    ).Shape()

    pin_holes = [
        BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(sx * holes.mount_hole_x, cover_back_y - COVER_PIN_HOLE_DEPTH, pz), gp_Dir(0, 1, 0)),
            COVER_PIN_HOLE_DIAMETER / 2,
            COVER_PIN_HOLE_DEPTH + 0.5,
        ).Shape()
        for sx in (-1, 1)
        for pz in (holes.hole_top_z, holes.hole_bottom_z)
    ]
    cover = cover_plate
    for pin_hole in pin_holes:
        cover = cut(cover, pin_hole)
    cover = cut(cover, lens_hole)
    lens_recess = make_box(
        LENS_RECESS_WIDTH_X,
        LENS_RECESS_DEPTH + 0.5,
        COVER_RECESS_Z,
        x=LENS_OFFSET_X,
        y=cover_back_y - LENS_RECESS_DEPTH / 2 + 0.25,
        z=cover_bottom_z + COVER_RECESS_BOTTOM_FROM_EDGE,
    )
    cover = cut(cover, lens_recess)
    if not with_frame:
        return cover

    axis_x = LENS_OFFSET_X
    axis_z = cover_bottom_z + COVER_RECESS_BOTTOM_FROM_EDGE + COVER_RECESS_Z / 2
    cover_center_z = cover_bottom_z + CAM_HOUSING_HEIGHT / 2
    standoff = cut(
        make_box(
            CAM_HOUSING_WIDTH,
            HOOD_STANDOFF_DEPTH,
            CAM_HOUSING_HEIGHT,
            y=cover_front_y - HOOD_STANDOFF_DEPTH / 2,
            z=cover_bottom_z,
        ),
        make_box(
            CAM_HOUSING_WIDTH - 2 * HOOD_WALL,
            HOOD_STANDOFF_DEPTH + 2,
            CAM_HOUSING_HEIGHT - 2 * HOOD_WALL,
            y=cover_front_y - HOOD_STANDOFF_DEPTH / 2,
            z=cover_bottom_z + HOOD_WALL,
        ),
    )

    stack_y0 = cover_front_y - HOOD_STANDOFF_DEPTH
    stack = make_box(
        CAM_HOUSING_WIDTH,
        DOOR_STACK_DEPTH,
        CAM_HOUSING_HEIGHT,
        y=stack_y0 - DOOR_STACK_DEPTH / 2,
        z=cover_bottom_z,
    )
    bore = make_box(
        FRAME_BORE_WIDTH,
        DOOR_STACK_DEPTH + 2,
        FRAME_BORE_HEIGHT,
        x=axis_x,
        y=stack_y0 - DOOR_STACK_DEPTH / 2,
        z=axis_z - FRAME_BORE_HEIGHT / 2,
    )
    # Rear layer: X doors (left/right), slot open through both sides.
    slot_x_doors = make_box(
        CAM_HOUSING_WIDTH + 2,
        DOOR_SLOT_DEPTH,
        DOOR_X_HEIGHT + DOOR_SLOT_MARGIN,
        y=stack_y0 - DOOR_SLOT_DEPTH / 2,
        z=axis_z - (DOOR_X_HEIGHT + DOOR_SLOT_MARGIN) / 2,
    )
    # Front layer: Z doors (top/bottom), slot open through top and bottom.
    slot_z_y = stack_y0 - DOOR_SLOT_DEPTH - DOOR_RIB
    slot_z_doors = make_box(
        DOOR_Z_WIDTH + DOOR_SLOT_MARGIN,
        DOOR_SLOT_DEPTH,
        CAM_HOUSING_HEIGHT + 2,
        x=axis_x,
        y=slot_z_y - DOOR_SLOT_DEPTH / 2,
        z=cover_bottom_z - 1,
    )
    stack = cut(cut(cut(stack, bore), slot_x_doors), slot_z_doors)
    return fuse(cover, standoff, stack)


def make_barn_door_x() -> TopoDS_Shape:
    """Left/right door (print 2x), flat: X = sliding length, Y = height."""
    return make_box(DOOR_LENGTH, DOOR_X_HEIGHT, DOOR_THICKNESS, z=0)


def make_barn_door_z() -> TopoDS_Shape:
    """Top/bottom door (print 2x), flat: X = width, Y = sliding length."""
    return make_box(DOOR_Z_WIDTH, DOOR_LENGTH, DOOR_THICKNESS, z=0)


def make_ball(center: gp_Pnt, radius: float) -> TopoDS_Shape:
    # Poles on the Y axis: the sphere's pole fans never sit on the contact tip
    # (+Z) where they used to produce degenerate triangles in the STL.
    return BRepPrimAPI_MakeSphere(
        gp_Ax2(center, gp_Dir(0, 1, 0), gp_Dir(1, 0, 0)), radius
    ).Shape()


def make_external_thread(
    root_radius: float,
    pitch: float,
    depth: float,
    length: float,
    start_z: float,
    inward: bool = False,
) -> TopoDS_Shape:
    """Sweep a triangular V-profile along a helix to make a printable
    thread ridge, starting at z=start_z and running +Z for `length` on a
    cylinder of the given root radius. Outward (rod) ridges point away from
    the axis; with inward=True (internal thread) they point toward it."""
    sgn = -1.0 if inward else 1.0
    # Keep the whole swept profile inside [start_z, start_z + length]: the
    # flanks overhanging the rod ends used to leave sliver faces (degenerate
    # triangles / non-manifold edges) where the sweep met the end caps.
    half_width = (pitch / 2) - 0.05
    # Sink the flank base 0.05 mm into the body so the helical sweep crosses
    # the cylinder transversally instead of lying exactly on it (that
    # coincidence left sliver triangles in the STL); tip radius unchanged.
    sink = 0.05
    root_radius -= sgn * sink
    depth += sink
    start_z += half_width
    length -= 2 * half_width
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

    # The profile base is buried in the core so the fuse never has to resolve
    # a tangent/coincident cylinder surface.
    embed = 0.2
    profile = BRepBuilderAPI_MakePolygon()
    # First vertex sits exactly on the root radius: MakePipeShell with
    # contact moves the profile so its first vertex touches the spine, so
    # starting inside the core would shift the whole flank outward by
    # `embed` (measured: crest diameter +0.4 mm too large before this fix).
    profile.Add(gp_Pnt(root_radius, 0, start_z - half_width))
    profile.Add(gp_Pnt(root_radius + sgn * depth, 0, start_z))
    profile.Add(gp_Pnt(root_radius, 0, start_z + half_width))
    profile.Add(gp_Pnt(root_radius - sgn * embed, 0, start_z + half_width))
    profile.Add(gp_Pnt(root_radius - sgn * embed, 0, start_z - half_width))
    profile.Close()

    pipe = BRepOffsetAPI_MakePipeShell(helix_wire)
    pipe.Add(profile.Wire(), False, False)
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
    thread_start_z = (ROD_LENGTH / 2) - THREAD_LENGTH - 1.0
    thread = make_external_thread(
        rod_radius,
        THREAD_PITCH,
        THREAD_DEPTH,
        THREAD_LENGTH,
        thread_start_z,
    )
    ball = make_ball(
        gp_Pnt(0, 0, (ROD_LENGTH / 2) + (BALL_DIAMETER / 2) - BALL_OVERLAP),
        BALL_DIAMETER / 2,
    )
    drive_square = make_box(
        DRIVE_SQUARE_WIDTH,
        DRIVE_SQUARE_WIDTH,
        DRIVE_SQUARE_LENGTH,
        z=-(ROD_LENGTH / 2) - (DRIVE_SQUARE_LENGTH / 2),
    )
    drive_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(0, 0, -(ROD_LENGTH / 2) - (DRIVE_SQUARE_LENGTH / 2) - 1),
            gp_Dir(0, 0, 1),
        ),
        M3_TAP_PILOT_DIAMETER / 2,
        DRIVE_SQUARE_LENGTH / 2 + 1 + 4,
    ).Shape()
    rod = fuse(rod, ball)
    rod = fuse(rod, thread)
    return cut(fuse(rod, drive_square), drive_hole)


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
    # Square socket for the rod's drive square (5 mm + 0.2 mm clearance),
    # open on the hub's free face.
    socket = make_box(
        WHEEL_SOCKET_WIDTH,
        WHEEL_SOCKET_WIDTH,
        WHEEL_SOCKET_DEPTH + 1,
        z=-(WHEEL_HUB_LENGTH / 2) - 1,
    )
    return cut(cut(fuse(wheel, hub), hub_hole), socket)


def make_fit_test() -> TopoDS_Shape:
    return make_box(PLATE_WIDTH, MATERIAL_THICKNESS, PLATE_HEIGHT)


def make_cylinder_z(radius: float, z: float, height: float) -> TopoDS_Shape:
    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), radius, height
    ).Shape()


def make_plate_slot_fit_test() -> TopoDS_Shape:
    """Pocket gauge for the 28.05 x 7 mm camera support plate."""
    block = make_box(
        PLATE_SLOT_WIDTH + 2 * SLOT_TEST_WALL,
        PLATE_SLOT_DEPTH + 2 * SLOT_TEST_WALL,
        SLOT_TEST_HEIGHT,
    )
    pocket = make_box(
        PLATE_SLOT_WIDTH,
        PLATE_SLOT_DEPTH,
        SLOT_TEST_HEIGHT - SLOT_TEST_FLOOR + 1,
        z=SLOT_TEST_FLOOR,
    )
    return cut(block, pocket)


def make_ball_screw() -> TopoDS_Shape:
    """M5 x 0.8 screw with a 6.5 mm ball head (shaft along +Z, ball on top)."""
    shaft = make_cylinder_z(BALL_SCREW_ROOT_RADIUS, 0, BALL_SCREW_LENGTH)
    thread = make_external_thread(
        BALL_SCREW_ROOT_RADIUS,
        BALL_SCREW_PITCH,
        BALL_SCREW_THREAD_DEPTH,
        BALL_SCREW_THREAD_LENGTH,
        BALL_SCREW_THREAD_START,
    )
    ball = make_ball(
        gp_Pnt(0, 0, BALL_SCREW_LENGTH - BALL_SCREW_BALL_RECESS),
        BALL_DIAMETER / 2,
    )
    driver_slot = make_box(
        BALL_SCREW_SLOT_LENGTH,
        BALL_SCREW_SLOT_WIDTH,
        BALL_SCREW_SLOT_DEPTH + 1,
        z=-1,
    )
    return cut(fuse(shaft, thread, ball), driver_slot)


def make_camera_support_plate(screw_holes: bool = True) -> TopoDS_Shape:
    """28.05 x 7 x 1 mm plate with a 4-petal snap-fit socket for the ball."""
    plate = make_box(SUPPORT_LENGTH, SUPPORT_WIDTH, SUPPORT_THICKNESS)
    collar = make_cylinder_z(
        SUPPORT_COLLAR_RADIUS, SUPPORT_THICKNESS - 0.2, PETAL_HEIGHT + 0.2
    )
    body = fuse(plate, collar)
    top = SUPPORT_THICKNESS + PETAL_HEIGHT
    lip_z = top - PETAL_LIP_HEIGHT
    bore = make_cylinder_z(
        SUPPORT_SOCKET_DIAMETER / 2,
        SUPPORT_THICKNESS,
        lip_z - PETAL_LIP_UNDERCUT - SUPPORT_THICKNESS,
    )
    under_chamfer = BRepPrimAPI_MakeCone(
        gp_Ax2(gp_Pnt(0, 0, lip_z - PETAL_LIP_UNDERCUT), gp_Dir(0, 0, 1)),
        SUPPORT_SOCKET_DIAMETER / 2,
        SUPPORT_LIP_DIAMETER / 2,
        PETAL_LIP_UNDERCUT,
    ).Shape()
    lip_hole = make_cylinder_z(
        SUPPORT_LIP_DIAMETER / 2, top - PETAL_LIP_HEIGHT, PETAL_LIP_HEIGHT + 1
    )
    shaft_hole = make_cylinder_z(
        SUPPORT_SHAFT_HOLE_DIAMETER / 2, -1, SUPPORT_THICKNESS + 2
    )
    chamfer = BRepPrimAPI_MakeCone(
        gp_Ax2(gp_Pnt(0, 0, top - PETAL_CHAMFER), gp_Dir(0, 0, 1)),
        SUPPORT_LIP_DIAMETER / 2,
        SUPPORT_LIP_DIAMETER / 2 + PETAL_CHAMFER,
        PETAL_CHAMFER,
    ).Shape()
    slit_x = make_box(
        SUPPORT_COLLAR_RADIUS * 2 + 2,
        PETAL_SLIT_WIDTH,
        PETAL_HEIGHT + 1,
        z=SUPPORT_THICKNESS,
    )
    slit_y = make_box(
        PETAL_SLIT_WIDTH,
        SUPPORT_COLLAR_RADIUS * 2 + 2,
        PETAL_HEIGHT + 1,
        z=SUPPORT_THICKNESS,
    )
    body = cut(body, bore)
    body = cut(body, under_chamfer)
    body = cut(body, lip_hole)
    body = cut(body, chamfer)
    body = cut(body, shaft_hole)
    body = cut(body, slit_x)
    body = cut(body, slit_y)
    for sign in ((-1, 1) if screw_holes else ()):
        body = cut(
            body,
            BRepPrimAPI_MakeCylinder(
                gp_Ax2(
                    gp_Pnt(sign * SUPPORT_HOLE_SPACING / 2, 0, -1),
                    gp_Dir(0, 0, 1),
                ),
                M3_CLEARANCE_DIAMETER / 2,
                SUPPORT_THICKNESS + 2,
            ).Shape(),
        )
    return body


def make_camera_carrier_with_plate() -> TopoDS_Shape:
    """Parts 3 + 5 in one printable solid, built in the assembled frame.

    The support plate (5) is placed exactly as assemble.py does (Rx(-90),
    base on the carrier back face, petals toward +Y), then trimmed to the
    carrier width so nothing hangs out at the sides (the 28.05 mm plate
    overhung the 25 mm carrier by 1.525 mm per side), and fused to the
    carrier. The ball pad pocket is narrowed to a 3.5 mm radius: the ball only
    dips into it through the 5.3 mm shaft hole, and a 12 mm wide pocket under
    the fused plate would be an unsupported bridge with enclosed supports."""
    ear = ear_geometry()
    carrier_back_y = ear.plate_front_y - CARRIER_STANDOFF_GAP
    boss_z = PLATE_HEIGHT - M5_THREAD_HOLE_OFFSET_FROM_TOP

    carrier = make_camera_carrier(ball_pad_radius=MERGED_BALL_POCKET_RADIUS, screw_pilots=False)

    rotate = gp_Trsf()
    rotate.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(0, carrier_back_y, boss_z))
    plate = BRepBuilderAPI_Transform(make_camera_support_plate(screw_holes=False), rotate, True).Shape()
    plate = BRepBuilderAPI_Transform(plate, move, True).Shape()

    side_cut_width = SUPPORT_LENGTH
    for sign in (-1, 1):
        plate = cut(
            plate,
            make_box(
                side_cut_width,
                SUPPORT_THICKNESS + PETAL_HEIGHT + 2,
                SUPPORT_WIDTH + 2,
                x=sign * (CAM_HOUSING_WIDTH / 2 + side_cut_width / 2),
                y=carrier_back_y + (SUPPORT_THICKNESS + PETAL_HEIGHT) / 2,
                z=boss_z - SUPPORT_WIDTH / 2 - 1,
            ),
        )
    return fuse(carrier, plate)


def repair_stl(path: Path, tolerance: float = 0.02) -> None:
    """Weld vertices closer than `tolerance` mm and drop collapsed triangles.

    The OpenCascade mesher leaves micron-sized cracks and sliver triangles
    where a swept helical thread meets its core cylinder (non-manifold edges
    in the slicer). Welding those few vertices closes the cracks without
    changing the shape visibly (0.02 mm is far below print resolution)."""
    tris = load_stl(path)
    points = np.round(tris.reshape(-1, 3), 5)
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    parent = list(range(len(unique)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Only vertices on open/non-manifold edges are candidates for welding, so
    # intact regions (sphere poles, seams) are never touched.
    faces = inverse.reshape(-1, 3)
    directed = Counter()
    for a, b, c in faces:
        directed[(a, b)] += 1
        directed[(b, c)] += 1
        directed[(c, a)] += 1
    candidates = {
        v
        for (a, b), n in directed.items()
        if n != 1 or directed.get((b, a), 0) != 1
        for v in (a, b)
    }
    slivers = 0.5 * np.linalg.norm(
        np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1
    ) < DEGENERATE_AREA_MM2
    candidates.update(int(v) for v in faces[slivers].reshape(-1))

    cells: dict[tuple[int, int, int], list[int]] = {}
    for idx in sorted(candidates):
        p = unique[idx]
        cell = tuple(np.floor(p / tolerance).astype(int))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    key = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                    for other in cells.get(key, ()):
                        if np.linalg.norm(unique[other] - p) < tolerance:
                            parent[find(idx)] = find(other)
        cells.setdefault(cell, []).append(idx)

    roots = np.array([find(i) for i in range(len(unique))])
    welded = unique.copy()
    for root in np.unique(roots):
        members = roots == root
        if members.sum() > 1:
            welded[members] = unique[members].mean(axis=0)
    new_tris = welded[roots[inverse]].reshape(-1, 3, 3)
    face_roots = roots[inverse].reshape(-1, 3)
    keep = (
        (face_roots[:, 0] != face_roots[:, 1])
        & (face_roots[:, 1] != face_roots[:, 2])
        & (face_roots[:, 0] != face_roots[:, 2])
    )
    new_tris = new_tris[keep]
    cross = np.cross(new_tris[:, 1] - new_tris[:, 0], new_tris[:, 2] - new_tris[:, 0])
    norms = np.linalg.norm(cross, axis=1)
    new_tris, cross, norms = new_tris[norms > 2e-9], cross[norms > 2e-9], norms[norms > 2e-9]
    normals = cross / norms[:, None]
    with open(path, "wb") as handle:
        handle.write(b"repaired by generate.py".ljust(80, b" "))
        handle.write(struct.pack("<I", len(new_tris)))
        for normal, tri in zip(normals, new_tris):
            handle.write(struct.pack("<12fH", *normal, *tri.reshape(-1), 0))


def export_model(model: TopoDS_Shape, filename: str) -> None:
    if not BRepCheck_Analyzer(model).IsValid():
        raise ValueError(f"Invalid solid: {filename}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Fine linear deflection (was 0.05) avoids tessellation gaps on swept
    # helical thread geometry that otherwise show up as non-watertight STL.
    BRepMesh_IncrementalMesh(model, 0.01, False, 0.1, True)
    writer = StlAPI_Writer()
    target = OUTPUT_DIR / filename
    writer.Write(model, str(target))
    info = analyse(load_stl(target))
    if info["degenerate"] or info["bad_edges"]:
        repair_stl(target)
        info = analyse(load_stl(target))
    if info["degenerate"] or info["bad_edges"] or info["volume"] <= 0:
        raise ValueError(f"STL is not a closed manifold: {filename}: {info}")


if __name__ == "__main__":
    export_model(make_mount(), "pi_camera_tilt_base.stl")
    export_model(make_fit_test(), "fit_test_rear_cavity_30.45x38.2.stl")
    export_model(make_adjustment_rod(), "adjustment_rod_M5x50_ball6.5_square_m3.stl")
    export_model(make_wheel_crank(), "wheel_crank_50mm_square_m3.stl")
    export_model(make_camera_carrier_with_plate(), "camera_carrier_plate_v4_onepiece.stl")
    export_model(make_camera_front_cover(False), "camera_front_cover_v3_clip_no_frame.stl")
    export_model(make_camera_front_cover(True), "camera_front_cover_v3_clip_with_frame.stl")
    export_model(make_barn_door_x(), "camera_barn_door_x_x2.stl")
    export_model(make_barn_door_z(), "camera_barn_door_z_x2.stl")
    export_model(make_ball_screw(), "ball_screw_M5x40_ball6.5.stl")
    from stamp_stl_settings import stamp_all

    stamp_all()
