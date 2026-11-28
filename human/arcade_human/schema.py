"""ARCADE-Checkout-Human dataset schema: names, layout and conventions shared by the reader and validator.

Covers 3-D body and hand motion, product 6-DoF trajectories, grasp/release events, per-hand
holding intervals, 2-D hand-object-interaction labels and segmentation masks.

Design rules
------------
* One frame, one clock: every 3-D quantity is in the canonical counter frame (see
  ``COORDINATE_FRAME``) and every per-frame array of an episode has the same length ``T``.
* Validity is explicit. A position whose ``valid`` flag is False is stored as NaN, never as a
  zero vector or a copied neighbour.
* Measured vs. derived is explicit where it matters (``body/filled``, ``hand/*/gap_filled``), and the product pose
  carries its per-frame agreement with the camera masks (``object/mask_iou``).
"""
from __future__ import annotations

from typing import Dict, Tuple

SCHEMA_NAME = "arcade_human"
SCHEMA_VERSION = "1.1.0"
#: per-episode archive of the segmentation masks: <view>/<track_id>/<frame>.png, stored uncompressed
MASKS_ZIP = "masks.zip"

# --------------------------------------------------------------------------- coordinate frame
COORDINATE_FRAME: Dict[str, str] = {
    "name": "counter",
    "handedness": "right",
    "x_axis": "forward: the direction the shopper faces, across the counter",
    "y_axis": "left of the shopper",
    "z_axis": "up, normal of the counter top",
    "origin": "on the counter top (z = 0), at the checkout-lane centroid",
    "position_unit": "meter",
    "rotation": "quaternion, order xyzw, scalar last",
    "pose_vector": "[x, y, z, qx, qy, qz, qw]",
}

# --------------------------------------------------------------------------- skeleton
# COCO-WholeBody (the definition the 2-D keypoint model emits). Face keypoints are not released.
BODY_JOINT_NAMES: Tuple[str, ...] = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_big_toe", "left_small_toe", "left_heel",
    "right_big_toe", "right_small_toe", "right_heel",
)
#: index of each released body joint in the 133-point COCO-WholeBody layout
BODY_SOURCE_INDICES: Tuple[int, ...] = tuple(range(23))

HAND_LANDMARK_NAMES: Tuple[str, ...] = (
    "wrist",
    "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
)
HAND_SOURCE_INDICES: Dict[str, Tuple[int, ...]] = {
    "left": tuple(range(91, 112)),
    "right": tuple(range(112, 133)),
}
N_BODY = len(BODY_JOINT_NAMES)
N_HAND = len(HAND_LANDMARK_NAMES)
SIDES: Tuple[str, str] = ("left", "right")

BODY_CONNECTIONS: Tuple[Tuple[int, int], ...] = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (0, 1), (0, 2), (1, 3), (2, 4),
)
HAND_CONNECTIONS: Tuple[Tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12), (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
)
HAND_WRIST, HAND_INDEX_MCP, HAND_MIDDLE_MCP, HAND_PINKY_MCP = 0, 5, 9, 17

WRIST_FRAME: Dict[str, str] = {
    "origin": "hand landmark 'wrist'",
    "x_axis": "wrist -> middle_mcp (along the fingers)",
    "y_axis": "right hand: pinky_mcp -> index_mcp; left hand: index_mcp -> pinky_mcp; "
              "orthogonalised against x",
    "z_axis": "x cross y: the back-of-hand normal (the palm faces -z) for both hands",
    "derived_from": "released hand landmarks (no extra measurement)",
}

# --------------------------------------------------------------------------- object
OBJECT_STATES: Dict[int, str] = {
    0: "rest_before",   # on the counter before the first grasp
    1: "held_left",
    2: "held_right",
    3: "rest_after",    # on the counter after a release
}
OBJECT_FRAME: Dict[str, str] = {
    "origin": "centre of the product mesh bounding box",
    "axes": "product axes; a cylinder's axis and a box's 'h' edge are the local z axis",
    "mesh": "objects/<product>/<product>_p<perm>.obj is already expressed in this frame, so "
            "world_vertex = R(q) @ mesh_vertex + p",
}

EVENT_KINDS: Tuple[str, ...] = ("grasp", "release")

