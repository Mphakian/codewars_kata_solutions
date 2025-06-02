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
    def __init__(self) -> None:
        self.visited = set()
        self.map = {}  # {(x, y): cell}
        self.position = None
        self.exit_pos = None
        self.move_queue = []
        self.directions = {
            'W': (0, -1),  # Up
            'S': (0, 1),   # Down
            'A': (-1, 0),  # Left
            'D': (1, 0)    # Right
        }
        self.reverse_dir = {v: k for k, v in self.directions.items()}

    def on_state(self, m, position) -> None:  # m[y][x], position=(x,y)
        self.position = position
        x, y = position
        # Update map with visible 3x3 cells
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cell = m[dy+1][dx+1]
                nx, ny = x + dx, y + dy
                self.map[(nx, ny)] = cell
                if cell == 'O':
                    self.exit_pos = (nx, ny)
        self.visited.add(position)
        # If exit is found, plan path to it
        if self.exit_pos:
            self.move_queue = self._bfs(self.position, self.exit_pos)
        else:
            # Explore nearest unknown cell
            unknown = [pos for pos, val in self._adjacent_cells(x, y) if val == '?']
            if unknown:
                self.move_queue = self._bfs(self.position, unknown[0])
            else:
                # Explore any unvisited open cell
                open_cells = [pos for pos, val in self.map.items() if val not in ['#'] and pos not in self.visited]
                if open_cells:
                    self.move_queue = self._bfs(self.position, open_cells[0])

    def _adjacent_cells(self, x, y):
        for move, (dx, dy) in self.directions.items():
            nx, ny = x + dx, y + dy
            yield (nx, ny), self.map.get((nx, ny), '?')

    def _bfs(self, start, goal):
        from collections import deque
        queue = deque()
        queue.append((start, []))
        seen = set()
        while queue:
            (cx, cy), path = queue.popleft()
            if isinstance(goal, list) or isinstance(goal, tuple):
                if (cx, cy) == goal or (isinstance(goal, list) and (cx, cy) in goal):
                    return path
            else:
                if (cx, cy) == goal:
                    return path
            for move, (dx, dy) in self.directions.items():
                nx, ny = cx + dx, cy + dy
                if self.map.get((nx, ny), '#') != '#' and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    queue.append(((nx, ny), path + [move]))
        return []

    def read_map(self, map : str) -> list:
        with open(f'.\Labyrinth Game\{map}', encoding='utf-8') as f:
            content = f.read()
        return content.splitlines()
    
    def starting_pos(self, mapped_list : list) -> tuple:
        for i in range(len(mapped_list)):
            for j in range(len(mapped_list[i])):
                if mapped_list[i][j] == '0':
                    return j, i  # (x, y)
        
    def do_move(self) -> str:  # return single character of WASD or 8426
        if self.move_queue:
            return self.move_queue.pop(0)
        # Default: try to move up if nothing else
        return 'W'
        
if __name__ == '__main__':
    import time

    ai = WormAI()
    map_name = 'map_1.txt'
    mapped_list = ai.read_map(map_name)
    start_pos = ai.starting_pos(mapped_list)
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