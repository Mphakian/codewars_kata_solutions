'''
This module provides a function to perform basic mathematical operations.

The function `basic_op` takes three arguments:
1. `operator` (string/char): The mathematical operation to perform ('+', '-', '*', '/').
2. `value1` (number): The first operand.
3. `value2` (number): The second operand.

It returns the result of applying the specified operation to the two operands.

Examples:
('+', 4, 7) --> 11
('-', 15, 18) --> -3
('*', 5, 5) --> 25
('/', 49, 7) --> 7
'''

def basic_op(operator: str, value1: int, value2: int) -> int:
    '''
    Perform a basic mathematical operation on two numbers.

    Args:
        operator (str): The operation to perform. Supported operators are:
                        '+' for addition,
                        '-' for subtraction,
                        '*' for multiplication,
                        '/' for division.
        value1 (int): The first operand.
        value2 (int): The second operand.

    Returns:
        int or float: The result of the operation. If division by zero occurs, returns None.

    Raises:
        None: Division by zero is handled internally and returns None.
    '''
    # Perform the operation based on the operator
    if operator == '+': 
        return value1 + value2  # Perform addition
    elif operator == '-': 
        return value1 - value2  # Perform subtraction
    elif operator == '*': 
        return value1 * value2  # Perform multiplication
    elif operator == '/': 
        # Handle division and catch division by zero errors
        try:
            return value1 / value2  # Perform division
        except ZeroDivisionError:
            return None  # Return None if division by zero occurs
    else:
        # Handle unsupported operators
        raise ValueError(f"Unsupported operator: {operator}. Supported operators are '+', '-', '*', '/'.")

