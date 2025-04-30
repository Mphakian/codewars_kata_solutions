'''
This script implements the Polybius square cipher.

The Polybius square cipher replaces every letter with a two-digit number. 
The first digit represents the row number, and the second digit represents 
the column number in the cipher square. Letters 'I' and 'J' are treated 
as the same and are represented by "24".

Cipher Square:
    1	2	3	4	5
1	A	B	C	D	E
2	F	G	H	I/J	K
3	L	M	N	O	P
4	Q	R	S	T	U
5	V	W	X	Y	Z

Input:
- Only uppercase letters (A-Z) and spaces are valid. No input validation is required.

Examples:
"A" --> "11"
"IJ" --> "2424"
"CODEWARS" --> "1334141552114243"
"POLYBIUS SQUARE CIPHER" --> "3534315412244543 434145114215 132435231542"
'''

def polybius(text):
    '''
    Encrypts a given text using the Polybius square cipher.

    Args:
        text (str): The input text to be encrypted. It contains only uppercase 
                    letters (A-Z) and spaces.

    Returns:
        str: The encrypted text where each letter is replaced by its corresponding 
             two-digit number from the Polybius square.
    '''
    # Define the Polybius square cipher table
    decryption_tablet = [
        ['A', 'B', 'C', 'D', 'E'],
        ['F', 'G', 'H', 'I/J', 'K'],
        ['L', 'M', 'N', 'O', 'P'],
        ['Q', 'R', 'S', 'T', 'U'],
        ['V', 'W', 'X', 'Y', 'Z']
    ]
    
    # Initialize an empty string to store the encrypted code
    encrypted_code = ''
    
    # Iterate through each character in the input text
    for letter in text:
        # Handle the special case for 'I' and 'J'
        if letter.upper() == 'I' or letter.upper() == 'J':
            encrypted_code = encrypted_code + '24'
        # Preserve spaces in the input text
        elif letter == ' ':
            encrypted_code = encrypted_code + ' '
        # Search for the letter in the cipher table
        for col in range(len(decryption_tablet)):
            for row in range(len(decryption_tablet[col])):
                # If the letter matches, append its position as a two-digit number
                if letter.upper() == decryption_tablet[col][row]:
                    encrypted_code = encrypted_code + f'{col + 1}{row + 1}'
    return encrypted_code
