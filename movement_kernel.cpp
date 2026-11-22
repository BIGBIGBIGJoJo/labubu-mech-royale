// Exact grounded-segment predicates from arena_map.py. No fast-math or FMA.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace {
struct Point { double x, y; };
struct Prism {
    double base, top, x0, y0, x1, y1;
    std::vector<std::vector<Point>> rings;
};
struct World {
    const int16_t* samples;
    int nx, ny;
    double min_x, min_y, step, scale;
    double bx0, by0, bx1, by1, step_up, slope, margin, epsilon;
    std::vector<Prism> prisms;

    double ground(double x, double y) const {
        double fx=std::max(0.0,std::min(nx-1.000001,(x-min_x)/step));
        double fy=std::max(0.0,std::min(ny-1.000001,(y-min_y)/step));
        int i=static_cast<int>(fx), j=static_cast<int>(fy);
        double u=fx-i, v=fy-j;
        size_t k=static_cast<size_t>(j)*nx+i;
        double a=samples[k], b=samples[k+1], c=samples[k+nx], d=samples[k+nx+1];
        return ((a*(1-u)+b*u)*(1-v)+(c*(1-u)+d*u)*v)*scale;
    }
    double grade(double x,double y,double dx,double dy) const {
        double fx=std::max(0.0,std::min(nx-1.000001,(x-min_x)/step));
        double fy=std::max(0.0,std::min(ny-1.000001,(y-min_y)/step));
        int i=static_cast<int>(fx), j=static_cast<int>(fy);
        double u=fx-i, v=fy-j;
        size_t k=static_cast<size_t>(j)*nx+i;
        double a=samples[k], b=samples[k+1], c=samples[k+nx], d=samples[k+nx+1];
        return (((b-a)*(1-v)+(d-c)*v)*dx+((c-a)*(1-u)+(d-b)*u)*dy)*(scale/step);
    }
    bool grade_clear(double x,double y,double ex,double ey,double d) const {
        double dx=ex-x,dy=ey-y;
        if(d<1e-6) return true;
        std::vector<double> cuts{0,1};
        double origins[]={x,y},deltas[]={dx,dy},starts[]={min_x,min_y};
        for(int axis=0;axis<2;++axis) {
            double o=origins[axis],delta=deltas[axis],start=starts[axis];
            if(std::abs(delta)<1e-9) continue;
            int first=static_cast<int>(std::floor((std::min(o,o+delta)-start)/step))+1;
            int last=static_cast<int>(std::floor((std::max(o,o+delta)-start)/step));
            for(int k=first;k<=last;++k) cuts.push_back((start+k*step-o)/delta);
        }
        std::sort(cuts.begin(),cuts.end());
        for(size_t i=1;i<cuts.size();++i) {
            double a=cuts[i-1],b=cuts[i];
            if(b-a<1e-9) continue;
            for(double f:{a+(b-a)*1e-5,b-(b-a)*1e-5})
                if(grade(x+dx*f,y+dy*f,dx/d,dy/d)>slope+.02) return false;
        }
        return true;
    }
};

bool inside(double x,double y,const std::vector<Point>& ring) {
    bool result=false;
    Point a=ring.back();
    for(Point b:ring) {
        if((a.y>y)!=(b.y>y) && x<(b.x-a.x)*(y-a.y)/(b.y-a.y)+a.x) result=!result;
        a=b;
    }
    return result;
}
bool solid(const Prism& p,double x,double y) {
    if(!(p.x0<=x && x<=p.x1 && p.y0<=y && y<=p.y1) || !inside(x,y,p.rings[0])) return false;
    for(size_t i=1;i<p.rings.size();++i) if(inside(x,y,p.rings[i])) return false;
    return true;
}
double point_distance(double x,double y,Point a,Point b) {
    double dx=b.x-a.x,dy=b.y-a.y,den=dx*dx+dy*dy;
    double t=den ? std::max(0.0,std::min(1.0,((x-a.x)*dx+(y-a.y)*dy)/den)) : 0;
    // CPython float ** uses libm pow; prohibit compiler strength reduction.
    return std::pow(x-a.x-t*dx,2.0)+std::pow(y-a.y-t*dy,2.0);
}
double segment_distance(Point a,Point b,Point c,Point d) {
    double ux=b.x-a.x,uy=b.y-a.y,vx=d.x-c.x,vy=d.y-c.y,cross=ux*vy-uy*vx;
    if(std::abs(cross)>1e-10) {
        double wx=c.x-a.x,wy=c.y-a.y,s=(wx*vy-wy*vx)/cross,t=(wx*uy-wy*ux)/cross;
        if(0<=s && s<=1 && 0<=t && t<=1) return 0;
    }
    return std::min({point_distance(a.x,a.y,c,d),point_distance(b.x,b.y,c,d),
                     point_distance(c.x,c.y,a,b),point_distance(d.x,d.y,a,b)});
}
bool point_clear(const World& w,double x,double y,double z,double radius,double height) {
    double collision=std::max(0.0,radius-w.epsilon),inset=std::max(radius,w.margin);
    if(!(w.bx0+inset-1e-6<=x && x<=w.bx1-inset+1e-6 &&
         w.by0+inset-1e-6<=y && y<=w.by1-inset+1e-6)) return false;
    for(const Prism& p:w.prisms) {
        if(p.top<=z+w.step_up+.02 || p.base>=z+height-.02 ||
           x+radius<p.x0 || x-radius>p.x1 || y+radius<p.y0 || y-radius>p.y1) continue;
        if(solid(p,x,y)) return false;
        for(const auto& ring:p.rings) {
            Point a=ring.back();
            for(Point b:ring) {
                if(point_distance(x,y,a,b)<collision*collision) return false;
                a=b;
            }
        }
    }
    return true;
}
bool move_clear(const World& w,double x,double y,double z,double ex,double ey,double radius,double height,double d) {
    double dx=ex-x,dy=ey-y,collision=std::max(0.0,radius-w.epsilon);
    if(z<=w.ground(x,y)+w.step_up && !w.grade_clear(x,y,ex,ey,d)) return false;
    for(const Prism& p:w.prisms) {
        if(p.top<=z+w.step_up+.02 || p.base>=z+height-.02 ||
           std::max(x,ex)+radius<p.x0 || std::min(x,ex)-radius>p.x1 ||
           std::max(y,ey)+radius<p.y0 || std::min(y,ey)-radius>p.y1) continue;
        for(const auto& ring:p.rings) {
            Point a=ring.back();
            for(Point b:ring) {
                if(segment_distance({x,y},{ex,ey},a,b)<collision*collision-1e-6) return false;
                a=b;
            }
        }
    }
    int count=std::max(1,static_cast<int>(std::ceil(d/std::max(.8,std::min(2.0,radius*.65)))));
    double previous=z;
    for(int i=1;i<=count;++i) {
        double px=x+dx*i/count,py=y+dy*i/count,ground=w.ground(px,py),current=ground;
        if(previous>ground+w.step_up) {
            for(const Prism& p:w.prisms)
                if(p.top<=previous+w.step_up && p.top>current && solid(p,px,py)) current=p.top;
        }
        double rise=current-previous;
        if(rise>w.step_up+.02 && rise>w.slope*d/count+.02) return false;
        if(!point_clear(w,px,py,current,radius,height)) return false;
        previous=current;
    }
    return true;
}
}

