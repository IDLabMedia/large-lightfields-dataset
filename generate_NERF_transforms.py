import os
import math
import numpy as np
import json
import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--dataset-config", type=str, required=True, help="dataset config file (i.e.: the 'lightfield.cfg' file).")
parser.add_argument("--subdir", type=str, required=False, help="path prefix to include in the filename paths")
parser.add_argument("--output-transforms", type=str, required=True, help="path to the transforms.json to produce.")
parser.add_argument("--scene", type=str,
        choices=["garden", "barbershop", "lone_monk", "kitchen"],
        help="A specific scene name that will be used to pick sane scaling/aabb defaults.")
parser.add_argument("--scale", type=float,
        help="A scale for NeRF to fit the unit cube.")
parser.add_argument("--extra-offset", type=float, nargs=3,
        help="A 3-vector that defines extra offset in NeRF coordinates")
parser.add_argument("--render-aabb", type=float, nargs=6,
        help="Two 3-vectors that define the AABB min and max in NeRF coordinates")
args = parser.parse_args()

names = []
positions = [] # camera positions in 3-tuples
rotations = [] # camera orientations in 3-tuples (degrees)

if args.dataset_config.endswith(".cfg"):
    # Load the stupid format.
    with open(args.dataset_config, "r") as file:
        def nextline():
            return file.readline().split(",")
        file.readline()
        resolution = [int(x) for x in nextline()]
        proj0 = [float(x) for x in nextline()]
        proj1 = [float(x) for x in nextline()]
        proj2 = [float(x) for x in nextline()]
        proj3 = [float(x) for x in nextline()]
        camera_lines = file.readlines()
        for cl in camera_lines:
            p = cl.split(",")
            names.append(p[0])
            positions.append([float(x) for x in p[1:4]])
            rotations.append([float(x) for x in p[4:]])

    print("proj matrix")
    print(proj0)
    print(proj1)
    print(proj2)
    print(proj3)

    camera_angle_x = 2.0 * np.arctan(1.0 / proj0[0])
    camera_angle_y = 2.0 * np.arctan(1.0 / proj1[1])
elif args.dataset_config.endswith(".json"):
    with open(args.dataset_config, "r") as file:
        cfg = json.load(file)
        cam_type = cfg['camera']['type']
        resolution = cfg['resolution']
        if cam_type == 'PERSP':
            proj = cfg['camera']['projection_matrix']
            camera_angle_x = 2.0 * np.arctan(1.0 / proj[0][0])
            camera_angle_y = 2.0 * np.arctan(1.0 / proj[1][1])
        else:
            # Not supported by Nerf
            raise NotImplementedError("Not supported by NerF")

        for fr in cfg['frames']:
            names.append(fr['name'])
            positions.append(fr['position'])
            rotations.append(fr['rotation'])
else:
    parser.print_usage()
    print("Not a valid config file given. Either .json (preferred) or .cfg (deprecated)")
    exit(1)

focal = [float(x) for x in resolution]
principal_point = [x * 0.5 for x in focal]
print("camera_angle_x", camera_angle_x, "rad =", camera_angle_x / np.pi * 180, "degrees")
print("camera_angle_y", camera_angle_y, "rad =", camera_angle_y / np.pi * 180, "degrees")
average_position = np.mean(positions, axis=0)
print("average_position", average_position)

def generate_transform_matrix(pos, rot):
    def Rx(theta):
      return np.matrix([[ 1, 0            , 0            ],
                        [ 0, np.cos(theta),-np.sin(theta)],
                        [ 0, np.sin(theta), np.cos(theta)]])
    def Ry(theta):
      return np.matrix([[ np.cos(theta), 0, np.sin(theta)],
                        [ 0            , 1, 0            ],
                        [-np.sin(theta), 0, np.cos(theta)]])
    def Rz(theta):
      return np.matrix([[ np.cos(theta), -np.sin(theta), 0 ],
                        [ np.sin(theta), np.cos(theta) , 0 ],
                        [ 0            , 0             , 1 ]])

    R = Rz(rot[2]) * Ry(rot[1]) * Rx(rot[0])
    xf_rot = np.eye(4)
    xf_rot[:3,:3] = R

    xf_pos = np.eye(4)
    xf_pos[:3,3] = pos # - average_position

    # barbershop_mirros_hd_dense:
    # - camera plane is y+z plane, meaning: constant x-values
    # - cameras look to +x

    # Don't ask me...
    extra_xf = np.matrix([
        [-1, 0, 0, 0],
        [ 0, 0, 1, 0],
        [ 0, 1, 0, 0],
        [ 0, 0, 0, 1]])
    # NerF will cycle forward, so lets cycle backward.
    shift_coords = np.matrix([
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]])
    xf = shift_coords @ extra_xf @ xf_pos
    assert np.abs(np.linalg.det(xf) - 1.0) < 1e-4
    xf = xf @ xf_rot
    return xf


average_position_transformed = np.transpose(np.mean([generate_transform_matrix(positions[i], [0,0,0])[:3,3] for i in range(len(names))], axis=0))
print("Average position transformed: ", average_position_transformed)

frames = [{
    "file_path": names[i] if args.subdir is None else os.path.join(args.subdir, names[i]),
    "transform_matrix": generate_transform_matrix(positions[i], rotations[i]).tolist(),
} for i in range(len(names))]

transforms_config = {
    "camera_angle_x": camera_angle_x,
    "scale": 0.2,
    "offset": [0.5, 0.5, 0.5],
}

if args.scene == "barbershop":
    transforms_config.update({
        "scale": 0.1,
        "offset": [0.5, 0.75, 0.5],
    })
elif args.scene == "garden":
    transforms_config.update({
        "scale": 0.1,
        "offset": [0.5, 0.5, 0.2],
    })
elif args.scene == "lone_monk":
    transforms_config.update({
        "scale": 0.03,
        "offset": [0.35, 0.5, 0.2]
    })
elif args.scene == "kitchen":
    transforms_config.update({
    "scale": 0.2,
    "offset": [0.2, 0.25, 0.5],
    })

if args.scale is not None:
    print("Overriding scale:", args.scale)
    transforms_config["scale"] = args.scale

offset = np.array(transforms_config["offset"]).squeeze()
offset -= transforms_config["scale"] * average_position_transformed.squeeze()
if args.extra_offset is not None:
    print("Apply extra offset:", args.extra_offset)
    offset += np.array(args.extra_offset)

transforms_config["offset"] = offset.tolist()

if args.render_aabb:
    transforms_config["render_aabb"] = [args.render_aabb[:3], args.render_aabb[3:]]

print()
print("Generating config:")
print(transforms_config)

transforms_config.update({
    "frames": frames,
    })


with open(args.output_transforms, "w") as outfile:
    json.dump(transforms_config, outfile, indent=4)
