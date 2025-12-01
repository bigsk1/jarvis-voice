#!/usr/bin/env python3
"""
Advanced Calculator Tool
Supports: arithmetic, algebra, statistics, trigonometry, unit conversion, percentages, financial math

Input: { "expression": "sqrt(144) + 5^2", "type": "auto" }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json
import math
import statistics
import re
from typing import Dict, Any, Optional, Tuple

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

# Safe math functions available in expressions
SAFE_MATH_FUNCS = {
    # Basic
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sum': sum,
    'len': len,
    
    # Math module
    'sqrt': math.sqrt,
    'cbrt': lambda x: x ** (1/3),
    'pow': pow,
    'exp': math.exp,
    'log': math.log,
    'log10': math.log10,
    'log2': math.log2,
    'ln': math.log,
    
    # Trigonometry (radians)
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'asin': math.asin,
    'acos': math.acos,
    'atan': math.atan,
    'atan2': math.atan2,
    'sinh': math.sinh,
    'cosh': math.cosh,
    'tanh': math.tanh,
    
    # Trigonometry (degrees)
    'sind': lambda x: math.sin(math.radians(x)),
    'cosd': lambda x: math.cos(math.radians(x)),
    'tand': lambda x: math.tan(math.radians(x)),
    
    # Rounding
    'floor': math.floor,
    'ceil': math.ceil,
    'trunc': math.trunc,
    
    # Special
    'factorial': math.factorial,
    'gcd': math.gcd,
    'lcm': math.lcm,
    'degrees': math.degrees,
    'radians': math.radians,
    
    # Constants
    'pi': math.pi,
    'e': math.e,
    'tau': math.tau,
    'inf': math.inf,
    
    # Statistics
    'mean': statistics.mean,
    'median': statistics.median,
    'mode': statistics.mode,
    'stdev': statistics.stdev,
    'variance': statistics.variance,
    'pstdev': statistics.pstdev,
    'pvariance': statistics.pvariance,
    'harmonic_mean': statistics.harmonic_mean,
    'geometric_mean': statistics.geometric_mean,
}

# Unit conversion factors (to base unit)
UNIT_CONVERSIONS = {
    # Length (base: meters)
    'length': {
        'm': 1, 'meter': 1, 'meters': 1,
        'km': 1000, 'kilometer': 1000, 'kilometers': 1000,
        'cm': 0.01, 'centimeter': 0.01, 'centimeters': 0.01,
        'mm': 0.001, 'millimeter': 0.001, 'millimeters': 0.001,
        'mi': 1609.344, 'mile': 1609.344, 'miles': 1609.344,
        'yd': 0.9144, 'yard': 0.9144, 'yards': 0.9144,
        'ft': 0.3048, 'foot': 0.3048, 'feet': 0.3048,
        'in': 0.0254, 'inch': 0.0254, 'inches': 0.0254,
        'nm': 1852, 'nautical_mile': 1852,
    },
    # Weight (base: grams)
    'weight': {
        'g': 1, 'gram': 1, 'grams': 1,
        'kg': 1000, 'kilogram': 1000, 'kilograms': 1000,
        'mg': 0.001, 'milligram': 0.001, 'milligrams': 0.001,
        'lb': 453.592, 'pound': 453.592, 'pounds': 453.592,
        'oz': 28.3495, 'ounce': 28.3495, 'ounces': 28.3495,
        'ton': 907185, 'tons': 907185,
        'tonne': 1000000, 'metric_ton': 1000000,
        'st': 6350.29, 'stone': 6350.29,
    },
    # Volume (base: liters)
    'volume': {
        'l': 1, 'liter': 1, 'liters': 1, 'litre': 1, 'litres': 1,
        'ml': 0.001, 'milliliter': 0.001, 'milliliters': 0.001,
        'gal': 3.78541, 'gallon': 3.78541, 'gallons': 3.78541,
        'qt': 0.946353, 'quart': 0.946353, 'quarts': 0.946353,
        'pt': 0.473176, 'pint': 0.473176, 'pints': 0.473176,
        'cup': 0.236588, 'cups': 0.236588,
        'floz': 0.0295735, 'fl_oz': 0.0295735, 'fluid_ounce': 0.0295735,
        'tbsp': 0.0147868, 'tablespoon': 0.0147868, 'tablespoons': 0.0147868,
        'tsp': 0.00492892, 'teaspoon': 0.00492892, 'teaspoons': 0.00492892,
    },
    # Temperature (special handling)
    'temperature': {
        'c': 'celsius', 'celsius': 'celsius',
        'f': 'fahrenheit', 'fahrenheit': 'fahrenheit',
        'k': 'kelvin', 'kelvin': 'kelvin',
    },
    # Data (base: bytes)
    'data': {
        'b': 1, 'byte': 1, 'bytes': 1,
        'kb': 1024, 'kilobyte': 1024, 'kilobytes': 1024,
        'mb': 1024**2, 'megabyte': 1024**2, 'megabytes': 1024**2,
        'gb': 1024**3, 'gigabyte': 1024**3, 'gigabytes': 1024**3,
        'tb': 1024**4, 'terabyte': 1024**4, 'terabytes': 1024**4,
        'pb': 1024**5, 'petabyte': 1024**5, 'petabytes': 1024**5,
    },
    # Time (base: seconds)
    'time': {
        's': 1, 'sec': 1, 'second': 1, 'seconds': 1,
        'ms': 0.001, 'millisecond': 0.001, 'milliseconds': 0.001,
        'min': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'wk': 604800, 'week': 604800, 'weeks': 604800,
        'mo': 2592000, 'month': 2592000, 'months': 2592000,  # 30 days
        'yr': 31536000, 'year': 31536000, 'years': 31536000,  # 365 days
    },
}


def find_unit_type(unit: str) -> Optional[Tuple[str, float]]:
    """Find which category a unit belongs to and its conversion factor."""
    unit_lower = unit.lower().strip()
    for category, units in UNIT_CONVERSIONS.items():
        if unit_lower in units:
            return (category, units[unit_lower])
    return None


def convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between temperature units."""
    # First convert to Celsius
    if from_unit == 'fahrenheit':
        celsius = (value - 32) * 5/9
    elif from_unit == 'kelvin':
        celsius = value - 273.15
    else:
        celsius = value
    
    # Then convert to target
    if to_unit == 'fahrenheit':
        return celsius * 9/5 + 32
    elif to_unit == 'kelvin':
        return celsius + 273.15
    else:
        return celsius


