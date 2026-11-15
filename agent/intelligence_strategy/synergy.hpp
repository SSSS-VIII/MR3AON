// Heuristic future activation, not simulated future purchases or measured probabilities.
#pragma once
struct Potential {
    double value=0;
    std::array<std::array<double,5>,9> completion{};
    std::array<double,9> by_cell{},confidence{};
    std::array<int,9> activation{},progress{},threshold{},reason{};
};
constexpr double FUTURE_SHOP_EXPOSURES=10.0;

// A cached count-only reference, not a rollout of future actions or random hands.
// Each future round offers five cards. Unbought cards return to the pool; only
// collected matching copies are removed. Budget uses their pool-average cost.
std::array<double,5> completion_reference(int total,int matching,int missing,
                                          int matching_cost,int cash,int current_draws) {
    using Key=std::array<int,6>;
    static std::map<Key,std::array<double,5>> cache;
    Key key={total,matching,missing,matching_cost,cash,current_draws};
    auto found=cache.find(key);if(found!=cache.end())return found->second;
    auto choose=[](int n,int k) {
        if(k<0 || k>n)return 0.0;
        k=std::min(k,n-k);double value=1;
        for(int i=1;i<=k;++i)value=value*(n-k+i)/i;
        return value;
    };
    std::array<double,6> dp{};dp[0]=1;
    std::array<double,5> result{};
    for(int step=0;step<5;++step) {
        std::array<double,6> next{};
        int affordable=std::min(missing,(cash+3*step)*matching/matching_cost);
        for(int held=0;held<=missing;++held)if(dp[held]>0) {
            if(held==missing){next[held]+=dp[held];continue;}
            int n=total-held,m=matching-held;
            int draws=std::min(n,step==0?current_draws:5);
            double denominator=choose(n,draws);
            for(int got=std::max(0,draws-(n-m));got<=std::min(m,draws);++got) {
                double probability=choose(m,got)*choose(n-m,draws-got)/denominator;
                int bought=std::min(missing,std::max(held,std::min(affordable,held+got)));
                next[bought]+=dp[held]*probability;
            }
        }
        dp=next;result[step]=std::clamp(dp[missing],0.0,1.0);
    }
    cache.emplace(key,result);return result;
}

