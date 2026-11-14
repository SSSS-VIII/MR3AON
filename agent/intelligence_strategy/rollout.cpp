// Sample complete single-sided continuations using only the known physical pool.
// The rollout policy uses a small beam; current visible choices still come from
// the exhaustive engine. Shared random numbers compare every shortlisted choice.
#define main pool_engine_entry
#include "engine.cpp"
#undef main
#include <iomanip>
#include <random>
#include <set>

struct BeamState {
    std::array<Cell,9> cells;int cash=0,mask=0;double value=0;bool finish=false;
};
struct Continuation {
    int cash,refresh_slots,purchases;double fallback;std::array<Cell,9> cells;
};
int main() {
    int n,base_turn,count,samples,width,finish_priority;double passive,aura,vacancy,income_weight,unused,seconds,past,safety,early,role_position_bias;
    std::uint64_t seed;
    std::cin>>n>>base_turn>>growth_mode>>count>>passive>>aura>>vacancy>>income_weight>>unused>>seconds
        >>samples>>width>>role_position_bias>>finish_priority>>seed>>past>>safety>>early;
    std::array<double,5> before,after;
    for(auto& x:before)std::cin>>x;for(auto& x:after)std::cin>>x;
    cards.resize(n);
    for(auto& c:cards) {
        std::cin>>c.attack>>c.cost>>c.element>>c.category>>c.copies>>c.effect>>c.param;
        if(c.effect==CAT || c.effect==GHOST || c.effect==RING)c.effect=PLAIN;
    }
    std::vector<int> pool(n);for(auto& x:pool)std::cin>>x;
    std::array<Cell,9> original;for(auto& c:original)std::cin>>c.id>>c.entered>>c.bonus;
    std::vector<Continuation> candidates(count);
    for(auto& c:candidates) {
        std::cin>>c.cash>>c.refresh_slots>>c.purchases>>c.fallback;
        for(auto& cell:c.cells)std::cin>>cell.id>>cell.entered>>cell.bonus;
    }
    if(!std::cin)return 2;
    const auto started=Clock::now();U layouts=0;bool inventory_valid=true;
    auto expired=[&]{return seconds>0 && std::chrono::duration<double>(Clock::now()-started).count()>=seconds;};
    auto rank=[](const BeamState& a,const BeamState& b) {
        if(a.finish!=b.finish)return a.finish>b.finish;
        if(std::abs(a.value-b.value)>1e-9)return a.value>b.value;
        return a.cash>b.cash;
    };
    auto plan=[&](const std::vector<int>& hand,const std::vector<int>& deck,int refreshes,double cumulative)->bool {
        const auto point=board;const int starting_cash=gold;
        auto supply=std::vector<int>(n);
        for(int id:deck)++supply[id];for(int id:hand)++supply[id];
        auto value=[&](BeamState& state) {
            ++layouts;board=state.cells;gold=state.cash;
            auto e=evaluate(0);auto potential=estimate_potential(e,supply,point,passive,aura);
            int empty=0,elements=0,black=0,amulets=0,max_cost=0,min_cost=1000;
            auto remaining=supply;
            for(int i=0;i<9;++i)if(point[i].id<0 && board[i].id>=0)--remaining[board[i].id];
            for(auto cell:board)if(cell.id<0)++empty;else {
                auto c=cards[cell.id];if(c.element)elements|=1<<c.element;
                black+=c.effect==INCOME;amulets+=c.effect==AMULET;
            }
            for(int id=0;id<n;++id)if(remaining[id]>0) {
                max_cost=std::max(max_cost,cards[id].cost);min_cost=std::min(min_cost,cards[id].cost);
            }
            int bought=__builtin_popcount((unsigned)state.mask),slots=hand.size()-bought;
            double cash=std::min(state.cash,empty*max_cost);
            bool refresh=refreshes>0 && slots>0 && empty>0 && state.cash>=min_cost;
            double spending=refresh?std::min(cash,3.0*slots):0;
            double money=spending*before[turn-1]+(cash-spending)*after[turn-1];
            double economic=0,capacity=std::max(0.0,2.5*empty-state.cash-3*(5-turn));
            for(int r=turn;r<5;++r) {
                double income=black+amulets*std::min(4.0,__builtin_popcount((unsigned)elements)+.5*(r-turn));
                double useful=std::min(capacity,income);capacity-=useful;
                economic+=useful*before[r]*income_weight;
            }
            state.finish=finish_priority>0 && cumulative+e.rounds[turn-1]>=100;
            state.value=state.finish?double(e.rounds[turn-1]):e.damage+potential.value-vacancy*(5-turn)*bought+money+economic;
            // Stable tie preference, not an extra damage term.
            for(int i=0;i<9;++i)if(point[i].id<0 && board[i].id>=0) {
                auto c=cards[board[i].id];bool edge=i==1 || i==3 || i==5 || i==7;
                if(c.effect==MASK || c.effect==SHEATH)state.value+=1e-7*(i==4?100:edge?40:0);
                if((role_position_bias>0 && c.category==0) || c.effect==WIND_TRIPLE || c.effect==ICE_CRANE || c.effect==WATER_DOUBLE || c.effect==SELF_DAMAGE)state.value+=1e-7*(edge?30:i==4?20:0);
            }
        };
        std::vector<BeamState> beam={{point,starting_cash,0,0,false}};value(beam[0]);
        for(int at=0;at<(int)hand.size();++at) {
            if(expired())return false;
            std::vector<BeamState> next=beam;
            int id=hand[at];
            for(auto state:beam)if(state.cash>=cards[id].cost)for(int cell=0;cell<9;++cell)if(state.cells[cell].id<0) {
                auto child=state;child.cells[cell]={id,turn,0};child.cash-=cards[id].cost;child.mask|=1<<at;
                value(child);next.push_back(child);
            }
            std::stable_sort(next.begin(),next.end(),rank);
            std::set<std::array<int,9>> seen;
            std::vector<BeamState> distinct;
            for(auto state:next) {
                std::array<int,9> ids;for(int i=0;i<9;++i)ids[i]=state.cells[i].id;
                if(seen.insert(ids).second)distinct.push_back(state);
            }
            beam.clear();int groups=0;
            std::vector<bool> kept(distinct.size());
            for(unsigned i=0;i<distinct.size() && (int)beam.size()<width;++i) {
                int k=__builtin_popcount((unsigned)distinct[i].mask);
                if(!(groups&(1<<k))){beam.push_back(distinct[i]);kept[i]=true;groups|=1<<k;}
            }
            for(unsigned i=0;i<distinct.size() && (int)beam.size()<width;++i)if(!kept[i])beam.push_back(distinct[i]);
        }
        auto best=*std::max_element(beam.begin(),beam.end(),[&](const auto& a,const auto& b){return rank(b,a);});
        board=best.cells;gold=best.cash;
        return true;
    };
    auto simulate=[&](const Continuation& candidate,int sample,double& answer)->bool {
        board=candidate.cells;turn=base_turn;gold=candidate.cash;
        auto remaining=pool;
        for(int i=0;i<9;++i)if(original[i].id<0 && board[i].id>=0)--remaining[board[i].id];
        std::vector<int> deck;for(int id=0;id<n;++id)for(int k=0;k<remaining[id];++k)deck.push_back(id);
        std::mt19937_64 rng(seed+std::uint64_t(sample)*0x9e3779b97f4a7c15ULL);
        auto draw=[&]() {
            if(deck.empty())return -1;
            std::size_t at=rng()%deck.size();int id=deck[at];deck[at]=deck.back();deck.pop_back();return id;
        };
        auto valid_inventory=[&](const std::vector<int>& hand) {
            std::vector<int> actual(n);for(int id:deck)++actual[id];for(int id:hand)++actual[id];
            for(int i=0;i<9;++i)if(original[i].id<0 && board[i].id>=0)++actual[board[i].id];
            if(actual!=pool){inventory_valid=false;return false;}return true;
        };
        double damage=0,cumulative=past;bool hit4=cumulative>=100 && turn<=4;
        int slots=candidate.refresh_slots,refreshes=0;
        while(turn<=5) {
            std::vector<int> hand;
            for(int k=0;k<slots;++k){int id=draw();if(id>=0)hand.push_back(id);}
            if(!valid_inventory(hand))return false;
            while(!hand.empty()) {
                const auto point=board;
                if(!plan(hand,deck,refreshes,cumulative))return false;
                auto bought=std::vector<int>(n);
                for(int i=0;i<9;++i)if(point[i].id<0 && board[i].id>=0)++bought[board[i].id];
                std::vector<int> unbought;
                for(int id:hand)if(bought[id]>0)--bought[id];else unbought.push_back(id);
                hand=unbought;
                if(!valid_inventory(hand))return false;
                bool empty=false;for(auto cell:board)empty|=cell.id<0;
                int min_cost=1000;for(int id:deck)min_cost=std::min(min_cost,cards[id].cost);
                for(int id:hand)min_cost=std::min(min_cost,cards[id].cost);
                if(refreshes>0 && !hand.empty() && empty && gold>=min_cost) {
                    --refreshes;int number=hand.size();deck.insert(deck.end(),hand.begin(),hand.end());hand.clear();
                    for(int k=0;k<number;++k){int id=draw();if(id>=0)hand.push_back(id);}
                } else break;
            }
            if(expired())return false;
            auto e=evaluate(0);damage+=e.rounds[turn-1];cumulative+=e.rounds[turn-1];
            if(turn<=4 && cumulative>=100)hit4=true;
            int new_buys=0,elements=0,black=0,amulets=0;
            for(auto cell:board)if(cell.id>=0) {
                auto c=cards[cell.id];if(c.element)elements|=1<<c.element;
                black+=c.effect==INCOME;amulets+=c.effect==AMULET;
                new_buys+=cell.entered==turn;
            }
            gold+=black+amulets*__builtin_popcount((unsigned)elements);
            deck.insert(deck.end(),hand.begin(),hand.end());
            ++turn;if(turn>5)break;
            gold+=3+(new_buys==0?2:new_buys==1?1:0);slots=5;refreshes=1;
        }
        answer=damage-(cumulative<100?safety:0)+(hit4?early:0);return true;
    };
    std::vector<double> sum(count,0);int completed=0;
    for(int sample=0;sample<samples;++sample) {
        std::vector<double> batch(count);bool valid=true;
        for(int k=0;k<count;++k)if(!simulate(candidates[k],sample,batch[k])){valid=false;break;}
        if(!valid)break;
        for(int k=0;k<count;++k)sum[k]+=batch[k];++completed;
    }
    std::cout<<std::setprecision(12)<<"{\"complete\":"<<(completed==samples?"true":"false")
        <<",\"inventory_valid\":"<<(inventory_valid?"true":"false")<<",\"samples_completed\":"<<completed<<",\"layouts\":"<<layouts<<",\"elapsed_s\":"
        <<std::chrono::duration<double>(Clock::now()-started).count()<<",\"scores\":[";
    if(completed)for(int k=0;k<count;++k){if(k)std::cout<<',';std::cout<<sum[k]/completed;}
    std::cout<<"]}\n";
}
