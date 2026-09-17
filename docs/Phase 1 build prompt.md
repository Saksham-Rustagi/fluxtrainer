# Phase 1 build prompt: FluxCore (C++)

Paste the block below into Claude Code at the repo root, with `docs/SPEC.md` already in place.

---

## Context

You are building **FluxCore**, the C++ engine behind a training app for the competitive Boggle variant Flux. The full product spec is at `docs/SPEC.md`. Read Sections 2, 3.5, 5, and 7.6 before planning. This session covers **Phase 1 only**: the engine, the offline simulator, and the measurements that decide whether later phases get built. No Swift, no UI, no iOS project. Do not start those.

This machine has many cores and the simulator is meant to use them.

## Task A: the old code

There is a prior project on this machine, **LetterCounter**, whose main file is `boggle_search_4x4.cpp`. It has already been reviewed. It is a multithreaded simulated-annealing search for *high-scoring boards*, not a ranked-board simulator, so it solves a different problem. The review below is authoritative; do not re-derive it, but do locate the repo to recover the two things not in that file.

```
mdfind -name LetterCounter
find ~ -maxdepth 6 -iname '*lettercounter*' -not -path '*/Library/*' 2>/dev/null
```

**Recover from the repo:**

1. `bogwords.txt`, the dictionary it loads. Identify which list it is (line count, presence of CSW21-only words such as ZA, QI, EW, OK). If it is not Collins 21, note it and keep using it as a stand-in, marking every derived number provisional.
2. Any saved board files, leaderboards or test fixtures. Boards with known solution counts are the highest-value thing in that repo.

### Port directly

These are correct and solve exactly the problem D3 has. Port them, cleaned up:

- `random_self_avoiding_path` and `dfs_build_random_path`: seed-path placement on the grid. Fix the per-call `vector<int> neigh` copy in the DFS; use a fixed-size array and shuffle indices in place.
- `embed_word`, including its `allow_overlap` mode. **The overlap mode is better than what the spec describes**: allowing a second seed to reuse cells where letters agree is what produces the dense overlapping clusters real Spam boards have. Keep it and expose it as a generator option.
- `canonical_board_string` and `transform_coord`: canonical form under the 8 dihedral symmetries. Useful for board dedup in the anti-memorization store, and for collapsing equivalent boards during simulation.
- `score_for_length`: already matches the Flux scoring table exactly. Verify against the spec table and move it into the config rather than code.
- The worker-thread and leaderboard skeleton in `anneal_worker` / `GlobalState` is a reasonable shape for the simulator's thread pool. Take the structure, not the annealing.

### Use as an oracle, do not ship

The trie-based `score_board` and `dfs_collect_words4x4` are an independent, straightforward, almost certainly correct solver. That makes them the **differential-test oracle** D6 asks for, which is worth more than any code you would ship from this file.

To use it: lower `MIN_WORD_LEN_FOR_SCORE` to 3 (it defaults to 8, so it currently ignores most of the board), wrap it behind a test-only interface, and compare word sets against the new DAWG solver across thousands of random boards. Any disagreement is a bug in the new solver until proven otherwise.

Note for the spec: this solver dedups found words into an `unordered_set<string>`, so a word reachable by three paths scores once. That matches the assumption in §16.3 but does not confirm it for Flux itself.

### Do not carry over