def convert_units(value: float, from_unit: str, to_unit: str) -> Tuple[float, str]:
    """Convert between units. Returns (result, explanation)."""
    from_info = find_unit_type(from_unit)
    to_info = find_unit_type(to_unit)
    
    if not from_info or not to_info:
        raise ValueError(f"Unknown unit: {from_unit if not from_info else to_unit}")
    
    from_cat, from_factor = from_info
    to_cat, to_factor = to_info
    
    if from_cat != to_cat:
        raise ValueError(f"Cannot convert between {from_cat} and {to_cat}")
    
    # Special handling for temperature
    if from_cat == 'temperature':
        result = convert_temperature(value, from_factor, to_factor)
    else:
        # Convert to base unit, then to target
        base_value = value * from_factor
        result = base_value / to_factor
    
    return result, from_cat


def parse_percentage(expr: str) -> Optional[Tuple[float, str, float]]:
    """Parse percentage expressions like '15% of 200' or 'what percent is 30 of 200'."""
    # "X% of Y"
    match = re.match(r'(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)', expr, re.IGNORECASE)
    if match:
        pct, total = float(match.group(1)), float(match.group(2))
        result = (pct / 100) * total
        return (result, 'percent_of', pct)
    
    # "what percent is X of Y" or "X is what percent of Y"
    match = re.match(r'(?:what\s+percent(?:age)?\s+is\s+)?(\d+(?:\.\d+)?)\s+(?:of|out\s+of)\s+(\d+(?:\.\d+)?)', expr, re.IGNORECASE)
    if match:
        part, whole = float(match.group(1)), float(match.group(2))
        if whole == 0:
            raise ValueError("Cannot calculate percentage of zero")
        result = (part / whole) * 100
        return (result, 'what_percent', part)
    
    return None


def parse_conversion(expr: str) -> Optional[Tuple[float, str, str]]:
    """Parse unit conversion expressions like '5 miles to km' or 'convert 100 f to c'."""
    patterns = [
        r'(?:convert\s+)?(\d+(?:\.\d+)?)\s*([a-zA-Z_]+)\s+(?:to|in|as)\s+([a-zA-Z_]+)',
        r'(\d+(?:\.\d+)?)\s*([a-zA-Z_]+)\s*=\s*\?\s*([a-zA-Z_]+)',
        r'how\s+many\s+([a-zA-Z_]+)\s+(?:is|are|in)\s+(\d+(?:\.\d+)?)\s*([a-zA-Z_]+)',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, expr, re.IGNORECASE)
        if match:
            groups = match.groups()
            if 'how many' in pattern.lower():
                # "how many X in Y Z" -> convert Y Z to X
                return (float(groups[1]), groups[2], groups[0])
            return (float(groups[0]), groups[1], groups[2])
    
    return None


