#!/usr/bin/env python3
"""Albedo from a baked car texture: remove the concept render's lighting.

Image-to-3D bakes the concept's shading into the texture: specular blobs,
shadow gradients, a lit side and a dark side. Under the game's own lighting that
reads as smears and dirt. This separates a smooth shading field from the texture
(a wide low-pass of the luminance, edge-aware so livery edges are kept) and
divides it out, then kills the remaining highlight blobs (texels far brighter
than their surroundings) by filling them from the neighbourhood colour.

    delight_texture.py in.png out.png [--sigma 24] [--report]

Also exposes `highlight_fraction(img)` and `shading_variance(img)` for the scorer.
"""
import argparse, sys
import numpy as np
from PIL import Image, ImageFilter


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def blur(a, sigma):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(sigma)), np.float32) / 255


def highlight_mask(rgb, sigma=12, k=1.25):
    """Specular blobs: texels far brighter than the bilateral low-pass of their own paint
    region. (A plain Gaussian low-pass flags every white panel next to black trim.)"""
    L = lum(rgb)
    S = bilateral_lum(L, sigma, sigma_r=0.15)
    return (L > k * S + 0.08) & (L > 0.6)


def highlight_fraction(rgb):
    """Share of texels that are specular blobs (lit far above their surroundings)."""
    return float(highlight_mask(rgb).mean())


def shading_variance(rgb, sigma=24):
    """Baked shading gradients: variance of the local bilateral low-pass of the luminance
    around the regional one (the paint level itself, black or white, does not count)."""
    L = lum(rgb)
    S_loc = bilateral_lum(L, sigma)
    S_reg = bilateral_lum(L, 128, sigma_r=0.12)
    return float(((S_loc - S_reg) ** 2).mean())


def bilateral_lum(L, sigma_s, sigma_r=0.1, bins=12, scale=4):
    """Fast bilateral low-pass of the luminance (piecewise-linear bilateral grid, at 1/scale
    resolution): smooths shading across texels of similar brightness but not across albedo
    edges, so a black underside next to white paint does not bleed a grey halo into either."""
    from scipy import ndimage
    H, W = L.shape
    small = np.asarray(Image.fromarray((np.clip(L, 0, 1) * 65535).astype(np.uint16)).resize((W // scale, H // scale), Image.BILINEAR),
                       np.float32) / 65535 if scale > 1 else L
    levels = np.linspace(0, 1, bins)
    num = []; den = []
    for l in levels:
        w = np.exp(-0.5 * ((small - l) / sigma_r) ** 2)
        num.append(ndimage.gaussian_filter(w * small, sigma_s / scale, mode='nearest'))
        den.append(ndimage.gaussian_filter(w, sigma_s / scale, mode='nearest'))
    planes = np.stack([n / np.maximum(d, 1e-6) for n, d in zip(num, den)], 0)       # bins x h x w
    if scale > 1:
        planes = np.stack([np.asarray(Image.fromarray(p_.astype(np.float32), 'F').resize((W, H), Image.BILINEAR)) for p_ in planes], 0)
    # interpolate between the two levels that bracket each texel's own luminance
    t = np.clip(L, 0, 1) * (bins - 1)
    i0 = np.clip(np.floor(t).astype(int), 0, bins - 2); f = t - i0
    yy, xx = np.indices(L.shape)
    return planes[i0, yy, xx] * (1 - f) + planes[i0 + 1, yy, xx] * f


def delight(rgb, sigma=24, strength=0.85, region_sigma=128):
    """rgb float [0,1] HxWx3 -> albedo-like rgb.

    Shading = the local bilateral low-pass of the luminance over the regional one: inside one
    paint region (similar brightness) the gradient a lit side and a shadowed side leave is
    divided out, while the regional level, i.e. the albedo, stays (black stays black, white stays
    white; the old global-median target turned black trim grey). Specular blobs are then filled
    from their non-blob surroundings (normalised convolution, so the blob does not feed its fill)."""
    from scipy import ndimage
    L = lum(rgb)
    S_loc = bilateral_lum(L, sigma)
    S_reg = bilateral_lum(L, region_sigma, sigma_r=0.12)
    gain = np.where(S_loc > 0.02, S_reg / np.maximum(S_loc, 0.02), 1.0)
    gain = 1.0 + strength * (gain - 1.0)
    gain = np.clip(gain, 0.6, 1.6)
    out = np.clip(rgb * gain[..., None], 0, 1)
    hm = highlight_mask(out)
    if hm.any():
        hm_d = ndimage.binary_dilation(hm, iterations=2)
        keep = (~hm_d).astype(np.float32)
        den = ndimage.gaussian_filter(keep, 6)
        fill = np.stack([ndimage.gaussian_filter(out[..., c] * keep, 6) for c in range(3)], -1) / np.maximum(den, 1e-3)[..., None]
        out = np.where(hm_d[..., None] & (den[..., None] > 0.05), fill, out)
    return np.clip(out, 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out'); ap.add_argument('--sigma', type=float, default=24)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()
    im = Image.open(a.src).convert('RGBA')
    arr = np.asarray(im, np.float32) / 255
    rgb, alpha = arr[..., :3], arr[..., 3:]
    before = (highlight_fraction(rgb), shading_variance(rgb))
    out = delight(rgb, a.sigma)
    after = (highlight_fraction(out), shading_variance(out))
    Image.fromarray((np.concatenate([out, alpha], -1) * 255).astype(np.uint8)).save(a.out)
    if a.report:
        print(f"highlights {before[0]*100:.2f}% -> {after[0]*100:.2f}%, shading var {before[1]:.4f} -> {after[1]:.4f}")


if __name__ == '__main__':
    main()
