"""Bounded, dependency-free geometry and ground navigation for mechfight/1.

Only terrain and solid prisms obstruct movement/shots. Trees intentionally do not
block shots. The map is read-only; preprocessing and caches stay in memory.
"""
from __future__ import annotations

from array import array
import heapq
import json
import math
from pathlib import Path
import sys
import time
from terrain_kernel import make_kernel


def _inside(x, y, ring):
    inside = False
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i], ring[i + 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
        ax, ay = bx, by
    return inside


def _distance2(x, y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / den)) if den else 0.0
    return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2


def _direction(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-8 else (0.0, 0.0)


def _segments_distance2(ax,ay,bx,by,cx,cy,dx,dy):
    ux,uy=bx-ax,by-ay
    vx,vy=dx-cx,dy-cy
    cross=ux*vy-uy*vx
    if abs(cross)>1e-10:
        wx,wy=cx-ax,cy-ay
        s=(wx*vy-wy*vx)/cross
        t=(wx*uy-wy*ux)/cross
        if 0<=s<=1 and 0<=t<=1:
            return 0.0
    return min(_distance2(ax,ay,cx,cy,dx,dy),_distance2(bx,by,cx,cy,dx,dy),
               _distance2(cx,cy,ax,ay,bx,by),_distance2(dx,dy,ax,ay,bx,by))


class ArenaMap:
    """Load map geometry once; methods accept current, cube-scaled dimensions.

    ``deadline`` uses time.perf_counter(). Navigation does at most 600 A* nodes
    per call and continues an unfinished search on subsequent observations.
    ``available`` is false if the map could not be loaded. Callers can log
    ``error`` to stderr and use the explicit direct-steering fallback.
    """
    BIN = 24.0
    GRID = 5.0
    CONTACT_EPS = 0.015  # Observed world positions are rounded to centimetres.

    def __init__(self, map_dir, config):
        self.available = False
        self.error = None
        self._terrain_kernel = None
        self.prisms = []
        self.bins = {}
        self._walk_cache = {}
        self._edge_cache = {}
        self._active_dims = None
        self._search = None
        self._path = []
        self._path_key = None
        self._cover = []
        self._cover_bins = {}
        self._cover_dims = None
        self._cover_dynamic = {}
        self._cover_cache = None
        mech = config.get("mech", {})
        self.step_up = float(mech.get("step_up", 1.2))
        self.max_slope = math.tan(math.radians(float(mech.get("max_slope_deg", 50))))
        self.arena_margin = max(0.0,float(config.get("match",{}).get("arena_margin",0)))
        try:
            root = Path(map_dir) / "v2"
            world = json.loads((root / "world.json").read_text(encoding="utf-8"))
            self.bounds = world["bounds"]
            self.terrain = world["terrain"]
            self.nx, self.ny = int(self.terrain["nx"]), int(self.terrain["ny"])
            self.samples = array("h")
            self.samples.frombytes((root / self.terrain["file"]).read_bytes())
            if sys.byteorder != "little":
                self.samples.byteswap()
            if len(self.samples) != self.nx * self.ny:
                raise ValueError("terrain sample count differs from map metadata")
            for source in world["prisms"]:
                p = dict(source)
                ring = p["ring"]
                p["box"] = (min(ring[::2]), min(ring[1::2]), max(ring[::2]), max(ring[1::2]))
                p["edges"] = []
                p["edge_bins"] = {}
                for poly in [ring] + p.get("holes", []):
                    ax, ay = poly[-2:]
                    for i in range(0, len(poly), 2):
                        bx, by = poly[i:i + 2]
                        p["edges"].append((ax, ay, bx, by))
                        edge=p["edges"][-1]
                        for ix in range(math.floor(min(ax,bx)/self.BIN),math.floor(max(ax,bx)/self.BIN)+1):
                            for iy in range(math.floor(min(ay,by)/self.BIN),math.floor(max(ay,by)/self.BIN)+1):
                                p["edge_bins"].setdefault((ix,iy),[]).append(edge)
                        ax, ay = bx, by
                index = len(self.prisms)
                self.prisms.append(p)
                x0, y0, x1, y1 = p["box"]
                for ix in range(math.floor(x0 / self.BIN), math.floor(x1 / self.BIN) + 1):
                    for iy in range(math.floor(y0 / self.BIN), math.floor(y1 / self.BIN) + 1):
                        self.bins.setdefault((ix, iy), []).append(index)
            self.gx = int(math.ceil((self.bounds["maxX"] - self.bounds["minX"]) / self.GRID)) + 1
            self.gy = int(math.ceil((self.bounds["maxY"] - self.bounds["minY"]) / self.GRID)) + 1
            self.available = True
            self._terrain_kernel = make_kernel(self)
            self._prepare_cover(float(mech.get("radius",2.5)),float(mech.get("height",9)))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def _prepare_cover(self,radius,height):
        """Build valid wall-adjacent points once, outside the decision budget."""
        self._cover_base_radius=radius
        self._cover_base_height=height
        seen=set()
        for prism in self.prisms:
            for ax,ay,bx,by in prism["edges"]:
                dx,dy=bx-ax,by-ay
                length=math.hypot(dx,dy)
                if length<0.4:
                    continue
                nx,ny=-dy/length,dx/length
                for px,py in ((ax,ay),(bx,by),((ax+bx)*0.5,(ay+by)*0.5)):
                    for sign in (-1,1):
                        ux,uy=sign*nx,sign*ny
                        x,y=px+ux*(radius+2),py+uy*(radius+2)
                        key=(round(x/2.5),round(y/2.5))
                        if key in seen:
                            continue
                        # Mark after checking validity, so an interior candidate
                        # cannot suppress a nearby usable exterior one.
                        z=self.ground_height(x,y)
                        if prism["top"]<z+height*0.6 or not self.point_clear((x,y,z),radius,height):
                            continue
                        seen.add(key)
                        index=len(self._cover)
                        self._cover.append((x,y,z,ux,uy,prism["top"]))
                        self._cover_bins.setdefault((math.floor(x/self.BIN),math.floor(y/self.BIN)),[]).append(index)

    def ground_height(self, x, y):
        if not self.available:
            return 0.0
        t = self.terrain
        fx = max(0.0, min(self.nx - 1.000001, (x - t["minX"]) / t["step"]))
        fy = max(0.0, min(self.ny - 1.000001, (y - t["minY"]) / t["step"]))
        i, j = int(fx), int(fy)
        u, v = fx - i, fy - j
        k = j * self.nx + i
        a, b, c, d = self.samples[k], self.samples[k + 1], self.samples[k + self.nx], self.samples[k + self.nx + 1]
        return ((a * (1-u) + b*u) * (1-v) + (c * (1-u) + d*u) * v) * t.get("scale", 0.01)

    def _terrain_grade(self,x,y,dx,dy):
        t=self.terrain
        fx=max(0.0,min(self.nx-1.000001,(x-t["minX"])/t["step"]))
        fy=max(0.0,min(self.ny-1.000001,(y-t["minY"])/t["step"]))
        i,j=int(fx),int(fy)
        u,v=fx-i,fy-j
        k=j*self.nx+i
        a,b,c,d=self.samples[k],self.samples[k+1],self.samples[k+self.nx],self.samples[k+self.nx+1]
        scale=t.get("scale",0.01)/t["step"]
        return (((b-a)*(1-v)+(d-c)*v)*dx+((c-a)*(1-u)+(d-b)*u)*dy)*scale

    def _terrain_cuts(self,pos,end):
        dx,dy=end[0]-pos[0],end[1]-pos[1]
        cuts=[0.0,1.0]
        terrain=self.terrain
        for origin,delta,start in ((pos[0],dx,terrain["minX"]),(pos[1],dy,terrain["minY"])):
            if abs(delta)<1e-9:
                continue
            first=math.floor((min(origin,origin+delta)-start)/terrain["step"])+1
            last=math.floor((max(origin,origin+delta)-start)/terrain["step"])
            for index in range(first,last+1):
                cuts.append((start+index*terrain["step"]-origin)/delta)
        cuts.sort()
        return cuts

    def _grade_clear(self,pos,end):
        dx,dy=end[0]-pos[0],end[1]-pos[1]
        distance=math.hypot(dx,dy)
        if distance<1e-6:
            return True
        cuts=self._terrain_cuts(pos,end)
        for a,b in zip(cuts,cuts[1:]):
            if b-a<1e-9:
                continue
            for fraction in (a+(b-a)*1e-5,b-(b-a)*1e-5):
                if self._terrain_grade(pos[0]+dx*fraction,pos[1]+dy*fraction,dx/distance,dy/distance)>self.max_slope+0.02:
                    return False
        return True

    def _candidates(self, x0, y0, x1, y1):
        result = set()
        for ix in range(math.floor(x0 / self.BIN), math.floor(x1 / self.BIN) + 1):
            for iy in range(math.floor(y0 / self.BIN), math.floor(y1 / self.BIN) + 1):
                result.update(self.bins.get((ix, iy), ()))
        return result

    @staticmethod
    def _solid(p, x, y):
        a,b,c,d=p["box"]
        if not (a<=x<=c and b<=y<=d):
            return False
        return _inside(x, y, p["ring"]) and not any(_inside(x, y, h) for h in p.get("holes", ()))

    def point_clear(self, pos, radius=2.5, height=9.0):
        """Cylinder clearance at specified feet height, allowing step-up surfaces."""
        if not self.available:
            return True
        x, y, z = pos
        collision_radius=max(0.0,radius-self.CONTACT_EPS)
        b = self.bounds
        # arena_margin is an authoritative center-position inset. Recorded
        # centers clamp at raw minY+30, not minY+30+body_radius. The larger
        # clearance also keeps very large bodies inside the physical map.
        inset=max(radius,self.arena_margin)
        if not (b["minX"] + inset-1e-6 <= x <= b["maxX"] - inset+1e-6 and b["minY"] + inset-1e-6 <= y <= b["maxY"] - inset+1e-6):
            return False
        for index in self._candidates(x-radius, y-radius, x+radius, y+radius):
            p = self.prisms[index]
            if p["top"] <= z + self.step_up + 0.02 or p["base"] >= z + height - 0.02:
                continue
            a,b,c,d=p["box"]
            if x+radius<a or x-radius>c or y+radius<b or y-radius>d:
                continue
            if self._solid(p,x,y):
                return False
            for ix in range(math.floor((x-radius)/self.BIN),math.floor((x+radius)/self.BIN)+1):
                for iy in range(math.floor((y-radius)/self.BIN),math.floor((y+radius)/self.BIN)+1):
                    if any(_distance2(x,y,*edge)<collision_radius*collision_radius for edge in p["edge_bins"].get((ix,iy),())):
                        return False
        return True

    def support_height(self,x,y,previous_z):
        """Highest walkable supporting surface no more than step_up above feet."""
        ground=self.ground_height(x,y)
        if not self.available:
            return ground
        result=ground
        for index in self._candidates(x,y,x,y):
            p=self.prisms[index]
            if result<p["top"]<=previous_z+self.step_up+0.02 and self._solid(p,x,y):
                result=p["top"]
        return result

    def move_clear(self, pos, end, radius=2.5, height=9.0):
        """Test a short grounded segment; also supports travel across a roof.

        An initial elevated foot height is kept only while supported by a prism.
        Drops are allowed; climbing higher than step_up needs the caller's jet.
        """
        if not self.available:
            return True
        dx, dy = end[0]-pos[0], end[1]-pos[1]
        distance = math.hypot(dx, dy)
        collision_radius=max(0.0,radius-self.CONTACT_EPS)
        if pos[2]<=self.ground_height(pos[0],pos[1])+self.step_up and not self._grade_clear(pos,end):
            return False
        # An exact horizontal capsule catches glancing corners that sampling
        # alone can miss. The terrain/support checks below handle vertical motion.
        for index in self._candidates(min(pos[0],end[0])-radius,min(pos[1],end[1])-radius,
                                      max(pos[0],end[0])+radius,max(pos[1],end[1])+radius):
            prism=self.prisms[index]
            if prism["top"]<=pos[2]+self.step_up+0.02 or prism["base"]>=pos[2]+height-0.02:
                continue
            a,b,c,d=prism["box"]
            if max(pos[0],end[0])+radius<a or min(pos[0],end[0])-radius>c or max(pos[1],end[1])+radius<b or min(pos[1],end[1])-radius>d:
                continue
            edges=set()
            for ix in range(math.floor((min(pos[0],end[0])-radius)/self.BIN),math.floor((max(pos[0],end[0])+radius)/self.BIN)+1):
                for iy in range(math.floor((min(pos[1],end[1])-radius)/self.BIN),math.floor((max(pos[1],end[1])+radius)/self.BIN)+1):
                    edges.update(prism["edge_bins"].get((ix,iy),()))
            if any(_segments_distance2(pos[0],pos[1],end[0],end[1],*edge)<collision_radius*collision_radius-1e-6 for edge in edges):
                return False
        count = max(1, int(math.ceil(distance / max(0.8, min(2.0, radius * 0.65)))))
        prev_z = float(pos[2])
        for i in range(1, count + 1):
            x, y = pos[0] + dx * i/count, pos[1] + dy*i/count
            ground = self.ground_height(x, y)
            z = ground
            if prev_z > ground + self.step_up:
                for index in self._candidates(x, y, x, y):
                    p = self.prisms[index]
                    if p["top"] <= prev_z + self.step_up and p["top"] > z and self._solid(p, x, y):
                        z = p["top"]
            rise = z - prev_z
            if rise > self.step_up + 0.02 and rise > self.max_slope * distance/count + 0.02:
                return False
            if not self.point_clear((x, y, z), radius, height):
                return False
            prev_z = z
        return True

    def line_of_fire(self, start, end):
        """Solid-prism intersection plus terrain obstruction; trees are ignored.

        Polygon holes and overhangs are respected. Bilinear terrain intersections
        are checked in every traversed terrain cell, with a 5 cm clearance margin.
        """
        if not self.available:
            return True
        x, y, z = start
        dx, dy, dz = end[0]-x, end[1]-y, end[2]-z
        for index in self._candidates(min(x,end[0]), min(y,end[1]), max(x,end[0]), max(y,end[1])):
            p = self.prisms[index]
            if abs(dz) < 1e-9:
                if z < p["base"] or z > p["top"]:
                    continue
                lo, hi = 0.0, 1.0
            else:
                a, b = (p["base"]-z)/dz, (p["top"]-z)/dz
                lo, hi = max(0.0,min(a,b)), min(1.0,max(a,b))
                if hi < lo:
                    continue
            if self._solid(p, x+dx*lo, y+dy*lo) or self._solid(p, x+dx*hi, y+dy*hi):
                return False
            cuts = [lo, hi]
            for ax, ay, bx, by in p["edges"]:
                ex, ey = bx-ax, by-ay
                cross = dx*ey-dy*ex
                if abs(cross) < 1e-10:
                    continue
                tx, ty = ax-x, ay-y
                u = (tx*ey-ty*ex)/cross
                v = (tx*dy-ty*dx)/cross
                if lo <= u <= hi and -1e-8 <= v <= 1+1e-8:
                    cuts.append(u)
            cuts.sort()
            for a,b in zip(cuts,cuts[1:]):
                mid=(a+b)*0.5
                if self._solid(p,x+dx*mid,y+dy*mid):
                    return False
        kernel=getattr(self,'_terrain_kernel',None)
        if kernel is not None:
            result=kernel.line_clear(self,start,end)
            if result is not None:
                return result
        cuts=self._terrain_cuts(start,end)
        for a,b in zip(cuts,cuts[1:]):
            if b-a<1e-10:
                continue
            mid=(a+b)*0.5
            fa=z+dz*a-self.ground_height(x+dx*a,y+dy*a)
            fb=z+dz*b-self.ground_height(x+dx*b,y+dy*b)
            fm=z+dz*mid-self.ground_height(x+dx*mid,y+dy*mid)
            if min(fa,fb,fm)<0.05:
                return False
            # Ground along a line through one bilinear cell is quadratic.
            # Check its interior clearance minimum as well as its endpoints.
            qa=2*(fa+fb-2*fm)
            qb=fb-fa-qa
            if qa>1e-10:
                u=-qb/(2*qa)
                if 0<u<1 and qa*u*u+qb*u+fa<0.05:
                    return False
        return True

    def _cell(self, p):
        return (max(0,min(self.gx-1,round((p[0]-self.bounds["minX"])/self.GRID))),
                max(0,min(self.gy-1,round((p[1]-self.bounds["minY"])/self.GRID))))

    def _point(self, cell):
        x=self.bounds["minX"]+cell[0]*self.GRID
        y=self.bounds["minY"]+cell[1]*self.GRID
        return (x,y,self.ground_height(x,y))

    def _free(self, cell, dims):
        if not (0 <= cell[0] < self.gx and 0 <= cell[1] < self.gy):
            return False
        key=(dims,cell)
        value=self._walk_cache.get(key)
        if value is None:
            p=self._point(cell)
            r,h=dims
            value=self.point_clear(p,r,h)
            if value:
                x,y,z=p
                # Local maximum uphill slope at one terrain-cell spacing.
                value=all(self.ground_height(x+dx,y+dy)-z <= self.max_slope+0.02
                          for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))
            self._walk_cache[key]=value
        return value

    def _nearest_free(self, cell, dims, deadline=None):
        if self._free(cell,dims):
            return cell
        for rad in range(1,9):
            if deadline is not None and time.perf_counter()>=deadline:
                return None
            ring=[]
            for d in range(-rad,rad+1):
                ring.extend(((cell[0]+d,cell[1]-rad),(cell[0]+d,cell[1]+rad)))
            for d in range(-rad+1,rad):
                ring.extend(((cell[0]-rad,cell[1]+d),(cell[0]+rad,cell[1]+d)))
            ring.sort(key=lambda c:(c[0]-cell[0])**2+(c[1]-cell[1])**2)
            for candidate in ring:
                if deadline is not None and time.perf_counter()>=deadline:
                    return None
                if self._free(candidate,dims):
                    return candidate
        return None

    @staticmethod
    def _heuristic(a,b):
        dx,dy=abs(a[0]-b[0]),abs(a[1]-b[1])
        return max(dx,dy)+0.41421356237*min(dx,dy)

    def _traversable(self,cell,nxt,dims):
        # Terrain traversal is directional: a steep drop can be legal even
        # when climbing the same edge is impossible.
        edge_key=(dims,cell,nxt)
        result=self._edge_cache.get(edge_key)
        if result is None:
            result=self.move_clear(self._point(cell),self._point(nxt),*dims)
            self._edge_cache[edge_key]=result
        return result

    def _local_steer(self,pos,goal,radius,height,deadline=None):
        dx,dy=_direction(pos,goal)
        if not dx and not dy:
            return (0.0,0.0)
        angle=math.atan2(dy,dx)
        for turn in (0,0.45,-0.45,0.85,-0.85,1.25,-1.25,1.7,-1.7,2.3,-2.3,math.pi):
            if deadline is not None and time.perf_counter()>=deadline:
                break
            vx,vy=math.cos(angle+turn),math.sin(angle+turn)
            if self.move_clear(pos,(pos[0]+vx*5,pos[1]+vy*5,pos[2]),radius,height):
                return (vx,vy)
        return (0.0,0.0)

    def navigate(self,pos,goal,radius=2.5,height=9.0,deadline=None):
        """Ground route steering, with bounded incremental A* and local avoidance."""
        if not self.available:
            return _direction(pos,goal)
        if deadline is None:
            deadline=time.perf_counter()+0.008
        if time.perf_counter()>=deadline:
            return (0.0,0.0)
        if math.hypot(goal[0]-pos[0],goal[1]-pos[1])<1.0:
            return (0.0,0.0)
        if math.hypot(goal[0]-pos[0],goal[1]-pos[1]) < 40 and self.move_clear(pos,goal,radius,height):
            return _direction(pos,goal)
        # Round clearance upward so caches never understate a growing mech.
        dims=(math.ceil(radius*2)/2,math.ceil(height*2)/2)
        if dims!=self._active_dims:
            self._walk_cache.clear()
            self._edge_cache.clear()
            self._active_dims=dims
        target=self._nearest_free(self._cell(goal),dims,deadline)
        start=self._nearest_free(self._cell(pos),dims,deadline)
        if target is None or start is None:
            return self._local_steer(pos,goal,radius,height,deadline)
        key=(target,dims)
        search=self._search
        if search is None or search["key"] != key or self._heuristic(start,search["start"])>7:
            search={"key":key,"start":start,"heap":[(self._heuristic(start,target),0.0,start)],
                    "g":{start:0.0},"came":{},"closed":set(),"best":start,"done":False}
            self._search=search
            self._path=[]
        expanded=0
        # Keep time for validating a steering segment after the graph search.
        search_deadline=deadline-0.0025
        while search["heap"] and not search["done"] and expanded<600:
            if time.perf_counter()>=search_deadline:
                break
            _,cost,cell=heapq.heappop(search["heap"])
            if cell in search["closed"]:
                continue
            search["closed"].add(cell)
            expanded+=1
            if self._heuristic(cell,target)<self._heuristic(search["best"],target):
                search["best"]=cell
            if cell==target:
                search["done"]=True
                search["best"]=cell
                break
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt=(cell[0]+dx,cell[1]+dy)
                if nxt in search["closed"] or not self._free(nxt,dims):
                    continue
                if dx and dy and (not self._free((cell[0]+dx,cell[1]),dims) or not self._free((cell[0],cell[1]+dy),dims)):
                    continue
                # Segment checking prevents cutting across thin walls or slopes
                # between otherwise valid grid-cell centers.
                if not self._traversable(cell,nxt,dims):
                    continue
                new=cost+(1.41421356237 if dx and dy else 1)
                if new < search["g"].get(nxt,float("inf")):
                    search["g"][nxt]=new
                    search["came"][nxt]=cell
                    heapq.heappush(search["heap"],(new+self._heuristic(nxt,target),new,nxt))
        cell=search["best"]
        path=[self._point(cell)]
        while cell in search["came"]:
            cell=search["came"][cell]
            path.append(self._point(cell))
        path.reverse()
        self._path=path
        # Skip passed points; seek the farthest short, unobstructed waypoint.
        nearest=min(range(len(path)),key=lambda i:(path[i][0]-pos[0])**2+(path[i][1]-pos[1])**2)
        for i in range(min(len(path)-1,nearest+3),nearest,-1):
            if time.perf_counter()>=deadline:
                break
            if self.move_clear(pos,path[i],radius,height):
                return _direction(pos,path[i])
        if (search["done"] and time.perf_counter()<deadline
                and math.hypot(pos[0]-goal[0],pos[1]-goal[1])<40
                and self.move_clear(pos,goal,radius,height)):
            return _direction(pos,goal)
        return self._local_steer(pos,goal,radius,height,deadline)

    def cover_candidates(self,pos,zone_center,zone_radius,radius=2.5,height=9.0,limit=16,deadline=None):
        """At most twelve spatially diverse wall-adjacent ground positions.

        These are geometry candidates, not guaranteed protection from a particular
        enemy. Cached geometry keeps generation within a three-millisecond target;
        the tactical controller should reserve additional time to score protection.
        """
        if not self.available or limit<=0:
            return []
        now=time.perf_counter()
        deadline=min(deadline if deadline is not None else now+0.003,now+0.003)
        if now>=deadline:
            return []
        limit=min(limit,12)
        reach=min(150.0,max(40.0,zone_radius))
        shift=radius-self._cover_base_radius
        buckets=[[] for _ in range(8)]
        for ix in range(math.floor((pos[0]-reach-abs(shift))/self.BIN),math.floor((pos[0]+reach+abs(shift))/self.BIN)+1):
            for iy in range(math.floor((pos[1]-reach-abs(shift))/self.BIN),math.floor((pos[1]+reach+abs(shift))/self.BIN)+1):
                for index in self._cover_bins.get((ix,iy),()):
                    x,y,z,nx,ny,top=self._cover[index]
                    x,y=x+nx*shift,y+ny*shift
                    dx,dy=x-pos[0],y-pos[1]
                    distance=math.hypot(dx,dy)
                    if not (4<distance<=reach) or math.hypot(x-zone_center[0],y-zone_center[1])+radius+2>zone_radius:
                        continue
                    sector=int((math.atan2(dy,dx)+math.pi)/(math.pi/4))%8
                    buckets[sector].append((distance,index,x,y,z,top))
        for bucket in buckets:
            bucket.sort(reverse=True)
        dims=(radius,height)
        if dims!=self._cover_dims:
            self._cover_dynamic.clear()
            self._cover_dims=dims
        base_dims=abs(shift)<1e-8 and abs(height-self._cover_base_height)<1e-8
        selected=[]
        sectors=[0]*8
        attempts=0
        while len(selected)<limit and attempts<128:
            if time.perf_counter()>=deadline:
                break
            available=[i for i in range(8) if buckets[i]]
            if not available:
                break
            sector=min(available,key=lambda i:buckets[i][-1][0]+8*sectors[i])
            _,index,x,y,z,top=buckets[sector].pop()
            attempts+=1
            if any((x-a)**2+(y-b)**2<49 for a,b,_ in selected):
                continue
            if not base_dims:
                point=self._cover_dynamic.get(index)
                if point is None:
                    z=self.ground_height(x,y)
                    point=(x,y,z) if top>=z+height*0.6 and self.point_clear((x,y,z),radius,height) else False
                    self._cover_dynamic[index]=point
                if point is False:
                    continue
                x,y,z=point
            selected.append((x,y,z))
            sectors[sector]+=1
        return selected
