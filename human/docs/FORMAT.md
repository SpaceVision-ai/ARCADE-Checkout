# ARCADE-Checkout-Human data format (schema `arcade_human` 1.0.0)

A release is a directory:

```
<release>/
├── meta/
│   ├── info.json          dataset-level metadata, conventions, versions, what is not included
│   ├── episodes.jsonl     one JSON object per episode (the index)
│   ├── products.json      product catalogue: shape, median dimensions, mesh variants
│   └── skeleton.json      joint / landmark names and connectivity
├── data/
│   └── human_motion.hdf5  all per-frame data, one group per episode
├── objects/<product>/     product meshes (OBJ + MTL + texture)
└── segmentation/<episode_id>/
    ├── instances.json     tracked objects and which one is the episode's product
    └── masks.zip          the masks: <view>/<track_id>/<frame>.png
```

All 3-D quantities share one frame and one unit. See [COORDINATES.md](COORDINATES.md).

## Episodes

An episode is one product handled by the shopper. It starts shortly before the first
grasp, while the product still rests on the counter, and ends after the product has been
put down again. (`J00000_left`, at the very start of the recording, is the one exception: the
product is already held in its first frame.) The release has 97 episodes from one capture
session with 5 products, at 19.94 fps: 14,802 episode frames, which cover 8,660 unique frames
(7.2 min) because episodes overlap (see below). They are the episodes that pass an automatic
quality check of the 3-D reconstruction ([METHOD.md](METHOD.md)).

`task_kind` says what the hands do in the episode's core window:

| `task_kind` | episodes | meaning |
|---|---|---|
| `pass` | 49 | both hands hold the product and it ends in the other hand |
| `both_hands` | 10 | both hands hold it, then the hand that picked it up puts it down |
| `one_hand` | 37 | one hand only (33 right, 4 left) |
| `repeated` | 1 | the product is put down and picked up again |

It is decided from the holding intervals inside the core window. The context frames around it
can show the end or the start of a neighbouring handling of the same product; those do not
count. `Episode.task` gives the kind as one sentence, in the form the robot dataset uses for its
language task (`arcade_human.tasks`).

`episode_id` (for example `J03826_left`) is a stable, opaque key, shared with the robot
dataset. Its number and hand label were assigned at segmentation: they are close to, but not
always equal to, `core_window[0]` and the first grasping hand. Use `source_frame_range`,
`core_window`, `first_grasp_hand` and `hands` for timing and hands. `episode_index` is the
0-based position in `meta/episodes.jsonl`, sorted by session time.

### `meta/episodes.jsonl`

| key | meaning |
|---|---|
| `episode_index`, `episode_id` | see above |
| `n_frames`, `duration_s` | episode length |
| `source_frame_range` | `[first, last]` session frame (inclusive) |
| `core_window` | `[start, end_excl)` session frames of the segmented action, without the lead-in and tail context |
| `product`, `product_shape`, `product_mesh` | product name, `cylinder` or `box`, mesh path relative to the release root |
| `hands`, `task_kind` | which hands held the product; `pass`, `both_hands`, `one_hand` or `repeated` (above) |
| `first_grasp_hand`, `last_release_hand` | the hand that picks the product up and the one that puts it down |
| `n_events`, `n_grasp`, `n_release`, `n_scan_events` | event counts |
| `object_mask_iou_median` | median agreement of the posed product with its camera masks (see `object/mask_iou`) |
| `hand_valid_frac` | fraction of valid hand landmarks per hand (including interpolated frames, see `gap_filled`) |
| `segmentation` | relative path of the episode's masks, or `null` |

## `data/human_motion.hdf5`

Root attributes: `schema_name`, `schema_version`, `release_version`, and `coordinate_frame` (JSON).

Each episode is the group `/episodes/<episode_id>`. `T` is the number of frames and `E` the
number of events. Every per-frame array has length `T`.

