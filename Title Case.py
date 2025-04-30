'''
This module contains a function `title_case` that converts a string into title case.

A string is considered to be in title case if each word in the string is either:
(a) capitalized (only the first letter of the word is in uppercase), or
(b) considered an exception (minor word) and put entirely in lowercase unless it is the first word.

The function takes two arguments:
1. `title` (str): The original string to be converted.
2. `minor_words` (str, optional): A space-delimited list of minor words that must always be lowercase 
   except for the first word in the string. If not provided, all words are treated as non-minor.

Returns:
    str: The title-cased string.
'''

def title_case(title: str, minor_words='') -> str:
    # Split the title and minor words into lists of words
    title = title.split(' ')
    minor_words = minor_words.split(' ')
    capt_text = ''  # Initialize the result string
    
    # Convert all minor words to lowercase for case-insensitive comparison
    minor_words_lower = [item.lower() for item in minor_words]
    
    # Iterate through each word in the title
    for _ in range(len(title)):
        if _ == 0:
            # Always capitalize the first word
            capt_text += title[_].capitalize() + ' '
        elif title[_].lower() not in minor_words_lower:
            # Capitalize the word if it's not a minor word
            if _ == len(title):
                capt_text += title[_].capitalize()
            else:
                capt_text += title[_].capitalize() + ' '
        else:
            # Keep the word in lowercase if it's a minor word
            if _ == len(title):
                capt_text += title[_].lower()
            else:
                capt_text += title[_].lower() + ' '
    
    return capt_text.strip()

