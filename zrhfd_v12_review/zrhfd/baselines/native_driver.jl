# Thin data/seed wrapper: all diffusion and sweeps call retained author methods.
using SparseArrays, LinearAlgebra, DelimitedFiles, Random
BLAS.set_num_threads(1)
mode, source, edgepath = ARGS[1:3]
n = parse(Int, ARGS[4])
seed = parse(Int, ARGS[5]) + 1
sigma = parse(Float64, ARGS[6])
iterations = parse(Int, ARGS[7])
p = parse(Float64, ARGS[8])
masses = parse.(Float64, split(ARGS[9], ","))
rngseed = parse(Int, ARGS[10])
epsilon = parse(Float64, ARGS[11])
cm_tol = parse(Float64, ARGS[12])
edges = [parse.(Int, split(line, ",")) .+ 1 for line in eachline(edgepath)]
if mode in ("hfd", "hfd_hyper")
    include(joinpath(source, "ucHFD.jl"))
    incidence = [Int[] for _ in 1:n]
    for (eid, edge) in enumerate(edges), v in edge
        push!(incidence[v], eid)
    end
    degree = length.(incidence)
    H = HyperGraph(incidence, edges, degree, length.(edges), n, length(edges))
elseif mode == "pnorm"
    include(joinpath(source, "pNormDiffusion.jl"))
    adjacency = [Int[] for _ in 1:n]
    for edge in edges
        length(edge) == 2 || error("p-norm author code supports ordinary graphs")
        u, v = edge
        push!(adjacency[u], v)
        push!(adjacency[v], u)
    end
    G = AdjacencyList(adjacency, length.(adjacency), n)
else
    error("Unknown source baseline")
end
for mass in masses
    Random.seed!(rngseed)
    if mode in ("hfd", "hfd_hyper")
        injection = zeros(Float64, n)
        injection[seed] = mass
        cluster, cond, excess, seconds, counts = ucHFD(H, injection; sigma=sigma, max_iters=iterations, p=p)
        support = findall(>(0), excess)
        record = "{\"mass\":$mass,\"conductance\":$(isfinite(cond) ? string(cond) : "null"),\"kernel_seconds\":$seconds,\"vertices\":$(sort(cluster .- 1)),\"final_support\":$(support .- 1),\"nznodes_by_iteration\":$counts}"
        if mode == "hfd_hyper"
            heights = [H.degree[v] > 0 ? excess[v] / H.degree[v] / sigma : 0.0 for v in 1:n]
            record = record[1:end-1] * ",\"dual_heights\":$heights}"
        end
    else
        mass < sum(G.degree) || error("p-norm hard-capacity injection must be below total volume")
        start = time_ns()
        heights = pnormdiffusion(G, Dict(seed => mass); p=p, max_iters=iterations, epsilon=epsilon, cm_tol=cm_tol)
        cluster, cond = sweepcut(G, heights)
        seconds = (time_ns() - start) / 1e9
        support = findall(>(0), heights)
        q = p / (p - 1)
        injection = zeros(Float64, n)
        injection[seed] = mass
        max_excess = maximum(compute_mass_v(heights, v, heights[v], G.adjlist, injection, q, 0) - G.degree[v] for v in 1:n)
        record = "{\"mass\":$mass,\"conductance\":$(isfinite(cond) ? string(cond) : "null"),\"kernel_seconds\":$seconds,\"vertices\":$(sort(cluster .- 1)),\"final_support\":$(support .- 1),\"max_primal_excess\":$max_excess}"
    end
    println(record)
    flush(stdout)
end
