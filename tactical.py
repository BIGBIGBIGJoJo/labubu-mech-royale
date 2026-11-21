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


def pursuit_distance(config,me,target,stats,*,line_clear=True):
    """Preferred horizontal engagement distance, not firing authorization.

    Anchors are deliberate aggressive-policy parameters. Body/pitch/blast
    floors avoid common unusable close positions; Combat still checks the
    actual shot. Occluded targets are approached toward the geometric floor.
    Gun-only mech engagements restore the ordinary anchor if the target closes.
    Other loadouts and NPCs retain their closer clear-target preference. This
    function performs no geometry queries.
    """
    weapons=[w for w in me.get("weapons",[])[:2] if w]
    live={w["kind"]:{**config.get("weapons",{}).get(w["kind"],{}),
                     **w.get("stats",{})} for w in weapons}
    npc=target.get("kind")=="npc"
    body=config.get("npc" if npc else "mech",{})
    scale=1.0 if npc else 1.0+config.get("cubes",{}).get("size_per_cube",.05)*target.get("cubes",0)
    target_radius=body.get("radius",1.8 if npc else 2.5)*scale
    target_height=body.get("height",3.5 if npc else 9.0)*scale
    own_radius=stats.get("radius",config.get("mech",{}).get("radius",2.5))
    # This also keeps the ordinary own-radius+.5 barrel extension short of
    # the target's body. Dynamic actor collision is not part of ArenaMap.
    minimum=own_radius+target_radius+2.0
    if "gun" in live or "laser" in live:
        muzzle=me["pos"][2]+stats.get("muzzle_height",7.0)
        bottom=target["pos"][2]+target_height*.1
        top=target["pos"][2]+target_height*.9
        down=-stats.get("min_pitch",-.7)
        up=stats.get("max_pitch",1.3)
        if muzzle>top and 0<down<math.pi/2:
            minimum=max(minimum,(muzzle-top)/math.tan(down)+2.0)
        elif bottom>muzzle and 0<up<math.pi/2:
            minimum=max(minimum,(bottom-muzzle)/math.tan(up)+2.0)
    if "mortar" in live:
        minimum=max(minimum,15.0,live["mortar"].get("splash_radius",7.0)+own_radius+3.0)
    anchor=35.0 if npc else (80.0 if "laser" in live or "mortar" in live else 70.0)
    direct_ranges=[live[k].get("range",230.0 if k=="gun" else 280.0)
                   for k in ("gun","laser") if k in live]
    if direct_ranges:
        anchor=min(anchor,max(0.0,min(direct_ranges)-6.0))
    lightning=live.get("lightning")
    # This helper is used only for ordinary pursuit. Match Combat's normal
    # lightning trigger reserve; paying the raw shot cost alone is insufficient.
    if lightning and me.get("energy",0)>=lightning.get("energy",3.0)+8.0:
        anchor=min(anchor,max(0.0,lightning.get("range",45.0)-6.0))
    distance=math.hypot(me["pos"][0]-target["pos"][0],me["pos"][1]-target["pos"][1])
    if line_clear and target.get("kind")=="mech" and len(weapons)==1 and "gun" in live:
        return max(minimum,anchor)
    return max(minimum,min(anchor,distance)) if line_clear else minimum