def parse_statistics(expr: str) -> Optional[Tuple[str, list]]:
    """Parse statistics expressions like 'mean of 1,2,3,4,5' or 'stdev [1,2,3,4,5]'."""
    # Extract function name and numbers
    match = re.match(r'(mean|median|mode|stdev|variance|pstdev|pvariance|harmonic_mean|geometric_mean|average|avg)\s*(?:of\s*)?\[?([\d\s,.-]+)\]?', expr, re.IGNORECASE)
    if match:
        func_name = match.group(1).lower()
        if func_name in ('average', 'avg'):
            func_name = 'mean'
        
        numbers_str = match.group(2)
        numbers = [float(n.strip()) for n in re.split(r'[,\s]+', numbers_str) if n.strip()]
        
        if len(numbers) < 2:
            raise ValueError("Need at least 2 numbers for statistics")
        
        return (func_name, numbers)
    
    return None


def safe_eval(expr: str) -> float:
    """Safely evaluate a mathematical expression."""
    # Normalize expression
    expr = expr.replace('^', '**')  # Support ^ for exponents
    expr = expr.replace('×', '*').replace('÷', '/')
    expr = expr.replace('²', '**2').replace('³', '**3')
    expr = expr.replace('√', 'sqrt')
    
    # Create safe namespace
    namespace = {'__builtins__': {}}
    namespace.update(SAFE_MATH_FUNCS)
    
    try:
        result = eval(expr, namespace)
        return float(result)
    except Exception as e:
        raise ValueError(f"Cannot evaluate expression: {e}")


def calculate(expression: str, calc_type: str = 'auto') -> Dict[str, Any]:
    """Main calculation function."""
    expr = expression.strip()
    result_data = {
        'expression': expr,
        'type': calc_type,
    }
    
    # Try percentage parsing
    if calc_type in ('auto', 'percentage'):
        pct_result = parse_percentage(expr)
        if pct_result:
            value, pct_type, pct_val = pct_result
            result_data['result'] = value
            result_data['type'] = 'percentage'
            
            if pct_type == 'percent_of':
                speech = f"{pct_val}% of that is {value:,.4g}"
            else:
                speech = f"That's {value:,.2f}%"
            
            return {'ok': True, 'speech': speech, 'data': result_data}
    
    # Try unit conversion
    if calc_type in ('auto', 'conversion'):
        conv_result = parse_conversion(expr)
        if conv_result:
            value, from_unit, to_unit = conv_result
            converted, category = convert_units(value, from_unit, to_unit)
            
            result_data['result'] = converted
            result_data['type'] = 'conversion'
            result_data['category'] = category
            result_data['from_unit'] = from_unit
            result_data['to_unit'] = to_unit
            
            # Format nicely
            if converted == int(converted):
                speech = f"{value:,.4g} {from_unit} is {int(converted):,} {to_unit}"
            else:
                speech = f"{value:,.4g} {from_unit} is {converted:,.4g} {to_unit}"
            
            return {'ok': True, 'speech': speech, 'data': result_data}
    
    # Try statistics
    if calc_type in ('auto', 'statistics'):
        stat_result = parse_statistics(expr)
        if stat_result:
            func_name, numbers = stat_result
            func = SAFE_MATH_FUNCS[func_name]
            value = func(numbers)
            
            result_data['result'] = value
            result_data['type'] = 'statistics'
            result_data['function'] = func_name
            result_data['numbers'] = numbers
            result_data['count'] = len(numbers)
            
            speech = f"The {func_name} is {value:,.4g}"
            return {'ok': True, 'speech': speech, 'data': result_data}
    
    # Default: evaluate as math expression
    result = safe_eval(expr)
    result_data['result'] = result
    result_data['type'] = 'expression'
    
    # Nice speech output
    if result == int(result) and abs(result) < 1e15:
        speech = f"The answer is {int(result):,}"
    elif abs(result) < 0.0001 or abs(result) > 1e10:
        speech = f"The answer is {result:.6e}"
    else:
        speech = f"The answer is {result:,.6g}"
    
    return {'ok': True, 'speech': speech, 'data': result_data}


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        expression = args.get('expression')
        if not expression:
            raise ValueError("expression parameter is required")
        
        calc_type = args.get('type', 'auto')
        
        result = calculate(expression, calc_type)
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Calculation error: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

