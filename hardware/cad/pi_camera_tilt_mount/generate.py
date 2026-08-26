from pathlib import Path

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.StlAPI import StlAPI_Writer
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt


OUTPUT_DIR = Path(__file__).parent / "stl"

# Measurements taken from the existing removable white camera holder.
ORIGINAL_TONGUE_WIDTH = 27.89
ORIGINAL_TONGUE_DEPTH = 7.55
ORIGINAL_INSERTION_DEPTH = 16.08
ORIGINAL_HOLE_HEIGHT = 26.42

# FDM clearance for the replacement tongue.
TONGUE_WIDTH = 27.60
TONGUE_DEPTH = 7.30
TONGUE_HEIGHT = 16.00

HOLDER_WIDTH = 32.14
YOKE_WALL = 3.00
YOKE_CLEARANCE = 0.46
YOKE_INNER_WIDTH = HOLDER_WIDTH + YOKE_CLEARANCE
YOKE_OUTER_WIDTH = YOKE_INNER_WIDTH + (2 * YOKE_WALL)
YOKE_DEPTH = 10.00
BRIDGE_HEIGHT = 3.00

PIVOT_HEIGHT = TONGUE_HEIGHT + (
    ORIGINAL_HOLE_HEIGHT - ORIGINAL_INSERTION_DEPTH
)
PIVOT_FROM_FRONT = 2.00
PIVOT_Y = -(TONGUE_DEPTH / 2) + PIVOT_FROM_FRONT
PIVOT_CLEARANCE_DIAMETER = 3.40
PIVOT_TOP_MARGIN = 4.00
CSI_SLOT_WIDTH = 18.00
CSI_REAR_SPINE = 1.80


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


def make_csi_slot(height: float) -> TopoDS_Shape:
    slot_depth = YOKE_DEPTH - CSI_REAR_SPINE + 2
    slot_center_y = -(YOKE_DEPTH / 2) - 1 + (slot_depth / 2)
    return make_box(
        CSI_SLOT_WIDTH,
        slot_depth,
        height + 2,
        y=slot_center_y,
        z=-1,
    )


def make_mount() -> TopoDS_Shape:
    tongue = make_box(TONGUE_WIDTH, TONGUE_DEPTH, TONGUE_HEIGHT)
    bridge = make_box(
        YOKE_OUTER_WIDTH,
        YOKE_DEPTH,
        BRIDGE_HEIGHT,
        z=TONGUE_HEIGHT,
    )

    arm_height = PIVOT_HEIGHT + PIVOT_TOP_MARGIN - TONGUE_HEIGHT
    arm_z = TONGUE_HEIGHT
    arm_offset = (YOKE_INNER_WIDTH + YOKE_WALL) / 2
    left_arm = make_box(YOKE_WALL, YOKE_DEPTH, arm_height, x=-arm_offset, z=arm_z)
    right_arm = make_box(YOKE_WALL, YOKE_DEPTH, arm_height, x=arm_offset, z=arm_z)

    mount = fuse(tongue, bridge, left_arm, right_arm)
    mount = cut(mount, make_csi_slot(TONGUE_HEIGHT + BRIDGE_HEIGHT))
    pivot_hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(
            gp_Pnt(-(YOKE_OUTER_WIDTH / 2) - 1, PIVOT_Y, PIVOT_HEIGHT),
            gp_Dir(1, 0, 0),
        ),
        PIVOT_CLEARANCE_DIAMETER / 2,
        YOKE_OUTER_WIDTH + 2,
    ).Shape()
    return cut(mount, pivot_hole)


def make_fit_test() -> TopoDS_Shape:
    tongue = make_box(TONGUE_WIDTH, TONGUE_DEPTH, 6.00)
    stop = make_box(TONGUE_WIDTH + 6, TONGUE_DEPTH + 6, 2.00, z=6.00)
    return cut(fuse(tongue, stop), make_csi_slot(8.00))


def export_model(model: TopoDS_Shape, filename: str) -> None:
    if not BRepCheck_Analyzer(model).IsValid():
        raise ValueError(f"Invalid solid: {filename}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BRepMesh_IncrementalMesh(model, 0.05, False, 0.1, True)
    writer = StlAPI_Writer()
    writer.Write(model, str(OUTPUT_DIR / filename))


if __name__ == "__main__":
    export_model(make_mount(), "pi_camera_tilt_base.stl")
    export_model(make_fit_test(), "fit_test_27.6x7.3.stl")