class TacticalPlanner:
    def __init__(self,config,arena):
        self.config=config
        self.map=arena
        self.dt=1.0/max(1.0,float(config.get("match",{}).get("tick_hz",20)))
        self.action_dt=self.dt*max(1,int(config.get("match",{}).get("decide_every",2)))
        self.steps=max(2,int(round(0.6/self.dt)))
        self.horizon=self.steps*self.dt
        self.last_direction=(0.0,0.0)
        self.last_report={}

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
            if not actor.get("charging") or (not q.get("los") and q.get("los_known",True)):
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
                visible=1.0 if q.get("los") or not q.get("los_known",True) else .3
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
        return result

    def choose(self,obs,navigation,threats,stats,*,goal=None,recover=False,
               urgent=False,spacing_boost=False,pursuit=False,shot_energy=0.0,deadline=None):
        begin=time.perf_counter()
        deadline=min(deadline if deadline is not None else begin+.014,begin+.014)-.0015
        if deadline<=begin:
            self.last_report={"ms":(time.perf_counter()-begin)*1000,"candidates":0,
                              "geometry_checked":0,"projectiles":0,"fallback":True,
                              "pursuit":bool(pursuit)}
            return (0.0,0.0),False
        me=obs["self"]
        shot_energy=max(0.0,float(shot_energy))
        if shot_energy:
            me={**me,"energy":max(0.0,me["energy"]-shot_energy)}
        nav=unit(*navigation)
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
        tracks=self._projectiles(obs,min(deadline,begin+.0015))
        boost_reserve=12.0 if urgent else 35.0
        allow_boost=(me.get("grounded",True)
                     and me["energy"]-stats["boost_drain"]*self.action_dt>=boost_reserve)
        ranked=[]
        cheap_deadline=min(deadline-.004,begin+.006)
        for direction in unique:
            for boost in ((False,True) if allow_boost and direction!=(0.0,0.0) else (False,)):
                if time.perf_counter()>=cheap_deadline and ranked:
                    break
                path=self.rollout(me,direction,boost,stats)
                end=path[-1]
                progress=(end[1]-me["pos"][0])*nav[0]+(end[2]-me["pos"][1])*nav[1]
                cost=-1.3*progress
                if nav==(0.0,0.0):
                    cost+=math.hypot(end[1]-me["pos"][0],end[2]-me["pos"][1])*1.5
                if goal is not None and math.hypot(goal[0]-me["pos"][0],goal[1]-me["pos"][1])<12:
                    cost+=math.hypot(end[1]-goal[0],end[2]-goal[1])*.8
                if boost:
                    cost+=1.8 if urgent or recover or spacing_boost or pursuit else 6.5
                    cost+=max(0,35-end[7])*.15
                cost+=.3*(1-direction[0]*self.last_direction[0]-direction[1]*self.last_direction[1])
                bullet=self.projectile_cost(path,tracks,stats)
                cost+=bullet+self._zone_cost(path,obs,stats)+self._beam_cost(path,pressure,stats)
                exposure=self._exposure(path,pressure,stats,False,deadline)
                cost+=exposure*(1.0 if recover else .65)
                ranked.append((cost,direction,boost,path,bullet,exposure))
            if time.perf_counter()>=cheap_deadline:
                break
        ranked.sort(key=lambda item:item[0])
        best=None
        checked=0
        # Exact geometry and incoming LOS are reserved for promising candidates.
        for cost,direction,boost,path,bullet,exposure in ranked:
            if time.perf_counter()>=deadline or checked>=6:
                break
            checked+=1
            charging=any(w and w["kind"]=="laser" and w.get("charge",0)>0 for w in me["weapons"])
            corrected=self._geometry(path,stats,deadline,direction,boost,charging)
            if corrected is None:
                continue
            adjusted=cost-bullet-exposure*(1.0 if recover else .65)
            adjusted+=self.projectile_cost(corrected,tracks,stats)
            adjusted+=self._exposure(corrected,pressure[:2],stats,True,deadline)*(1.0 if recover else .65)
            # Third threat is retained conservatively without extra ray queries.
            if len(pressure)>2:
                adjusted+=self._exposure(corrected,pressure[2:],stats,False,deadline)*(1.0 if recover else .65)
            if best is None or adjusted<best[0]:
                best=(adjusted,direction,boost)
            if checked>=3 and not tracks and not any(q["actor"].get("charging") for q in pressure):
                break
        if best is None:
            # A neutral intention brakes under the same acceleration limit. It
            # is the bounded fallback; no unvalidated wall traversal is issued.
            result=((0.0,0.0),False)
        else:
            result=(best[1],best[2])
            self.last_direction=best[1]
        self.last_report={"ms":(time.perf_counter()-begin)*1000,"candidates":len(ranked),
                          "geometry_checked":checked,"projectiles":len(tracks),"fallback":best is None,
                          "pursuit":bool(pursuit),"boost_allowed":bool(allow_boost),
                          "boost_reserve":boost_reserve,"shot_energy":shot_energy}
        return result
