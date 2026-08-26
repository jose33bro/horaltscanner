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
BASE_HEIGHT = 7.00
SIDE_SCREW_PILOT_DIAMETER = 2.70
SIDE_SCREW_PILOT_DEPTH = 10.00
SIDE_SCREW_HEIGHT = 3.50

# Measurements taken from the existing removable white camera holder.
HOLDER_WIDTH = 32.14
PIVOT_HEIGHT = 26.42
YOKE_WALL = 2.80
YOKE_CLEARANCE = 0.46
YOKE_INNER_WIDTH = HOLDER_WIDTH + YOKE_CLEARANCE
YOKE_OUTER_WIDTH = YOKE_INNER_WIDTH + (2 * YOKE_WALL)
YOKE_DEPTH = BASE_DEPTH
PIVOT_FROM_FRONT = 2.00
PIVOT_Y = -(BASE_DEPTH / 2) + PIVOT_FROM_FRONT
PIVOT_CLEARANCE_DIAMETER = 3.40
PIVOT_TOP_MARGIN = 4.00


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
    arm_height = PIVOT_HEIGHT + PIVOT_TOP_MARGIN - BASE_HEIGHT
    arm_z = BASE_HEIGHT
    arm_offset = (YOKE_INNER_WIDTH + YOKE_WALL) / 2
    left_arm = make_box(YOKE_WALL, YOKE_DEPTH, arm_height, x=-arm_offset, z=arm_z)
    right_arm = make_box(YOKE_WALL, YOKE_DEPTH, arm_height, x=arm_offset, z=arm_z)

    mount = fuse(base, left_arm, right_arm)
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
            gp_Pnt(-(BASE_WIDTH / 2) - 1, PIVOT_Y, PIVOT_HEIGHT),
            gp_Dir(1, 0, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        BASE_WIDTH + 2,
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
