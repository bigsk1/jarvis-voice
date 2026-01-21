#!/usr/bin/env python3
"""
Generate secure random passwords with configurable length and character types.
"""
import sys
import os
import json
import random
import string

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config

def generate_password(length=16, uppercase=True, lowercase=True, numbers=True, symbols=True):
    """
    Generate a random password with specified character types.
    
    Args:
        length: Password length (8-128)
        uppercase: Include uppercase letters
        lowercase: Include lowercase letters
        numbers: Include numbers
        symbols: Include special symbols
    
    Returns:
        Generated password string
    """
    # Build character pool
    char_pool = ''
    
    if uppercase:
        char_pool += string.ascii_uppercase
    if lowercase:
        char_pool += string.ascii_lowercase
    if numbers:
        char_pool += string.digits
    if symbols:
        char_pool += '!@#$%^&*()_+-=[]{}|;:,.<>?'
    
    if not char_pool:
        raise ValueError("At least one character type must be enabled")
    
    # Generate password ensuring at least one character from each enabled type
    password_chars = []
    
    # Add at least one of each required type
    if uppercase:
        password_chars.append(random.choice(string.ascii_uppercase))
    if lowercase:
        password_chars.append(random.choice(string.ascii_lowercase))
    if numbers:
        password_chars.append(random.choice(string.digits))
    if symbols:
        password_chars.append(random.choice('!@#$%^&*()_+-=[]{}|;:,.<>?'))
    
    # Fill remaining length with random characters from pool
    remaining_length = length - len(password_chars)
    password_chars.extend(random.choices(char_pool, k=remaining_length))
    
    # Shuffle to avoid predictable patterns
    random.shuffle(password_chars)
    
    return ''.join(password_chars)

def assess_strength(password, length, has_upper, has_lower, has_numbers, has_symbols):
    """
    Assess password strength based on length and character diversity.
    
    Returns:
        Strength rating: 'weak', 'moderate', 'strong', 'very strong'
    """
    score = 0
    
    # Length scoring
    if length >= 16:
        score += 3
    elif length >= 12:
        score += 2
    elif length >= 10:
        score += 1
    
    # Diversity scoring
    types_used = sum([has_upper, has_lower, has_numbers, has_symbols])
    score += types_used
    
    # Rating
    if score >= 6:
        return 'very strong'
    elif score >= 4:
        return 'strong'
    elif score >= 2:
        return 'moderate'
    else:
        return 'weak'

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        # Extract parameters with defaults
        length = args.get('length', 16)
        uppercase = args.get('uppercase', True)
        lowercase = args.get('lowercase', True)
        numbers = args.get('numbers', True)
        symbols = args.get('symbols', True)
        count = args.get('count', 1)
        
        # Validate length
        if not isinstance(length, int) or length < 8 or length > 128:
            raise ValueError("Length must be between 8 and 128 characters")
        
        # Validate count
        if not isinstance(count, int) or count < 1 or count > 10:
            raise ValueError("Count must be between 1 and 10")
        
        # Generate password(s)
        passwords = []
        for _ in range(count):
            password = generate_password(length, uppercase, lowercase, numbers, symbols)
            strength = assess_strength(password, length, uppercase, lowercase, numbers, symbols)
            passwords.append({
                'password': password,
                'length': length,
                'strength': strength
            })
        
        # Build character types description
        types = []
        if uppercase:
            types.append('uppercase')
        if lowercase:
            types.append('lowercase')
        if numbers:
            types.append('numbers')
        if symbols:
            types.append('symbols')
        types_str = ', '.join(types)
        
        # Build response
        if count == 1:
            pwd_info = passwords[0]
            speech = f"Generated a {pwd_info['strength']} password with {length} characters using {types_str}. Password: {pwd_info['password']}"
        else:
            speech = f"Generated {count} passwords with {length} characters using {types_str}."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "passwords": passwords,
                "config": {
                    "length": length,
                    "uppercase": uppercase,
                    "lowercase": lowercase,
                    "numbers": numbers,
                    "symbols": symbols
                }
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to generate password: {e}"
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()