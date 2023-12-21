import os
import math
import numpy as np
import json
import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--dataset-config", type=str, required=True, help="dataset config file (i.e.: the 'lightfield.json' file).")
parser.add_argument("--config-type", required=True, choices=["mpeg", "silvr"], help="Which config style is the input.")
parser.add_argument("--subdir", type=str, required=False, help="path prefix to include in the filename paths")
parser.add_argument("--output-transforms", type=str, required=True, help="path to the transforms.json to produce.")
parser.add_argument("--no-bananas", action='store_true', help='Assume NeRF_loader.h has no bananas transformations')
parser.add_argument("--inverse-transform-all", action='store_true', help='Inverse transform all cameras with their average transform.')
parser.add_argument("--scene", type=str,
        choices=["garden", "barbershop", "lone_monk", "kitchen", "painter"],
        help="A specific scene name that will be used to pick sane scaling/aabb defaults.")
parser.add_argument("--scale", type=float,
        help="A scale for NeRF to fit the unit cube.")
parser.add_argument("--aabb-scale", type=int, default=1,
        help="An int to scale up the unitcube in NeRF.")
parser.add_argument("--extra-offset", type=float, nargs=3,
        help="A 3-vector that defines extra offset in NeRF coordinates")
parser.add_argument("--render-aabb", type=float, nargs=6,
        help="Two 3-vectors that define the AABB min and max in NeRF coordinates")
args = parser.parse_args()

names = []
positions = [] # camera positions in 3-tuples
rotations = [] # camera orientations in 3-tuples (degrees)
camera_angle_x = None
fov_x_per_image = None

if args.config_type == "silvr":
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
        # Load the JSON rich format
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
        print("Not a valid SILVR config file given. Either .json (preferred) or .cfg (deprecated)")
        exit(1)
elif args.config_type == "mpeg":
    if args.dataset_config.endswith(".json"):
        with open(args.dataset_config, "r") as file:
            cfg = json.load(file)
            frames = cfg["cameras"]
            cam_type = None # first matched frame will fill in
            resolution = None
            if cam_type == "Perspective" or cam_type is None:
                fov_x_per_image = []
                fov_y_per_image = []
                cs_x = []
                cs_y = []
                for i in range(len(frames)):
                    fr = frames[i]
                    if fr["Name"] == "viewport":
                        continue
                    if cam_type is None and resolution is None:
                        cam_type = fr["Projection"]
                        resolution = fr["Resolution"]
                    assert fr["Projection"] == cam_type
                    assert fr["Resolution"] == resolution
                    fov_x = 2.0 * np.arctan(0.5 * resolution[0] / fr["Focal"][0])
                    fov_y = 2.0 * np.arctan(0.5 * resolution[1] / fr["Focal"][1])
                    fov_x_per_image.append(fov_x)
                    fov_y_per_image.append(fov_y)
                    cs_x.append(fr["Principle_point"][0])
                    cs_y.append(fr["Principle_point"][1])

                    names.append(fr["Name"])

                    # OMAF to Blender (Julie)
                    #pos_blender = [ -fr['Position'][1], fr['Position'][2], -fr['Position'][0] ]
                    #rot_blender = [ -fr['Rotation'][1], fr['Rotation'][0], -fr['Rotation'][2] ]

                    # OMAF to Blender (Martijn)
                    pos_blender = [  fr['Position'][1]   , -fr['Position'][0]    ,  fr['Position'][2] ]
                    rot_blender = [ -fr['Rotation'][1]-90, -fr['Rotation'][0]+180,  fr['Rotation'][2] ]

                    # to radians
                    rot_blender = [np.deg2rad(r) for r in rot_blender]

                    positions.append(pos_blender)
                    rotations.append(rot_blender)

                c_x = np.mean(cs_x, axis=0)
                c_y = np.mean(cs_y, axis=0)
            else:
                # Not supported by Nerf
                raise NotImplementedError("Not supported by NerF")


else:
    parser.print_usage()
    print("Not a valid config file type given.")
    exit(1)


focal = [float(x) for x in resolution]
principal_point = [x * 0.5 for x in focal]
if camera_angle_x is not None:
    print("camera_angle_x", camera_angle_x, "rad =", camera_angle_x / np.pi * 180, "degrees")
    print("camera_angle_y", camera_angle_y, "rad =", camera_angle_y / np.pi * 180, "degrees")
average_position = np.mean(positions, axis=0)
average_rotation = np.mean(rotations, axis=0)
print("average_position", average_position)
print("average_rotation", average_position)


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
    xf_pos[:3,3] = pos

    # barbershop_mirros_hd_dense:
    # - camera plane is y+z plane, meaning: constant x-values
    # - cameras look to +x

    if not args.no_bananas:
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
        total_xf = shift_coords @ extra_xf
        #print(total_xf)
        xf = total_xf @ xf_pos
    else:
        xf = xf_pos

    assert np.abs(np.linalg.det(xf) - 1.0) < 1e-4
    xf = xf @ xf_rot
    return xf


transformation_matrices = []
for i in range(len(positions)):
    transformation_matrices.append(generate_transform_matrix(positions[i], rotations[i]))

if args.inverse_transform_all:
    xf = generate_transform_matrix(average_position, average_rotation)
    xf_inv = np.linalg.inv(xf)
    for i in range(len(positions)):
        transformation_matrices[i] = xf_inv @ transformation_matrices[i]

# In NeRF cameras are upside down (y-up is pointing down, and z-up is pointing towards the scene)
# so, we'll append this final rotation after the transforms, as all
cameras_are_upside_down = np.array([
    [1, 0, 0, 0],
    [0,-1, 0, 0],
    [0, 0,-1, 0],
    [0, 0, 0, 1]])
for i in range(len(positions)):
    transformation_matrices[i] = transformation_matrices[i] @ cameras_are_upside_down

average_position_transformed = np.transpose(np.mean([generate_transform_matrix(positions[i], [0,0,0])[:3,3] for i in range(len(names))], axis=0))
print("Average position transformed: ", average_position_transformed)

def produce_frame(i):
    frame = {
        "file_path": names[i] if args.subdir is None else os.path.join(args.subdir, names[i]),
        "transform_matrix": transformation_matrices[i].tolist(),
    }
    if fov_x_per_image is not None:
        frame.update({
            "x_fov": np.rad2deg(fov_x_per_image[i]),
            "y_fov": np.rad2deg(fov_y_per_image[i]),
            "camera_angle_x": fov_x_per_image[i],
            "camera_angle_y": fov_y_per_image[i],
        })
    return frame
frames = [produce_frame(i) for i in range(len(names))]

transforms_config = {
    "w": resolution[0],
    "h": resolution[1],
    "scale": 0.2,
    "aabb_scale": args.aabb_scale,
    "offset": [0.5, 0.5, 0.5],
}
if camera_angle_x is not None:
    transforms_config["camera_angle_x"] = camera_angle_x
if args.config_type == "mpeg":
    transforms_config["c_x"] = c_x
    transforms_config["c_y"] = c_y


if args.scene is not None:
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
    elif args.scene == "painter":
        transforms_config.update({
            "scale": 0.2,
            "offset": [0.5, 0.5, 0.5],
        })

if args.scale is not None:
    print("Overriding scale:", args.scale)
    transforms_config["scale"] = args.scale

offset = np.zeros((3,))
#offset -= transforms_config["scale"] * average_position_transformed.squeeze()
offset += np.array(transforms_config["offset"]).squeeze()
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
