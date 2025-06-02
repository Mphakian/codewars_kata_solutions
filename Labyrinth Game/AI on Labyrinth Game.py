'''
Make AI for search path on labyrinth

Instructions:
Write class WormAI implementation for search exit of labyrinth. The labyrinth is a matrix, at the begining AI does not know dimension of matrix (map) and can not see all matrix data at one time (fog of war). 
AI can see only 3x3 near cell of hi's position. Before start "game" and on each step will be call function on_state(m,(x,y)) with view of near cell and current position. After them will be call do_move() to 
return move command - standart game key WASD for action move :)

Target of AI: find exit from labyrinth (symbol 'O') with minimal step, do not walk in wall ('#'). Given the limited visibility and map size, finding the shortest path is impossible. But AI should try it.
Do remember previous position for AI has been more effective. The limit of move to win in many test case will be up to 2*width*height step. In easy map the limit will be 1.5*width*height. On same big map 
limit may be x3.
'''


class WormAI:
    """
    AI agent for searching the exit in a labyrinth with fog of war.
    The agent only sees a 3x3 area around itself and must explore efficiently.
    """

    def __init__(self) -> None:
        # Stores the discovered map: (x, y) -> cell character (' ', '#', 'O', etc.)
        self.map = {}
        # Current position of the AI (x, y)
        self.position = None
        # Position of the exit if found (x, y)
        self.exit_pos = None
        # Queue of planned moves (as WASD chars)
        self.move_queue = []
        # Directions: WASD mapped to (dx, dy)
        self.directions = {
            'W': (0, -1),  # Up
            'S': (0, 1),   # Down
            'A': (-1, 0),  # Left
            'D': (1, 0)    # Right
        }
        # Set of cells that are fully explored (all neighbors known)
        self.explored = set()

    def on_state(self, m, position) -> None:
        """
        Called each turn with the current 3x3 view and position.
        Updates the internal map, marks explored cells, and plans moves.

        :param m: 3x3 list of lists, m[y][x], centered on current position
        :param position: (x, y) tuple of current position
        """
        self.position = position
        x, y = position

        # --- Update map with visible 3x3 cells ---
        for dy in range(-1, 2):  # dy: -1, 0, 1
            for dx in range(-1, 2):  # dx: -1, 0, 1
                # m[dy+1][dx+1] is the cell at (x+dx, y+dy)
                cell = m[dy+1][dx+1]
                nx, ny = x + dx, y + dy
                self.map[(nx, ny)] = cell  # Remember what we see
                if cell == 'O':
                    self.exit_pos = (nx, ny)  # Remember exit if seen

        # --- Mark cells as explored if all neighbors are known ---
        for (cx, cy), val in list(self.map.items()):
            if val == '#':
                continue  # Skip walls
            all_known = True
            # Check all 4 neighbors (up, down, left, right)
            for ddx, ddy in self.directions.values():
                adj = (cx + ddx, cy + ddy)
                # If any neighbor is unknown ('?'), this cell is not fully explored
                if self.map.get(adj, '?') == '?':
                    all_known = False
                    break
            if all_known:
                self.explored.add((cx, cy))  # Mark as explored

        # --- Only recalculate path if move_queue is empty ---
        if not self.move_queue:
            if self.exit_pos:
                # If exit is known, plan shortest path to exit
                self.move_queue = self._bfs(self.position, self.exit_pos)
            else:
                # Find all frontier cells (open, not explored, next to unknown)
                frontier = set()
                for (cx, cy), val in self.map.items():
                    # Only consider open, unexplored cells
                    if val != ' ' or (cx, cy) in self.explored:
                        continue
                    # If any neighbor is unknown, this is a frontier cell
                    for ddx, ddy in self.directions.values():
                        adj = (cx + ddx, cy + ddy)
                        if self.map.get(adj, '?') == '?':
                            frontier.add((cx, cy))
                            break
                if frontier:
                    # Go to nearest frontier cell (min path length)
                    paths = [self._bfs(self.position, f) for f in frontier]
                    paths = [p for p in paths if p]  # Remove empty paths
                    if paths:
                        self.move_queue = min(paths, key=len)  # Shortest path

    def _bfs(self, start, goal):
        """
        Breadth-first search for shortest path from start to goal.
        Returns a list of moves (WASD) to reach the goal.

        :param start: (x, y) tuple, starting position
        :param goal: (x, y) tuple, goal position
        :return: list of moves (WASD) to reach goal, or [] if unreachable
        """
        from collections import deque
        queue = deque()
        queue.append((start, []))  # Each item: ((x, y), path_so_far)
        seen = set()
        while queue:
            (cx, cy), path = queue.popleft()
            if (cx, cy) == goal:
                return path  # Found goal, return path
            for move, (dx, dy) in self.directions.items():
                nx, ny = cx + dx, cy + dy
                # Only consider non-wall and unseen cells
                if self.map.get((nx, ny), '#') != '#' and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    queue.append(((nx, ny), path + [move]))
        return []  # No path found

    def read_map(self, map : str) -> list:
        """
        Reads a map file and returns it as a list of strings (rows).
        :param map: filename
        :return: list of strings (rows)
        """
        with open(f'.\Labyrinth Game\{map}', encoding='utf-8') as f:
            content = f.read()
        return content.splitlines()
    
    def starting_pos(self, mapped_list : list) -> tuple:
        """
        Finds the starting position '0' in the map and returns its (x, y) coordinates.
        :param mapped_list: list of strings (rows)
        :return: (x, y) tuple or None if not found
        """
        for i in range(len(mapped_list)):
            for j in range(len(mapped_list[i])):
                if mapped_list[i][j] == '0':
                    return j, i  # (x, y)
        
    def do_move(self) -> str:
        """
        Returns the next move for the AI (WASD).
        If no moves are planned, defaults to 'W'.
        :return: single character (W/A/S/D)
        """
        if self.move_queue:
            return self.move_queue.pop(0)
        return 'W'
        
