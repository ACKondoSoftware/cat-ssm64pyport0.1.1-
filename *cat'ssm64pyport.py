#!/usr/bin/env python3
# ============================================================================
#  SM64-STYLE PY PORT -- sm64.py
#  Single-file software-rendered 3D platformer. pygame-ce only, no assets:
#  procedural Mario-style visuals, original physics and synth audio.
#
#    pip3 install pygame-ce        (plain pygame works too)
#    python3 sm64.py
#
#  WASD move | SPACE jump (chain x3) | SHIFT crouch / ground-pound in air
#  SHIFT+SPACE moving = long jump | SHIFT+SPACE still = backflip
#  SPACE against a wall in mid-air = wall kick
#  ARROWS camera | C recenter | M music | R respawn | ESC pause
# ============================================================================
import array
import math
import random
import sys
from operator import itemgetter

import pygame

W, H = 960, 540
HW, HH = W // 2, H // 2
FOV = 520.0
NEAR = 0.3
FPS = 60
TILE = 3.0
ISLE = 24.0
WATER_Y = -2.0

_l = math.sqrt(0.4 ** 2 + 0.8 ** 2 + 0.45 ** 2)
LX, LY, LZ = 0.4 / _l, 0.8 / _l, 0.45 / _l

STONE = (172, 172, 184)
BRICK = (196, 112, 84)
WOOD = (146, 100, 58)
LEAF = (52, 150, 66)
GRASS = (92, 190, 86)
GRASS2 = (80, 172, 76)
SAND = (224, 204, 146)
CLOUD = (240, 242, 252)
METAL = (122, 144, 208)
DIRT = (150, 108, 70)
FUR = (242, 152, 52)
FUR_D = (196, 112, 36)
BUNNY = (150, 92, 200)
GOLD = (255, 214, 48)

G = 0.022
RUN = 0.165
PR, PH = 0.32, 0.95


def shade(col, f):
    r, g, b = col
    r = int(r * f); g = int(g * f); b = int(b * f)
    return (255 if r > 255 else r, 255 if g > 255 else g, 255 if b > 255 else b)


# ----------------------------------------------------------------------------
# world geometry
# ----------------------------------------------------------------------------
class Box:
    __slots__ = ("x0", "y0", "z0", "x1", "y1", "z1", "col", "top", "groups",
                 "mover", "base", "dx", "dy", "dz", "id", "draw")

    def __init__(self, x0, y0, z0, x1, y1, z1, col, top=None, mover=None, draw=True):
        self.x0, self.y0, self.z0, self.x1, self.y1, self.z1 = x0, y0, z0, x1, y1, z1
        self.col = col
        self.top = top or col
        self.mover = mover            # (axis, amplitude, speed)
        self.base = (x0, y0, z0, x1, y1, z1)
        self.dx = self.dy = self.dz = 0.0
        self.id = 0
        self.draw = draw
        self.groups = []
        if draw:
            self.build()

    def build(self):
        lo = (self.x0, self.y0, self.z0)
        hi = (self.x1, self.y1, self.z1)
        groups = []
        for i in range(3):
            u = (i + 1) % 3
            v = (i + 2) % 3
            for sg in (1, -1):
                if i == 1 and sg == -1 and self.y0 <= 0.01:
                    continue
                n = [0.0, 0.0, 0.0]
                n[i] = sg
                f = 0.62 + 0.38 * (n[0] * LX + n[1] * LY + n[2] * LZ)
                pos = hi[i] if sg > 0 else lo[i]
                col = self.top if (i == 1 and sg == 1) else self.col
                nu = max(1, math.ceil((hi[u] - lo[u]) / TILE - 1e-6))
                nv = max(1, math.ceil((hi[v] - lo[v]) / TILE - 1e-6))
                tiles = []
                for a in range(nu):
                    u0 = lo[u] + (hi[u] - lo[u]) * a / nu
                    u1 = lo[u] + (hi[u] - lo[u]) * (a + 1) / nu
                    for c in range(nv):
                        v0 = lo[v] + (hi[v] - lo[v]) * c / nv
                        v1 = lo[v] + (hi[v] - lo[v]) * (c + 1) / nv
                        vs = []
                        for uu, vv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                            p = [0.0, 0.0, 0.0]
                            p[i] = pos; p[u] = uu; p[v] = vv
                            vs.append(tuple(p))
                        tiles.append((vs, shade(col, f * (1.0 if (a + c) % 2 == 0 else 0.93))))
                groups.append((i, sg, pos, tiles))
        self.groups = groups

    def step(self, t):
        axis, amp, spd = self.mover
        off = amp * math.sin(t * spd)
        b = self.base
        ox, oy, oz = self.x0, self.y0, self.z0
        if axis == 0:
            self.x0, self.x1 = b[0] + off, b[3] + off
        elif axis == 1:
            self.y0, self.y1 = b[1] + off, b[4] + off
        else:
            self.z0, self.z1 = b[2] + off, b[5] + off
        self.dx, self.dy, self.dz = self.x0 - ox, self.y0 - oy, self.z0 - oz
        self.build()


def seg_hits(b, ax, ay, az, bx, by, bz):
    t0, t1 = 0.0, 0.97
    for a, d, lo, hi in ((ax, bx - ax, b.x0, b.x1), (ay, by - ay, b.y0, b.y1), (az, bz - az, b.z0, b.z1)):
        if -1e-9 < d < 1e-9:
            if a < lo or a > hi:
                return False
        else:
            ta = (lo - a) / d
            tb = (hi - a) / d
            if ta > tb:
                ta, tb = tb, ta
            if ta > t0:
                t0 = ta
            if tb < t1:
                t1 = tb
            if t0 > t1:
                return False
    return True