- **The trie.** 26 raw child pointers and a `new` per node is roughly 200+ bytes per node across millions of nodes, with pointer chasing on every step. This is what the DAWG in D1 replaces, and it is the main reason the old solver is slow.
- **`string current` and `unordered_set<string> found` in the DFS hot loop.** Every found word allocates and hashes a string. The new solver emits dense word IDs into a preallocated buffer. This single change is worth more than any other optimization.
- **`full_words`,** a second full copy of the dictionary as an `unordered_set<string>`.
- **`compute_letter_weights`.** It hand-tunes a distribution with a +200 vowel bonus and +150 for ERSTAIN. That is a heuristic for making *good* boards, not a model of Flux's actual letter distribution, and carrying it into the generator would silently bias every statistic the simulator produces. The distribution comes from config, per D3.
- **Global mutable state** (`trie_root`, `letterFreq`, the seed-word vectors as file-scope globals). Incompatible with the clean `core/` boundary and with linking into an iOS static library. Everything becomes an explicit context object.
- **The `BOARD_SIDE` macro.** Board size becomes a template parameter or a runtime value so one binary handles 4x4 and 5x5 without recompiling.
- **`mt19937` seeded from the clock.** Replace per D3's reproducibility requirement.
- **The annealing itself.** Flux ranks best-of-N over independently generated candidates. That is not the same as hill-climbing toward a maximum, and the boards it produces have a different character. Do not reuse the search as a generator. It may later be useful for constructing the fixed benchmark boards in spec §11.3, where you do want deliberately extreme boards.

### What is genuinely missing

The old solver records **no paths at all**, only word strings. Every path-dependent measurement in D5 (reachability, cellmate pathability, enumerability) needs full path enumeration. That is new work, not a port, and it is the part to write carefully.

## Task B: plan

After the recon, produce a plan covering the deliverables below. Wait for approval before implementing.

## Deliverables

### D1: DAWG

Offline builder (`tools/build_dawg`) plus a runtime loader in the core.

- Build by incremental minimization (Daciuk-style) from a sorted word list. Do not build a full trie and minimize afterwards unless memory shows it is fine.
- Make it a **numbered (perfect-hash) DAWG**: each node stores the count of words reachable through it, so any terminal maps to a stable dense integer word ID with no side table. Every downstream artifact keys on that ID, so this property is required, not optional.
- Node layout: pack into `uint32_t` (child index, 5-bit letter, end-of-word, end-of-list). Document the exact bit layout in a header comment.
- Serialize as a flat little-endian binary loaded with `mmap`, no parse step. Version the format with a magic number and a header carrying word count, node count, and a hash of the source list.
- Expected size under 1 MB for roughly 280k words. If it comes out much larger, say so rather than proceeding.

The word list is not in the repo. Take a path argument, and if CSW21 is not available locally, build and test against whatever public list is present and mark every derived number as provisional.

### D2: Solver

- DFS from every cell, DAWG-guided, `uint32_t` visited bitmask (16 or 25 bits).
- 8-way adjacency. No tile reuse within a word. Q and U are ordinary separate tiles, so no special-casing anywhere.
- Two modes: `count` (word IDs and path counts only) and `full` (every distinct path per word). Family and reachability analysis needs `full`; the simulator hot loop uses `count`.
- Guard against path-count blowup: cap stored paths per word at a configurable limit and record when the cap was hit.
- Output is a compact struct-of-arrays, not a `map<string, vector<vector<int>>>`. Allocate once per worker thread and reuse.

**Targets:** 4x4 under 300 microseconds, 5x5 under 3 ms, single-threaded, release build. Report actuals.

### D3: Generator

Implements `docs/SPEC.md` §2.3 exactly.

- 60/40 grid split; tiers Spam 20% / Good Casual 50% / Casual 30% with best-of-N candidate counts as specced.
- **Candidates are ranked by total available points on the board.** This is confirmed, not assumed.
- 50% of boards carry a seed word; seed lengths per the spec table; the longest seeds are restricted to Spam.
- Seed placement: lay the seed's path as a self-avoiding walk on the grid, then fill remaining cells from the letter distribution.
- The letter distribution, tier table, seed table and scoring table all live in a versioned config file (JSON or TOML) loaded at runtime. **No generation constant appears in a `.cpp` file.** The distribution is a placeholder and will be replaced, so every derived artifact records the config hash it was produced under.
- RNG must be deterministic and reproducible: seeded PCG or splitmix64, one independent stream per worker thread derived from a root seed, never a shared global.

Add a cheap-candidate-scoring path: losing candidates in a best-of-625 do not need a full solve. Implement an early-exit scorer, verify it picks the same winner as full solving on a sample, then report the speedup.

### D4: Simulator CLI

