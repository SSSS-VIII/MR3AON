// One-card Bellman bootstrap over a hidden physical pool; no future game RNG.
#define main pool_engine_entry
#include "engine.cpp"
#undef main
#include <iomanip>

int main() {
    int n,base_turn,count;double passive,aura,vacancy,income_weight,gold_scale,deadline;
    std::cin>>n>>base_turn>>growth_mode>>count>>passive>>aura>>vacancy>>income_weight>>gold_scale>>deadline;
    std::array<double,5> before,after;
    for(auto& x:before)std::cin>>x;
    for(auto& x:after)std::cin>>x;
    cards.resize(n);
    for(auto& c:cards) {
        std::cin>>c.attack>>c.cost>>c.element>>c.category>>c.copies>>c.effect>>c.param;
        if(c.effect==CAT || c.effect==GHOST || c.effect==RING)c.effect=PLAIN;
    }
    std::vector<int> full_pool(n);
    for(auto& x:full_pool)std::cin>>x;
    std::array<Cell,9> original;
    for(auto& c:original)std::cin>>c.id>>c.entered>>c.bonus;
    struct Candidate {int cash,refresh_slots,purchases;double fallback;std::array<Cell,9> cells;};
    std::vector<Candidate> candidates(count);
    for(auto& c:candidates) {
        std::cin>>c.cash>>c.refresh_slots>>c.purchases>>c.fallback;
        for(auto& cell:c.cells)std::cin>>cell.id>>cell.entered>>cell.bonus;
    }
    if(!std::cin)return 2;
    const auto started=Clock::now();
    bool complete=true;U layouts=0;
    std::vector<double> answers;
    auto expired=[&]{return deadline>0 && std::chrono::duration<double>(Clock::now()-started).count()>deadline;};
    for(auto& candidate:candidates) {
        if(expired()){complete=false;break;}
        board=candidate.cells;turn=base_turn;gold=candidate.cash;
        auto current=evaluate(0);
        auto remaining=full_pool;
        for(int i=0;i<9;++i)if(original[i].id<0 && board[i].id>=0)--remaining[board[i].id];
        int elements=0,producers=0,amulets=0,new_buys=0,total=0;
        for(auto cell:board)if(cell.id>=0) {
            auto c=cards[cell.id];if(c.element)elements|=1<<c.element;
            producers+=c.effect==INCOME;amulets+=c.effect==AMULET;
            new_buys+=cell.entered==turn;
        }
        int samples=candidate.refresh_slots;
        I prefix=0;
        if(samples==0) {
            if(turn==5){answers.push_back(candidate.fallback);continue;}
            prefix=current.rounds[turn-1];
            gold+=3+(new_buys==0?2:new_buys==1?1:0)+producers+amulets*__builtin_popcount((unsigned)elements);
            ++turn;samples=10; // New five slots plus one free refresh; at most one modeled purchase.
        }
        for(int copies:remaining)total+=copies;
        samples=std::min(samples,total);
        auto point=board;
        auto utility=[&](int cost) {
            ++layouts;
            auto e=evaluate(cost);
            auto p=estimate_potential(e,remaining,point,passive,aura);
            int empty=0,element_mask=0,black=0,amulet=0,max_cost=0;
            for(auto cell:board)if(cell.id<0)++empty;else {
                const auto& c=cards[cell.id];if(c.element)element_mask|=1<<c.element;
                black+=c.effect==INCOME;amulet+=c.effect==AMULET;
            }
            for(int i=0;i<n;++i)if(remaining[i]>0)max_cost=std::max(max_cost,cards[i].cost);
            int cash=gold-cost;
            // Extra money above what open slots can use has no shadow value.
            double cash_cap=std::max(0.0,2.5*empty-3*(5-turn));
            double money=std::min(double(cash),std::min(cash_cap,double(empty*max_cost)));
            double economic=0,capacity=std::max(0.0,2.5*empty-cash-3*(5-turn));
            for(int r=turn;r<5;++r) {
                double produced=black+amulet*std::min(4.0,__builtin_popcount((unsigned)element_mask)+.5*(r-turn));
                double useful=std::min(capacity,produced);capacity-=useful;
                economic+=useful*before[r]*income_weight;
            }
            int bought=0;for(int i=0;i<9;++i)bought+=point[i].id<0 && board[i].id>=0;
            return e.damage+p.value-vacancy*(5-turn)*bought+economic+money*before[turn-1]*gold_scale;
        };
        double baseline=utility(0);
        std::vector<std::pair<double,int>> distribution;
        for(int id=0;id<n;++id)if(remaining[id]>0) {
            if(expired()){complete=false;break;}
            double best=baseline;
            if(cards[id].cost<=gold)for(int i=0;i<9;++i)if(point[i].id<0) {
                board[i]={id,turn,0};best=std::max(best,utility(cards[id].cost));board[i]=point[i];
            }
            distribution.emplace_back(best,remaining[id]);
        }
        if(!complete)break;
        double expected=baseline,previous_cdf=0;
        if(samples>0) {
            expected=0;int cumulative=0;
            std::sort(distribution.begin(),distribution.end());
            for(auto [value,copies]:distribution) {
                cumulative+=copies;double cdf=1;
                for(int k=0;k<samples;++k)cdf*=cumulative>k?double(cumulative-k)/(total-k):0;
                expected+=value*(cdf-previous_cdf);previous_cdf=cdf;
            }
        }
        answers.push_back(prefix+expected-vacancy*(5-base_turn)*candidate.purchases);
    }
    std::cout<<std::setprecision(12)<<"{\"complete\":"<<(complete?"true":"false")
        <<",\"layouts\":"<<layouts<<",\"elapsed_s\":"<<std::chrono::duration<double>(Clock::now()-started).count()<<",\"scores\":[";
    for(unsigned i=0;i<answers.size();++i){if(i)std::cout<<',';std::cout<<answers[i];}
    std::cout<<"]}\n";
}