def build_level():
    B = Box
    bs = [B(-ISLE, -3, -ISLE, ISLE, 0, ISLE, DIRT, draw=False)]       # main island (collision only)
    # tiered tower
    bs += [B(-6, 0, -6, 6, 1.5, 6, STONE, GRASS2), B(-4, 1.5, -4, 4, 3, 4, STONE, GRASS2),
           B(-2, 3, -2, 2, 4.5, 2, STONE), B(-.75, 4.5, -.75, .75, 7.5, .75, BRICK)]
    for i in range(3):
        bs.append(B(-1.5, 0, -8.25 + i * .75, 1.5, .375 * (i + 1), -7.5 + i * .75, STONE))
    # wall-kick shaft
    bs += [B(12, 0, 12, 14, 9, 18, BRICK), B(17, 0, 12, 20, 9, 18, BRICK)]
    # cloud steps
    bs += [B(-18, 1.5, -14, -15, 2, -11, CLOUD), B(-21, 3, -9, -18, 3.5, -6, CLOUD),
           B(-17, 4.5, -4, -14, 5, -1, CLOUD), B(-21, 6, 1, -18, 6.5, 4, CLOUD),
           B(-18, 7.5, 7, -13, 8, 12, CLOUD)]
    # deck + elevator
    bs += [B(-12, 6, 14, -6, 6.5, 20, WOOD),
           B(-15.5, 2.9, 14.5, -12.5, 3.4, 17.5, METAL, mover=(1, 3.1, 0.018))]
    # ferry + islet
    bs += [B(25.5, -.5, -1.5, 28.5, 0, 1.5, METAL, mover=(0, 1.4, 0.02)),
           B(30, -3, -5, 38, 0, 5, SAND, GRASS)]
    # pillars
    bs += [B(16, 0, -6, 18, 1, -4, STONE), B(19, 0, -3, 21, 2.2, -1, STONE), B(16, 0, 0, 18, 3.4, 2, STONE)]
    # trees
    for tx, tz in ((-10, -18), (10, -18), (21, -18), (-20, 20), (8, 21), (-21, -20), (35, 3)):
        bs += [B(tx - .3, 0, tz - .3, tx + .3, 2, tz + .3, WOOD), B(tx - 1.2, 2, tz - 1.2, tx + 1.2, 4, tz + 1.2, LEAF)]
    for i, b in enumerate(bs):
        b.id = i
    coins = []
    for i in range(8):
        a = i * math.pi / 4
        coins.append([math.cos(a) * 2.5, .8, -15 + math.sin(a) * 2.5])
    coins += [[0, 2.3, -5], [0, 3.8, -3], [5, 2.3, 5], [-5, 2.3, 5], [5, 2.3, -5], [-5, 2.3, -5],
              [-16.5, 2.8, -12.5], [-19.5, 4.3, -7.5], [-15.5, 5.8, -2.5], [-19.5, 7.3, 2.5],
              [15.5, 2, 15], [15.5, 4.5, 15], [15.5, 7, 15],
              [17, 1.8, -5], [20, 3, -2], [17, 4.2, 1],
              [31.5, .8, 0], [33, .8, 2], [35, .8, -2], [36.5, .8, 0], [27, .8, 0]]
    coins += [[-11 + i, 7.3, 15.5] for i in range(5)]
    coins += [[-6 + i * 3, .8, -21.5] for i in range(5)]
    fish = [[0, 8.6, 0, True], [34, 1.2, -1, True], [-15.5, 9.2, 9.5, True],
            [18.5, 10.2, 15, True], [-9, 7.7, 18, True], [0, 1.3, -15, False]]
    bunnies = [Bunny(14, -14, 3), Bunny(-13, 9, 2), Bunny(0, 14, 3), Bunny(20, 6, 2)]
    return bs, coins, fish, bunnies


class Bunny:
    def __init__(self, cx, cz, r):
        self.cx, self.cz, self.r = cx, cz, r
        self.a = random.random() * 6.28
        self.alive = True
        self.x = self.z = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.step()

    def step(self):
        self.a += 0.02
        self.x = self.cx + math.cos(self.a) * self.r
        self.z = self.cz + math.sin(self.a) * self.r
        self.yaw = math.atan2(-math.sin(self.a), math.cos(self.a))
        self.y = abs(math.sin(self.a * 6)) * 0.15


class Cat:
    def __init__(self):
        self.lives = 9
        self.reset()

    def reset(self):
        self.x, self.y, self.z = 0.0, 0.0, -20.0
        self.vx = self.vy = self.vz = 0.0
        self.yaw = 0.0
        self.ground = True
        self.gbox = None
        self.jumps = 0
        self.land_t = 0
        self.coyote = 0
        self.wall_t = 0
        self.wnx = self.wnz = 0.0
        self.pound = 0
        self.lj = False
        self.crouch = False
        self.hp = 8
        self.inv = 0
        self.anim = 0.0
        self.safe = (0.0, 0.0, -20.0)


# ----------------------------------------------------------------------------
# synth audio
# ----------------------------------------------------------------------------
SR = 22050


def tone(f0, f1, dur, vol=0.25, sq=True):
    n = int(SR * dur)
    out = array.array("h", bytes(2 * n))
    ph = 0.0
    for i in range(n):
        t = i / n
        ph += (f0 + (f1 - f0) * t) / SR
        s = (1.0 if (ph % 1.0) < 0.5 else -1.0) if sq else math.sin(ph * 6.2832)
        out[i] = int(s * (1.0 - t) * vol * 32767)
    return out


