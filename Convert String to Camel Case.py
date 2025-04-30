'''
Description:
    Complete the method/function so that it converts dash/underscore delimited words into camel casing.
    The first word within the output should be capitalized only if the original word was capitalized (known as Upper Camel Case, also often referred to as Pascal case). 
    The next words should be always capitalized.

    Examples
    "the-stealth-warrior" gets converted to "theStealthWarrior"

    "The_Stealth_Warrior" gets converted to "TheStealthWarrior"

    "The_Stealth-Warrior" gets converted to "TheStealthWarrior"
'''

def to_camel_case(text: str) -> str:
    '''
    Converts a dash/underscore delimited string into camel case.

    Args:
        text (str): The input string containing words separated by dashes or underscores.

    Returns:
        str: The camel case version of the input string.
    '''
    import re  # Import the regular expressions module

    # Split the input string into a list of words using dashes or underscores as delimiters
    text_split_list = re.split(r'[-_]', text)

    # Initialize an empty string to store the camel case result
    capt_text = ''

    # Iterate through the list of words
    for _ in range(len(text_split_list)):
        if _ == 0:
            # For the first word, keep it as is (preserve original capitalization)
            capt_text += text_split_list[_]
        else:
            # For subsequent words, capitalize the first letter and append to the result
            capt_text += text_split_list[_].capitalize()

    # Return the final camel case string
    return capt_text