| dataset | shape, dtype | meaning |
|---|---|---|
| `frame_index` | `[T] int32` | session frame number (contiguous) |
| `timestamp` | `[T] float64` | seconds on the session clock, `frame_index / fps` |
| `body/position` | `[T,23,3] float32` | COCO-WholeBody body joints (names in `skeleton.json`). NaN where not valid |
| `body/confidence` | `[T,23] float32` | 2-D detector confidence of the triangulated joint |
| `body/valid` | `[T,23] bool` | the joint has a position: measured or filled from the body fit |
| `body/filled` | `[T,23] bool` | the joint was not seen in this frame and comes from the fitted skeleton (fixed bone lengths). Treat it as derived, not measured |
| `hand/{left,right}/position` | `[T,21,3] float32` | 21 hand landmarks (wrist, then thumb to pinky, MCP to tip). NaN where not valid |
| `hand/{left,right}/confidence` | `[T,21] float32` | detector confidence |
| `hand/{left,right}/valid` | `[T,21] bool` | landmark available |
| `hand/{left,right}/gap_filled` | `[T] bool` | the hand was not observed in this frame and was filled from its neighbours in joint-angle space. Treat it as derived, not measured |
| `wrist/{left,right}/pose` | `[T,7] float32` | wrist SE(3) `[x,y,z,qx,qy,qz,qw]`, derived from the hand landmarks (frame defined below). NaN where not valid |
| `wrist/{left,right}/valid` | `[T] bool` | the four landmarks were available and not degenerate |
| `object/pose` | `[T,7] float32` | product pose (product frame to counter frame) |
| `object/valid` | `[T] bool` | pose available (all frames in this release) |
| `object/state` | `[T] uint8` | `0` rest before the first grasp, `1` carried by the left hand, `2` carried by the right hand, `3` rest after a release. It names the one hand the product moves with; use `interaction/*/holding` for frames where both hands hold |
| `object/source` | `[T] str` | the phase of the fit: `rest_<k>` (resting; one pose per resting phase, on a stable face of the product, on the counter) or `held_<hand>` (carried by that hand, with a slowly varying grasp) |
| `object/mask_iou` | `[T] float32` | agreement of the posed product with its multi-view camera masks in this frame (silhouette IoU, 0 to 1); NaN where no mask was available |
| `interaction/{left,right}/holding` | `[T] bool` | the hand holds the product: from its grasp to its release event. During a hand-over both hands hold |
| `interaction/{left,right}/carrying` | `[T] bool` | the hand the product is attached to in the 6-DoF fit: the holding interval trimmed to firm contact, and at a hand-over the switch to the receiving hand. The robot retargeting follows it. It stays within a few frames of `holding` |
| `interaction/{left,right}/hoi_holding` | `[T] bool` | 2-D hand-object-interaction label: the detector agrees in at least 2 of 3 camera views (with hysteresis) |
| `interaction/{left,right}/hoi_confidence` | `[T] float32` | its confidence |
| `events/frame` | `[E] int32` | episode-relative frame of the event |
| `events/session_frame` | `[E] int32` | the same frame on the session clock |
| `events/hand` | `[E] str` | `left` or `right` |
| `events/kind` | `[E] str` | `grasp` or `release` |

Episode attributes. Values that are lists or dicts are stored as JSON strings, and
`arcade_human.reader` decodes them.

| attribute | meaning |
|---|---|
| `episode_id`, `episode_index`, `session_id`, `fps`, `n_frames` | identity and timing |
| `source_frame_range`, `core_window` | as in `episodes.jsonl` |
| `product`, `product_shape`, `product_dims` | name. Measured dimensions in metres: cylinder `{r, h}`, box `{l, w, h}` |
| `product_mesh` | mesh path, relative to the release root (see Products) |
| `hands`, `task_kind`, `first_grasp_hand`, `last_release_hand` | as in `episodes.jsonl` |
| `recognition` | product recognition: `predicted`, `score` (a distance; lower is a better match), `margin` (distance to the runner-up), `ranking`, `method`, `agrees_with_product` (97 of 97) |
| `n_scan_events` | number of scan events |

### Wrist frame

* Origin: landmark `wrist`.
* `x`: from `wrist` to `middle_mcp`, along the fingers.
* `y`: from `pinky_mcp` to `index_mcp` on the right hand, and from `index_mcp` to `pinky_mcp` on the left hand, orthogonalised against `x`.
* `z = x × y`: the back-of-hand normal. The palm faces `-z` on both hands.