def make_music():
    chords = ((262, 330, 392, 523), (220, 262, 330, 440), (175, 220, 262, 349), (196, 247, 294, 392))
    pat = (0, 1, 2, 3, 2, 1, 2, 3)
    step = int(SR * 0.14)
    out = array.array("h", bytes(2 * step * 8 * len(chords) * 2))
    k = 0
    for _ in range(2):
        for ch in chords:
            bass = ch[0] / 2
            for j in pat:
                f = ch[j]
                for i in range(step):
                    t = i / step
                    a = math.sin(6.2832 * f * i / SR) * (1 - t) ** 2 * 0.10
                    b = (1.0 if (bass * i / SR) % 1.0 < 0.5 else -1.0) * 0.035 * (1 - t * 0.5)
                    out[k] = int((a + b) * 32767)
                    k += 1
    return out


class Audio:
    def __init__(self):
        self.ok = False
        self.s = {}
        self.music_on = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(SR, -16, 1, 512)
            ch = pygame.mixer.get_init()[2]

            def mk(a):
                if ch == 2:
                    st = array.array("h", bytes(4 * len(a)))
                    st[0::2] = a
                    st[1::2] = a
                    a = st
                return pygame.mixer.Sound(buffer=a.tobytes())

            self.s = {"jump": mk(tone(330, 660, .12)), "jump2": mk(tone(392, 784, .13)),
                      "jump3": mk(tone(523, 1175, .2)), "coin": mk(tone(988, 1319, .1, .18)),
                      "stomp": mk(tone(220, 60, .15, .3)), "hurt": mk(tone(300, 90, .3, .3)),
                      "fish": mk(tone(523, 1568, .6, .22, False)), "kick": mk(tone(500, 900, .09)),
                      "pound": mk(tone(120, 40, .25, .35)), "splash": mk(tone(900, 100, .35, .2, False))}
            self.music = mk(make_music())
            self.mch = pygame.mixer.Channel(0)
            self.ok = True
        except Exception:
            self.ok = False

    def play(self, name):
        if self.ok:
            self.s[name].play()

    def set_music(self, on):
        self.music_on = on
        if not self.ok:
            return
        if on:
            self.mch.play(self.music, loops=-1)
        else:
            self.mch.stop()