extern "C" int movement_kernel_version() { return 1; }

// Metadata: terrain origin/step/scale, bounds, step/slope/margin/contact epsilon.
// Prism records: base, top, ring_count, then [vertex_count, x,y,...] per ring.
extern "C" void* movement_create(const int16_t* samples,int nx,int ny,
    const double* metadata,const double* data,size_t length) {
    if(!samples || !metadata || !data || nx<2 || ny<2) return nullptr;
    for(int i=0;i<12;++i) if(!std::isfinite(metadata[i])) return nullptr;
    if(metadata[2]<=0 || metadata[8]<0 || metadata[9]<0 || metadata[10]<0 || metadata[11]<0) return nullptr;
    World* w=nullptr;
    try {
        w=new World{samples,nx,ny,metadata[0],metadata[1],metadata[2],metadata[3],
                    metadata[4],metadata[5],metadata[6],metadata[7],
                    metadata[8],metadata[9],metadata[10],metadata[11],{}};
        size_t index=0;
        while(index<length) {
            if(length-index<3) { delete w; return nullptr; }
            Prism p{};p.base=data[index++];p.top=data[index++];double n=data[index++];
            if(!std::isfinite(p.base) || !std::isfinite(p.top) || !std::isfinite(n) || n<1 || n>10000 || n!=std::floor(n)) {delete w;return nullptr;}
            for(int i=0;i<static_cast<int>(n);++i) {
                if(index>=length) {delete w;return nullptr;}
                double vertices=data[index++];
                if(!std::isfinite(vertices) || vertices<3 || vertices>100000 || vertices!=std::floor(vertices) || vertices>(length-index)/2) {delete w;return nullptr;}
                std::vector<Point> ring;
                for(int j=0;j<static_cast<int>(vertices);++j) {
                    double x=data[index++],y=data[index++];
                    if(!std::isfinite(x) || !std::isfinite(y)) {delete w;return nullptr;}
                    ring.push_back({x,y});
                }
                p.rings.push_back(std::move(ring));
            }
            p.x0=p.x1=p.rings[0][0].x;p.y0=p.y1=p.rings[0][0].y;
            for(Point q:p.rings[0]) {p.x0=std::min(p.x0,q.x);p.x1=std::max(p.x1,q.x);p.y0=std::min(p.y0,q.y);p.y1=std::max(p.y1,q.y);}
            w->prisms.push_back(std::move(p));
        }
        return w;
    } catch(...) {delete w;return nullptr;}
}
extern "C" void movement_destroy(void* context) { delete static_cast<World*>(context); }
extern "C" int movement_clear(void* context,double x,double y,double z,double ex,double ey,double ez,double radius,double height,double distance) {
    const double input[]={x,y,z,ex,ey,ez,radius,height,distance};
    for(double v:input) if(!std::isfinite(v) || std::abs(v)>1e6) return -1;
    if(!context || radius<0 || height<0 || distance<0 || distance>10000) return -1;
    const World& w=*static_cast<World*>(context);
    // Bound cuts/samples for unsupported extreme queries; Python remains authoritative.
    if(std::abs(ex-x)/w.step+std::abs(ey-y)/w.step>100000 ||
       std::abs((x-w.min_x)/w.step)>1e8 || std::abs((y-w.min_y)/w.step)>1e8) return -1;
    try {return move_clear(w,x,y,z,ex,ey,radius,height,distance) ? 1 : 0;} catch(...) {return -1;}
}