Potential estimate_potential(const Evaluation& evaluated,const std::vector<int>& future_pool,
                             const std::array<Cell,9>& original, double passive_weight=1, double aura_weight=0) {
    Potential p;
    auto remaining=future_pool;
    int empty=0,tigers=0,thunder=0,roles=0,weapons=0,fire=0,total=0;
    int cash=gold,purchased=0;
    for(int i=0;i<9;++i) {
        if(board[i].id<0){++empty;continue;}
        const auto& c=cards[board[i].id];
        if(original[i].id<0){--remaining[board[i].id];cash-=c.cost;++purchased;}
        tigers+=c.effect==TIGER2 || c.effect==TIGER4 || c.effect==TIGER5;
        thunder+=c.element==4;fire+=c.element==1;
        roles+=c.category==0;weapons+=c.category==1;
    }
    int future_elements=0,future_categories=0;
    for(unsigned id=0;id<cards.size();++id)if(remaining[id]>0) {
        total+=remaining[id];
        if(cards[id].element)future_elements|=1<<cards[id].element;
        future_categories|=1<<(cards[id].category+1);
    }
    auto supply=[&](int element,bool tiger,bool weapon) {
        int count=0;
        for(unsigned i=0;i<cards.size();++i) {
            const auto& c=cards[i];
            bool qualifies=tiger?(c.effect==TIGER2 || c.effect==TIGER4 || c.effect==TIGER5):
                           weapon?c.category==1:c.element==element;
            if(qualifies)count+=std::max(0,remaining[i]);
        }
        return count;
    };
    auto multiplier=[&](int i,int r) {
        const auto& c=cards[board[i].id];
        if(c.effect==WIND_TRIPLE && r>=4)return 3;
        if(c.effect==THUNDER_TRIPLE && thunder>=5)return 3;
        if(c.effect==TIGER5 && tigers>=5)return 4;
        if(c.effect==WATER_DOUBLE) {
            int water=0;
            for(int j=i/3*3;j<i/3*3+3;++j)water+=board[j].id>=0 && cards[board[j].id].element==2;
            if(water==3)return 2;
        }
        return 1;
    };
    for(int i=0;i<9;++i)if(board[i].id>=0) {
        const auto& c=cards[board[i].id];
        int target=0,progress=0,available=0,capacity=empty;
        if(c.effect==WATER_DOUBLE) {
            target=3;capacity=0;
            for(int j=i/3*3;j<i/3*3+3;++j) {
                capacity+=board[j].id<0;
                progress+=board[j].id>=0 && cards[board[j].id].element==2;
            }
            available=supply(2,false,false);
        } else if(c.effect==TIGER2 || c.effect==TIGER4 || c.effect==TIGER5) {
            target=c.effect==TIGER2?2:c.effect==TIGER4?4:5;
            progress=tigers;available=supply(0,true,false);
        } else if(c.effect==THUNDER_TRIPLE || c.effect==THUNDER_DRAGON) {
            target=5;progress=thunder;available=supply(4,false,false);
        } else if(c.effect==WEILI || c.effect==DRAGON) {
            // One expected matching purchase per future round at most; no base damage
            // is invented for those unknown cards, only this source's +2 growth.
            available=supply(c.effect==DRAGON?1:0,false,c.effect==WEILI);
            p.progress[i]=c.effect==DRAGON?fire:weapons;
            double slots=empty,copies=available;
            double chance=total?std::min(1.0,FUTURE_SHOP_EXPOSURES*available/total):0;
            for(int r=turn+1;r<=5 && slots>0 && copies>0;++r) {
                double arrivals=std::min({1.0,slots,copies})*chance;
                p.by_cell[i]+=2*arrivals*(6-r);slots-=arrivals;copies-=arrivals;
            }
            p.confidence[i]=chance;p.activation[i]=turn<5?turn+1:0;
            p.reason[i]=p.by_cell[i]>0?5:4;p.value+=p.by_cell[i];continue;
        } else continue;  // Blood shadow/cranes' deterministic timed effects already in D.
        p.progress[i]=progress;p.threshold[i]=target;
        if(progress>=target){
            p.confidence[i]=1;
            for(int r=turn;r<=5;++r)p.completion[i][r-1]=1;
            continue; // Already realized in real damage.
        }
        int missing=target-progress;
        if(capacity<missing){p.reason[i]=c.effect==WATER_DOUBLE?1:2;continue;}
        if(available<missing){p.reason[i]=3;continue;}
        int matching_cost=0;
        for(unsigned id=0;id<cards.size();++id) {
            const auto& item=cards[id];
            bool qualifies=c.effect==WATER_DOUBLE?item.element==2:
                (c.effect==TIGER2 || c.effect==TIGER4 || c.effect==TIGER5)?
                    (item.effect==TIGER2 || item.effect==TIGER4 || item.effect==TIGER5):item.element==4;
            if(qualifies)matching_cost+=std::max(0,remaining[id])*item.cost;
        }
        int current_draws=reference_refreshes>0?std::max(0,reference_shop_slots-purchased):0;
        auto reference=completion_reference(total,available,missing,matching_cost,std::max(0,cash),current_draws);
        p.reason[i]=turn==5 && current_draws==0?4:5;
        for(int r=turn;r<=5;++r) {
            double confidence=reference[r-turn];p.completion[i][r-1]=confidence;
            if(confidence>0 && p.activation[i]==0)p.activation[i]=r;
            if(c.effect==WATER_DOUBLE)p.by_cell[i]+=evaluated.attack_by_round[r-1][i]*confidence;
            if(c.effect==TIGER2)p.by_cell[i]+=2*confidence;
            if(c.effect==TIGER5)p.by_cell[i]+=3*evaluated.attack_by_round[r-1][i]*confidence;
            if(c.effect==THUNDER_TRIPLE)p.by_cell[i]+=2*evaluated.attack_by_round[r-1][i]*confidence;
            if(c.effect==TIGER4) {
                double recipients=missing;
                for(int j=0;j<9;++j)if(board[j].id>=0 && cards[board[j].id].category==0)recipients+=multiplier(j,r);
                p.by_cell[i]+=recipients*confidence;
            }
            if(c.effect==THUNDER_DRAGON) {
                double recipients=0;int row_empty=0;
                for(int j=i/3*3;j<i/3*3+3;++j) {
                    row_empty+=board[j].id<0;
                    if(j!=i && board[j].id>=0)recipients+=multiplier(j,r);
                }
                recipients+=std::min(missing,row_empty);
                p.by_cell[i]+=4*recipients*confidence;
            }
        }
        p.confidence[i]=p.completion[i][4];
        p.value+=p.by_cell[i];
    }
    for(int i=0;i<9;++i)p.by_cell[i]*=passive_weight;
    p.value*=passive_weight;
    // Expected future occupancy is shared across empty cells, not one invented
    // full-strength recipient for every source. Unknown cards' own damage is absent.
    if(aura_weight>0 && empty>0 && total>0)for(int i=0;i<9;++i)if(board[i].id>=0) {
        const auto& c=cards[board[i].id];
        int mask=0;
        if(c.effect==FLAG || c.effect==DRUM)for(int j=0;j<9;++j)if(board[j].id>=0 && board[j].entered>=board[i].entered) {
            int kind=c.effect==FLAG?cards[board[j].id].element:cards[board[j].id].category+1;
            if(kind)mask|=1<<kind;
        }
        int distinct=__builtin_popcount((unsigned)mask);
        double added=0;
        for(int r=turn+1;r<=5;++r) {
            double filled=std::min({1.0,double(total)/empty,2.0*(r-turn)/empty});
            int available_types=__builtin_popcount((unsigned)((c.effect==FLAG?future_elements:future_categories)&~mask));
            double diversity=std::min(double(available_types),.5*(r-turn));
            bool active=r-board[i].entered<2;
            for(int j=0;j<9;++j)if(j!=i) {
                bool row=i/3==j/3,col=i%3==j%3;
                bool adjacent=std::abs(i/3-j/3)+std::abs(i%3-j%3)==1;
                if(board[j].id<0) {
                    double boost=0;
                    if(c.effect==MASK && adjacent)boost=1.25;
                    if(c.effect==SHEATH && adjacent)boost=.8;
                    if((c.effect==FLAG || c.effect==DRUM) && row)boost=distinct+diversity;
                    if(c.effect==FOX && row)boost=2;
                    if(active && c.effect==COLUMN_ELEMENT && col)boost=.75;
                    if(active && c.effect==ROW_ELEMENT && row)boost=.75;
                    if(active && c.effect==COLUMN_ALL && col)boost=2;
                    if(active && c.effect==ROW_ALL && row)boost=2;
                    if(active && c.effect==THUNDER_ALL)boost=.25;
                    added+=boost*filled;
                } else if(row && (c.effect==FLAG || c.effect==DRUM))added+=diversity*multiplier(j,r);
            }
        }
        added*=aura_weight;p.value+=added;p.by_cell[i]+=added;
        if(added>0)p.reason[i]=6;
    }
    return p;
}
