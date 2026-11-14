#pragma once
// Ordered score bands, not real damage: any round-4 win outranks any round-5 win.
inline double finish_score(int hit_round,double damage_at_stop) {
    if(!hit_round)return damage_at_stop;
    return 100.0*(6-hit_round)+std::min(99.0,std::max(0.0,damage_at_stop-100.0));
}