The wrist pose adds no information beyond the landmarks. It is provided so that consumers
do not each derive their own.

### Grasp and release events

Events come from the segmentation step. They mark when a hand starts and stops holding the
episode's product. During a hand-over both hands can hold at once. `holding` intervals are
consistent with the events. The `hoi_holding` label is an independent 2-D signal and
can disagree with them, especially when the hand is near but not on the product.

## Products: `meta/products.json`, `objects/`

`products.json` maps each product name to:

* `shape`
* `dims_median_m`: median over the episodes. For boxes, `l`/`w`/`h` follow each episode's mesh
  variant (`h` is the extent along product `z`), so per-episode `product_dims` is the precise value
* `n_episodes`
* `meshes`: `{perm: {path}}`
* `mass_kg`, `friction`: not measured (`null`)

Each mesh is expressed in the **product frame**:

* the origin is the centre of the mesh bounding box;
* a cylinder's axis, and a box's `h` edge, is the local `z` axis;
* units are metres.

To place it in the scene, apply the pose:

```python
R, p = quat_xyzw_to_matrix(pose[3:]), pose[:3]
world_vertices = mesh_vertices @ R.T + p
```

`arcade_human.Episode.object_vertices_world(t)` does exactly this.

The tracker assigned each product mesh's axes to the product axes, recorded as a
permutation `perm`:

* product axis `i` is mesh axis `perm[i]`;
* for an odd permutation the product `x` axis is negated, so the map is always a proper
  rotation (`arcade_human.geometry.product_axes`).

Each assignment is baked into its own file, `<product>_p<perm>.obj`. Variants of one product
are the same mesh, rotated. None is mirrored, and texture coordinates are unchanged,
so printed labels read correctly. Meshes are approximate shapes reconstructed from photos,
not CAD.

A cylinder's pose is ambiguous about the rotation around its own axis where the printed label
is not visible.

## Segmentation masks

`segmentation/<episode_id>/masks.zip` holds one PNG per mask, `<view>/<track_id>/<frame>.png`, stored
uncompressed. The reader reads the zip directly (`ArcadeHuman.masks`, `product_mask`). To get the PNG files,
unpack it next to it: `unzip masks.zip -d masks`. The reader then uses the `masks/` folder.

* `<view>` is one of `left`, `right`, `top` (the top-down camera);
* `<frame>` is the **episode-relative** frame, zero-padded to 5 digits;
* each file is an 8-bit binary mask at full camera resolution (0 = background, 255 = object);
* a track has files only for the frames where the object was segmented.

`instances.json` contains:

* `instances`: cross-view groups of tracks, `{instance_id, tracks: {view: [track_id]}, first_frame, last_frame}`;
* `hero_instance`: the instance that is the episode's product;
* `hero_by_frame`: per episode-relative frame, which instance and view matched the product, with IoU.

RGB camera video will be released after de-identification.

## Validation

`arcade-human validate` checks the schema and three expectations:

* a resting product sits on the counter;
* a holding hand is near the product;
* the grasp/release events agree with the holding intervals.

On the full release it reports 0 errors and 2 warnings.

## Episode overlap

Episodes come from one continuous capture and overlap in time. Each carries lead-in and tail
context, and with two hands one product can be picked up while another is being put down.
Together, the 14,802 episode frames cover 8,660 unique session frames (7.2 min).

* Split by time with `arcade_human.splits.time_split`; it guarantees no shared frames between splits
  (full release: train 74 / val 8 / test 13 episodes, plus 2 that straddle a boundary).
* Hold out a product with `product_split`. By default it also drops train episodes that share
  frames with the held-out product's episodes (29 to 40 of them, depending on the product);
  `drop_overlapping=False` keeps them, and the shopper's motion then leaks into test.

## Reading without this package

The files are plain HDF5, JSON, OBJ and PNG:

```python
import h5py, json
f = h5py.File("samples/arcade_human_sample/data/human_motion.hdf5", "r")
g = f["episodes/J03826_left"]
hand = g["hand/right/position"][:]          # (T, 21, 3)
obj = g["object/pose"][:]                   # (T, 7)
dims = json.loads(g.attrs["product_dims"])
```