`tools/simulate --config <file> --boards-per-cell N --threads T --out <dir>`

- Six cells: {4x4, 5x5} x {Spam, Good Casual, Casual}. Each parameterized independently, since Spam costs far more per board.
- Thread pool, per-thread partial aggregates merged at the end. **Never** accumulate per-board word lists in memory.
- Per-thread counters are dense arrays indexed by word ID, which is why D1 needs the numbered DAWG.
- Progress to stderr, results to disk, and a `manifest.json` recording config hash, git SHA, root seed, boards per cell, wall time and thread count. A run that cannot be reproduced from its manifest is a bug.

### D5: Measurements (the actual point of Phase 1)

Three numbers decide whether Phases 3 and 4 get built as written. Produce all three as a written report, not just files.

**M1 — Reachability.** For a stem S with a valid path on a board, and an additive affix A giving word W (W's path is S's path plus cells, S's own cells untouched and in order): what is `P(W has a valid path | S has a valid path)`, by affix and by stem length?

Build a bounded candidate stem set for this; a few thousand stems is plenty for a decision, do not try to be exhaustive. Report the implied number of extra words per game under the spec's assumption of about 100 swipes. **If that number is closer to 2 than to 10, say so loudly.** The family curriculum is built on this being large, and it is better to kill it now than in Phase 4.

**M2 — Cellmate pathability.** For a word W with a valid path and an anagram W' of W: `P(W' has a valid path | W has a valid path)`, by word length. Build a sorted-letter-key index over the dictionary to find anagram sets. Also report the drop-one relation. Expectation is high for 5s and falling off at 7+, but that is a guess and the point is to replace it.

**M3 — Stem enumerability.** For a stem S present on a board, `E[distinct members of S findable on that board]`, per tier. This decides which stems work as hunting cues (spec §7.5, target range 2 to 6). Report the distribution across stem lengths 2 to 7 so the cutoff is set from data rather than picked.

Also emit `board_norms`: distribution of total points, word count and 5+ word count per tier, which later phases use to classify tiers and sanity-check Par.

### D6: Tests and benchmarks

- **Differential test against a brute-force oracle.** On 3x3 and 4x4 boards with a small dictionary, enumerate paths exhaustively without the DAWG and compare word sets and path counts exactly. This is the most important test in the phase; LetterCounter may serve as a second oracle.
- Round-trip test: every word in the source list is found, nothing else is, word IDs are dense and stable across rebuilds of the same list.
- Solver invariants: no cell reused within a path, every reported path actually spells its word, adjacency is 8-way.
- Generator: tier point distributions ordered as expected (Spam > Good Casual > Casual), seeds appear at the specced rate, the same root seed reproduces byte-identical output.
- Benchmark harness reporting solve times by grid and tier, generation cost by tier, and simulator throughput scaling across thread counts. Include the scaling table in the final report.

## Constraints

- C++17. CMake. Single-header test framework or a hand-rolled harness; no heavyweight dependencies.
- **The core must later compile for iOS arm64 as a static library.** No `std::filesystem`, no platform APIs, no I/O inside `core/`. All file handling lives in `tools/`. Keep a clean `core/` boundary now so the bridge is a formality later.
- Expose a C shim header (`core/include/fluxcore.h`) with flat structs, even though nothing consumes it yet.
- No SIMD, no custom allocators, no assembly until a benchmark justifies it. Correct and measured first.

## How to work

- Use Explore to survey LetterCounter and report; do not let exploration output flood this conversation.
- Delegate the DAWG builder, the solver and the generator to separate subagents working against the tests, since they are largely independent. The simulator comes after all three land.
- Commit at each deliverable. Small commits, real messages.
- If something in `docs/SPEC.md` is ambiguous or wrong, stop and say so rather than guessing. The spec is a draft and several parameters in §2.4 are explicitly marked provisional.

## Report format

End with: the recon verdict on LetterCounter, a benchmark table, M1, M2 and M3 with their numbers and confidence, and a plain statement of which spec assumptions the data supports and which it does not.
