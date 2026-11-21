"""Incremental ground-route recovery for a confirmed small coarse component.

This module composes ArenaMap. Ordinary navigation and all tactical collision,
projectile and zone selection remain with their existing owners.
"""
from __future__ import annotations

import collections
import math
import time


class LocalRouteRecovery:
    STEP=.5
    LIMIT=2048
    POINT_LIMIT=16384
    EDGE_LIMIT=16384
    COMPONENT_LIMIT=128
    def __init__(self,arena):
        self.arena=arena
        self.local=None
        self.episodes=collections.deque(maxlen=8)
        self.status='coarse'
        self.goal=None
        self.dims=None
        self.map_identity=id(arena)
        self.components={}
        self.component_jobs={}
        self.failed_anchors=[]
        self.last_report={}
        self._reason=None

    @property
    def active(self):
        return self.local is not None

    def navigate(self,obs,strategic_goal,stats,request_recovery=False,deadline=None):
        """Return navigation and a local tactical goal without changing strategy.

        Deadlines use perf_counter. Discovery resumes across calls and the
        caller's existing tactical planner still validates every issued action.
        """
        begin=time.perf_counter()
        deadline=deadline if deadline is not None else begin+.006
        self._reason=None
        if deadline<=begin:
            self.status=('local_following' if self.local['path'] is not None else 'local_searching') if self.active else 'searching'
            self._reason='deadline'
            result=((0.,0.),strategic_goal)
        else:
            result=self._navigate(obs,strategic_goal,stats,request_recovery,deadline)
        episode=(self.local['episode'] if self.active else self.episodes[-1]
                 if self.episodes and self.status in ('local_declined','exit_reached') else {})
        self.last_report={'status':self.status,'active':self.active,'ms':(time.perf_counter()-begin)*1000,
                          'reason':self._reason or episode.get('failed') or episode.get('reason'),
                          'nodes':len(self.local['parents']) if self.active else episode.get('nodes',0),
                          'component':episode.get('initial_component_cap8'),
                          'exit_component':episode.get('exit_component_cap8')}
        return result

    def _fail(self,reason):
        if self.local is not None:
            self.local['episode']['failed']=reason
            self.failed_anchors.append(tuple(self.local['origin']))
            self.failed_anchors=self.failed_anchors[-8:]
        self.local=None
        self.status='local_declined'
        self._reason=reason

    def _component(self,cell,dims,deadline):
        """At most eight reachable coarse cells; pause between neighbour checks."""
        key=(cell,dims)
        if key in self.components:return self.components[key]
        if key not in self.component_jobs and len(self.component_jobs)>=self.COMPONENT_LIMIT:
            self._fail('component_cache_cap');return None
        job=self.component_jobs.setdefault(key,{'queue':collections.deque([cell]),'seen':{cell},'active':None,'cursor':0})
        offsets=((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1))
        while time.perf_counter()+.0008<deadline and len(job['seen'])<8:
            if job['active'] is None:
                if not job['queue']:break
                job['active']=job['queue'].popleft();job['cursor']=0
            current=job['active'];dx,dy=offsets[job['cursor']];nxt=(current[0]+dx,current[1]+dy)
            if nxt not in job['seen'] and self.arena._free(nxt,dims):
                valid=not dx or not dy or (self.arena._free((current[0]+dx,current[1]),dims) and self.arena._free((current[0],current[1]+dy),dims))
                if valid:
                    if time.perf_counter()+.0008>=deadline:return None
                    if self.arena._traversable(current,nxt,dims):job['seen'].add(nxt);job['queue'].append(nxt)
            job['cursor']+=1
            if job['cursor']==len(offsets):job['active']=None
        if len(job['seen'])>=8 or (job['active'] is None and not job['queue']):
            self.components[key]=len(job['seen']);return len(job['seen'])
        return None

    def _start(self,obs,goal,stats,reason):
        pos=obs['self']['pos'][:]
        required=('_search','_cell','_point','_free','_nearest_free','_traversable','move_clear','point_clear')
        if not getattr(self.arena,'available',False) or not all(hasattr(self.arena,name) for name in required):
            self.status='local_declined';self._reason='coarse_geometry_unavailable';return False
        if any(math.dist(pos[:2],anchor[:2])<6 for anchor in self.failed_anchors):
            self.status='local_declined';self._reason='failed_anchor';return False
        local={'origin':pos,'started':obs['t'],'queue':collections.deque([(0,0)]),'parents':{(0,0):None},
               'free':{},'edges':{},'active':None,'cursor':0,'path':None,'index':0,'cpu_ms':0.0,
               'initial_cell':None,'initial_linked':False,'initial_component':None,'exit_pending':None,'exit_cells':{},'exit_links':{},
               'episode':{'start_t':obs['t'],'origin':pos,'reason':reason,'discovered_t':None,'finished_t':None}}
        self.local=local;self.episodes.append(local['episode'])
        return True

    def _point(self,cell):
        x=self.local['origin'][0]+cell[0]*self.STEP
        y=self.local['origin'][1]+cell[1]*self.STEP
        return (x,y,self.arena.ground_height(x,y))

    def _ordered_offsets(self,cell,obs,stats):
        # A refreshed goal/zone affects discovery preference, not connectivity
        # cache validity. Freeze this order for the current partial expansion.
        zone=obs['zone'];start=max(obs['t'],zone['shrink_start'])
        fraction=max(0,min(1,(obs['t']+3-start)/max(.001,zone['shrink_end']-start)))
        cx=zone['center'][0]+fraction*(zone['next_center'][0]-zone['center'][0])
        cy=zone['center'][1]+fraction*(zone['next_center'][1]-zone['center'][1])
        radius=zone['radius']+fraction*(zone['next_radius']-zone['radius'])
        def score(offset):
            point=(self.local['origin'][0]+(cell[0]+offset[0])*self.STEP,
                   self.local['origin'][1]+(cell[1]+offset[1])*self.STEP)
            return math.dist(point[:2],self.goal[:2])+4*max(0,math.hypot(point[0]-cx,point[1]-cy)+stats['radius']-radius)
        return tuple(sorted(((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)),key=score))

    def _search(self,obs,stats,deadline):
        local=self.local;begin=time.perf_counter()
        dims=(math.ceil(stats['radius']*2)/2,math.ceil(stats['height']*2)/2)
        # ArenaMap may retain an old A* origin while the actor moves. Classify
        # the current recovery anchor, never that stale search's component.
        if local['initial_cell'] is None:
            if time.perf_counter()+.0008>=deadline:return
            local['initial_cell']=self.arena._nearest_free(self.arena._cell(local['origin']),dims,deadline-.0008)
            if local['initial_cell'] is None:
                if time.perf_counter()+.0008<deadline:self._fail('no_coarse_anchor')
                return
        if not local['initial_linked']:
            if time.perf_counter()+.0008>=deadline:return
            if not self.arena.move_clear(local['origin'],self.arena._point(local['initial_cell']),stats['radius'],stats['height']):
                self._fail('coarse_anchor_not_connected');return
            local['initial_linked']=True
        if local['initial_component'] is None:
            local['initial_component']=self._component(local['initial_cell'],dims,deadline)
            if self.local is None:return
            if local['initial_component'] is None:return
            local['episode']['initial_component_cap8']=local['initial_component']
            if local['initial_component']>=8:
                self._fail('initial_component_not_small');return
        while time.perf_counter()+.0007<deadline and len(local['parents'])<self.LIMIT:
            if len(local['free'])>=self.POINT_LIMIT or len(local['edges'])>=self.EDGE_LIMIT or len(local['exit_links'])>=self.EDGE_LIMIT or len(local['exit_cells'])>=self.COMPONENT_LIMIT:
                self._fail('geometry_cache_cap');return
            if local['exit_pending'] is not None:
                cell=local['exit_pending'];point=self._point(cell);coarse=self.arena._cell(point)
                if coarse not in local['exit_cells']:
                    nearest=self.arena._nearest_free(coarse,dims,deadline-.0008)
                    if nearest is None and time.perf_counter()+.0008>=deadline:break
                    local['exit_cells'][coarse]=nearest if nearest is not None else False
                nearest=local['exit_cells'][coarse]
                linked=False
                if nearest is not False:
                    link=(cell,nearest)
                    if link not in local['exit_links']:
                        if time.perf_counter()+.0008>=deadline:break
                        local['exit_links'][link]=self.arena.move_clear(point,self.arena._point(nearest),stats['radius'],stats['height'])
                    linked=local['exit_links'][link]
                component=self._component(nearest,dims,deadline) if linked else 0
                if self.local is None:return
                if component is None:break
                if component>local['initial_component']:
                    path=[];p=cell
                    while p is not None:path.append(self._point(p));p=local['parents'][p]
                    path=list(reversed(path))
                    # Finish at the checked coarse-cell centre, not just near
                    # the portal where 1.5m arrival may still snap to old cells.
                    coarse_point=self.arena._point(nearest)
                    if math.dist(path[-1][:2],coarse_point[:2])>.05:path.append(coarse_point)
                    local['path']=path;local['episode'].update(discovered_t=obs['t'],exit_component_cap8=component,exit_cell=nearest);break
                local['exit_pending']=None
                if time.perf_counter()+.0007>=deadline:break
            if local['active'] is None:
                if not local['queue']:break
                cell=local['queue'].popleft()
                local['active']=cell;local['cursor']=0;local['offsets']=self._ordered_offsets(cell,obs,stats)
                if math.hypot(*cell)*self.STEP>=25:
                    local['exit_pending']=cell;continue
            cell=local['active'];dx,dy=local['offsets'][local['cursor']]
            nxt=(cell[0]+dx,cell[1]+dy)
            if nxt not in local['parents'] and max(abs(nxt[0]),abs(nxt[1]))*self.STEP<=28:
                if nxt not in local['free']:
                    local['free'][nxt]=self.arena.point_clear(self._point(nxt),stats['radius'],stats['height'])
                if local['free'][nxt]:
                    # Resume this neighbour if the point query consumed its reserve.
                    if time.perf_counter()+.0007>=deadline:break
                    key=(cell,nxt)
                    if key not in local['edges']:
                        local['edges'][key]=self.arena.move_clear(self._point(cell),self._point(nxt),stats['radius'],stats['height'])
                    if local['edges'][key]:
                        local['parents'][nxt]=cell;local['queue'].append(nxt)
            local['cursor']+=1
            if local['cursor']==len(local['offsets']):local['active']=None
        local['cpu_ms']+=(time.perf_counter()-begin)*1000
        local['episode'].update(nodes=len(local['parents']),cpu_ms=local['cpu_ms'])
        if local['path'] is None and (len(local['parents'])>=self.LIMIT or (local['active'] is None and not local['queue'])):
            self._fail('cap_or_exhausted')

    def _steer(self,obs,stats,deadline):
        local=self.local;path=local['path'];pos=obs['self']['pos']
        nearest=min(range(max(0,local['index']-2),len(path)),key=lambda i:math.dist(pos[:2],path[i][:2]));local['index']=nearest
        if math.dist(pos[:2],path[-1][:2])<=1.5:
            local['episode'].update(finished_t=obs['t'],exit_pos=pos[:])
            self.local=None;self.arena._search=None;self.status='exit_reached'
            return (0.,0.),path[-1]
        for i in range(min(len(path)-1,nearest+16),nearest-1,-1):
            if time.perf_counter()+.0007>=deadline:break
            d=math.dist(pos[:2],path[i][:2])
            if d>=1 and self.arena.move_clear(pos,path[i],stats['radius'],stats['height']):
                return ((path[i][0]-pos[0])/d,(path[i][1]-pos[1])/d),path[-1]
        return (0.,0.),path[-1]

    def _navigate(self,obs,goal,stats,request_recovery,deadline):
        dims=(stats['radius'],stats['height'])
        # Connectivity does not depend on which refreshed cover goal root picks.
        # Keep the episode anchored to body/map/start; current goal stays live.
        changed=self.dims not in (None,dims) or id(self.arena)!=self.map_identity
        if changed:
            if self.local:self.local['episode']['invalidated']='body_or_map_changed'
            self.local=None;self.components.clear();self.component_jobs.clear();self.failed_anchors.clear()
            if hasattr(self.arena,'_search'):self.arena._search=None
        self.goal=list(goal);self.dims=dims;self.map_identity=id(self.arena)
        self.failed_anchors=[anchor for anchor in self.failed_anchors if math.dist(obs['self']['pos'][:2],anchor[:2])<8]
        if self.active and math.dist(obs['self']['pos'][:2],goal[:2])<=1.5:
            self.local['episode']['invalidated']='strategic_goal_reached';self.local=None;self.status='direct'
            self._reason='strategic_goal_reached'
            return (0.,0.),goal
        if self.active and (obs['t']<self.local['started'] or math.dist(obs['self']['pos'][:2],self.local['origin'][:2])>40):
            self.local['episode']['invalidated']='relocated_or_time_reset';self.local=None
        if self.active and obs['t']-self.local['started']>30:
            self._fail('episode_timeout')
            return (0.,0.),goal
        ground_level=bool(obs['self'].get('grounded',False) and abs(obs['self']['pos'][2]-self.arena.ground_height(*obs['self']['pos'][:2]))<=.05)
        if self.local is not None and not ground_level:
            self.local['episode']['invalidated']='vertical_level_changed';self.local=None
        if self.local is not None:
            if self.local['path'] is None:
                self.status='local_searching';self._search(obs,stats,deadline-.0015)
            if self.local is None:return (0.,0.),goal
            if self.local['path'] is not None:
                self.status='local_following';return self._steer(obs,stats,deadline)
            return (0.,0.),goal
        nav=self.arena.navigate(obs['self']['pos'],goal,*dims,deadline)
        self.status=getattr(self.arena,'last_route_status','direct')
        confirmed_failure=self.status=='unreachable' and math.hypot(*obs['self']['vel'][:2])<2
        if ground_level and math.dist(obs['self']['pos'][:2],goal[:2])>8 and (confirmed_failure or request_recovery):
            if self._start(obs,goal,stats,'coarse_exhausted' if self.status=='unreachable' else 'planner_stalled'):
                self.status='local_searching'
        return nav,goal