# ----------------------------------------------------------------------------
# game
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, bench=0):
        pygame.mixer.pre_init(SR, -16, 1, 512)
        pygame.init()
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE, vsync=1)
        except Exception:
            self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("SM64-STYLE PY PORT | SINGLE FILE")
        self.clock = pygame.time.Clock()
        self.big = pygame.font.Font(None, 110)
        self.mid = pygame.font.Font(None, 44)
        self.small = pygame.font.Font(None, 26)
        self.audio = Audio()
        self.sky = pygame.Surface((W, H))
        for y in range(H):
            t = y / H
            pygame.draw.line(self.sky, (int(70 + 110 * t), int(140 + 90 * t), int(235 + 15 * t)), (0, y), (W, y))
        self.bench = bench
        self.state = "title"
        self.t = 0
        self.q = []
        self.cam = (0.0, 5.0, -30.0)
        self.cyaw, self.cpitch, self.cdist = 0.0, 0.38, 7.5
        self.ctx, self.cty, self.ctz = 0.0, 1.0, -20.0
        self.cyw = self.syw = self.cp = self.sp = 0.0
        self.new_game()

    def new_game(self):
        self.boxes, self.coins, self.fish, self.bunnies = build_level()
        self.movers = [b for b in self.boxes if b.mover]
        self.drawn = [b for b in self.boxes if b.draw]
        self.cat = Cat()
        self.ncoins = 0
        self.nfish = 0
        self.parts = []
        self.toast = ""
        self.toast_t = 0
        self.shake = 0
        gt = []
        n = 8
        s = 2 * ISLE / n
        for i in range(n):
            for j in range(n):
                x0 = -ISLE + i * s
                z0 = -ISLE + j * s
                gt.append((((x0, 0, z0), (x0 + s, 0, z0), (x0 + s, 0, z0 + s), (x0, 0, z0 + s)),
                           GRASS if (i + j) % 2 == 0 else GRASS2))
        self.gtiles = gt

    # ---------------- renderer ----------------
    def set_cam(self):
        cy, sy = math.cos(self.cyaw), math.sin(self.cyaw)
        cp, sp = math.cos(self.cpitch), math.sin(self.cpitch)
        d = self.cdist
        sx = sz = 0.0
        if self.shake:
            sx = random.uniform(-.08, .08) * self.shake
            sz = random.uniform(-.08, .08) * self.shake
        self.cam = (self.ctx - sy * cp * d + sx, max(0.4, self.cty + sp * d + sz), self.ctz - cy * cp * d)
        self.cyw, self.syw, self.cp, self.sp = cy, sy, cp, sp

    def poly(self, verts, col, key=None, tag=-1, near=0.0):
        cx, cy, cz = self.cam
        cyw, syw, cp, sp = self.cyw, self.syw, self.cp, self.sp
        cs = []
        behind = 0
        ax = ay = az = 0.0
        for x, y, z in verts:
            dx = x - cx; dy = y - cy; dz = z - cz
            x1 = dx * cyw - dz * syw
            z1 = dx * syw + dz * cyw
            z2 = z1 * cp - dy * sp
            y2 = dy * cp + z1 * sp
            cs.append((x1, y2, z2))
            if z2 < NEAR:
                behind += 1
            ax += x1; ay += y2; az += z2
        n = len(cs)
        if behind == n:
            return None
        if behind:
            out = []
            for i in range(n):
                a = cs[i]
                b = cs[(i + 1) % n]
                ina = a[2] >= NEAR
                if ina:
                    out.append(a)
                if ina != (b[2] >= NEAR):
                    t = (NEAR - a[2]) / (b[2] - a[2])
                    out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, NEAR))
            cs = out
            if len(cs) < 3:
                return None
        pts = []
        l = r = u = d = 0
        for x, y, z in cs:
            k = FOV / z
            px = HW + x * k
            py = HH - y * k
            if px < 0: l += 1
            elif px > W: r += 1
            if py < 0: u += 1
            elif py > H: d += 1
            pts.append((-8000 if px < -8000 else 8000 if px > 8000 else px,
                        -8000 if py < -8000 else 8000 if py > 8000 else py))
        m = len(pts)
        if l == m or r == m or u == m or d == m:
            return None
        if key is None:
            ax /= n; ay /= n; az /= n
            dist = math.sqrt(ax * ax + ay * ay + az * az) - near
            key = dist
        self.q.append((key, col, pts, tag))
        return key

    def obox(self, cx, cy, cz, hx, hy, hz, c, s, col):
        camx, camy, camz = self.cam
        front = None
        axes = (((c, 0.0, -s), hx), ((0.0, 1.0, 0.0), hy), ((s, 0.0, c), hz))
        for i in range(3):
            n, h = axes[i]
            u, hu = axes[(i + 1) % 3]
            v, hv = axes[(i + 2) % 3]
            ux, uy, uz = u[0] * hu, u[1] * hu, u[2] * hu
            vx, vy, vz = v[0] * hv, v[1] * hv, v[2] * hv
            for sg in (1, -1):
                nx, ny, nz = n[0] * sg, n[1] * sg, n[2] * sg
                fx, fy, fz = cx + nx * h, cy + ny * h, cz + nz * h
                if nx * (camx - fx) + ny * (camy - fy) + nz * (camz - fz) <= 0:
                    continue
                f = 0.62 + 0.38 * (nx * LX + ny * LY + nz * LZ)
                k = self.poly(((fx + ux + vx, fy + uy + vy, fz + uz + vz), (fx - ux + vx, fy - uy + vy, fz - uz + vz),
                               (fx - ux - vx, fy - uy - vy, fz - uz - vz), (fx + ux - vx, fy + uy - vy, fz + uz - vz)),
                              shade(col, f))
                if i == 2 and sg == 1:
                    front = k
        return front

    def project(self, x, y, z):
        cx, cy, cz = self.cam
        dx = x - cx; dy = y - cy; dz = z - cz
        x1 = dx * self.cyw - dz * self.syw
        z1 = dx * self.syw + dz * self.cyw
        z2 = z1 * self.cp - dy * self.sp
        if z2 < NEAR:
            return None
        y2 = dy * self.cp + z1 * self.sp
        return (HW + x1 * FOV / z2, HH - y2 * FOV / z2, z2)

    def disc(self, x, y, z, r, col, key=None):
        self.poly([(x + math.cos(i * .785) * r, y, z + math.sin(i * .785) * r) for i in range(8)], col, key=key)

    def floor(self, x, z, y):
        fy = 0.0 if (-ISLE <= x <= ISLE and -ISLE <= z <= ISLE) else None
        fb = None
        for b in self.drawn:
            if b.x0 <= x <= b.x1 and b.z0 <= z <= b.z1 and b.y1 <= y + 0.1 and (fy is None or b.y1 > fy):
                fy = b.y1
                fb = b
        return fy, fb

    def draw_mario(self):
        """Procedural low-poly Mario-inspired character; no external textures."""
        p = self.cat
        yaw = p.yaw + (self.t * .6 if p.pound else 0.0)
        c, sn = math.cos(yaw), math.sin(yaw)
        px, py, pz = p.x, p.y, p.z
        def L(x, y, z):
            return (px + x*c + z*sn, py+y, pz-x*sn+z*c)
        def cube(x,y,z,hx,hy,hz,color):
            self.obox(*L(x,y,z),hx,hy,hz,c,sn,color)
        RED=(214,36,42); BLUE=(35,74,192); SKIN=(245,181,132)
        BROWN=(92,49,29); DARK=(38,29,29); WHITE=(250,249,242)
        GOLDEN=(246,201,62)
        speed=math.hypot(p.vx,p.vz)
        swing=math.sin(p.anim)*.16*min(1,speed/.08) if p.ground else .12
        crouch=-.14 if p.crouch and p.ground else 0
        # Brown shoes and blue trouser legs animate independently.
        for side,phase in ((-.14,1),(.14,-1)):
            cube(side,.12,phase*swing,.13,.105,.19,BROWN)
            cube(side,.30+crouch*.4,phase*swing*.7,.105,.16,.12,BLUE)
        # Red shirt, blue overalls, straps and gold buttons.
        cube(0,.58+crouch,0,.28,.25,.19,RED)
        cube(0,.48+crouch,.20,.235,.19,.035,BLUE)
        for side in (-.17,.17):
            cube(side,.68+crouch,.205,.055,.19,.04,BLUE)
            cube(side,.70+crouch,.25,.035,.035,.018,GOLDEN)
            cube(side*1.75,.59+crouch,-.02,.12,.13,.13,RED)
            cube(side*2.35,.51+crouch,.04,.085,.085,.09,WHITE)
        # Face, brown sideburns, ears, nose and moustache.
        cube(0,.94+crouch,.015,.225,.22,.205,SKIN)
        for side in (-1,1):
            cube(side*.24,.92+crouch,.015,.045,.085,.07,SKIN)
            cube(side*.19,.98+crouch,.10,.055,.11,.065,BROWN)
            cube(side*.09,1.00+crouch,.218,.052,.07,.025,WHITE)
            cube(side*.09,1.00+crouch,.246,.021,.044,.012,(37,73,143))
            cube(side*.105,.86+crouch,.224,.095,.043,.027,BROWN)
        cube(0,.91+crouch,.26,.095,.08,.08,SKIN)
        # Cap and brim with a white emblem.
        cube(0,1.19+crouch,-.015,.25,.10,.23,RED)
        cube(0,1.12+crouch,.20,.26,.038,.13,RED)
        cube(0,1.24+crouch,.218,.085,.065,.02,WHITE)
        cube(0,1.24+crouch,.241,.046,.035,.008,RED)

    def draw_bunny(self, e):
        c, s = math.cos(e.yaw), math.sin(e.yaw)

        def L(lx, ly, lz):
            return e.x + lx * c + lz * s, e.y + ly, e.z - lx * s + lz * c

        x, y, z = L(0, .36, 0)
        k = self.obox(x, y, z, .4, .36, .4, c, s, BUNNY)
        for sx in (-.2, .2):
            x, y, z = L(sx, .95, -.05)
            self.obox(x, y, z, .08, .24, .06, c, s, shade(BUNNY, .85))
        if k is not None:
            for ex in (-.16, .16):
                self.poly((L(ex - .08, .38, .405), L(ex + .08, .38, .405), L(ex + .08, .56, .405), L(ex - .08, .56, .405)),
                          (250, 250, 250), key=k)
                self.poly((L(ex - .03, .4, .41), L(ex + .03, .4, .41), L(ex + .03, .5, .41), L(ex - .03, .5, .41)),
                          (30, 20, 40), key=k)

    def render(self):
        scr = self.screen
        scr.blit(self.sky, (0, 0))
        self.set_cam()
        cam = self.cam
        polygon = pygame.draw.polygon
        # --- ground layer (never needs sorting: camera is always above it)
        self.q = []
        wv = int(8 * math.sin(self.t * .03))
        self.poly(((-400, WATER_Y, -400), (400, WATER_Y, -400), (400, WATER_Y, 400), (-400, WATER_Y, 400)),
                  (52 + wv, 132 + wv, 220))
        I = ISLE
        for (ax, sg, verts) in ((0, 1, ((I, -3, -I), (I, 0, -I), (I, 0, I), (I, -3, I))),
                                (0, -1, ((-I, -3, -I), (-I, 0, -I), (-I, 0, I), (-I, -3, I))),
                                (2, 1, ((-I, -3, I), (-I, 0, I), (I, 0, I), (I, -3, I))),
                                (2, -1, ((-I, -3, -I), (-I, 0, -I), (I, 0, -I), (I, -3, -I)))):
            if cam[ax] * sg > I:
                self.poly(verts, shade(DIRT, .75 if ax == 0 else .9))
        for verts, col in self.gtiles:
            self.poly(verts, col)
        p = self.cat
        fy, fb = self.floor(p.x, p.z, p.y)
        if fy is not None and fb is None:
            self.disc(p.x, 0.01, p.z, .36, (46, 112, 50))
        for e in self.bunnies:
            if e.alive:
                self.disc(e.x, 0.01, e.z, .42, (46, 112, 50))
        for _, col, pts, _ in self.q:
            polygon(scr, col, pts)
        # --- static tiles + small sprites
        self.q = []
        cxp, cyp, czp = cam
        for b in self.drawn:
            bid = b.id
            for ax, sg, pos, tiles in b.groups:
                if cam[ax] * sg <= pos * sg:
                    continue
                for verts, col in tiles:
                    self.poly(verts, col, tag=bid)
        spin = self.t * .08
        cs, sn = math.cos(spin) * .3, math.sin(spin) * .3
        ccol = shade(GOLD, .7 + .3 * abs(math.cos(spin)))
        ring = [(math.cos(i * 1.0472), math.sin(i * 1.0472)) for i in range(6)]
        for x, y, z in self.coins:
            if (x - cxp) ** 2 + (z - czp) ** 2 > 1600:
                continue
            self.poly([(x + u * cs, y + v * .3, z - u * sn) for u, v in ring], ccol, near=1.5)
        fs = self.t * .05
        fc, fn = math.cos(fs), math.sin(fs)
        body = ((.5, 0), (.22, .27), (-.15, .22), (-.35, 0), (-.15, -.22), (.22, -.27))
        tail = ((-.3, 0), (-.62, .26), (-.62, -.26))
        for x, y, z, vis in self.fish:
            if not vis:
                continue
            y += math.sin(self.t * .06) * .15
            k = self.poly([(x + u * fc, y + v, z - u * fn) for u, v in body], (255, 190, 60), near=1.5)
            if k is not None:
                self.poly([(x + u * fc, y + v, z - u * fn) for u, v in tail], (255, 140, 40), key=k)
                for o in (.012, -.012):
                    ex, ez = x + .3 * fc + o * fn, z - .3 * fn + o * fc
                    self.poly([(ex - .04 * fc, y + .04, ez + .04 * fn), (ex + .04 * fc, y + .04, ez - .04 * fn),
                               (ex + .04 * fc, y + .12, ez - .04 * fn), (ex - .04 * fc, y + .12, ez + .04 * fn)],
                              (30, 30, 40), key=k)
        S = self.q
        S.sort(key=itemgetter(0), reverse=True)
        # --- dynamic groups, slotted in front of whatever actually occludes them
        groups = []

        def group(x, y, z, fn):
            self.q = []
            fn()
            if not self.q:
                return
            g = self.q
            g.sort(key=itemgetter(0), reverse=True)
            occ = {b.id for b in self.drawn if seg_hits(b, cxp, cyp, czp, x, y, z)}
            idx = len(S)
            if occ:
                for i, it in enumerate(S):
                    if it[3] in occ:
                        idx = i
                        break
            groups.append((idx, -((x - cxp) ** 2 + (y - cyp) ** 2 + (z - czp) ** 2), g))

        def cat_group():
            if fb is not None:
                self.disc(p.x, fy + .02, p.z, .36, shade(fb.top, .45), key=1e9)
            if p.inv == 0 or (self.t // 3) % 2:
                self.draw_mario()

        group(p.x, p.y + .5, p.z, cat_group)
        for e in self.bunnies:
            if e.alive:
                group(e.x, e.y + .5, e.z, lambda e=e: self.draw_bunny(e))
        groups.sort(key=lambda g: (g[0], g[1]))
        gi = 0
        ng = len(groups)
        for i, it in enumerate(S):
            while gi < ng and groups[gi][0] == i:
                for _, col, pts, _ in groups[gi][2]:
                    polygon(scr, col, pts)
                gi += 1
            polygon(scr, it[1], it[2])
        while gi < ng:
            for _, col, pts, _ in groups[gi][2]:
                polygon(scr, col, pts)
            gi += 1
        for pt in self.parts:
            pr = self.project(pt[0], pt[1], pt[2])
            if pr:
                sz = max(2, int(60 / pr[2] * pt[6] / 30))
                scr.fill(pt[7], (int(pr[0]) - sz // 2, int(pr[1]) - sz // 2, sz, sz))

    # ---------------- gameplay ----------------
    def burst(self, x, y, z, col, n=12, sp=.08):
        for _ in range(n):
            a = random.random() * 6.28
            v = random.random() * sp
            self.parts.append([x, y, z, math.cos(a) * v, random.random() * sp * 1.5, math.sin(a) * v, 30, col])

    def say(self, msg, t=180):
        self.toast, self.toast_t = msg, t

    def hurt(self, n, kx=0.0, kz=0.0):
        p = self.cat
        if p.inv:
            return
        p.hp -= n
        p.inv = 90
        p.vx, p.vz, p.vy = kx * .16, kz * .16, .24
        p.pound = 0
        self.audio.play("hurt")
        self.shake = 6
        if p.hp <= 0:
            lives = p.lives - 1
            if lives <= 0:
                self.state = "title"
                self.new_game()
                return
            p.reset()
            p.lives = lives
            p.inv = 90
            self.say("%d LIVES LEFT" % lives)

    def collide(self):
        p = self.cat
        boxes = self.boxes
        r, h = PR, PH
        was_ground = p.ground
        # X
        p.x += p.vx
        for b in boxes:
            if p.x + r > b.x0 and p.x - r < b.x1 and p.z + r > b.z0 and p.z - r < b.z1 \
                    and p.y + h > b.y0 and p.y < b.y1 - 1e-4:
                if was_ground and b.y1 - p.y <= 0.4:
                    p.y = b.y1
                    continue
                left = p.vx > 0 if p.vx else p.x < (b.x0 + b.x1) * .5
                p.x = b.x0 - r if left else b.x1 + r
                if not was_ground:
                    p.wall_t, p.wnx, p.wnz = 10, (-1.0 if left else 1.0), 0.0
                p.vx = 0.0
        # Z
        p.z += p.vz
        for b in boxes:
            if p.x + r > b.x0 and p.x - r < b.x1 and p.z + r > b.z0 and p.z - r < b.z1 \
                    and p.y + h > b.y0 and p.y < b.y1 - 1e-4:
                if was_ground and b.y1 - p.y <= 0.4:
                    p.y = b.y1
                    continue
                near = p.vz > 0 if p.vz else p.z < (b.z0 + b.z1) * .5
                p.z = b.z0 - r if near else b.z1 + r
                if not was_ground:
                    p.wall_t, p.wnx, p.wnz = 10, 0.0, (-1.0 if near else 1.0)
                p.vz = 0.0
        # Y
        prev = p.y
        p.y += p.vy
        p.ground = False
        p.gbox = None
        for b in boxes:
            if p.x + r > b.x0 and p.x - r < b.x1 and p.z + r > b.z0 and p.z - r < b.z1 \
                    and p.y + h > b.y0 and p.y < b.y1:
                if p.vy <= 0 and prev >= b.y1 - 0.05:
                    p.y = b.y1; p.vy = 0.0; p.ground = True; p.gbox = b
                elif p.vy > 0:
                    p.y = b.y0 - h; p.vy = 0.0
                else:
                    p.y = b.y1; p.vy = 0.0; p.ground = True; p.gbox = b

    def update(self, keys, jump, crouch_edge):
        p = self.cat
        self.t += 1
        t = self.t
        # camera input
        if keys[pygame.K_LEFT]: self.cyaw -= .04
        if keys[pygame.K_RIGHT]: self.cyaw += .04
        if keys[pygame.K_UP]: self.cpitch = min(1.25, self.cpitch + .02)
        if keys[pygame.K_DOWN]: self.cpitch = max(.06, self.cpitch - .02)
        if keys[pygame.K_c]:
            d = (p.yaw - self.cyaw + math.pi) % (2 * math.pi) - math.pi
            self.cyaw += d * .15
        # movers carry their rider
        for b in self.movers:
            b.step(t)
            if p.gbox is b:
                p.x += b.dx; p.y += b.dy; p.z += b.dz
        # input -> world direction
        ix = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
        iz = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
        if ix and iz:
            ix *= .7071; iz *= .7071
        cy, sy = math.cos(self.cyaw), math.sin(self.cyaw)
        wx = cy * ix + sy * iz
        wz = -sy * ix + cy * iz
        p.crouch = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])
        spd = math.hypot(p.vx, p.vz)
        if p.pound:
            p.pound += 1
            p.vx = p.vz = 0.0
            p.vy = 0.0 if p.pound < 12 else -.55
        elif p.ground:
            ts = RUN * (.35 if p.crouch else 1.0)
            p.vx += (wx * ts - p.vx) * .2
            p.vz += (wz * ts - p.vz) * .2
        else:
            p.vx += wx * .008
            p.vz += wz * .008
            cap = .36 if p.lj else .19
            s2 = math.hypot(p.vx, p.vz)
            if s2 > cap:
                p.vx *= cap / s2; p.vz *= cap / s2
        if (ix or iz) and not p.pound and not p.lj:
            d = (math.atan2(wx, wz) - p.yaw + math.pi) % (2 * math.pi) - math.pi
            p.yaw += d * (.3 if p.ground else .12)
        # jumping
        if jump and not p.pound:
            if p.ground or p.coyote > 0:
                fx, fz = math.sin(p.yaw), math.cos(p.yaw)
                if p.crouch and spd > .08:
                    p.vx, p.vz, p.vy, p.lj = fx * .34, fz * .34, .26, True
                    p.jumps = 0
                    self.audio.play("jump2")
                elif p.crouch:
                    p.vx, p.vz, p.vy = -fx * .06, -fz * .06, .5
                    p.jumps = 0
                    self.audio.play("jump3")
                elif p.land_t > 0 and p.jumps == 1:
                    p.jumps, p.vy = 2, .40
                    self.audio.play("jump2")
                elif p.land_t > 0 and p.jumps == 2 and spd > .1:
                    p.jumps, p.vy = 3, .52
                    self.audio.play("jump3")
                else:
                    p.jumps, p.vy = 1, .34
                    self.audio.play("jump")
                p.ground = False
                p.coyote = 0
            elif p.wall_t > 0:
                p.vx, p.vz, p.vy = p.wnx * .2, p.wnz * .2, .40
                p.yaw = math.atan2(p.wnx, p.wnz)
                p.jumps, p.wall_t, p.lj = 1, 0, False
                self.audio.play("kick")
                self.burst(p.x - p.wnx * .3, p.y + .4, p.z - p.wnz * .3, (255, 255, 255), 6, .04)
        if crouch_edge and not p.ground and not p.pound and p.coyote == 0:
            p.pound = 1
            p.lj = False
        if not p.pound:
            p.vy -= G
            if p.vy > 0 and not keys[pygame.K_SPACE] and not p.lj:
                p.vy -= G * 1.2
            if p.vy < -.6:
                p.vy = -.6
        if p.wall_t: p.wall_t -= 1
        if p.coyote: p.coyote -= 1
        was = p.ground
        self.collide()
        if p.ground:
            if not was:
                p.land_t = 10
                p.lj = False
                if p.pound:
                    p.pound = 0
                    self.shake = 8
                    self.audio.play("pound")
                    self.burst(p.x, p.y + .1, p.z, (230, 230, 230), 16, .12)
                    for e in self.bunnies:
                        if e.alive and (e.x - p.x) ** 2 + (e.z - p.z) ** 2 < 4 and abs(e.y - p.y) < 1.5:
                            self.kill(e)
            elif p.land_t:
                p.land_t -= 1
                if p.land_t == 0:
                    p.jumps = 0
            p.anim += spd * 3.2
            if p.gbox is self.boxes[0]:
                p.safe = (max(-22, min(22, p.x)), 0.0, max(-22, min(22, p.z)))
        elif was and p.vy <= 0:
            p.coyote = 6
        if p.inv: p.inv -= 1
        # water
        if p.y < WATER_Y - .3:
            self.audio.play("splash")
            self.burst(p.x, WATER_Y, p.z, (200, 230, 255), 20, .15)
            p.x, p.y, p.z = p.safe
            p.vx = p.vy = p.vz = 0.0
            p.pound = 0
            p.inv = 0
            self.hurt(2)
        # pickups
        cyc = p.y + .5
        for c in self.coins[:]:
            if (c[0] - p.x) ** 2 + (c[2] - p.z) ** 2 < .7 and abs(c[1] - cyc) < 1.0:
                self.coins.remove(c)
                self.ncoins += 1
                p.hp = min(8, p.hp + 1)
                self.audio.play("coin")
                self.burst(c[0], c[1], c[2], GOLD, 6, .05)
        for f in self.fish:
            if f[3] and (f[0] - p.x) ** 2 + (f[2] - p.z) ** 2 < 1.0 and abs(f[1] - cyc) < 1.3:
                f[3] = False
                f[1] = -99
                self.nfish += 1
                self.audio.play("fish")
                self.burst(p.x, p.y + 1, p.z, (255, 240, 120), 30, .14)
                self.say("ALL STARS COLLECTED!" if self.nfish == len(self.fish)
                         else "STAR GET!  %d / %d" % (self.nfish, len(self.fish)), 260)
        # bunnies
        for e in self.bunnies:
            if not e.alive:
                continue
            e.step()
            dx, dz = p.x - e.x, p.z - e.z
            if dx * dx + dz * dz < .6 and e.y - .9 < p.y < e.y + 1.0:
                if p.vy < -.01 and p.y > e.y + .3:
                    self.kill(e)
                    p.vy = .32
                    p.jumps = 1
                else:
                    d = math.hypot(dx, dz) or 1.0
                    self.hurt(2, dx / d, dz / d)
        for pt in self.parts:
            pt[0] += pt[3]; pt[1] += pt[4]; pt[2] += pt[5]
            pt[4] -= .006
            pt[6] -= 1
        self.parts = [pt for pt in self.parts if pt[6] > 0]
        if self.shake: self.shake -= 1
        if self.toast_t: self.toast_t -= 1
        self.ctx += (p.x - self.ctx) * .15
        self.cty += (p.y + .9 - self.cty) * .12
        self.ctz += (p.z - self.ctz) * .15

    def kill(self, e):
        e.alive = False
        self.audio.play("stomp")
        self.burst(e.x, e.y + .4, e.z, BUNNY, 16, .1)
        self.coins.append([e.x, .8, e.z])
        if not any(b.alive for b in self.bunnies):
            self.fish[5][3] = True
            self.say("A FISH APPEARED NEAR THE START!", 260)

    # ---------------- HUD / screens ----------------
    def text(self, font, msg, x, y, col=(255, 255, 255), center=False):
        sh = font.render(msg, True, (20, 24, 50))
        im = font.render(msg, True, col)
        if center:
            x -= im.get_width() // 2
        self.screen.blit(sh, (x + 2, y + 2))
        self.screen.blit(im, (x, y))

    def hud(self):
        p = self.cat
        self.text(self.mid, "MARIO x%d" % p.lives, 20, 14)
        self.text(self.mid, "STARS %d/%d" % (self.nfish, len(self.fish)), W - 355, 14, (255, 200, 80))
        self.text(self.mid, "COINS %d" % self.ncoins, W - 160, 14, GOLD)
        for i in range(8):
            col = ((90, 220, 110) if p.hp > 4 else (240, 200, 60) if p.hp > 2 else (240, 80, 80)) if i < p.hp else (40, 44, 70)
            pygame.draw.rect(self.screen, (20, 24, 50), (HW - 84 + i * 21, 18, 19, 24), border_radius=5)
            pygame.draw.rect(self.screen, col, (HW - 82 + i * 21, 20, 15, 20), border_radius=4)
        self.text(self.small, "%d FPS" % self.clock.get_fps(), 20, H - 30)
        if self.toast_t:
            self.text(self.mid, self.toast, HW, 90, (255, 240, 140), True)

    def title(self):
        self.t += 1
        self.cyaw += .004
        self.ctx += (0 - self.ctx) * .05
        self.cty += (3 - self.cty) * .05
        self.ctz += (0 - self.ctz) * .05
        self.cdist += (26 - self.cdist) * .05
        for b in self.movers:
            b.step(self.t)
        for e in self.bunnies:
            e.step()
        self.render()
        self.text(self.big, "SM64 PY PORT", HW, 90, (255, 170, 60), True)
        self.text(self.mid, "P Y   P O R T", HW, 175, (255, 255, 255), True)
        if (self.t // 30) % 2:
            self.text(self.mid, "PRESS ENTER", HW, 300, (255, 240, 140), True)
        for i, l in enumerate(("WASD move   SPACE jump (chain 3)   SHIFT crouch / ground pound",
                               "SHIFT+SPACE long jump / backflip   SPACE on a wall = wall kick",
                               "ARROWS camera   C recenter   M music   R respawn   ESC pause")):
            self.text(self.small, l, HW, 400 + i * 28, (235, 240, 255), True)

    def run(self):
        frames = 0
        spent = 0
        if self.bench:
            self.state = "play"
            self.cdist = 7.5
        else:
            self.audio.set_music(True)
        while True:
            jump = crouch_edge = False
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type == pygame.KEYDOWN:
                    k = ev.key
                    if k == pygame.K_m:
                        self.audio.set_music(not self.audio.music_on)
                    if self.state == "title":
                        if k in (pygame.K_RETURN, pygame.K_SPACE):
                            self.state = "play"
                            self.cyaw, self.cpitch, self.cdist = 0.0, .38, 7.5
                        elif k == pygame.K_ESCAPE:
                            return
                    elif self.state == "pause":
                        if k == pygame.K_ESCAPE:
                            self.state = "play"
                        elif k == pygame.K_q:
                            return
                    else:
                        if k == pygame.K_SPACE: jump = True
                        elif k in (pygame.K_LSHIFT, pygame.K_RSHIFT): crouch_edge = True
                        elif k == pygame.K_ESCAPE: self.state = "pause"
                        elif k == pygame.K_r:
                            c = self.cat
                            c.x, c.y, c.z = 0.0, 0.0, -20.0
                            c.vx = c.vy = c.vz = 0.0
            if self.state == "title":
                self.title()
            elif self.state == "play":
                keys = pygame.key.get_pressed()
                if self.bench:
                    keys = BenchKeys(frames)
                    jump = frames % 40 == 0
                    crouch_edge = frames % 170 == 100
                self.update(keys, jump, crouch_edge)
                if self.state == "play":
                    self.render()
                    self.hud()
            else:
                self.render()
                self.hud()
                self.text(self.big, "PAUSED", HW, 190, (255, 255, 255), True)
                self.text(self.mid, "ESC resume    Q quit", HW, 290, (255, 240, 140), True)
            pygame.display.flip()
            if self.bench:
                spent += self.clock.tick()
                frames += 1
                if frames >= self.bench:
                    print("bench: %d frames, %.2f ms/frame avg" % (frames, spent / frames))
                    return
            else:
                self.clock.tick(FPS)


class BenchKeys:
    def __init__(self, f):
        self.on = {pygame.K_w, pygame.K_SPACE}
        if (f // 120) % 2:
            self.on.add(pygame.K_d)
        if (f // 90) % 3 == 0:
            self.on.add(pygame.K_LEFT)

    def __getitem__(self, k):
        return k in self.on


if __name__ == "__main__":
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--bench" else 0
    Game(n).run()
    pygame.quit()
