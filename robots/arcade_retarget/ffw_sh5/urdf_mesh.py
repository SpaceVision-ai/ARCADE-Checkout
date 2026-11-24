"""Shared geometry: vertex samples of URDF collision meshes."""
import os, struct, numpy as np, pinocchio as pin
import xml.etree.ElementTree as ET
def stl(p):
    b = open(p, "rb").read()
    if b[:5] == b"solid" and b"facet" in b[:300]: return np.array([[float(x) for x in l.split()[1:4]] for l in b.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")])
    n = struct.unpack("<I", b[80:84])[0]; return np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3).astype(float)
def link_meshes(urdf, mesh_root, names, k_finger=40, k_other=160):
    """[(link name, vertex samples in link coordinates)]."""
    out = []
    for l in ET.parse(urdf).getroot().iter("link"):
        if l.get("name") not in names: continue
        for c in l.iter("collision"):
            g = c.find("geometry")[0]; o = c.find("origin")
            if g.tag != "mesh": continue
            fp = g.get("filename").replace("package://", mesh_root)
            if not os.path.exists(fp): continue
            V = stl(fp) * np.array([float(x) for x in g.get("scale", "1 1 1").split()])
            if o is not None: V = V @ pin.utils.rpyToMatrix(*[float(x) for x in o.get("rpy", "0 0 0").split()]).T + np.array([float(x) for x in o.get("xyz", "0 0 0").split()])
            k = k_finger if "finger" in l.get("name") else k_other; V = V[np.linspace(0, len(V) - 1, min(k, len(V))).astype(int)]
            out.append((l.get("name"), V))
    return out
