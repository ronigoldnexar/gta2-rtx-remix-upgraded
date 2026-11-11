#!/usr/bin/env python3
"""VEHICLE-ART-27: draw a finished kit body out along its length (the limousines 032 / 033 from 050 / 070).

warp(car, zsrc, zdst, sx=1.0): every vertex's z goes through the piecewise-linear station map zsrc -> zdst (knots
in metres, +z nose); keep the map's slope 1 over each wheel zone (axle +- arch + margin) so the tyres, rims and arches
move rigidly and stay round. x is scaled by sx (the sprite's width against the base's). Normals follow the inverse
transpose (n / (sx, 1, slope)); markers move with the map.

pillars(car, bands, seal=0.022): side glass (|n.x| > 0.45) inside each z band [z0, z1] (warped frame) becomes body
paint with a thin dark seal strip on both edges: a stretched window turns into several bays with pillars between,
on the same surface with the same uvs (the glass and the paint were one surface, regions only), so nothing moves.
"""
import numpy as np

from carkit import Part


def _extrap(z, zs, zd):
    zs = np.asarray(zs, float); zd = np.asarray(zd, float)
    out = np.interp(z, zs, zd)
    lo = z < zs[0]; hi = z > zs[-1]
    out[lo] = zd[0] + (z[lo] - zs[0])           # slope 1 past the ends (bumpers keep their size)
    out[hi] = zd[-1] + (z[hi] - zs[-1])
    return out


def _slope(z, zs, zd):
    zs = np.asarray(zs, float); zd = np.asarray(zd, float)
    k = np.clip(np.searchsorted(zs, z) - 1, 0, len(zs) - 2)
    s = (zd[k + 1] - zd[k]) / (zs[k + 1] - zs[k])
    s[(z < zs[0]) | (z > zs[-1])] = 1.0
    return s


def warp(car, zsrc, zdst, sx=1.0):
    for part in car.parts.values():
        for k in range(len(part.p)):
            p = part.p[k].copy(); n = part.n[k].copy()
            s = _slope(p[:, 2], zsrc, zdst)
            p[:, 2] = _extrap(p[:, 2], zsrc, zdst)
            p[:, 0] *= sx
            n[:, 0] /= sx
            n[:, 2] /= s
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            part.p[k] = p; part.n[k] = n
    car.markers = [(nm, [xyz[0] * sx, xyz[1], float(_extrap(np.array([xyz[2]]), zsrc, zdst)[0])]) for nm, xyz in car.markers]
    return car


def _clip_plane(poly, c, keep_above):
    """Sutherland-Hodgman on z = c; poly: list of (p, n, t) tuples"""
    out = []
    m = len(poly)
    for i in range(m):
        a = poly[i]; b = poly[(i + 1) % m]
        da = a[0][2] - c; db = b[0][2] - c
        ina = da >= 0 if keep_above else da < 0
        inb = db >= 0 if keep_above else db < 0
        if ina:
            out.append(a)
        if ina != inb:
            t = da / (da - db)
            out.append(tuple(a[j] + (b[j] - a[j]) * t for j in range(3)))
    return out


def _split(poly, cuts):
    """split a polygon by the planes z = c for c in cuts (ascending): list of (piece, slab index)"""
    pieces = []
    rest = poly
    for i, c in enumerate(cuts):
        below = _clip_plane(rest, c, False)
        if len(below) >= 3:
            pieces.append((below, i))
        rest = _clip_plane(rest, c, True)
        if len(rest) < 3:
            return pieces
    pieces.append((rest, len(cuts)))
    return pieces


def pillars(car, bands, glass="glass", paint="paint_body", seal_mat="seal", seal=0.022):
    g = car.parts.get(glass)
    if g is None or not g.p:
        return
    P, N, T, F = (np.concatenate(g.p), np.concatenate(g.n), np.concatenate(g.t), np.concatenate(g.f))
    cuts = []
    for z0, z1 in bands:
        cuts += [z0 - seal, z0, z1, z1 + seal]
    order = np.argsort(cuts)
    cuts = list(np.asarray(cuts)[order])
    # slab index -> material: seal, paint, seal per band, glass elsewhere
    slab_mat = {}
    for bi in range(len(bands)):
        for j, mat in zip(range(4 * bi + 1, 4 * bi + 4), (seal_mat, paint, seal_mat)):
            slab_mat[j] = mat
    newg = Part(); outs = {}
    for f in F:
        side = abs(N[f].mean(0)[0]) > 0.45
        zz = P[f][:, 2]
        if not side or zz.max() < cuts[0] or zz.min() > cuts[-1]:
            newg.add(P[f], N[f], T[f], [[0, 1, 2]])
            continue
        poly = [(P[i], N[i], T[i]) for i in f]
        for piece, slab in _split(poly, cuts):
            mat = slab_mat.get(slab, glass)
            pp = np.array([q[0] for q in piece]); nn = np.array([q[1] for q in piece]); tt = np.array([q[2] for q in piece])
            tri = [[0, i, i + 1] for i in range(1, len(piece) - 1)]
            (newg if mat == glass else outs.setdefault(mat, Part())).add(pp, nn, tt, tri)
    car.parts[glass] = newg
    for mat, part in outs.items():
        dst = car.part(mat)
        for k in range(len(part.p)):
            dst.add(part.p[k], part.n[k], part.t[k], part.f[k] - part.f[k].min())
