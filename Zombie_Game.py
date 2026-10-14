"""
Zombie Simulation with Decoupled Multi-Backend Storage
Demonstrating OOP Abstraction, Strategy Pattern, Composite Storage,
and Empirical Benchmark Comparison.
"""

from abc import ABC, abstractmethod
from collections import defaultdict
import json
import math
import os
import random
import time
import tkinter as tk
from concurrent.futures import ProcessPoolExecutor


# =====================================================================
# 1. STORAGE ABSTRACTION & CONCRETE IMPLEMENTATIONS (OOP Decoupling)
# =====================================================================

class StateStorage(ABC):
    """Abstract interface defining the contract for state persistence."""

    @abstractmethod
    def record_tick(self, tick: int, humans: int, zombies: int):
        """Record live population numbers for an individual tick."""
        pass

    @abstractmethod
    def finalize_run(self, metadata: dict):
        """Save final aggregate summary when the simulation finishes."""
        pass

    @abstractmethod
    def get_metrics(self) -> dict:
        """Return empirical performance metrics for this storage backend."""
        pass


class InMemoryStorage(StateStorage):
    """Storage Solution 1: Pure volatile RAM storage using Python lists."""

    def __init__(self):
        self.history = []
        self.final_summary = None
        self.write_durations_ns = []

    def record_tick(self, tick: int, humans: int, zombies: int):
        t0 = time.perf_counter_ns()
        self.history.append({"tick": tick, "humans": humans, "zombies": zombies})
        t1 = time.perf_counter_ns()
        self.write_durations_ns.append(t1 - t0)

    def finalize_run(self, metadata: dict):
        self.final_summary = metadata

    def get_metrics(self) -> dict:
        total_time_ms = sum(self.write_durations_ns) / 1_000_000
        avg_time_us = (
            (sum(self.write_durations_ns) / len(self.write_durations_ns)) / 1_000
            if self.write_durations_ns
            else 0.0
        )
        return {
            "name": "In-Memory (RAM)",
            "total_records": len(self.history),
            "total_write_time_ms": total_time_ms,
            "avg_write_latency_us": avg_time_us,
            "persistence": "Volatile (RAM)",
        }


class FileStorage(StateStorage):
    """Storage Solution 2: Disk-based persistence using a JSON log file."""

    def __init__(self, filename: str = "simulation_run.json"):
        self.filename = filename
        self.history = []
        self.write_durations_ns = []
        self.disk_flush_ms = 0.0

    def record_tick(self, tick: int, humans: int, zombies: int):
        t0 = time.perf_counter_ns()
        self.history.append({"tick": tick, "humans": humans, "zombies": zombies})
        t1 = time.perf_counter_ns()
        self.write_durations_ns.append(t1 - t0)

    def finalize_run(self, metadata: dict):
        t0 = time.perf_counter_ns()
        payload = {
            "metadata": metadata,
            "tick_records": self.history,
        }
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        t1 = time.perf_counter_ns()
        self.disk_flush_ms = (t1 - t0) / 1_000_000

    def get_metrics(self) -> dict:
        total_time_ms = (sum(self.write_durations_ns) / 1_000_000) + self.disk_flush_ms
        avg_time_us = (
            (sum(self.write_durations_ns) / len(self.write_durations_ns)) / 1_000
            if self.write_durations_ns
            else 0.0
        )
        return {
            "name": "File-Based (JSON Disk)",
            "total_records": len(self.history),
            "total_write_time_ms": total_time_ms,
            "avg_write_latency_us": avg_time_us,
            "persistence": f"Permanent ({self.filename})",
        }


class CompositeStorage(StateStorage):
    """Dispatches simulation state to multiple storage backends simultaneously."""

    def __init__(self, storages: list[StateStorage]):
        self.storages = storages

    def record_tick(self, tick: int, humans: int, zombies: int):
        for storage in self.storages:
            storage.record_tick(tick, humans, zombies)

    def finalize_run(self, metadata: dict):
        for storage in self.storages:
            storage.finalize_run(metadata)

    def get_metrics(self) -> list[dict]:
        return [s.get_metrics() for s in self.storages]


