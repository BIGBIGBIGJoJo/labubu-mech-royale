"""Bounded observed-motion forecasts, without inferring enemy control inputs."""
import math


class TargetMotion:
    """Keep one preceding/current sample per visible mech, at most 64 actors.

    Horizontal velocity is unchanged. Vertical gravity is used only after two
    consecutive observations support it; jets and unseen motion remain unknown.
    Landing is an endpoint support estimate, not a full movement simulation.
    """
    MAX_ACTORS=64
    ACCEL_TOLERANCE=3.0

    def __init__(self,config,arena):
        self.arena=arena
        self.gravity=float(config['mech']['gravity'])
        self.sim_dt=1.0/float(config['match']['tick_hz'])
        self.observe_ticks=int(config['match']['decide_every'])
        self.body_width=2.0*float(config['mech']['radius'])
        self._tick=None
        self._actors={}

    def update(self,obs):
        tick=obs['tick']
        if tick==self._tick:
            return
        consecutive=self._tick is not None and tick-self._tick==self.observe_ticks
        previous=self._actors if consecutive else {}
        current={}
        dt=self.observe_ticks*self.sim_dt
        for actor in obs.get('mechs',()):
            if actor.get('kind')!='mech' or len(current)>=self.MAX_ACTORS:
                continue
            ident=actor['id']
            pos=tuple(actor['pos'])
            velocity=tuple(actor.get('vel',(0.0,0.0,0.0)))
            before=previous.get(ident)
            falling=False
            if before is not None:
                acceleration=(velocity[2]-before['velocity'][2])/dt
                # A reused ID/teleport must not inherit another body's trend.
                # This generous continuity check rejects a body-width jump
                # beyond the displacement implied by the observed velocities.
                expected=tuple(before['pos'][i]+.5*(before['velocity'][i]+velocity[i])*dt for i in range(3))
                continuous=math.dist(pos,expected)<=self.body_width
                falling=(continuous and abs(acceleration+self.gravity)<self.ACCEL_TOLERANCE
                         and abs(velocity[2])>.5)
            current[ident]={'pos':pos,'velocity':velocity,'freefall':falling}
        self._actors=current
        self._tick=tick

    def forecast(self,target,seconds):
        """Return predicted feet; the caller adds the cube-scaled body center."""
        pos=target['pos']
        velocity=target.get('vel',(0.0,0.0,0.0))
        if not math.isfinite(seconds) or seconds<=0:
            return list(pos)
        result=[pos[i]+velocity[i]*seconds for i in range(3)]
        if target.get('kind')!='mech':
            return result
        current=self._actors.get(target.get('id'))
        if (current is not None and current['pos']==tuple(pos)
                and current['velocity']==tuple(velocity) and current['freefall']):
            result[2]-=.5*self.gravity*seconds*seconds
        support=getattr(self.arena,'support_height',None)
        if support is not None and getattr(self.arena,'available',False):
            result[2]=max(result[2],support(result[0],result[1],pos[2]))
        return result
