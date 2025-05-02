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

#To do
#AI should be placed at the correct starting point ('0') -------------Done
#able to detct walls
#able to see 3x3 near cells ('#')
#should be able to move up, down, left, and right -------------------Next Task
#Must remember last positions
#limit of moves to win is 2*width*height 
#should be able to recognize empty cells
#should be able to detect if it had won (when on cell with symbol 'I')


class WormAI:
    def __init__(self, game_map : str) -> None:
        self.game_map = game_map
        self.hist_pos = []

    def on_state(self, m, position) -> None: # m[y][x], position=(x,y)
        ...
        
    def read_map(self) -> list:
        with open(f'.\Labyrinth Game\{self.game_map}', encoding='utf-8') as f:
            content = f.read()
        return content.splitlines()                                                    #The contents (strings) in the mappped_list are not be replaced.... If I remember well
    
    def starting_pos(self, mapped_list : list) -> tuple:
        for i in range(len(mapped_list)):
            for j in range(len(mapped_list[i])):
                if mapped_list[i][j] == '0':
                    return i,j
        
    def do_move(self, move : str | int) -> tuple: #return single character of WASD or 8426
        current_pos = self.starting_pos(self.read_map())
        self.hist_pos.append(current_pos)
        #REMINDER: current_pos = (height, width) of the map
        #For W/8 -> 0 must be moved 1 postion up (1 height up)
            #Must check if it does not bump into walls..........this part will be solved when I implement the 3x3 scanned map
            #Maybe check if it the next current_pos is == 'I' which would mean it has solved the map
        if move == 'W' or move == 8 or move == 'w':
            #The desired output is current_pos = (height -1, width)
            current_pos = (current_pos[0] - 1, current_pos[1])
            self.hist_pos.append(current_pos)

            #Redraw the map
            

        #For S/2 -> 0 must be moved 1 postion down (1 height down)
        #For A/4 -> 0 must be moved 1 postion left (1 height left)
        #For D/6 -> 0 must be moved 1 postion right (1 height right)

        return current_pos
        
if __name__ == '__main__':

    test : WormAI = WormAI('map_1.txt')

    


