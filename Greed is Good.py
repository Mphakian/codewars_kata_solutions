'''
 Greed is a dice game played with five six-sided dice. Your mission, should you choose to accept it,
 is to score a throw according to these rules. You will always be given an array with five six-sided dice values.

    Three 1's => 1000 points
    Three 6's =>  600 points
    Three 5's =>  500 points
    Three 4's =>  400 points
    Three 3's =>  300 points
    Three 2's =>  200 points
    One   1   =>  100 points
    One   5   =>   50 point
    A single die can only be counted once in each roll. For example, a given "5" can only count as part of a triplet
    (contributing to the 500 points) or as a single 50 points, but not both in the same roll.

    Example scoring

    Throw       Score
    ---------   ------------------
    5 1 3 4 1   250:  50 (for the 5) + 2 * 100 (for the 1s)
    1 1 1 3 1   1100: 1000 (for three 1s) + 100 (for the other 1)
    2 4 4 5 4   450:  400 (for three 4s) + 50 (for the 5)
    Note: your solution must not modify the input list.
'''
from random import randint

def score():
    """
    Simulates a dice game scoring system based on the rules of the game "Greed".
    Rolls five dice and calculates the total score based on the following rules:
    - A roll of 1 is worth 100 points. Three 1s in a roll are worth 1000 points.
    - A roll of 5 is worth 50 points. Three 5s in a roll are worth 500 points.
    - Three 2s in a roll are worth 200 points.
    - Three 3s in a roll are worth 300 points.
    - Three 4s in a roll are worth 400 points.
    - Three 6s in a roll are worth 600 points.
    Returns:
        int: The total score calculated based on the rolled dice.
    """
    # Roll five dice with values between 1 and 6
    rolled = [randint(1, 6) for _ in range(5)]
    
    # Initialize counters for each dice value
    one, two, three, four, five, six = 0, 0, 0, 0, 0, 0
    
    # Initialize total score
    score = 0
    
    # Iterate through the rolled dice
    for _ in rolled: 
        if _ == 1:
            one += 100  # Increment counter for 1s
            score += 100  # Add 100 points for each 1
            if one == 300:  # Check if three 1s are rolled
                score += 1000 - 300  # Add bonus points for three 1s
                
        elif _ == 2: 
            two += 20  # Increment counter for 2s
        elif _ == 3: 
            three += 30  # Increment counter for 3s
        elif _ == 4: 
            four += 40  # Increment counter for 4s
                
        elif _ == 5:
            five += 50  # Increment counter for 5s
            score += 50  # Add 50 points for each 5
            if five == 150:  # Check if three 5s are rolled
                score += 500 - 250  # Add bonus points for three 5s
                
        elif _ == 6: 
            six += 60  # Increment counter for 6s
            
        # Check for three of a kind for 2s, 3s, 4s, and 6s
        if two == 60: 
            score += 200  # Add 200 points for three 2s
            two = 0  # Reset counter for 2s
        if three == 90: 
            score += 300  # Add 300 points for three 3s
            three = 0  # Reset counter for 3s
        if four == 120: 
            score += 400  # Add 400 points for three 4s
            four = 0  # Reset counter for 4s
        if six == 180:
            score += 600  # Add 600 points for three 6s
            six = 0  # Reset counter for 6s

    return score
