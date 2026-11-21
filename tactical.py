"""Bounded trajectory selection for mechfight/1.

The horizontal integrator follows the recorded vector acceleration limit at the
configured physics rate. This is a short-horizon controller, not a full match
simulator. Geometry remains authoritative through ArenaMap collision queries.
"""
from __future__ import annotations

import math
import time


def clamp(value,low,high):
    return max(low,min(high,value))


def unit(x,y):
    length=math.hypot(x,y)
    return (x/length,y/length) if length>1e-9 else (0.0,0.0)


def accelerate(vx,vy,target_x,target_y,maximum_delta):
    """Limit the velocity-vector change, rather than each component separately."""
    dx,dy=target_x-vx,target_y-vy
    length=math.hypot(dx,dy)
    fraction=min(1.0,maximum_delta/max(length,1e-12))
    return vx+dx*fraction,vy+dy*fraction


class TacticalPlanner:
    def __init__(self,config,arena):
        self.config=config
        self.map=arena
        self.dt=1.0/max(1.0,float(config.get("match",{}).get("tick_hz",20)))
        self.steps=max(2,int(round(0.6/self.dt)))
        self.horizon=self.steps*self.dt
        self.action_dt=self.dt*max(1,int(config.get("match",{}).get("decide_every",2)))
        self.last_direction=(0.0,0.0)
        self.last_report={}
        self._geometry_recovery_pending=False
        self.boost_recharging=None
        self._boost_frame=None
        self._boost_time=-float("inf")
        self.lightning_escape_range=float(config["weapons"]["lightning"]["range"])
        for upgrade in config.get("upgrades",()):
            for effect in upgrade.get("effects",()):
                if effect.get("path")=="weapons.lightning.range":
                    for _ in range(int(upgrade.get("max",1))):
                        self.lightning_escape_range=(self.lightning_escape_range+max(0,effect.get("add",0)))*max(1,effect.get("mul",1))

    def _boost_permission(self,obs,stats,shot_energy):
        """Update the observed-energy latch once; never assume a shot occurred."""
        me=obs["self"]
        low=35.0
        high=min(65.0,float(me.get("max_energy",stats.get("energy",100))))
        remaining=float(me["energy"])-shot_energy-stats["boost_drain"]*self.action_dt
        frame=(obs.get("tick"),obs.get("t"))
        now=float(obs.get("t",0))
        if frame!=self._boost_frame or now<self._boost_time:
            if self.boost_recharging is None or now<self._boost_time:
                self.boost_recharging=me["energy"]<high
            if remaining<low:
                self.boost_recharging=True
            elif me["energy"]>=high:
                self.boost_recharging=False
            self._boost_frame=frame
            self._boost_time=now
        grounded=me.get("grounded",True)
        return grounded and not self.boost_recharging and remaining>=low, grounded and remaining>=12.0, high

    def _pursuit_gain(self,walk,boost,threats,stats):
        """Observed closing pursuer, with materially better boosted separation."""
        start=walk[0]
        for q in threats:
            actor=q["actor"]
            if not q.get("los") or actor.get("kind")!="mech":
                continue
            px,py=actor["pos"][:2]
            vx,vy=actor.get("vel",(0,0,0))[:2]
            dx,dy=start[1]-px,start[2]-py
            distance=math.hypot(dx,dy)
            if (vx*dx+vy*dy)/max(distance,.001)<2.0:
                continue
            enemy_radius=self.config["mech"]["radius"]*(1+self.config.get("cubes",{}).get("size_per_cube",.05)*actor.get("cubes",0))
            danger=(self.lightning_escape_range+stats["radius"]+3 if "lightning" in actor.get("weapons",())
                    else 30.0+stats["radius"]+enemy_radius)
            enemy=(px+vx*self.horizon,py+vy*self.horizon)
            walking=math.hypot(walk[-1][1]-enemy[0],walk[-1][2]-enemy[1])
            boosted=math.hypot(boost[-1][1]-enemy[0],boost[-1][2]-enemy[1])
            if walking<=danger and walking<distance-.5 and boosted-walking>=2.0:
                return True
        return False

    def _boost_override(self,walk,boost,walk_bullet,boost_bullet,walk_beam,boost_beam,threats,stats):
        if walk_bullet-boost_bullet>=max(12.0,self.config["weapons"]["gun"]["damage"]*.35):
            return "projectile"
        if walk_beam-boost_beam>=self.config["weapons"]["laser"]["damage"]*.05:
            return "aimed_beam"
        if self._pursuit_gain(walk,boost,threats,stats):
            return "close_pursuer"
        return None

    def rollout(self,me,direction,boost,stats):
        """Return states (t,x,y,z,vx,vy,vz,energy,grounded) at physics boundaries."""
        x,y,z=map(float,me["pos"])
        vx,vy,vz=map(float,me["vel"])
        energy=float(me["energy"])
        grounded=bool(me.get("grounded",True))
        charging=any(w and w["kind"]=="laser" and w.get("charge",0)>0 for w in me["weapons"])
        charge_mult=stats.get("charge_move_mult",0.5) if charging else 1.0
        dx,dy=direction
        moving=math.hypot(dx,dy)>1e-8
        path=[(0.0,x,y,z,vx,vy,vz,energy,grounded)]
        for i in range(self.steps):
            active=boost and moving and grounded and energy>=stats["boost_drain"]*self.dt
            speed=stats["boost_speed"] if active else stats["walk_speed"]
            if active:
                energy=max(0.0,energy-stats["boost_drain"]*self.dt)
            acceleration=stats["ground_accel"] if grounded else stats["air_accel"]
            vx,vy=accelerate(vx,vy,dx*speed*charge_mult,dy*speed*charge_mult,acceleration*self.dt)
            x+=vx*self.dt
            y+=vy*self.dt
            if not grounded:
                # Purposeful flight is not selected by this controller. Existing
                # jumps fall naturally; surface contact is checked subsequently.
                vz-=stats["gravity"]*self.dt
                z+=vz*self.dt
            path.append(((i+1)*self.dt,x,y,z,vx,vy,vz,energy,grounded))
        return path

    def _projectiles(self,obs,deadline):
        me=obs["self"]
        def arrival(p):
            speed=math.sqrt(sum(v*v for v in p["vel"]))
            return math.dist(p["pos"],me["pos"])/max(speed,1.0)-(0.3 if p["kind"]=="mortar" else 0)
        tracks=[]
        for bullet in sorted(obs.get("projectiles",()),key=arrival)[:12]:
            if time.perf_counter()>=deadline:
                break
            kind=bullet["kind"]
            weapon=self.config.get("weapons",{}).get(kind,{})
            gravity=float(self.config["weapons"]["mortar"]["gravity"]) if kind=="mortar" else 0.0
            px,py,pz=bullet["pos"]
            vx,vy,vz=bullet["vel"]
            points=[(px+vx*i*self.dt,py+vy*i*self.dt,pz+vz*i*self.dt-0.5*gravity*(i*self.dt)**2)
                    for i in range(self.steps+1)]
            damage=float(weapon.get("damage",self.config.get("npc",{}).get("damage",25)))
            track={"kind":kind,"points":points,"damage":damage,"impact":None,
                   "splash":float(weapon.get("splash",0)),"splash_radius":float(weapon.get("splash_radius",0))}
            if kind=="mortar" and gravity>0:
                # Terrain impact prediction; walls may cause an earlier blast,
                # handled conservatively by the shell's swept proximity cost.
                ground=self.map.ground_height(px,py)
                impact=None
                for _ in range(3):
                    discriminant=vz*vz+2*gravity*(pz-ground)
                    if discriminant<0:
                        break
                    ti=(vz+math.sqrt(discriminant))/gravity
                    if ti<0 or ti>self.horizon+0.25:
                        break
                    ix,iy=px+vx*ti,py+vy*ti
                    impact=(ti,ix,iy,ground)
                    ground=self.map.ground_height(ix,iy)
                track["impact"]=impact
            tracks.append(track)
        return tracks

    @staticmethod
    def _swept_distance(path,points,height):
        """Closest horizontal approach while projectile overlaps body height.

        Segment sweeps prevent a 252 m/s bullet tunneling between 20Hz samples.
        Vertical clipping happens before closest approach, so overhead shots do
        not trigger a pointless dodge. Body center is represented by feet+height.
        """
        best=float("inf")
        for i,(a,b) in enumerate(zip(path,path[1:])):
            pa,pb=points[i],points[i+1]
            rz0,rz1=pa[2]-a[3],pb[2]-b[3]
            low,high=0.0,1.0
            dz=rz1-rz0
            if abs(dz)<1e-12:
                if rz0<-.2 or rz0>height+.2:
                    continue
            else:
                lo,hi=(-.2-rz0)/dz,(height+.2-rz0)/dz
                low=max(low,min(lo,hi))
                high=min(high,max(lo,hi))
                if high<low:
                    continue
            x0,y0=pa[0]-a[1],pa[1]-a[2]
            x1,y1=pb[0]-b[1],pb[1]-b[2]
            dx,dy=x1-x0,y1-y0
            fraction=clamp(-(x0*dx+y0*dy)/max(dx*dx+dy*dy,1e-12),low,high)
            best=min(best,math.hypot(x0+dx*fraction,y0+dy*fraction))
        return best

    @staticmethod
    def _at(path,t):
        if t<=0:
            return path[0][1:4]
        for a,b in zip(path,path[1:]):
            if t<=b[0]:
                f=(t-a[0])/max(1e-9,b[0]-a[0])
                return tuple(a[j]+(b[j]-a[j])*f for j in (1,2,3))
        return path[-1][1:4]

    def projectile_cost(self,path,tracks,stats):
        total=0.0
        radius,height=stats["radius"],stats["height"]
        for track in tracks:
            miss=self._swept_distance(path,track["points"],height)
            # Known intersections dominate small progress gains. A one-metre
            # margin expresses state/model uncertainty, not a larger hitbox.
            direct_damage=track["damage"]+(track["splash"] if track["kind"]=="mortar" else 0)
            risk=direct_damage*clamp((radius+1.0-miss)/1.2,0,1)
            impact=track["impact"]
            if impact:
                ti,x,y,z=impact
                own=self._at(path,ti)
                d=math.dist((x,y,z),own)
                splash=track["splash_radius"]+radius
                if d<splash:
                    blast=track["splash"]*(1-.7*clamp(d/max(splash,.1),0,1))
                    risk=max(risk,blast*(1 if ti<=self.horizon else .7))
            total+=risk
        return total

    def _future_zone(self,obs,t):
        zone=obs["zone"]
        start=max(obs["t"],zone["shrink_start"])
        fraction=clamp((obs["t"]+t-start)/max(.001,zone["shrink_end"]-start),0,1)
        return (zone["center"][0]+fraction*(zone["next_center"][0]-zone["center"][0]),
                zone["center"][1]+fraction*(zone["next_center"][1]-zone["center"][1]),
                zone["radius"]+fraction*(zone["next_radius"]-zone["radius"]))

    def _zone_cost(self,path,obs,stats):
        cost=0.0
        for state in path[1:]:
            cx,cy,r=self._future_zone(obs,state[0])
            outside=max(0.0,math.hypot(state[1]-cx,state[2]-cy)+stats["radius"]-r)
            if outside:
                cost+=obs["zone"]["dps"]*self.dt+outside*.12
        return cost

    def _strength(self,actor,distance):
        """Intrinsic threat; deliberately excludes the current LOS discount."""
        cube=self.config.get("cubes",{})
        scale=1+cube.get("damage_per_cube",.04)*min(actor.get("cubes",0),cube.get("stat_cap",10))
        score=0.0
        kinds=actor.get("weapons",["npc"] if actor.get("kind")=="npc" else ["gun"])
        for kind in kinds:
            weapon=self.config.get("weapons",{}).get(kind,{})
            if kind=="npc":
                score+=15*clamp(1-distance/70,0,1)
                continue
            reach=weapon.get("range",230)
            if kind=="lightning":
                factor=clamp((reach+9-distance)/14,0,1)
            elif kind=="mortar":
                reach=weapon.get("speed",72)**2/max(1,weapon.get("gravity",22))
                factor=.22*clamp(1-distance/max(1,reach+20),0,1)
            else:
                factor=(.18+.55*math.exp(-distance/85))*clamp((reach+8-distance)/20,0,1)
            cooldown=weapon.get("cooldown",1)+ (weapon.get("charge",0) if kind=="laser" else 0)
            score+=weapon.get("damage",45)/max(.1,cooldown)*factor
        return score*scale

    def _beam_cost(self,path,threats,stats):
        cost=0.0
        laser=self.config["weapons"]["laser"]
        for q in threats:
            actor=q["actor"]
            if not actor.get("charging") or not q.get("los"):
                continue
            yaw,pitch=actor.get("aim",(0,0))
            scale=1+self.config.get("cubes",{}).get("size_per_cube",.05)*actor.get("cubes",0)
            muzzle=actor["pos"][2]+self.config["mech"]["muzzle_height"]*scale
            for index in (2,min(6,self.steps),self.steps):
                p=path[min(index,len(path)-1)]
                dx,dy=p[1]-actor["pos"][0],p[2]-actor["pos"][1]
                along=dx*math.cos(yaw)+dy*math.sin(yaw)
                if not 0<along<laser["range"]:
                    continue
                beam_z=muzzle+math.tan(pitch)*along
                if p[3]-.5<=beam_z<=p[3]+stats["height"]+.5:
                    miss=abs(dx*math.sin(yaw)-dy*math.cos(yaw))
                    cost+=laser["damage"]*.10*clamp((stats["radius"]+1.0-miss)/1.5,0,1)
        return cost

    def _exposure(self,path,threats,stats,exact,deadline):
        total=0.0
        for q in threats:
            actor=q["actor"]
            velocity=actor.get("vel",(0,0,0))
            for index in (max(1,self.steps//2),self.steps):
                point=path[index]
                t=point[0]
                enemy=(actor["pos"][0]+velocity[0]*t,actor["pos"][1]+velocity[1]*t,actor["pos"][2])
                distance=math.hypot(point[1]-enemy[0],point[2]-enemy[1])
                strength=self._strength(actor,distance)
                if strength<=0:
                    continue
                visible=1.0 if q.get("los") else .3
                if exact and time.perf_counter()+.0007<deadline:
                    scale=1+self.config.get("cubes",{}).get("size_per_cube",.05)*actor.get("cubes",0)
                    source_height=(self.config.get("npc",{}).get("height",3.5) if actor.get("kind")=="npc"
                                   else self.config["mech"]["muzzle_height"]*scale)
                    source=(enemy[0],enemy[1],enemy[2]+source_height)
                    center=(point[1],point[2],point[3]+stats["height"]*.5)
                    visible=1.0 if self.map.line_of_fire(source,center) else 0.0
                    if not visible:
                        if time.perf_counter()+.0007<deadline:
                            upper=(point[1],point[2],point[3]+stats["height"]*.9)
                            visible=.7 if self.map.line_of_fire(source,upper) else 0.0
                        else:
                            visible=.7
                total+=strength*visible*self.horizon*.5
        return total

    def _geometry(self,path,stats,deadline,direction=None,boost=False,charging=False):
        result=[path[0]]
        previous=path[0]
        if direction is None:
            direction=unit(path[-1][4],path[-1][5])
        for state in path[1:]:
            if time.perf_counter()>=deadline:
                return None
            t=state[0]
            energy=previous[7]
            active=boost and previous[8] and math.hypot(*direction)>1e-8 and energy>=stats["boost_drain"]*self.dt
            speed=stats["boost_speed"] if active else stats["walk_speed"]
            if active:
                energy=max(0,energy-stats["boost_drain"]*self.dt)
            if charging:
                speed*=stats.get("charge_move_mult",.5)
            acceleration=stats["ground_accel"] if previous[8] else stats["air_accel"]
            vx,vy=accelerate(previous[4],previous[5],direction[0]*speed,direction[1]*speed,acceleration*self.dt)
            x,y=previous[1]+vx*self.dt,previous[2]+vy*self.dt
            z,vz,grounded=previous[3],previous[6],previous[8]
            if previous[8]:
                support=getattr(self.map,"support_height",None)
                z=support(x,y,previous[3]) if support else self.map.ground_height(x,y)
                if z<previous[3]-stats.get("step_up",1.2):
                    # A drop becomes airborne rather than teleporting to terrain.
                    grounded=False
                    vz=previous[6]-stats["gravity"]*self.dt
                    z=previous[3]+vz*self.dt
                if not self.map.move_clear(previous[1:4],(x,y,z),stats["radius"],stats["height"]):
                    return None
            else:
                # Continue vertical integration if a grounded proposal walked
                # off a ledge during geometry validation.
                vz=previous[6]-stats["gravity"]*self.dt
                z=previous[3]+vz*self.dt
                grounded=False
                support=getattr(self.map,"support_height",None)
                ground=support(x,y,previous[3]) if support else self.map.ground_height(x,y)
                if z<=ground:
                    z,vz,grounded=ground,0.0,True
                if not self.map.point_clear((x,y,z),stats["radius"],stats["height"]):
                    return None
            current=(t,x,y,z,vx,vy,vz,energy,grounded)
            result.append(current)
            previous=current
            if direction==(0.0,0.0) and grounded and vx==vy==vz==0:
                # A fully checked stationary supported body repeats exactly.
                # Avoid twelve identical sweeps when comparing real braking
                # with a slow recovery path; moving inertia is never skipped.
                # Energy is constant too: zero input cannot activate boost,
                # and this integrator models no regeneration or future shots.
                result.extend((future[0],*current[1:]) for future in path[len(result):])
                break
        return result

    def _recovery_cost(self,path,obs,stats,nav,direction,goal,tracks,pressure,
                       route_weight,exposure_weight,deadline):
        """Same movement objectives, conservatively scored without extra rays."""
        me=obs["self"]
        end=path[-1]
        progress=(end[1]-me["pos"][0])*nav[0]+(end[2]-me["pos"][1])*nav[1]
        cost=-route_weight*progress
        if goal is not None and math.hypot(goal[0]-me["pos"][0],goal[1]-me["pos"][1])<12:
            cost+=math.hypot(end[1]-goal[0],end[2]-goal[1])*.8
        cost+=.3*(1-direction[0]*self.last_direction[0]-direction[1]*self.last_direction[1])
        return (cost+self.projectile_cost(path,tracks,stats)+self._beam_cost(path,pressure,stats)
                +self._zone_cost(path,obs,stats)
                +self._exposure(path,pressure,stats,False,deadline)*exposure_weight)

    def choose(self,obs,navigation,threats,stats,*,goal=None,recover=False,
               urgent=False,spacing_boost=False,deadline=None,boost_emergency=False,shot_energy=0):
        begin=time.perf_counter()
        shot_energy=max(0.0,float(shot_energy))
        ordinary_boost,emergency_boost,boost_high=self._boost_permission(obs,stats,shot_energy)
        boost_report={"boost_phase":"RECHARGING" if self.boost_recharging else "READY",
                      "boost_low":35.0,"boost_high":boost_high,"shot_energy":shot_energy}
        deadline=min(deadline if deadline is not None else begin+.014,begin+.014)-.0015
        if deadline<=begin:
            self._geometry_recovery_pending=False
            self.last_report={"ms":(time.perf_counter()-begin)*1000,"candidates":0,
                              "geometry_checked":0,"projectiles":0,"fallback":True,
                              "recovery_seed_checked":False,"recovery_seed_selected":False,
                              "boost_reason":"deadline",**boost_report}
            return (0.0,0.0),False
        me=obs["self"]
        planning_me=me if not shot_energy else {**me,"energy":max(0.0,me["energy"]-shot_energy)}
        # Rotation follows a validated route. Price routed progress against the
        # time spent in the damaging zone, rather than allowing a soft incoming
        # exposure estimate to keep backing away indefinitely. Actual shots,
        # charging beams, zone damage and collision checks keep full weight.
        route_weight=1.3+(max(3.0,obs["zone"]["dps"]/max(stats["walk_speed"],1)) if urgent else 0)
        exposure_weight=(1.0 if recover else .65)*(.35 if urgent else 1.0)
        nav=unit(*navigation)
        recovery_eligible=bool(self._geometry_recovery_pending and nav!=(0.0,0.0) and me.get("grounded",True))
        self._geometry_recovery_pending=False
        angle=math.atan2(nav[1],nav[0])
        directions=[nav,self.last_direction,(0.0,0.0)]
        directions.extend((math.cos(angle+a),math.sin(angle+a)) for a in (.35,-.35,.7,-.7,1.1,-1.1,1.57,-1.57,2.2,-2.2,math.pi))
        # Explicit braking against momentum is useful when an inertial arc would
        # cross a wall even though its requested direction points away from it.
        if math.hypot(*me["vel"][:2])>1:
            directions.append(unit(-me["vel"][0],-me["vel"][1]))
        unique=[]
        seen=set()
        for direction in directions:
            key=tuple(round(v,3) for v in direction)
            if key not in seen:
                unique.append(direction)
                seen.add(key)
        pressure=sorted(threats,key=lambda q:self._strength(q["actor"],q["d"]),reverse=True)[:3]
        pursuers=threats[:16]
        tracks=self._projectiles(obs,min(deadline,begin+.0015))
        # Recharge can be interrupted for a verified immediate benefit, not
        # merely because rotation/recovery is active or progress would be faster.
        possible_override=bool(tracks or any(q.get("los") and (q["actor"].get("charging") or q["d"]<self.lightning_escape_range+stats["radius"]+15) for q in pursuers))
        allow_boost=emergency_boost and (ordinary_boost or boost_emergency or possible_override)
        best=None
        checked=0
        seed_direction=None
        seed_checked=False
        charging=any(w and w["kind"]=="laser" and w.get("charge",0)>0 for w in me["weapons"])
        if recovery_eligible and time.perf_counter()+.0015<deadline:
            # Check one slow, continuously applied command before ordinary
            # full-speed candidates can consume the geometry budget. No future
            # brake is assumed: the returned fractional input matches rollout.
            seed_checked=True
            direction=(nav[0]*.5,nav[1]*.5)
            path=self.rollout(planning_me,direction,False,stats)
            checked+=1
            corrected=self._geometry(path,stats,deadline-.001,direction,False,charging)
            if corrected is not None and time.perf_counter()+.0007<deadline:
                brake=self.rollout(planning_me,(0.0,0.0),False,stats)
                checked+=1
                safe_brake=self._geometry(brake,stats,deadline-.0005,(0.0,0.0),False,charging)
                if time.perf_counter()<deadline:
                    cost=self._recovery_cost(corrected,obs,stats,nav,direction,goal,tracks,pressure,
                                             route_weight,exposure_weight,deadline)
                    brake_cost=self._recovery_cost(safe_brake or brake,obs,stats,nav,(0.0,0.0),goal,
                                                   tracks,pressure,route_weight,exposure_weight,deadline)
                    if cost<brake_cost:
                        best=(cost,direction,False,None)
                        seed_direction=direction
        ranked=[]
        cheap_deadline=min(deadline-.004,begin+.006)
        for direction in unique:
            walking=None
            for boost in ((False,True) if allow_boost and direction!=(0.0,0.0) else (False,)):
                if time.perf_counter()>=cheap_deadline and ranked:
                    break
                path=self.rollout(planning_me,direction,boost,stats)
                end=path[-1]
                progress=(end[1]-me["pos"][0])*nav[0]+(end[2]-me["pos"][1])*nav[1]
                cost=-route_weight*progress
                if nav==(0.0,0.0):
                    cost+=math.hypot(end[1]-me["pos"][0],end[2]-me["pos"][1])*1.5
                if goal is not None and math.hypot(goal[0]-me["pos"][0],goal[1]-me["pos"][1])<12:
                    cost+=math.hypot(end[1]-goal[0],end[2]-goal[1])*.8
                if boost:
                    cost+=1.8 if urgent or recover or spacing_boost else 6.5
                    cost+=max(0,35-end[7])*.15
                cost+=.3*(1-direction[0]*self.last_direction[0]-direction[1]*self.last_direction[1])
                bullet=self.projectile_cost(path,tracks,stats)
                beam=self._beam_cost(path,pressure,stats)
                reason="ready" if boost and ordinary_boost else "requested_emergency" if boost and boost_emergency else None
                if not boost:
                    walking=(path,bullet,beam)
                elif reason is None:
                    if walking is None:
                        continue
                    reason=self._boost_override(walking[0],path,walking[1],bullet,walking[2],beam,pursuers,stats)
                    if reason is None:
                        continue
                cost+=bullet+self._zone_cost(path,obs,stats)+beam
                exposure=self._exposure(path,pressure,stats,False,deadline)
                cost+=exposure*exposure_weight
                ranked.append((cost,direction,boost,path,bullet,exposure,walking,reason))
            if time.perf_counter()>=cheap_deadline:
                break
        ranked.sort(key=lambda item:item[0])
        # Exact geometry and incoming LOS are reserved for promising candidates.
        for cost,direction,boost,path,bullet,exposure,walking,reason in ranked:
            if time.perf_counter()>=deadline or checked>=6:
                break
            checked+=1
            corrected=self._geometry(path,stats,deadline,direction,boost,charging)
            if corrected is None:
                continue
            if boost and reason not in ("ready","requested_emergency"):
                if checked>=6 or time.perf_counter()>=deadline:
                    continue
                checked+=1
                safe_walk=self._geometry(walking[0],stats,deadline,direction,False,charging)
                if safe_walk is None:
                    continue
                reason=self._boost_override(safe_walk,corrected,
                    self.projectile_cost(safe_walk,tracks,stats),self.projectile_cost(corrected,tracks,stats),
                    self._beam_cost(safe_walk,pressure,stats),self._beam_cost(corrected,pressure,stats),pursuers,stats)
                if reason is None:
                    continue
            adjusted=cost-bullet-exposure*exposure_weight
            adjusted+=self.projectile_cost(corrected,tracks,stats)
            adjusted+=self._exposure(corrected,pressure[:2],stats,True,deadline)*exposure_weight
            # Third threat is retained conservatively without extra ray queries.
            if len(pressure)>2:
                adjusted+=self._exposure(corrected,pressure[2:],stats,False,deadline)*exposure_weight
            if best is None or adjusted<best[0]:
                best=(adjusted,direction,boost,reason)
            if checked>=3 and not tracks and not any(q["actor"].get("charging") for q in pressure):
                break
        if best is None:
            # A neutral intention brakes under the same acceleration limit. It
            # is the bounded fallback; no unvalidated wall traversal is issued.
            result=((0.0,0.0),False)
        else:
            result=(best[1],best[2])
            self.last_direction=best[1]
        seed_selected=bool(best is not None and seed_direction is not None and best[1]==seed_direction and not best[2])
        self._geometry_recovery_pending=bool(nav!=(0.0,0.0) and me.get("grounded",True)
                                             and ((best is None and checked>0) or seed_selected))
        self.last_report={"ms":(time.perf_counter()-begin)*1000,"candidates":len(ranked),
                          "geometry_checked":checked,"projectiles":len(tracks),"fallback":best is None,
                          "recovery_seed_checked":seed_checked,"recovery_seed_selected":seed_selected,
                          "boost_reason":best[3] if best and best[2] else "recharging" if self.boost_recharging else "walk_selected",
                          **boost_report}
        return result