# =====================================================================
# 2. SPATIAL & MULTIPROCESSING UTILITIES
# =====================================================================

def _snapshot_grid(agents, cell_size):
    targets = [(agent.x, agent.y, agent.alive) for agent in agents]
    buckets = defaultdict(list)
    for index, (x, y, _) in enumerate(targets):
        buckets[(int(x // cell_size), int(y // cell_size))].append(index)
    return targets, dict(buckets)


def _nearest_targets(task):
    queries, targets, buckets, cell_size = task
    results = []

    for x, y, radius in queries:
        best_index = -1
        best_distance = radius

        min_cx = int((x - radius) // cell_size)
        max_cx = int((x + radius) // cell_size)
        min_cy = int((y - radius) // cell_size)
        max_cy = int((y + radius) // cell_size)

        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                for index in buckets.get((cx, cy), ()):
                    tx, ty, alive = targets[index]
                    if not alive:
                        continue
                    distance = math.hypot(x - tx, y - ty)
                    if distance < best_distance:
                        best_index = index
                        best_distance = distance
        results.append(best_index)
    return results


class SpatialGrid:
    def __init__(self, cell_size: float):
        self.cell_size = cell_size
        self.grid: dict[tuple[int, int], list["Agent"]] = defaultdict(list)

    def clear(self):
        self.grid.clear()

    def insert(self, agent: "Agent"):
        cx = int(agent.x // self.cell_size)
        cy = int(agent.y // self.cell_size)
        self.grid[(cx, cy)].append(agent)

    def query_radius(self, x: float, y: float, radius: float) -> list["Agent"]:
        min_cx = int((x - radius) // self.cell_size)
        max_cx = int((x + radius) // self.cell_size)
        min_cy = int((y - radius) // self.cell_size)
        max_cy = int((y + radius) // self.cell_size)

        candidates = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cell = self.grid.get((cx, cy))
                if cell:
                    candidates.extend(cell)
        return candidates


# =====================================================================
# 3. DOMAIN AGENTS
# =====================================================================

class Agent(ABC):
    def __init__(self, x: float, y: float, speed: float, max_health: float = 100.0):
        self.x = x
        self.y = y
        self.speed = speed
        self.health = max_health
        self.max_health = max_health
        self.alive = True

    def distance_to(self, other: "Agent") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def move_towards(self, target_x: float, target_y: float, arena_w: float, arena_h: float):
        dx = target_x - self.x
        dy = target_y - self.y
        dist = math.hypot(dx, dy)
        if dist > 0:
            self.x += (dx / dist) * self.speed
            self.y += (dy / dist) * self.speed
        self.clamp_position(arena_w, arena_h)

    def move_away_from(self, threat_x: float, threat_y: float, arena_w: float, arena_h: float):
        dx = self.x - threat_x
        dy = self.y - threat_y
        dist = math.hypot(dx, dy)
        if dist > 0:
            self.x += (dx / dist) * self.speed
            self.y += (dy / dist) * self.speed
        else:
            self.x += random.uniform(-1.0, 1.0) * self.speed
            self.y += random.uniform(-1.0, 1.0) * self.speed
        self.clamp_position(arena_w, arena_h)

    def clamp_position(self, arena_w: float, arena_h: float):
        self.x = max(0.0, min(self.x, arena_w))
        self.y = max(0.0, min(self.y, arena_h))

    def take_damage(self, amount: float):
        self.health -= amount
        if self.health <= 0:
            self.health = 0.0
            self.alive = False

    @abstractmethod
    def update(self, arena: "SimulationPlayground"):
        pass


class Human(Agent):
    def __init__(self, x: float, y: float, speed: float = 2.4):
        super().__init__(x=x, y=y, speed=speed)
        self.perception_radius = 25.0

    def get_nearest_zombie(self, arena: "SimulationPlayground"):
        if hasattr(self, "_parallel_target"):
            target = self._parallel_target
            if target is not None and target.alive:
                dist = self.distance_to(target)
                if dist < self.perception_radius:
                    return target, dist
            return None, self.perception_radius

        candidates = arena.zombie_grid.query_radius(self.x, self.y, self.perception_radius)
        nearest = None
        min_dist = self.perception_radius
        for zombie in candidates:
            if not zombie.alive:
                continue
            dist = self.distance_to(zombie)
            if dist < min_dist:
                min_dist = dist
                nearest = zombie
        return nearest, min_dist

    def update(self, arena: "SimulationPlayground"):
        if not self.alive:
            return

        nearest_zombie, _ = self.get_nearest_zombie(arena)
        if nearest_zombie:
            self.move_away_from(nearest_zombie.x, nearest_zombie.y, arena.width, arena.height)
        else:
            self.x += random.uniform(-1.0, 1.0) * (self.speed * 0.4)
            self.y += random.uniform(-1.0, 1.0) * (self.speed * 0.4)
            self.clamp_position(arena.width, arena.height)


class ArmedHuman(Human):
    def __init__(self, x: float, y: float, speed: float = 2.1):
        super().__init__(x=x, y=y, speed=speed)
        self.attack_range = 35.0
        self.shot_damage = 45.0
        self.cooldown_max = 6
        self.cooldown_timer = random.randint(0, self.cooldown_max)

    def update(self, arena: "SimulationPlayground"):
        if not self.alive:
            return

        if self.cooldown_timer > 0:
            self.cooldown_timer -= 1

        if hasattr(self, "_parallel_target"):
            nearest_zombie = self._parallel_target
            min_dist = (
                self.distance_to(nearest_zombie)
                if nearest_zombie and nearest_zombie.alive
                else self.attack_range
            )
            if min_dist >= self.attack_range:
                nearest_zombie = None
        else:
            candidates = arena.zombie_grid.query_radius(self.x, self.y, self.attack_range)
            nearest_zombie = None
            min_dist = self.attack_range
            for zombie in candidates:
                if not zombie.alive:
                    continue
                dist = self.distance_to(zombie)
                if dist < min_dist:
                    min_dist = dist
                    nearest_zombie = zombie

        if nearest_zombie and self.cooldown_timer == 0:
            nearest_zombie.take_damage(self.shot_damage)
            self.cooldown_timer = self.cooldown_max

        if nearest_zombie and min_dist <= self.perception_radius:
            self.move_away_from(nearest_zombie.x, nearest_zombie.y, arena.width, arena.height)
        else:
            self.x += random.uniform(-1.0, 1.0) * (self.speed * 0.4)
            self.y += random.uniform(-1.0, 1.0) * (self.speed * 0.4)
            self.clamp_position(arena.width, arena.height)


class Zombie(Agent):
    def __init__(self, x: float, y: float, speed: float = 2.1, bite_damage: float = 40.0):
        super().__init__(x=x, y=y, speed=speed, max_health=120.0)
        self.bite_range = 3.2
        self.bite_damage = bite_damage
        self.hunt_radius = 120.0

    def update(self, arena: "SimulationPlayground"):
        if not self.alive:
            return

        self.take_damage(0.05)
        if not self.alive:
            return

        if hasattr(self, "_parallel_target"):
            nearest_human = self._parallel_target
            min_dist = (
                self.distance_to(nearest_human)
                if nearest_human and nearest_human.alive
                else self.hunt_radius
            )
            if min_dist >= self.hunt_radius:
                nearest_human = None
        else:
            candidates = arena.human_grid.query_radius(self.x, self.y, self.hunt_radius)
            nearest_human = None
            min_dist = self.hunt_radius
            for human in candidates:
                if not human.alive:
                    continue
                dist = self.distance_to(human)
                if dist < min_dist:
                    min_dist = dist
                    nearest_human = human

        if nearest_human:
            self.move_towards(nearest_human.x, nearest_human.y, arena.width, arena.height)
            if min_dist <= self.bite_range:
                self.bite(nearest_human, arena)
        else:
            self.x += random.uniform(-1.0, 1.0) * self.speed
            self.y += random.uniform(-1.0, 1.0) * self.speed
            self.clamp_position(arena.width, arena.height)

    def bite(self, human: Human, arena: "SimulationPlayground"):
        human.take_damage(self.bite_damage)
        self.health = min(self.max_health, self.health + 18.0)
        if not human.alive:
            arena.convert_human_to_zombie(human)


# =====================================================================
# 4. SIMULATION PLAYGROUND (DECOUPLED LOGIC)
# =====================================================================

class SimulationPlayground:
    """Core simulation engine. Only communicates with StateStorage interface."""

    def __init__(
        self,
        width: float = 1200.0,
        height: float = 1200.0,
        use_multiprocessing: bool = True,
        workers: int = 4,
        storage: StateStorage = None,
    ):
        self.width = width
        self.height = height
        self.humans: list[Human] = []
        self.zombies: list[Zombie] = []
        self.new_zombies: list[Zombie] = []
        self.tick_count = 0

        self.initial_regular = 0
        self.initial_armed = 0
        self.initial_zombies = 0

        self.use_multiprocessing = use_multiprocessing
        self.workers = max(1, workers)
        self._executor = None

        self.human_grid = SpatialGrid(cell_size=80.0)
        self.zombie_grid = SpatialGrid(cell_size=80.0)

        # Injected decoupled storage abstraction
        self.storage = storage if storage is not None else InMemoryStorage()

    def populate(self, num_regular: int, num_armed: int, num_zombies: int):
        self.initial_regular = num_regular
        self.initial_armed = num_armed
        self.initial_zombies = num_zombies

        for _ in range(num_regular):
            self.humans.append(Human(x=random.uniform(0, self.width), y=random.uniform(0, self.height)))
        for _ in range(num_armed):
            self.humans.append(ArmedHuman(x=random.uniform(0, self.width), y=random.uniform(0, self.height)))
        for _ in range(num_zombies):
            self.zombies.append(Zombie(x=random.uniform(0, self.width), y=random.uniform(0, self.height)))

    def convert_human_to_zombie(self, human: Human):
        self.new_zombies.append(Zombie(x=human.x, y=human.y))

    def rebuild_spatial_grids(self):
        self.human_grid.clear()
        self.zombie_grid.clear()
        for h in self.humans:
            self.human_grid.insert(h)
        for z in self.zombies:
            self.zombie_grid.insert(z)

    def _parallel_target_search(self):
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self.workers)

        cell_size = self.human_grid.cell_size
        humans_snapshot, human_buckets = _snapshot_grid(self.humans, cell_size)
        zombies_snapshot, zombie_buckets = _snapshot_grid(self.zombies, cell_size)

        human_queries = [
            (h.x, h.y, h.attack_range if isinstance(h, ArmedHuman) else h.perception_radius)
            for h in self.humans
        ]
        zombie_queries = [(z.x, z.y, z.hunt_radius) for z in self.zombies]

        tasks = []
        assignments = []
        for agents, queries, targets, buckets in (
            (self.humans, human_queries, zombies_snapshot, zombie_buckets),
            (self.zombies, zombie_queries, humans_snapshot, human_buckets),
        ):
            chunk_size = max(128, (len(queries) + self.workers * 2 - 1) // (self.workers * 2))
            for start in range(0, len(queries), chunk_size):
                tasks.append((queries[start:start + chunk_size], targets, buckets, cell_size))
                assignments.append((agents, start, min(len(queries), start + chunk_size)))

        for (agents, start, end), indexes in zip(
            assignments, self._executor.map(_nearest_targets, tasks)
        ):
            target_agents = self.zombies if agents is self.humans else self.humans
            for agent, index in zip(agents[start:end], indexes):
                agent._parallel_target = target_agents[index] if index >= 0 else None

    def step(self):
        self.tick_count += 1
        self.new_zombies.clear()

        self.rebuild_spatial_grids()

        if self.use_multiprocessing and self.workers > 1:
            self._parallel_target_search()

        for human in self.humans:
            human.update(self)

        for zombie in self.zombies:
            zombie.update(self)

        for agent in (*self.humans, *self.zombies):
            if hasattr(agent, "_parallel_target"):
                del agent._parallel_target

        self.zombies.extend(self.new_zombies)
        self.humans = [h for h in self.humans if h.alive]
        self.zombies = [z for z in self.zombies if z.alive]

        # Record state exclusively through the abstract interface
        self.storage.record_tick(self.tick_count, len(self.humans), len(self.zombies))

    def finalize(self, outcome: str):
        metadata = {
            "initial_regular": self.initial_regular,
            "initial_armed": self.initial_armed,
            "initial_zombies": self.initial_zombies,
            "total_ticks": self.tick_count,
            "outcome": outcome,
        }
        self.storage.finalize_run(metadata)

    def close(self):
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None


# =====================================================================
# 5. USER INTERFACE (GUI)
# =====================================================================

class SimulationGUI:
    def __init__(self, root, sim: SimulationPlayground, scale: float = 0.52):
        self.root = root
        self.sim = sim
        self.scale = scale
        self.arena_px = int(sim.width * scale)
        self.graph_w = 360
        self.graph_h = self.arena_px

        self.root.title("Zombie Game Simulation - Decoupled Multi-Storage")
        self.root.configure(bg="#1E1E1E")

        self.status_label = tk.Label(
            root, text="", font=("Consolas", 11, "bold"), fg="#FFFFFF", bg="#1E1E1E", pady=6
        )
        self.status_label.pack()

        panes_frame = tk.Frame(root, bg="#1E1E1E")
        panes_frame.pack(padx=10, pady=5)

        self.arena_canvas = tk.Canvas(
            panes_frame, width=self.arena_px, height=self.arena_px, bg="#101010", highlightthickness=1
        )
        self.arena_canvas.grid(row=0, column=0, padx=6)

        self.graph_canvas = tk.Canvas(
            panes_frame, width=self.graph_w, height=self.graph_h, bg="#161616", highlightthickness=1
        )
        self.graph_canvas.grid(row=0, column=1, padx=6)

        self.human_history = [len(sim.humans)]
        self.zombie_history = [len(sim.zombies)]
        self.total_initial = len(sim.humans) + len(sim.zombies)

        self.running = True
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_loop()

    def on_close(self):
        self.running = False
        self.sim.finalize("MANUALLY_STOPPED")
        self.sim.close()
        self.root.destroy()

    def update_loop(self):
        if self.running:
            self.sim.step()
            self.human_history.append(len(self.sim.humans))
            self.zombie_history.append(len(self.sim.zombies))

            self.draw_arena()
            self.draw_graph()
            self.update_header()

            if not self.sim.humans or not self.sim.zombies:
                self.running = False
                outcome = "EXTINCTION (Zombies Won)" if not self.sim.humans else "CONTAINED (Humans Won)"
                self.sim.finalize(outcome)
                self.sim.close()

        self.root.after(20, self.update_loop)

    def draw_arena(self):
        self.arena_canvas.delete("all")
        s = self.scale

        for human in self.sim.humans:
            px = human.x * s
            py = human.y * s
            color = "#FFD700" if isinstance(human, ArmedHuman) else "#00D2FF"
            self.arena_canvas.create_rectangle(px, py, px + 2.0, py + 2.0, fill=color, outline="")

        for zombie in self.sim.zombies:
            px = zombie.x * s
            py = zombie.y * s
            self.arena_canvas.create_rectangle(px, py, px + 2.5, py + 2.5, fill="#44FF44", outline="")

    def draw_graph(self):
        self.graph_canvas.delete("all")
        margin = 35
        gw = self.graph_w - margin * 2
        gh = self.graph_h - margin * 2

        self.graph_canvas.create_line(margin, margin, margin, margin + gh, fill="#555555")
        self.graph_canvas.create_line(margin, margin + gh, margin + gw, margin + gh, fill="#555555")
        self.graph_canvas.create_text(
            margin + gw // 2, margin - 15, text="Live Population Dynamics", fill="#FFFFFF", font=("Consolas", 10, "bold")
        )

        pts = len(self.human_history)
        if pts < 2:
            return

        max_pop = max(self.total_initial, max(self.human_history), max(self.zombie_history))
        dx = gw / max(pts - 1, 30)

        human_coords, zombie_coords = [], []
        step_stride = max(1, pts // 250)
        for i in range(0, pts, step_stride):
            px = margin + i * dx
            hy = (margin + gh) - (self.human_history[i] / max_pop) * gh
            zy = (margin + gh) - (self.zombie_history[i] / max_pop) * gh
            human_coords.extend([px, hy])
            zombie_coords.extend([px, zy])

        if len(human_coords) >= 4:
            self.graph_canvas.create_line(*human_coords, fill="#00D2FF", width=2)
            self.graph_canvas.create_line(*zombie_coords, fill="#44FF44", width=2)

    def update_header(self):
        unarmed = sum(1 for h in self.sim.humans if not isinstance(h, ArmedHuman))
        armed = sum(1 for h in self.sim.humans if isinstance(h, ArmedHuman))
        zombies = len(self.sim.zombies)

        status = f"Step: {self.sim.tick_count:03d} | Civilians: {unarmed} | Armed: {armed} | Zombies: {zombies} | Total: {unarmed+armed+zombies}"
        if not self.sim.humans:
            status += "  [EXTINCTION: Zombies Win!]"
        elif not self.sim.zombies:
            status += "  [CONTAINED: Humans Win!]"

        self.status_label.config(text=status)


# =====================================================================
# 6. EXECUTION & SIDE-BY-SIDE BENCHMARK REPORT
# =====================================================================

if __name__ == "__main__":
    # Instantiate two distinct storage solutions
    ram_store = InMemoryStorage()
    json_store = FileStorage(filename="sim_dual_output.json")

    # Combine both behind the abstract StateStorage interface
    dual_storage = CompositeStorage([ram_store, json_store])

    # Inject the storage abstraction into the simulation
    playground = SimulationPlayground(
        width=1200.0,
        height=1200.0,
        use_multiprocessing=True,
        workers=4,
        storage=dual_storage,
    )
    playground.populate(num_regular=7500, num_armed=500, num_zombies=2000)

    print("[SETUP] Running simulation with dual storage (RAM + JSON) simultaneously...")
    app = tk.Tk()
    gui = SimulationGUI(app, playground, scale=0.52)
    app.mainloop()

    # =====================================================================
    # POST-RUN VERIFICATION & COMPARISON REPORT
    # =====================================================================
    print("\n" + "=" * 80)
    print("        STORAGE EFFICACY & EFFICIENCY BENCHMARK REPORT")
    print("=" * 80)

    metrics = dual_storage.get_metrics()
    ram_m = metrics[0]
    file_m = metrics[1]

    print(f"{'Metric':<28} | {'In-Memory (RAM)':<22} | {'File-Based (JSON Disk)':<22}")
    print("-" * 80)
    print(f"{'Persistence Model':<28} | {ram_m['persistence']:<22} | {file_m['persistence']:<22}")
    print(f"{'Total Snapshots Saved':<28} | {ram_m['total_records']:<22} | {file_m['total_records']:<22}")
    print(f"{'Average Write Latency':<28} | {ram_m['avg_write_latency_us']:.3f} us                | {file_m['avg_write_latency_us']:.3f} us")
    print(f"{'Total I/O Overhead':<28} | {ram_m['total_write_time_ms']:.3f} ms               | {file_m['total_write_time_ms']:.3f} ms")
    print("-" * 80)

    # Verification: Did both engines record the exact same simulation trajectory?
    data_match = ram_store.history == json_store.history
    print(f"Decoupling Verification: State records identical across backends? -> {data_match}")
    print("=" * 80 + "\n")