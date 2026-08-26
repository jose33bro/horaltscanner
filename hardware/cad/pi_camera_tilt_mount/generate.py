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
BASE_WIDTH = 30.45
BASE_DEPTH = 38.20
BASE_HEIGHT = 3.20
SIDE_SCREW_PILOT_DIAMETER = 2.70
SIDE_SCREW_PILOT_DEPTH = 10.00
SIDE_SCREW_HEIGHT = 1.60

SIDE_WALL_THICKNESS = 3.20
SIDE_WALL_LENGTH = 24.00
SIDE_WALL_HEIGHT = 6.20

LOWERED_CENTER_WIDTH = 16.90
LOWERED_CENTER_DROP = 5.00
EAR_PROJECTION = 8.70
EAR_WIDTH = 8.50
EAR_GAP = 5.33
EAR_HEIGHT = 5.99
PIVOT_CLEARANCE_DIAMETER = 3.40


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
    base = make_box(BASE_WIDTH, BASE_DEPTH, BASE_HEIGHT)
    wall_x = (BASE_WIDTH - SIDE_WALL_THICKNESS) / 2
    rear_y = BASE_DEPTH / 2
    wall_y = rear_y - (SIDE_WALL_LENGTH / 2)
    left_wall = make_box(
        SIDE_WALL_THICKNESS,
        SIDE_WALL_LENGTH,
        SIDE_WALL_HEIGHT,
        x=-wall_x,
        y=wall_y,
        z=BASE_HEIGHT,
    )
    right_wall = make_box(
        SIDE_WALL_THICKNESS,
        SIDE_WALL_LENGTH,
        SIDE_WALL_HEIGHT,
        x=wall_x,
        y=wall_y,
        z=BASE_HEIGHT,
    )

    center_height = SIDE_WALL_HEIGHT - LOWERED_CENTER_DROP
    center_support = make_box(
        LOWERED_CENTER_WIDTH,
        SIDE_WALL_LENGTH,
        center_height,
        y=wall_y,
        z=BASE_HEIGHT,
    )

    ear_radius = EAR_HEIGHT / 2
    ear_center_distance = EAR_PROJECTION - ear_radius
    front_y = -(BASE_DEPTH / 2)
    ear_tip_y = front_y - ear_center_distance
    ear_anchor_y = front_y + 1.00
    ear_box_depth = ear_anchor_y - ear_tip_y + 0.20
    ear_body_y = (ear_anchor_y + ear_tip_y - 0.20) / 2
    ear_x = (EAR_GAP + EAR_WIDTH) / 2
    left_ear_body = make_box(
        EAR_WIDTH,
        ear_box_depth,
        EAR_HEIGHT,
        x=-ear_x,
        y=ear_body_y,
        z=BASE_HEIGHT,
    )
    right_ear_body = make_box(
        EAR_WIDTH,
        ear_box_depth,
        EAR_HEIGHT,
        x=ear_x,
        y=ear_body_y,
        z=BASE_HEIGHT,
    )
    left_ear_round = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-ear_x - (EAR_WIDTH / 2), ear_tip_y, BASE_HEIGHT + ear_radius),
            gp_Dir(1, 0, 0),
        ),
        ear_radius,
        EAR_WIDTH,
    ).Shape()
    right_ear_round = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(ear_x - (EAR_WIDTH / 2), ear_tip_y, BASE_HEIGHT + ear_radius),
            gp_Dir(1, 0, 0),
        ),
        ear_radius,
        EAR_WIDTH,
    ).Shape()

    mount = fuse(
        base,
        left_wall,
        right_wall,
        center_support,
        left_ear_body,
        right_ear_body,
        left_ear_round,
        right_ear_round,
    )
    left_screw_pilot = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(BASE_WIDTH / 2) - 1, 0, SIDE_SCREW_HEIGHT),
            gp_Dir(1, 0, 0),
        ),
        SIDE_SCREW_PILOT_DIAMETER / 2,
        SIDE_SCREW_PILOT_DEPTH + 1,
    ).Shape()
    right_screw_pilot = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt((BASE_WIDTH / 2) + 1, 0, SIDE_SCREW_HEIGHT),
            gp_Dir(-1, 0, 0),
        ),
        SIDE_SCREW_PILOT_DIAMETER / 2,
        SIDE_SCREW_PILOT_DEPTH + 1,
    ).Shape()
    mount = cut(cut(mount, left_screw_pilot), right_screw_pilot)
    pivot_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(EAR_GAP / 2) - EAR_WIDTH - 1, ear_tip_y, BASE_HEIGHT + ear_radius),
            gp_Dir(1, 0, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        (2 * EAR_WIDTH) + EAR_GAP + 2,
    ).Shape()
    return cut(mount, pivot_hole)


def make_fit_test() -> TopoDS_Shape:
    return make_box(BASE_WIDTH, BASE_DEPTH, BASE_HEIGHT)


def export_model(model: TopoDS_Shape, filename: str) -> None:
    if not BRepCheck_Analyzer(model).IsValid():
        raise ValueError(f"Invalid solid: {filename}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BRepMesh_IncrementalMesh(model, 0.05, False, 0.1, True)
    writer = StlAPI_Writer()
    writer.Write(model, str(OUTPUT_DIR / filename))


if __name__ == "__main__":
    export_model(make_mount(), "pi_camera_tilt_base.stl")
    export_model(make_fit_test(), "fit_test_rear_cavity_38.2x30.45.stl")
