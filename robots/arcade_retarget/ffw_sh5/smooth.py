"""Joint trajectory smoothing, so that joint motion stays within what the real robot can execute: 5-frame median (single-frame spikes) → Gaussian (σ 1 frame) → joint velocity limit (URDF velocity / fps, forward-backward average, so no lag) → joint limits."""
import numpy as np
from scipy.ndimage import median_filter, gaussian_filter1d

FPS = 19.94

def joints(Q, vel, lo, hi, sigma=1.0, fps=FPS):
    """Q (n, j) in radians, vel (j,) in rad/s. Returns the smoothed Q."""
    Q = np.asarray(Q, float)
    if len(Q) < 3: return Q.copy()
    Y = gaussian_filter1d(median_filter(Q, size=(5, 1), mode="nearest"), sigma, axis=0, mode="nearest"); lim = np.asarray(vel, float) / fps
    def clamp(Z):
        Z = Z.copy()
        for k in range(1, len(Z)): Z[k] = Z[k - 1] + np.clip(Z[k] - Z[k - 1], -lim, lim)
        return Z
    return np.clip((clamp(Y) + clamp(Y[::-1])[::-1]) / 2, lo, hi)

def clamp(Q, vel, lo, hi, fps=FPS):
    """Joint velocity limit (forward-backward average) and joint limits only."""
    Q = np.asarray(Q, float); lim = np.asarray(vel, float) / fps
    def c(Z):
        Z = Z.copy()
        for k in range(1, len(Z)): Z[k] = Z[k - 1] + np.clip(Z[k] - Z[k - 1], -lim, lim)
        return Z
    return np.clip((c(Q) + c(Q[::-1])[::-1]) / 2, lo, hi)