# --------------------------------------------------------------------------- HDF5 layout
#: dataset path inside /episodes/<episode_id>/ -> (shape, dtype).
#: T = frames, E = events. Everything listed here is present in every episode.
EPISODE_LAYOUT: Dict[str, Tuple[str, str]] = {
    "frame_index": ("[T]", "int32"),
    "timestamp": ("[T]", "float64"),
    "body/position": ("[T,23,3]", "float32"),
    "body/confidence": ("[T,23]", "float32"),
    "body/valid": ("[T,23]", "bool"),
    "body/filled": ("[T,23]", "bool"),
    "hand/left/position": ("[T,21,3]", "float32"),
    "hand/left/confidence": ("[T,21]", "float32"),
    "hand/left/valid": ("[T,21]", "bool"),
    "hand/left/gap_filled": ("[T]", "bool"),
    "hand/right/position": ("[T,21,3]", "float32"),
    "hand/right/confidence": ("[T,21]", "float32"),
    "hand/right/valid": ("[T,21]", "bool"),
    "hand/right/gap_filled": ("[T]", "bool"),
    "wrist/left/pose": ("[T,7]", "float32"),
    "wrist/left/valid": ("[T]", "bool"),
    "wrist/right/pose": ("[T,7]", "float32"),
    "wrist/right/valid": ("[T]", "bool"),
    "object/pose": ("[T,7]", "float32"),
    "object/valid": ("[T]", "bool"),
    "object/state": ("[T]", "uint8"),
    "object/mask_iou": ("[T]", "float32"),
    "object/source": ("[T]", "str"),
    "interaction/left/holding": ("[T]", "bool"),
    "interaction/right/holding": ("[T]", "bool"),
    "interaction/left/carrying": ("[T]", "bool"),
    "interaction/right/carrying": ("[T]", "bool"),
    "interaction/left/hoi_holding": ("[T]", "bool"),
    "interaction/right/hoi_holding": ("[T]", "bool"),
    "interaction/left/hoi_confidence": ("[T]", "float32"),
    "interaction/right/hoi_confidence": ("[T]", "float32"),
    "events/frame": ("[E]", "int32"),
    "events/session_frame": ("[E]", "int32"),
    "events/hand": ("[E]", "str"),
    "events/kind": ("[E]", "str"),
}

#: attributes on /episodes/<episode_id>
EPISODE_ATTRS: Tuple[str, ...] = (
    "episode_id", "episode_index", "session_id", "fps", "n_frames",
    "source_frame_range", "core_window", "product", "product_shape", "product_dims",
    "product_mesh", "hands", "task_kind", "first_grasp_hand", "last_release_hand",
    "recognition", "n_scan_events", "check_passed", "check_failed",
)

#: the automatic quality check of the 3-D reconstruction: rule id -> what makes an episode fail it.
#: Every episode is released; ``check_passed`` is true when ``check_failed`` (the failed rule ids) is empty.
CHECK_RULES: Dict[str, str] = {
    "product_below_counter": "the product is below the counter top",
    "product_floating": "a resting product is not on the counter, or a carried product is away from the carrying hand",
    "resting_product_moves": "a resting product moves, tilts, stands upside down or is not on a stable face",
    "product_leaves_hand": "the carried product leaves the palm of the carrying hand",
    "product_slips_in_hand": "the carried product jumps in the hand from one frame to the next",
    "hand_product_gap": "a gap between hand and product at a grasp or a release",
    "product_jumps": "the product jumps between frames",
    "hand_in_product": "the hand is inside the product while carrying it",
    "product_pose_missing": "the product pose is unknown in too many frames",
    "product_vs_masks": "the posed product disagrees with its camera masks over the episode or over a run of frames",
    "held_product_vs_masks": "while carried well above the counter, the posed product disagrees with its camera masks",
    "held_product_axis": "while carried well above the counter, the long axis of the posed product disagrees with its masks",
}

#: release directory layout, relative to the release root
RELEASE_FILES: Dict[str, str] = {
    "meta/info.json": "dataset-level metadata, versions and conventions",
    "meta/episodes.jsonl": "one JSON object per episode (index of data/human_motion.hdf5)",
    "meta/products.json": "product catalogue: shape, dimensions, mesh variants",
    "meta/skeleton.json": "joint / landmark names and connectivity",
    "data/human_motion.hdf5": "all per-frame data, one group per episode",
    "objects/": "product meshes (OBJ + MTL + texture), one variant per axis permutation",
    "segmentation/": "per episode: instances.json and masks.zip, binary masks of the tracked objects (optional)",
}