if __name__ == '__main__':
    import time

    ai = WormAI()
    map_name = 'map_1.txt'
    mapped_list = ai.read_map(map_name)
    start_pos = ai.starting_pos(mapped_list)
    if start_pos is None:
        raise ValueError("No starting position ('0') found in the map!")
    position = start_pos

    # Convert map to dict for display
    def map_to_dict(mapped_list):
        d = {}
        for y, row in enumerate(mapped_list):
            for x, cell in enumerate(row):
                d[(x, y)] = cell
        return d

    full_map = map_to_dict(mapped_list)

    # Find exit position
    exit_pos = None
    for pos, cell in full_map.items():
        if cell == 'O':
            exit_pos = pos
            break

    # Game loop
    steps = 0
    max_steps = 3 * len(mapped_list) * len(mapped_list[0])
    while steps < max_steps:
        # Build 3x3 view
        x, y = position
        m = []
        for dy in range(-1, 2):
            row = []
            for dx in range(-1, 2):
                cell = full_map.get((x + dx, y + dy), '#')
                row.append(cell)
            m.append(row)
        ai.on_state(m, position)
        move = ai.do_move()
        dx, dy = ai.directions.get(move, (0, 0))
        new_pos = (x + dx, y + dy)
        # Check for wall
        if full_map.get(new_pos, '#') == '#':
            print(f"Hit wall at {new_pos}, staying at {position}")
            # Optionally, you can break or let AI try another move
            break
        position = new_pos
        steps += 1

        # Print map with current position
        display = []
        for y2 in range(len(mapped_list)):
            row = ''
            for x2 in range(len(mapped_list[0])):
                if (x2, y2) == position:
                    row += 'A'
                else:
                    row += full_map[(x2, y2)]
            display.append(row)
        print('\n'.join(display))
        print(f"Step: {steps}, Move: {move}, Position: {position}\n")
        time.sleep(0.1)

        if position == exit_pos:
            print(f"Exit found in {steps} steps!")
            break
    else:
        print("Failed to find exit within step limit.")