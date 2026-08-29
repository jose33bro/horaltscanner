from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
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

CAMERA_SUPPORT_HEIGHT_IN_EARS = 34.00
LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER = 5.30
LOWER_ADJUSTMENT_SCREW_MIN_EDGE_MARGIN = 3.00

EAR_PROJECTION = 8.70
EAR_WIDTH = 8.50
EAR_GAP = 5.33
EAR_HEIGHT = 5.99
PIVOT_CLEARANCE_DIAMETER = 3.40

CSI_SLOT_WIDTH_X = 18.00
CSI_SLOT_DEPTH_Y = 9.56


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
    lower_adjustment_screw_z = max(
        (LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER / 2)
        + LOWER_ADJUSTMENT_SCREW_MIN_EDGE_MARGIN,
        ear_center_z - CAMERA_SUPPORT_HEIGHT_IN_EARS,
    )
    # Drill the lower adjustment passage through the vertical plate thickness
    # (rear -> front), not across the mount width (left -> right).
    lower_adjustment_screw_x = 0.00
    lower_adjustment_screw_y = plate_back_y + 1.00
    lower_adjustment_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(lower_adjustment_screw_x, lower_adjustment_screw_y, lower_adjustment_screw_z),
            gp_Dir(0, -1, 0),
        ),
        LOWER_ADJUSTMENT_SCREW_CLEARANCE_DIAMETER / 2,
        MATERIAL_THICKNESS + 2,
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
