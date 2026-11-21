// Exact translation of ArenaMap's terrain-only ray test. No fast-math.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

extern "C" int terrain_kernel_version() { return 1; }

extern "C" int terrain_line_clear(
    const int16_t* samples, int nx, int ny,
    double min_x, double min_y, double step, double scale,
    double x, double y, double z, double end_x, double end_y, double end_z) {
    if (!samples || nx < 2 || ny < 2 || !(step > 0)) return -1;
    const double input[] = {min_x,min_y,step,scale,x,y,z,end_x,end_y,end_z};
    for (double value : input) if (!std::isfinite(value)) return -1;
    try {
        const double dx=end_x-x, dy=end_y-y, dz=end_z-z;
        auto ground = [&](double px, double py) {
            const double fx=std::max(0.0,std::min(nx-1.000001,(px-min_x)/step));
            const double fy=std::max(0.0,std::min(ny-1.000001,(py-min_y)/step));
            const int i=static_cast<int>(fx), j=static_cast<int>(fy);
            const double u=fx-i, v=fy-j;
            const size_t k=static_cast<size_t>(j)*nx+i;
            const double a=samples[k], b=samples[k+1], c=samples[k+nx], d=samples[k+nx+1];
            return ((a*(1-u)+b*u)*(1-v)+(c*(1-u)+d*u)*v)*scale;
        };
        std::vector<double> cuts{0.0,1.0};
        const double origins[]={x,y}, deltas[]={dx,dy}, starts[]={min_x,min_y};
        for (int axis=0; axis<2; ++axis) {
            const double origin=origins[axis], delta=deltas[axis], start=starts[axis];
            if (std::abs(delta)<1e-9) continue;
            const double first_d=std::floor((std::min(origin,origin+delta)-start)/step)+1;
            const double last_d=std::floor((std::max(origin,origin+delta)-start)/step);
            // Finite arena shots need fewer than nx+ny cuts. Unsupported extreme
            // input falls back to Python instead of allocating without a bound.
            if (last_d-first_d>100000 || first_d < -1e9 || last_d > 1e9) return -1;
            const int first=static_cast<int>(first_d), last=static_cast<int>(last_d);
            for (int index=first; index<=last; ++index)
                cuts.push_back((start+index*step-origin)/delta);
        }
        std::sort(cuts.begin(),cuts.end());
        for (size_t i=1;i<cuts.size();++i) {
            const double a=cuts[i-1], b=cuts[i];
            if (b-a<1e-10) continue;
            const double mid=(a+b)*0.5;
            const double fa=z+dz*a-ground(x+dx*a,y+dy*a);
            const double fb=z+dz*b-ground(x+dx*b,y+dy*b);
            const double fm=z+dz*mid-ground(x+dx*mid,y+dy*mid);
            if (std::min({fa,fb,fm})<0.05) return 0;
            const double qa=2*(fa+fb-2*fm), qb=fb-fa-qa;
            if (qa>1e-10) {
                const double u=-qb/(2*qa);
                if (0<u && u<1 && qa*u*u+qb*u+fa<0.05) return 0;
            }
        }
        return 1;
    } catch (...) { return -1; }
}
