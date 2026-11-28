# Coordinate frames

## Counter frame (all 3-D data)

Every position and pose in the release is expressed in one right-handed, metric frame
attached to the self-checkout counter:

| axis | direction |
|---|---|
| `+x` | forward: the direction the shopper faces, across the counter |
| `+y` | the shopper's left |
| `+z` | up, normal of the counter top |

* The origin is on the counter top (`z = 0`), at the centre of the checkout lane.
* A product resting on the counter therefore has its centre at `z = half its height`
  (or its radius when a bottle lies on its side).
* Units are metres.
* Rotations are quaternions in `xyzw` order (scalar last). A pose vector is
  `[x, y, z, qx, qy, qz, qw]`.

Sanity values from the sample episodes:

| quantity | typical value |
|---|---|
| shoulder midpoint (median) | `x ≈ -0.5`, `z ≈ 0.7` (the shopper stands at `x < 0` and reaches forward) |
| left shoulder minus right shoulder | `Δy ≈ +0.39` |

The frame was fixed once for the capture rig. It was derived from the multi-view camera
calibration and refined so that resting products sit on `z = 0`. The camera intrinsics and
extrinsics are not released.

### Counter footprint

The counter top is the rectangle `x ∈ [-0.551, 0.057]`, `y ∈ [-0.840, 0.541]` (m) at `z = 0`:
a box around every resting product position of the session. It is recorded in
`meta/info.json -> counter` (`x0`, `x1`, `y0`, `y1`, `top_z`), and the robot datasets record the
same footprint.

Renders use it as the counter (`arcade_human.render.CAPTURE_COUNTER` holds the same values). The
footprint is inferred from the products, so the shopper's hips are just inside its near edge;
renders cut a recess there.

## Product frame

* The origin is the centre of the product mesh bounding box.
* A cylinder's axis, and a box's `h` edge, is the local `z` axis.
* `object/pose` maps product-frame points to the counter frame.

The mesh files in `objects/` are already in this frame (see [FORMAT.md](FORMAT.md#products-metaproductsjson-objects)).

## Wrist frame

* The origin is the `wrist` landmark.
* `x` points toward `middle_mcp`.
* `z` is the back-of-hand normal on both hands, so the palm faces `-z`.

Details are in [FORMAT.md](FORMAT.md#wrist-frame).

## Retargeting to a robot

A robot user typically chooses where the counter sits in the robot's world. They then apply
one rigid transform, `T_robot_world_from_counter`, to every pose. The counter top is at
`z = 0` here. In the [robot data](../../robots/docs/FORMAT.md#frames-and-time) the counter top is
0.80 m above the floor, an assumed height.
