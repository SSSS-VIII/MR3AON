// Offline only: no Maa, ADB, runtime instances, screenshots or input.
#include "effects.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <vector>
using I = std::int64_t;
using U = std::uint64_t;
using Clock = std::chrono::steady_clock;
struct Card { int attack,cost,element,category,copies,effect,param; };
struct Cell { int id=-1, entered=1, bonus=0; };
struct Evaluation { I damage=0,gold=0,refresh=0; bool instant=false; std::array<I,5> rounds{}; std::array<I,9> cell_damage{}; std::array<std::array<I,9>,5> attack_by_round{}; };
std::vector<Card> cards;
std::array<Cell,9> board;
int turn, gold, growth_mode;

Evaluation evaluate(int spent) {
    Evaluation result;
    I money=gold-spent;
    int elements=0,weapons=0,tigers=0,thunder=0,armor=0;
    for(const auto& cell:board) if(cell.id>=0) {
        const auto& c=cards[cell.id];
        if(c.element) elements |= 1<<c.element;
        weapons += c.category==1;
        tigers += c.effect==TIGER2 || c.effect==TIGER4 || c.effect==TIGER5;
        thunder += c.element==4;
        if(c.category==4) armor |= 1<<c.param;
    }
    auto grown = [&](const Cell& source, int element, int category, bool distinct) {
        int count=0,mask=0;
        for(const auto& target:board) if(target.id>=0 && (!growth_mode || target.entered>=source.entered)) {
            const auto& t=cards[target.id];
            if(element>=0 && t.element!=element) continue;
            if(category>=0 && t.category!=category) continue;
            if(distinct) {
                int value=element==-2 ? t.element : t.category+1;
                if(value) mask |= 1<<value;
            } else ++count;
        }
        return distinct ? __builtin_popcount((unsigned)mask) : count;
    };
    int new_this_round=0;
    for(const auto& cell:board) if(cell.id>=0 && cell.entered==turn) ++new_this_round;
    for(int r=turn;r<=5;++r) {
        std::array<I,9> attack{};
        for(int i=0;i<9;++i) if(board[i].id>=0) {
            const auto& c=cards[board[i].id];
            attack[i]=c.attack+board[i].bonus;
            if(c.effect==TIGER2 && tigers>=2) attack[i]+=2;
            if(c.effect==WEILI) attack[i]+=2*grown(board[i],-1,1,false);
            if(c.effect==DRAGON) attack[i]+=2*grown(board[i],1,-1,false);
        }
        for(int i=0;i<9;++i) if(board[i].id>=0) {
            const auto& c=cards[board[i].id];
            const bool active=r-board[i].entered<2;
            int distinct=0;
            if(c.effect==FLAG) distinct=grown(board[i],-2,-1,true);
            if(c.effect==DRUM) distinct=grown(board[i],-1,-1,true);
            for(int j=0;j<9;++j) if(i!=j && board[j].id>=0) {
                const auto& t=cards[board[j].id];
                bool row=i/3==j/3,col=i%3==j%3;
                bool adjacent=std::abs(i/3-j/3)+std::abs(i%3-j%3)==1;
                if(c.effect==TIGER4 && tigers>=4 && t.category==0) ++attack[j];
                if(c.effect==MASK && adjacent) attack[j]+=1+(t.element==c.param);
                if(c.effect==SHEATH && adjacent && t.category==1) attack[j]+=2;
                if((c.effect==FLAG || c.effect==DRUM) && row) attack[j]+=distinct;
                if(c.effect==FOX && row && t.element==2) attack[j]+=4;
                if(c.effect==THUNDER_DRAGON && thunder>=5 && row) attack[j]+=4;
                if(active && c.effect==COLUMN_ELEMENT && col && t.element==c.param) attack[j]+=3;
                if(active && c.effect==ROW_ELEMENT && row && t.element==c.param) attack[j]+=3;
                if(active && c.effect==COLUMN_ALL && col) attack[j]+=2;
                if(active && c.effect==ROW_ALL && row) attack[j]+=2;
                if(active && c.effect==THUNDER_ALL && t.element==4) ++attack[j];
            }
            if(c.effect==TIGER4 && tigers>=4) ++attack[i];
            // The all-thunder temporary effect includes the source card.
            if(active && c.effect==THUNDER_ALL && c.element==4) ++attack[i];
        }
        for(int i=0;i<9;++i) if(board[i].id>=0) {
            const auto& c=cards[board[i].id];
            if(c.effect==TIGER5 && tigers>=5) attack[i]*=4;
            if(c.effect==WIND_TRIPLE && r>=4) attack[i]*=3;
            if(c.effect==THUNDER_TRIPLE && thunder>=5) attack[i]*=3;
            if(c.effect==WATER_DOUBLE) {
                int count=0;
                for(int j=i/3*3;j<i/3*3+3;++j) count+=board[j].id>=0 && cards[board[j].id].element==2;
                if(count==3) attack[i]*=2;
            }
        }
        result.attack_by_round[r-1]=attack;
        std::array<I,3> rows{},cols{};
        I damage=0;
        for(int i=0;i<9;++i) {damage+=attack[i];result.cell_damage[i]+=attack[i];rows[i/3]+=attack[i];cols[i%3]+=attack[i];}
        for(int i=0;i<9;++i) if(board[i].id>=0) {
            const auto& c=cards[board[i].id];
            I extra=0;
            if(c.effect==ICE_CRANE && r>=4) extra+=attack[i]*3;
            if(c.effect==CAT && r==5) extra+=money*4;
            if(c.effect==GHOST && armor==7) result.instant=true;
            if(board[i].entered==r) {
            switch(c.effect) {
                case HAYABUSA:extra+=15;break;
                case WIND_CRANE:extra+=weapons*4;break;
                case COLUMN_DAMAGE:extra+=cols[i%3];break;
                case ROW_DAMAGE:extra+=rows[i/3];break;
                case SELF_DAMAGE:extra+=attack[i]*3;break;
                case FIXED_DAMAGE:extra+=c.param;break;
                case EAGLE:extra+=cols[i%3]*2;break;
                case FIRE_DAMAGE:case THUNDER_DAMAGE: {
                    int wanted=c.effect==FIRE_DAMAGE?1:4,count=0;
                    for(const auto& cell:board) count+=cell.id>=0 && cards[cell.id].element==wanted;
                    extra+=count*4;break;
                }
                default:break;
            }
            }
            damage+=extra;result.cell_damage[i]+=extra;
        }
        result.rounds[r-1]=damage;result.damage+=damage;
        for(const auto& cell:board) if(cell.id>=0) {
            const auto& c=cards[cell.id];
            if(c.effect==INCOME) ++money;
            if(c.effect==AMULET) money+=__builtin_popcount((unsigned)elements);
            if(c.effect==RING && cell.entered==r) result.refresh+=2;
        }
        if(r<5) {
            int bought=r==turn?new_this_round:0;
            money+=3+(bought==0?2:bought==1?1:0);
        }
    }
    result.gold=money;return result;
}

