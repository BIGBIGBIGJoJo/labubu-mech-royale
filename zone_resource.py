"""Prototype: verify a short collect-and-exit witness before overriding rotation.

This is a conservative policy model, not authoritative game simulation. The
caller must preserve its ordinary exposure checks and combat target selection,
pass emergency=True to Combat.plan for an admitted plan, and execute/revalidate
the exit after collection. None means do not override rotation.
"""
from __future__ import annotations
import math
import time


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def circle_at(obs, seconds):
    zone = obs["zone"]
    begin = max(obs["t"], zone["shrink_start"])
    f = max(0.0, min(1.0, (obs["t"]+seconds-begin)/max(.001, zone["shrink_end"]-begin)))
    center = [zone["center"][i]+f*(zone["next_center"][i]-zone["center"][i]) for i in (0,1)]
    return center, zone["radius"]+f*(zone["next_radius"]-zone["radius"])


class ZoneResourcePlanner:
    # Policy hypotheses, not engine constants. Retain existing 12-second/8-m
    # planning scales; the release gap and exit reserve introduce hysteresis.
    LOOKAHEAD = 12.0
    BODY_MARGIN = 8.0
    ROTATION_RELEASE = 6.0
    EXIT_RESERVE_S = 4.0
    BUDGET_S = .006
    NO_PROGRESS_S = 2.0
    PROGRESS_M = .75

    def __init__(self, config, arena):
        self.config = config
        self.arena = arena
        self.rotating = False
        self.last_report = {"reason":"none"}
        self._lease = None
        self.retry_after = -math.inf

    def rotation_required(self, obs, stats):
        center, radius = circle_at(obs, self.LOOKAHEAD)
        slack = radius-distance(obs["self"]["pos"], center)-stats["radius"]-self.BODY_MARGIN
        if not obs["self"]["in_zone"] or slack < 0:
            self.rotating = True
        elif slack >= self.ROTATION_RELEASE:
            self.rotating = False
        return self.rotating

    def _reject(self, reason):
        self.last_report = {"reason":reason}
        return None

    def _known(self, obs, kind, item):
        return next((x for x in obs.get(kind,()) if x["id"] == item["id"]), None)

    def _growth(self, obs, pickup, escape, stats):
        """Overestimate incidental cubes on both XY segments, including high ones."""
        radius = self.config["cubes"]["pickup_radius"]
        points = [obs["self"]["pos"], pickup, escape]
        n = 0
        for cube in obs.get("cubes", ()):
            for a,b in zip(points, points[1:]):
                dx,dy=b[0]-a[0],b[1]-a[1]
                f=max(0.0,min(1.0,((cube["pos"][0]-a[0])*dx+(cube["pos"][1]-a[1])*dy)/max(1e-9,dx*dx+dy*dy)))
                if distance(cube["pos"], (a[0]+f*dx,a[1]+f*dy)) <= radius:
                    n += 1
                    break
        current = obs["self"].get("cubes",0)
        step = self.config["cubes"]["size_per_cube"]
        factor = (1+step*(current+n))/(1+step*current)
        return n, stats["radius"]*factor, stats["height"]*factor

    def _timeline(self, obs, points, radii, speed, acceleration, deadline):
        # A stopping/turning allowance delays each leg; it is deliberately
        # separate from full-speed transit. Collision/dodging remain tactical.
        hz = self.config["match"]["tick_hz"]
        decision = self.config["match"]["decide_every"]/hz
        elapsed = 0.0
        worst = math.inf
        for leg,(a,b) in enumerate(zip(points,points[1:])):
            delay = decision + ((math.hypot(*obs["self"]["vel"][:2])+speed)
                                if leg == 0 else 2*speed)/max(1,acceleration)
            delay_start = elapsed
            elapsed += delay
            duration = distance(a,b)/speed
            # Both position and circle are affine between hold/shrink endpoints.
            # Clearance is concave, so endpoints plus time-phase boundaries are
            # sufficient on each straight constant-speed leg.
            cuts=[0.0,1.0]
            if duration:
                for boundary in (obs["zone"]["shrink_start"],obs["zone"]["shrink_end"]):
                    f=(boundary-obs["t"]-elapsed)/duration
                    if 0<f<1: cuts.append(f)
            # Also test the stationary delay immediately before this leg.
            for seconds in (delay_start,elapsed):
                center,radius=circle_at(obs,seconds)
                worst=min(worst,radius-distance(a,center)-radii[leg]-self.BODY_MARGIN)
            for f in cuts:
                if time.perf_counter() >= deadline:
                    return None
                center,radius=circle_at(obs,elapsed+duration*f)
                point=(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f)
                worst=min(worst,radius-distance(point,center)-radii[leg]-self.BODY_MARGIN)
            elapsed += duration
        # Explicitly reserve time to start the next rotation after reaching the
        # exit. The point's construction alone does not prove this hold safe.
        for seconds in (elapsed, elapsed+self.EXIT_RESERVE_S):
            center,radius=circle_at(obs,seconds)
            worst=min(worst,radius-distance(points[-1],center)-radii[-1]-self.BODY_MARGIN)
        # Do not extrapolate beyond the currently announced phase when a later
        # phase's center/radius is unknown to this observation.
        known_until=max(obs["zone"]["shrink_end"]-obs["t"],0)
        if elapsed+self.EXIT_RESERVE_S > known_until:
            return None
        return elapsed,worst

    def _validate(self, obs, points, stats, deadline):
        """A full direct ground route is required, not a point or partial A*."""
        cubes,radius,height=self._growth(obs,points[-2],points[-1],stats)
        if any(distance(a,b)>150 for a,b in zip(points,points[1:])):
            return None
        for point in points:
            if time.perf_counter()>=deadline or not self.arena.point_clear(point,radius,height):
                return None
        for a,b in zip(points,points[1:]):
            if time.perf_counter()>=deadline or not self.arena.move_clear(a,b,radius,height):
                return None
        result=self._timeline(obs,points,[radius]*(len(points)-1),stats["walk_speed"],
                              stats["ground_accel"],deadline)
        if result is None or result[1]<0:
            return None
        return result[0],cubes,radius,height,result[1]

    def plan(self, obs, candidate, stats, deadline=None):
        """Validate a current cube/weapon candidate and an online escape point.

        `candidate` is an existing exposure-filtered resource_goal tuple. This
        component does not replace enemy-risk/value gates or claim that a clear
        point implies a complete route: both full ground segments must pass.
        """
        begin=time.perf_counter()
        deadline=min(deadline if deadline is not None else math.inf,begin+self.BUDGET_S)
        if time.perf_counter() >= deadline:
            return self._reject("budget")
        me=obs["self"]
        if not me.get("grounded") or not me.get("in_zone"):
            return self._reject("not_grounded_inside_zone")
        if not self.arena.available:
            return self._reject("map_unavailable")
        if any(w and w["kind"]=="laser" and w.get("charge",0)>0 for w in me["weapons"]):
            return self._reject("active_charge")
        if candidate is None or candidate[2] not in ("cubes","pickups"):
            return self._reject("not_immediate_pickup")
        kind,key,item=candidate[2],candidate[3],candidate[4]
        observed=self._known(obs,kind,item)
        if observed is None:
            return self._reject("not_currently_observed")
        if len(obs.get("cubes",()))>256:
            return self._reject("growth_scan_limit")
        pickup=tuple(observed["pos"])
        if abs(pickup[2]-self.arena.ground_height(*pickup[:2]))>3:
            return self._reject("pickup_not_grounded")
        speed=max(1,float(stats["walk_speed"]))
        initial_eta=distance(me["pos"],pickup)/speed
        horizon=max(self.LOOKAHEAD,initial_eta+self.EXIT_RESERVE_S)
        center,radius=circle_at(obs,horizon)
        bearing=math.atan2(pickup[1]-center[1],pickup[0]-center[0])
        for offset in (0,.35,-.35):
            if time.perf_counter() >= deadline:
                return self._reject("budget")
            # First estimate body growth, then recompute the inward radius once.
            grown_r=stats["radius"]
            for _ in range(2):
                reach=max(0,radius-grown_r-self.BODY_MARGIN-speed*self.EXIT_RESERVE_S)
                reach=min(reach,distance(pickup,center))
                angle=bearing+offset
                x,y=center[0]+reach*math.cos(angle),center[1]+reach*math.sin(angle)
                escape=(x,y,self.arena.ground_height(x,y))
                cubes,grown_r,grown_h=self._growth(obs,pickup,escape,stats)
            # Maximum incidental growth is used on both full segments. A narrow
            # approach can be conservatively rejected; size is not understated.
            result=self._validate(obs,[me["pos"],pickup,escape],stats,deadline)
            if result is None:
                continue
            duration,cubes,grown_r,grown_h,slack=result
            plan={"key":key,"pickup":pickup,"escape":escape,"trip_s":duration,
                  "min_zone_slack":slack,"modeled_cubes":cubes,"radius":grown_r,"height":grown_h,
                  "suppress_laser_charge":True,"speed":speed,"created":obs["t"],
                  "model":"grounded direct two-leg witness; not a simulation"}
            self.last_report={"reason":"admitted",**plan,"ms":(time.perf_counter()-begin)*1000}
            return plan  # First complete witness; no optional ranking work.
        return self._reject("route_or_zone_unsafe")

    def start_lease(self, obs, candidate, stats, deadline=None):
        """Caller already applied ordinary resource value/exposure checks."""
        if obs["t"]<self.retry_after:
            return self._reject("retry_delay")
        plan=self.plan(obs,candidate,stats,deadline)
        if plan is None:
            return None
        self._lease={**plan,"phase":"collect","initial_cubes":obs["self"]["cubes"],
                     "expires":obs["t"]+plan["trip_s"]+self.EXIT_RESERVE_S,
                     "best_distance":distance(obs["self"]["pos"],plan["pickup"]),
                     "progress_t":obs["t"]}
        return {**plan,"goal":plan["pickup"],"phase":"collect"}

    @property
    def lease_key(self):
        return self._lease["key"] if self._lease is not None else None

    @property
    def exiting(self):
        return self._lease is not None and self._lease["phase"]=="exit"

    def collection_observed(self, obs, stats):
        if self._lease is None:
            return False
        kind,item_id=self._lease["key"]
        if any(x["id"]==item_id for x in obs.get(kind,())):
            return False
        collected=(obs["self"]["cubes"]>self._lease["initial_cubes"] if kind=="cubes" else
                   any(e["type"]=="took" and e.get("id")==item_id for e in obs.get("events",())))
        near=distance(obs["self"]["pos"],self._lease["pickup"])<=self.config["cubes"]["pickup_radius"]+stats["walk_speed"]*.2
        return collected and near

    def cancel(self, reason="preempted", now=None):
        self._lease=None
        self.last_report={"reason":reason}
        if now is not None and reason!="exit_reached":
            self.retry_after=now+self.NO_PROGRESS_S

    def continue_lease(self, obs, stats, *, eligible, deadline=None):
        """Revalidate a stable collect/exit commitment from current state.

        `eligible` must repeat the caller's exposure/health/priority checks for
        the leased objective, not simply report whether *some* loot is eligible.
        False, None return, or any failure means ordinary rotation takes over.
        """
        lease=self._lease
        if lease is None:
            return None
        begin=time.perf_counter()
        deadline=min(deadline if deadline is not None else math.inf,begin+self.BUDGET_S)
        me=obs["self"]
        reason=None
        if not eligible:
            reason="preempted"
        elif obs["t"]>lease["expires"]:
            reason="expired"
        elif not me.get("grounded") or not me.get("in_zone") or not self.arena.available:
            reason="invalid_state"
        elif any(w and w["kind"]=="laser" and w.get("charge",0)>0 for w in me["weapons"]):
            reason="active_charge"
        elif len(obs.get("cubes",()))>256:
            reason="growth_scan_limit"
        if reason:
            self.cancel(reason,obs["t"])
            return None
        if lease["phase"]=="collect":
            kind,item_id=lease["key"]
            present=next((x for x in obs.get(kind,()) if x["id"]==item_id),None)
            if present is None:
                if not self.collection_observed(obs,stats):
                    self.cancel("resource_disappeared",obs["t"])
                    return None
                lease["phase"]="exit"
                lease["best_distance"]=distance(me["pos"],lease["escape"])
                lease["progress_t"]=obs["t"]
            elif distance(present["pos"],lease["pickup"])>1:
                self.cancel("resource_moved",obs["t"])
                return None
        goal=lease["pickup"] if lease["phase"]=="collect" else lease["escape"]
        remaining=distance(me["pos"],goal)
        if lease["phase"]=="exit" and remaining<1.5:
            self.cancel("exit_reached")
            return None
        if remaining<lease["best_distance"]-self.PROGRESS_M:
            lease["best_distance"],lease["progress_t"]=remaining,obs["t"]
        elif obs["t"]-lease["progress_t"]>self.NO_PROGRESS_S:
            self.cancel("no_progress",obs["t"])
            return None
        points=[me["pos"],lease["pickup"],lease["escape"]] if lease["phase"]=="collect" else [me["pos"],lease["escape"]]
        result=self._validate(obs,points,stats,deadline)
        if result is None:
            self.cancel("route_or_zone_unsafe",obs["t"])
            return None
        duration,cubes,radius,height,slack=result
        self.last_report={"reason":"continued","phase":lease["phase"],"min_zone_slack":slack,
                          "remaining_trip_s":duration,"ms":(time.perf_counter()-begin)*1000}
        return {**lease,"goal":goal,"radius":radius,"height":height,
                "min_zone_slack":slack,"remaining_trip_s":duration}
