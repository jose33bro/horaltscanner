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
BASE_WIDTH = 38.20
BASE_DEPTH = 30.45
BASE_HEIGHT = 3.20
SIDE_SCREW_PILOT_DIAMETER = 2.70
SIDE_SCREW_PILOT_DEPTH = 10.00
SIDE_SCREW_HEIGHT = 1.60

SIDE_WALL_THICKNESS = 3.20
SIDE_WALL_LENGTH = 24.00
SIDE_WALL_HEIGHT = 6.20

CAMERA_SUPPORT_WIDTH = 16.90
EAR_LENGTH = 8.70
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
    left_wall = make_box(
        SIDE_WALL_THICKNESS,
        SIDE_WALL_LENGTH,
        SIDE_WALL_HEIGHT,
        x=-wall_x,
        z=BASE_HEIGHT,
    )
    right_wall = make_box(
        SIDE_WALL_THICKNESS,
        SIDE_WALL_LENGTH,
        SIDE_WALL_HEIGHT,
        x=wall_x,
        z=BASE_HEIGHT,
    )

    ear_offset_y = (EAR_GAP + EAR_LENGTH) / 2
    front_ear = make_box(
        CAMERA_SUPPORT_WIDTH,
        EAR_LENGTH,
        EAR_HEIGHT,
        y=-ear_offset_y,
        z=BASE_HEIGHT,
    )
    rear_ear = make_box(
        CAMERA_SUPPORT_WIDTH,
        EAR_LENGTH,
        EAR_HEIGHT,
        y=ear_offset_y,
        z=BASE_HEIGHT,
    )

    mount = fuse(base, left_wall, right_wall, front_ear, rear_ear)
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
            gp_Pnt(0, -(EAR_GAP / 2) - EAR_LENGTH - 1, BASE_HEIGHT + (EAR_HEIGHT / 2)),
            gp_Dir(0, 1, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        (2 * EAR_LENGTH) + EAR_GAP + 2,
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