#include "synergy.hpp"

int main() {
    int n,mode,samples,profile,tiebreak,max_purchases,trace; double seconds; U max_layouts;
    if(!(std::cin>>n>>turn>>gold>>seconds>>max_layouts>>mode>>samples>>growth_mode>>profile>>tiebreak>>max_purchases>>trace)) return 2;
    double passive_weight,aura_weight,vacancy_weight,cumulative_damage,finish_priority;
    std::cin>>passive_weight>>aura_weight>>vacancy_weight>>cumulative_damage>>finish_priority;
    cards.resize(n);
    for(auto& c:cards) std::cin>>c.attack>>c.cost>>c.element>>c.category>>c.copies>>c.effect>>c.param;
    if(profile>=1) for(auto& c:cards)
        if(c.effect==CAT || c.effect==GHOST || c.effect==RING) c.effect=PLAIN;
    std::vector<int> pool(n),used(n);
    for(auto& x:pool)std::cin>>x;
    std::vector<int> future_pool(n);
    for(auto& x:future_pool)std::cin>>x;
    for(auto& c:board)std::cin>>c.id>>c.entered>>c.bonus;
    if(!std::cin) return 2;
    auto started=Clock::now();
    auto original=board;
    auto baseline=evaluate(0);
    auto baseline_potential=profile==2?estimate_potential(baseline,future_pool,original,passive_weight,aura_weight):Potential{};
    std::vector<int> empty,combo,best_combo;
    for(int i=0;i<9;++i)if(board[i].id<0)empty.push_back(i);
    U layouts=0,completed=0,physical=0,instant_count=0,instant_weight=0;
    bool stopped=false;
    std::map<I,std::pair<U,U>> histogram;
    I overall=std::numeric_limits<I>::min();
    double overall_value=-std::numeric_limits<double>::infinity(),overall_potential=0;
    auto best_board=board;bool overall_finished=false;
    auto expired=[&] {
        return (max_layouts && layouts>=max_layouts) ||
          (seconds>0 && std::chrono::duration<double>(Clock::now()-started).count()>=seconds);
    };
    struct Choice {std::vector<int> cards;int spent,priority;I damage;std::array<Cell,9> board;Evaluation eval;Potential potential;double strategic;bool finishing;};
    std::vector<Choice> choices;
    auto priority=[&] {
        int value=0;
        for(int i:empty)if(board[i].id>=0) {
            const auto& c=cards[board[i].id];
            bool center=i==4,edge=(i==1 || i==3 || i==5 || i==7);
            if(c.effect==MASK || c.effect==SHEATH) value+=center?100:edge?40:0;
            if(c.effect==TIGER5 || c.effect==WATER_DOUBLE || c.effect==WIND_TRIPLE ||
               c.effect==THUNDER_TRIPLE || c.effect==ICE_CRANE || c.effect==SELF_DAMAGE)
                value+=edge?30:center?20:0;
            if(c.effect==FLAG || c.effect==DRUM || c.effect==FOX || c.effect==ROW_ELEMENT || c.effect==ROW_ALL)
                value+=i/3==1?10:0;
            if(c.effect==COLUMN_ELEMENT || c.effect==COLUMN_ALL)value+=i%3==1?10:0;
        }
        return value;
    };
    auto run_combo=[&](int spent,U weight) {
        I best=std::numeric_limits<I>::min();
        auto candidate_board=board;
        Evaluation candidate_eval;Potential candidate_potential;double best_value=-std::numeric_limits<double>::infinity();int best_priority=std::numeric_limits<int>::min();
        bool instant=false,candidate_finished=false;
        auto place=[&](auto&& self,int at,int previous_cell)->void {
            if(stopped)return;
            if((layouts%1024==0 || (max_layouts && layouts>=max_layouts)) && expired()){stopped=true;return;}
            if(at==(int)combo.size()) {
                ++layouts;auto e=evaluate(spent);
                auto potential=profile==2?estimate_potential(e,future_pool,original,passive_weight,aura_weight):Potential{};
                bool finishing=finish_priority>0 && e.rounds[turn-1]+cumulative_damage>=100;
                double value=finishing?double(e.rounds[turn-1]):
                    e.damage+potential.value-vacancy_weight*(5-turn)*combo.size();
                int pos=tiebreak?priority():0;
                if(finishing>candidate_finished || (finishing==candidate_finished &&
                    (value>best_value+1e-9 || (std::abs(value-best_value)<1e-9 &&
                    (e.damage>best || (e.damage==best && pos>best_priority)))))) {
                    best=e.damage;best_value=value;best_priority=pos;candidate_board=board;
                    instant=e.instant;candidate_finished=finishing;candidate_eval=e;candidate_potential=potential;
                }
                return;
            }
            int begin=at>0 && combo[at]==combo[at-1]?previous_cell+1:0;
            for(int j=begin;j<(int)empty.size();++j)if(board[empty[j]].id<0) {
                board[empty[j]]={combo[at],turn,0};self(self,at+1,j);board[empty[j]]=original[empty[j]];
                if(stopped)return;
            }
        };
        place(place,0,-1);
        if(stopped)return;
        ++completed;physical+=weight;
        if(trace)choices.push_back({combo,spent,best_priority,best,candidate_board,candidate_eval,candidate_potential,best_value,candidate_finished});
        auto& bin=histogram[best-baseline.damage];++bin.first;bin.second+=weight;
        if(instant){++instant_count;instant_weight+=weight;}
        if(candidate_finished>overall_finished || (candidate_finished==overall_finished &&
            (best_value>overall_value+1e-9 || (std::abs(best_value-overall_value)<1e-9 && best>overall)))) {
            overall_finished=candidate_finished;overall=best;overall_value=best_value;overall_potential=candidate_potential.value;
            best_combo=combo;best_board=candidate_board;
        }
    };
    if(mode==0) {
        auto visit=[&](auto&& self,int start,int spent,U weight)->void {
            run_combo(spent,weight);if(stopped)return;
            if(combo.size()>=std::min(empty.size(),(std::size_t)max_purchases))return;
            for(int i=start;i<n;++i)if(used[i]<pool[i] && spent+cards[i].cost<=gold) {
                int before=used[i]++;
                // C(pool,k+1)/C(pool,k); pool<=2, so multiplication is exact.
                U next_weight=weight*(pool[i]-before)/(before+1);
                combo.push_back(i);self(self,i,spent+cards[i].cost,next_weight);combo.pop_back();--used[i];
                if(stopped)return;
            }
        };visit(visit,0,0,1);
    } else {
        for(int j=0;j<samples && !stopped;++j) {
            int k,spent=0;std::cin>>k;combo.resize(k);
            for(auto& id:combo){std::cin>>id;spent+=cards[id].cost;}
            run_combo(spent,1);
        }
    }
    double elapsed=std::chrono::duration<double>(Clock::now()-started).count();
    std::cout<<"{\"complete\":"<<(stopped?"false":"true")<<",\"elapsed_s\":"<<elapsed
      <<",\"layouts\":"<<layouts<<",\"combinations\":"<<completed<<",\"physical_subsets\":"<<physical
      <<",\"baseline_damage\":"<<baseline.damage<<",\"instant_win_combinations\":"<<instant_count
      <<",\"instant_win_physical\":"<<instant_weight<<",\"histogram\":[";
    bool first=true;
    for(auto [gain,counts]:histogram){if(!first)std::cout<<',';first=false;std::cout<<'['<<gain<<','<<counts.first<<','<<counts.second<<']';}
    std::cout<<"],\"best_combo\":[";
    for(unsigned i=0;i<best_combo.size();++i){if(i)std::cout<<',';std::cout<<best_combo[i];}
    std::cout<<"],\"best_board\":[";
    for(int i=0;i<9;++i){if(i)std::cout<<',';std::cout<<best_board[i].id;}
    board=best_board;int spent=0;for(auto id:best_combo)spent+=cards[id].cost;
    auto best=evaluate(spent);
    std::cout<<"],\"best_round_damage\":[";
    for(int i=0;i<5;++i){if(i)std::cout<<',';std::cout<<best.rounds[i];}
    std::cout<<"],\"best_damage\":"<<best.damage<<",\"best_end_gold\":"<<best.gold<<",\"best_potential\":"<<overall_potential;
    std::cout<<",\"baseline_cell_damage\":[";
    for(int i=0;i<9;++i){if(i)std::cout<<',';std::cout<<baseline.cell_damage[i];}
    std::cout<<"],\"baseline_potential\":"<<baseline_potential.value<<",\"choices\":[";
    bool first_choice=true;
    for(const auto& c:choices) {
        if(!first_choice)std::cout<<',';first_choice=false;
        std::cout<<"{\"spent\":"<<c.spent<<",\"gold_left\":"<<gold-c.spent
          <<",\"damage\":"<<c.damage<<",\"finishing\":"<<(c.finishing?"true":"false")<<",\"strategic_damage\":"<<c.strategic<<",\"position_priority\":"<<c.priority
          <<",\"end_gold\":"<<c.eval.gold<<",\"extra_refreshes\":"<<c.eval.refresh<<",\"cards\":[";
        for(unsigned i=0;i<c.cards.size();++i){if(i)std::cout<<',';std::cout<<c.cards[i];}
        std::cout<<"],\"board\":[";
        for(int i=0;i<9;++i){if(i)std::cout<<',';std::cout<<c.board[i].id;}
        std::cout<<"],\"cell_damage\":[";
        for(int i=0;i<9;++i){if(i)std::cout<<',';std::cout<<c.eval.cell_damage[i];}
        std::cout<<"],\"round_damage\":[";
        for(int i=0;i<5;++i){if(i)std::cout<<',';std::cout<<c.eval.rounds[i];}
        std::cout<<"],\"synergy_potential\":"<<c.potential.value<<",\"synergy_details\":[";
        bool first_term=true;
        for(int i=0;i<9;++i)if(c.potential.threshold[i] || c.potential.by_cell[i]!=0) {
            if(!first_term)std::cout<<',';first_term=false;
            std::cout<<"{\"cell\":"<<i<<",\"value\":"<<c.potential.by_cell[i]
              <<",\"progress\":"<<c.potential.progress[i]<<",\"threshold\":"<<c.potential.threshold[i]
              <<",\"activation_round\":"<<c.potential.activation[i]<<",\"confidence\":"<<c.potential.confidence[i]
              <<",\"reason\":"<<c.potential.reason[i]<<"}";
        }
        std::cout<<"]}";
    }
    std::cout<<"]}\n";
}
