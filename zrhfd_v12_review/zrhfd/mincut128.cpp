#include <algorithm>
#include <iostream>
#include <limits>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>
using I=__int128_t;
I parse(const std::string&s){I v=0;for(char c:s){if(c<'0'||c>'9')throw std::runtime_error("capacity syntax");if(v>((I(1)<<125)-10)/10)throw std::runtime_error("capacity overflow");v=v*10+(c-'0');}return v;}
std::string print(I x){if(!x)return "0";std::string s;while(x){s.push_back('0'+x%10);x/=10;}std::reverse(s.begin(),s.end());return s;}
struct E{int v,rev;I cap;};
struct Flow{
 std::vector<std::vector<E>> a;std::vector<int>level,it;
 Flow(int n):a(n),level(n),it(n){}
 void add(int u,int v,I c){E x{v,int(a[v].size()),c},y{u,int(a[u].size()),0};a[u].push_back(x);a[v].push_back(y);}
 bool bfs(int s,int t){std::fill(level.begin(),level.end(),-1);std::queue<int>q;q.push(s);level[s]=0;while(!q.empty()){int u=q.front();q.pop();for(auto&e:a[u])if(e.cap>0&&level[e.v]<0){level[e.v]=level[u]+1;q.push(e.v);}}return level[t]>=0;}
 I dfs(int u,int t,I f){if(u==t)return f;for(int&i=it[u];i<int(a[u].size());i++){E&e=a[u][i];if(e.cap>0&&level[e.v]==level[u]+1){I v=dfs(e.v,t,std::min(f,e.cap));if(v){e.cap-=v;a[e.v][e.rev].cap+=v;return v;}}}return 0;}
 I solve(int s,int t){I total=0;while(bfs(s,t)){std::fill(it.begin(),it.end(),0);while(I f=dfs(s,t,I(1)<<124))total+=f;}return total;}
 std::vector<int>reach(int s){std::vector<int>seen(a.size());std::queue<int>q;q.push(s);seen[s]=1;while(!q.empty()){int u=q.front();q.pop();for(auto&e:a[u])if(e.cap>0&&!seen[e.v]){seen[e.v]=1;q.push(e.v);}}std::vector<int>out;for(int i=0;i<int(a.size());i++)if(seen[i])out.push_back(i);return out;}
};
int main(){try{int n,m,s,t;if(!(std::cin>>n>>m>>s>>t))return 2;Flow f(n);for(int i=0;i<m;i++){int u,v;std::string c;std::cin>>u>>v>>c;if(!std::cin||u<0||v<0||u>=n||v>=n)throw std::runtime_error("input");f.add(u,v,parse(c));}I value=f.solve(s,t);auto reach=f.reach(s);std::cout<<print(value)<<"\n";for(int u:reach)std::cout<<u<<" ";std::cout<<"\n";return 0;}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 3;}}
