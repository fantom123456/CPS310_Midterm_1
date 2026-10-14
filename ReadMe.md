Zombie Game Simulation: Decoupled State Storage Architecture

1. Problem Statement & Objectives

In agent-based crowd simulations, managing the live state of agents, the environment, and runtime metrics is a critical architectural challenge. The objective of this project is to decouple the core simulation logic from the state storage medium so that:

The simulation logic remains completely agnostic of the underlying storage backend.

The storage solution can be altered, upgraded, or swapped without changing any code in the simulation engine.

At least two distinct state storage solutions are implemented and empirically compared.

2. Object-Oriented Design & Decoupling Strategy

The Decoupling Mechanism

To decouple simulation execution from persistence, I introduced an abstract base class, StateStorage, which acts as an explicit contract:

record_tick(tick, humans, zombies): Called once per step to persist or buffer frame counts.

finalize_run(metadata): Called once upon simulation exit to persist terminal metrics.

get_metrics(): Exposes empirical timing and write overhead diagnostics.

Why This Design Effectively Decouples the Layers

Dependency Inversion: SimulationPlayground does not import file handling modules, SQL drivers, or external I/O packages. It only requires an object conforming to StateStorage passed into its constructor (Dependency Injection).

Zero Modification to Simulation Code: Changing the storage destination (RAM list, JSON file, or an external database) requires changing only the storage instance passed to SimulationPlayground during instantiation. The methods driving agent kinematics, spatial partitioning, and tick stepping remain untouched.

Information Hiding: The simulation engine has no visibility into how data is serialized or buffered. It simply emits the latest population counts.

3. Storage Implementations Covered

Solution 1: In-Memory Storage (InMemoryStorage)

Mechanism: Stores tick records inside a Python list residing in system RAM.

Advantages: Near-zero write latency; causes no I/O blocking during the simulation loop.

Trade-offs: Volatile; all stored data is cleared from memory when the process terminates.

Solution 2: File-Based Storage (FileStorage)

Mechanism: Buffers tick states in memory and serializes the complete history to a disk-based JSON file (sim_dual_output.json) upon run finalization.

Advantages: Permanent, human-readable record that persists after process termination for post-run auditing.

Trade-offs: Incurs serialization overhead and operating system disk write latency upon finalization.

Simultaneous Execution (CompositeStorage)

To demonstrate and compare both storage mediums under identical execution conditions, I implemented CompositeStorage. This class also adheres to StateStorage and broadcasts every record_tick and finalize_run call to both InMemoryStorage and FileStorage concurrently.

4. Empirical Evaluation & Benchmark Results

The simulation was run with both backends operating simultaneously for however many ticks the simulation ran for. At run termination, high-resolution timers (time.perf_counter_ns) produced the following benchmark report:

================================================================================
        STORAGE EFFICACY & EFFICIENCY BENCHMARK REPORT
================================================================================
Metric                       | In-Memory (RAM)        | File-Based (JSON Disk)
--------------------------------------------------------------------------------
Persistence Model            | Volatile (RAM)         | Permanent (sim_dual_output.json)
Total Snapshots Saved        | 960                    | 960
Average Write Latency        | 1.120 us               | 0.293 us
Total I/O Overhead           | 1.075 ms               | 4.247 ms
--------------------------------------------------------------------------------
Decoupling Verification: State records identical across backends? -> True
================================================================================


Analysis

Efficacy of Decoupling: The integrity verification reported True, confirming that all 960 tick records matched identically across both storage engines without requiring separate simulation runs or data converters.

Efficiency Trade-offs: While in-loop memory appending is trivial for both solutions, writing the full history to disk at finalization increased the total I/O overhead of FileStorage to 4.247 ms (~4x that of InMemoryStorage). This quantifies the architectural trade-off between transient execution speed and persistent disk durability.

5. How to Run

Requirements

Python 3.10 or higher.

tkinter (included with standard Windows and macOS Python distributions).

Execution

Run the standalone simulation script:

python Zombie_Game.py


Close the GUI window or let the population reach extinction/containment to conclude the run.

The terminal will display the side-by-side benchmark report, and sim_dual_output.json will be generated in the root directory.