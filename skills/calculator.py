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
import ast
import operator
from typing import Any

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
        'mcg': 0.000001, 'microgram': 0.000001, 'micrograms': 0.000001,
        'ug': 0.000001, 'μg': 0.000001,
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
        'cc': 0.001,
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


def find_unit_type(unit: str) -> tuple[str, float] | None:
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


def convert_units(value: float, from_unit: str, to_unit: str) -> tuple[float, str]:
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


def parse_percentage(expr: str) -> tuple[float, str, float] | None:
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


def parse_conversion(expr: str) -> tuple[float, str, str] | None:
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


def parse_statistics(expr: str) -> tuple[str, list] | None:
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


def normalize_medical_expression(expr: str) -> str:
    """Normalize common dosage notation for parsing."""
    normalized = expr.lower()
    normalized = normalized.replace('μ', 'u').replace('µ', 'u')
    normalized = normalized.replace("iu's", 'iu').replace("ius", 'iu')
    normalized = normalized.replace('milliliters', 'ml').replace('millilitres', 'ml')
    normalized = normalized.replace('milliliter', 'ml').replace('millilitre', 'ml')
    normalized = normalized.replace('bacteriostatic water', 'bac water')
    normalized = normalized.replace('bacteriostatic', 'bac')
    normalized = normalized.replace('micrograms', 'mcg').replace('microgram', 'mcg')
    normalized = normalized.replace('milligrams', 'mg').replace('milligram', 'mg')
    normalized = normalized.replace('units', 'iu').replace('unit', 'iu')
    return normalized


def mass_to_mcg(value: float, unit: str) -> float:
    """Convert supported mass units to micrograms."""
    unit = unit.lower()
    factors = {
        'mcg': 1,
        'ug': 1,
        'g': 1_000_000,
        'mg': 1_000,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported mass unit: {unit}")
    return value * factors[unit]


def volume_to_ml(value: float, unit: str) -> float:
    """Convert supported volume units to mL."""
    unit = unit.lower()
    factors = {
        'ml': 1,
        'cc': 1,
        'l': 1000,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported volume unit: {unit}")
    return value * factors[unit]


def format_measurement(value: float, unit: str) -> str:
    """Format numeric output with a sensible number of decimals."""
    if value == int(value):
        return f"{int(value):,} {unit}"
    return f"{value:,.4f}".rstrip('0').rstrip('.') + f" {unit}"


def measurement_match_dict(match: re.Match[str], unit_group: int = 2, default_unit: str | None = None) -> dict[str, Any]:
    """Convert a regex match to a structured measurement record."""
    unit = default_unit if default_unit is not None else match.group(unit_group).lower()
    return {
        'value': float(match.group(1)),
        'unit': unit,
        'start': match.start(),
        'end': match.end(),
    }


def measurement_context(text: str, measurement: dict[str, Any], radius: int = 28) -> str:
    """Get nearby text around a parsed measurement."""
    start = max(0, measurement['start'] - radius)
    end = min(len(text), measurement['end'] + radius)
    return text[start:end]


def measurement_has_keywords(
    text: str,
    measurement: dict[str, Any],
    keywords: tuple[str, ...],
) -> bool:
    """Check whether a parsed measurement appears near cue words."""
    context = measurement_context(text, measurement)
    return any(keyword in context for keyword in keywords)


def extract_measurements(normalized: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract mass, volume, and IU measurements from text."""
    mass_matches = [
        measurement_match_dict(match)
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(mg|mcg|ug|g)\b', normalized)
    ]
    volume_matches = [
        measurement_match_dict(match)
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(ml|cc|l)\b', normalized)
    ]
    iu_matches = [
        measurement_match_dict(match, default_unit='iu')
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*iu\b', normalized)
    ]
    return mass_matches, volume_matches, iu_matches


def build_missing_input_result(
    total_mass_mcg: float,
    target_dose_mcg: float | None,
    missing: list[str],
) -> dict[str, Any]:
    """Return a structured response for under-specified dosage questions."""
    result: dict[str, Any] = {
        'type': 'dosage',
        'operation': 'missing_input',
        'total_peptide_mcg': total_mass_mcg,
        'missing': missing,
        'assumptions': [
            "IU means U-100 insulin syringe units",
            "100 IU = 1 mL",
        ],
    }
    if target_dose_mcg is not None:
        result['target_dose_mcg'] = target_dose_mcg
    return result


def parse_peptide_reconstitution(expr: str) -> dict[str, Any] | None:
    """
    Parse common peptide reconstitution questions.

    Examples:
    - "10mg peptide + 2ml bac water, 2iu is how many mcg"
    - "If I mix 5mg with 2ml, how many IU for 250mcg?"
    - "Concentration of 10mg in 2ml"
    """
    normalized = normalize_medical_expression(expr)

    if not any(term in normalized for term in ('peptide', 'bac water', 'bacteriostatic', 'reconstit', 'syringe', 'mcg', 'mg', 'iu')):
        return None

    mass_matches, volume_matches, iu_matches = extract_measurements(normalized)

    wants_bac_water = any(phrase in normalized for phrase in (
        'how much bac water',
        'how much water',
        'how much diluent',
        'how much liquid',
        'how much should i add',
        'what volume should i add',
        'how much to add',
        'how many ml should i add',
        'reconstit with',
    ))
    wants_dose_count = any(phrase in normalized for phrase in (
        'how many doses',
        'how many shots',
        'how many injections',
        'how many servings',
    ))
    wants_concentration = any(phrase in normalized for phrase in (
        'what concentration',
        'concentration',
        'mg/ml',
        'mcg/ml',
        'mcg per ml',
        'mg per ml',
    ))
    wants_iu = any(phrase in normalized for phrase in (
        'how many iu',
        'what iu',
        'what units',
        'how many units',
        'what line',
        'what mark',
        'how much should i pull',
        'how much do i pull',
        'how much should i draw',
        'how much do i draw',
        'pull for',
        'draw for',
    ))
    wants_mcg = any(phrase in normalized for phrase in (
        'how much mcg',
        'how many mcg',
        'what dose',
        'per dose',
        'per shot',
        'per injection',
    ))

    if not mass_matches:
        missing = ['total peptide amount (for example 10 mg)']
        if wants_bac_water and not iu_matches and not volume_matches:
            missing.append('desired shot size in IU or mL')
        return build_missing_input_result(0, None, missing)

    if len(mass_matches) == 1:
        only_mass = mass_matches[0]
        looks_like_target_dose = measurement_has_keywords(
            normalized,
            only_mass,
            ('dose', 'shot', 'each', 'target', 'want', 'per'),
        )
        looks_like_total_amount = measurement_has_keywords(
            normalized,
            only_mass,
            ('have', 'contains', 'vial', 'peptide', 'bottle'),
        )
        if looks_like_target_dose and not looks_like_total_amount:
            missing = ['total peptide amount (for example 10 mg)']
            if wants_bac_water and not iu_matches and not volume_matches:
                missing.append('desired shot size in IU or mL')
            return build_missing_input_result(
                0,
                mass_to_mcg(only_mass['value'], only_mass['unit']),
                missing,
            )

    total_mass = mass_to_mcg(mass_matches[0]['value'], mass_matches[0]['unit'])
    target_dose_mcg = None
    if len(mass_matches) >= 2:
        target_candidate = mass_matches[-1]
        target_dose_mcg = mass_to_mcg(target_candidate['value'], target_candidate['unit'])

    total_volume_ml = None
    if volume_matches:
        total_volume_ml = volume_to_ml(volume_matches[0]['value'], volume_matches[0]['unit'])

    pulled_iu = None
    if iu_matches:
        pulled_iu = iu_matches[-1]['value']

    pulled_volume_ml = None
    if len(volume_matches) >= 2:
        draw_volume_matches = [
            volume for volume in volume_matches[1:]
            if measurement_has_keywords(
                normalized,
                volume,
                ('pull', 'draw', 'dose', 'shot', 'each', 'per'),
            )
        ]
        selected_volume = draw_volume_matches[0] if draw_volume_matches else volume_matches[-1]
        pulled_volume_ml = volume_to_ml(selected_volume['value'], selected_volume['unit'])

    result: dict[str, Any] = {
        'type': 'dosage',
        'total_peptide_mcg': total_mass,
        'assumptions': [
            "IU means U-100 insulin syringe units",
            "100 IU = 1 mL",
        ],
    }
    if target_dose_mcg is not None:
        result['target_dose_mcg'] = target_dose_mcg
    if total_volume_ml is not None:
        result['total_volume_ml'] = total_volume_ml
    if pulled_iu is not None:
        result['pulled_iu'] = pulled_iu
    if pulled_volume_ml is not None:
        result['dose_volume_ml'] = pulled_volume_ml

    if wants_bac_water:
        if target_dose_mcg is None:
            return build_missing_input_result(
                total_mass,
                None,
                ['desired dose amount (for example 300 mcg per shot)'],
            )

        desired_dose_volume_ml = None
        if pulled_iu is not None:
            desired_dose_volume_ml = pulled_iu / 100
        elif pulled_volume_ml is not None:
            desired_dose_volume_ml = pulled_volume_ml

        if desired_dose_volume_ml is None:
            return build_missing_input_result(
                total_mass,
                target_dose_mcg,
                ['desired shot size in IU or mL'],
            )

        if desired_dose_volume_ml == 0:
            raise ValueError("Shot size cannot be zero")

        desired_concentration_mcg_per_ml = target_dose_mcg / desired_dose_volume_ml
        required_total_volume_ml = total_mass / desired_concentration_mcg_per_ml
        result.update({
            'operation': 'diluent_volume_for_target_dose',
            'dose_volume_ml': desired_dose_volume_ml,
            'concentration_mcg_per_ml': desired_concentration_mcg_per_ml,
            'required_total_volume_ml': required_total_volume_ml,
        })
        if pulled_iu is None:
            result['required_iu'] = desired_dose_volume_ml * 100
        return result

    if wants_dose_count and target_dose_mcg is not None:
        if target_dose_mcg == 0:
            raise ValueError("Target dose cannot be zero")
        result.update({
            'operation': 'dose_count',
            'dose_count': total_mass / target_dose_mcg,
        })
        return result

    if total_volume_ml is None and (wants_iu or wants_mcg or wants_concentration):
        return build_missing_input_result(
            total_mass,
            target_dose_mcg,
            ['total mixed volume in mL (for example 2 mL of bac water)'],
        )

    concentration_mcg_per_ml = None
    if total_volume_ml is not None:
        if total_volume_ml == 0:
            raise ValueError("Diluent volume cannot be zero")
        concentration_mcg_per_ml = total_mass / total_volume_ml
        result['concentration_mcg_per_ml'] = concentration_mcg_per_ml

    # Direct dose question: "2 IU is how many mcg?"
    if concentration_mcg_per_ml is not None and pulled_iu is not None and wants_mcg:
        dose_volume_ml = pulled_iu / 100
        dose_mcg = concentration_mcg_per_ml * dose_volume_ml

        result.update({
            'operation': 'dose_from_iu',
            'dose_volume_ml': dose_volume_ml,
            'dose_mcg': dose_mcg,
        })
        return result

    if concentration_mcg_per_ml is not None and pulled_volume_ml is not None and wants_mcg:
        dose_mcg = concentration_mcg_per_ml * pulled_volume_ml
        result.update({
            'operation': 'dose_from_volume',
            'required_iu': pulled_volume_ml * 100,
            'dose_mcg': dose_mcg,
        })
        return result

    # Inverse question: "how many IU for 250 mcg?" / "how much do I draw for 250 mcg?"
    if concentration_mcg_per_ml is not None and target_dose_mcg is not None and wants_iu:
        dose_volume_ml = target_dose_mcg / concentration_mcg_per_ml
        required_iu = dose_volume_ml * 100

        result.update({
            'operation': 'iu_from_target_dose',
            'dose_volume_ml': dose_volume_ml,
            'required_iu': required_iu,
        })
        return result

    if concentration_mcg_per_ml is not None and target_dose_mcg is not None and 'how much ml' in normalized:
        dose_volume_ml = target_dose_mcg / concentration_mcg_per_ml
        result.update({
            'operation': 'volume_from_target_dose',
            'dose_volume_ml': dose_volume_ml,
            'required_iu': dose_volume_ml * 100,
        })
        return result

    if concentration_mcg_per_ml is not None and target_dose_mcg is not None and any(
        phrase in normalized for phrase in ('what dose is', 'is how much mcg', 'equals how much mcg')
    ) and pulled_iu is not None:
        dose_volume_ml = pulled_iu / 100
        result.update({
            'operation': 'dose_from_iu',
            'dose_volume_ml': dose_volume_ml,
            'dose_mcg': concentration_mcg_per_ml * dose_volume_ml,
        })
        return result

    # Fallback: just return concentration math.
    result['operation'] = 'concentration'
    return result


class _SafeExprEvaluator(ast.NodeVisitor):
    """
    AST-based math expression evaluator.
    
    Only allows: numbers, arithmetic operators, unary +/-, function calls
    to whitelisted SAFE_MATH_FUNCS, and list/tuple literals (for stats functions).
    
    This replaces eval() to eliminate code injection risk entirely — arbitrary
    Python code (imports, attribute access, comprehensions, etc.) is rejected
    at the AST level before any execution occurs.
    """
    
    # Allowed binary operators
    _ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    
    # Allowed unary operators
    _unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    
    # Allowed comparison operators (for chained expressions like 2 < 3)
    _cmp_ops = {
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
    }
    
    def __init__(self, funcs: dict):
        self._funcs = funcs
    
    def evaluate(self, expr: str) -> float:
        """Parse and evaluate a math expression string."""
        try:
            tree = ast.parse(expr, mode='eval')
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {e}")
        return float(self.visit(tree.body))
    
    def visit_Expression(self, node):
        return self.visit(node.body)
    
    def visit_Constant(self, node):
        """Allow numeric and boolean constants only."""
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    
    # Python 3.7 compat (ast.Num deprecated but may appear)
    def visit_Num(self, node):
        return node.n
    
    def visit_BinOp(self, node):
        """Handle binary operations: +, -, *, /, //, %, **"""
        op_func = self._ops.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        # Guard against exponent bombs (e.g. 10**10**10)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and right > 1000:
            raise ValueError(f"Exponent too large: {right}")
        return op_func(left, right)
    
    def visit_UnaryOp(self, node):
        """Handle unary +/-"""
        op_func = self._unary_ops.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(self.visit(node.operand))
    
    def visit_Call(self, node):
        """Handle function calls — only whitelisted functions."""
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls allowed (no method calls)")
        
        func_name = node.func.id
        func = self._funcs.get(func_name)
        if func is None:
            raise ValueError(f"Unknown function: {func_name}")
        if callable(func):
            args = [self.visit(arg) for arg in node.args]
            return func(*args)
        else:
            # It's a constant (like pi, e, tau) — shouldn't be called
            raise ValueError(f"'{func_name}' is a constant, not a function")
    
    def visit_Name(self, node):
        """Handle named constants (pi, e, tau, inf)."""
        value = self._funcs.get(node.id)
        if value is None:
            raise ValueError(f"Unknown variable: {node.id}")
        if callable(value):
            # Functions referenced without calling — return the function
            # This handles cases like statistics where it might be used differently
            return value
        return value
    
    def visit_List(self, node):
        """Allow list literals for stats functions like mean([1,2,3])."""
        return [self.visit(elt) for elt in node.elts]
    
    def visit_Tuple(self, node):
        """Allow tuple literals."""
        return tuple(self.visit(elt) for elt in node.elts)
    
    def visit_Compare(self, node):
        """Handle comparisons (e.g. 2 < 3)."""
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_func = self._cmp_ops.get(type(op))
            if op_func is None:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            right = self.visit(comparator)
            if not op_func(left, right):
                return 0.0
            left = right
        return 1.0
    
    def generic_visit(self, node):
        """Reject any AST node type not explicitly handled."""
        raise ValueError(
            f"Unsupported expression element: {type(node).__name__}. "
            f"Only arithmetic, function calls, and constants are allowed."
        )


# Singleton evaluator instance
_evaluator = _SafeExprEvaluator(SAFE_MATH_FUNCS)


def safe_eval(expr: str) -> float:
    """
    Safely evaluate a mathematical expression using AST parsing.
    
    SECURITY: Uses ast.parse + NodeVisitor instead of eval().
    Only allows numbers, arithmetic operators (+, -, *, /, //, %, **),
    unary +/-, whitelisted function calls, and list/tuple literals.
    Rejects any other Python construct (imports, attribute access,
    comprehensions, lambdas, string operations, etc.).
    """
    # Normalize expression
    expr = expr.replace('^', '**')  # Support ^ for exponents
    expr = expr.replace('×', '*').replace('÷', '/')
    expr = expr.replace('²', '**2').replace('³', '**3')
    expr = expr.replace('√', 'sqrt')
    
    try:
        result = _evaluator.evaluate(expr)
        return float(result)
    except Exception as e:
        raise ValueError(f"Cannot evaluate expression: {e}")


def calculate(expression: str, calc_type: str = 'auto') -> dict[str, Any]:
    """Main calculation function."""
    expr = expression.strip()
    result_data = {
        'expression': expr,
        'type': calc_type,
    }
    
    # Try peptide/dosage math first so natural-language medical mixing questions
    # don't fall through to generic expression parsing.
    if calc_type in ('auto', 'dosage'):
        dosage_result = parse_peptide_reconstitution(expr)
        if dosage_result:
            result_data.update(dosage_result)

            operation = dosage_result['operation']
            concentration_mcg_per_ml = dosage_result.get('concentration_mcg_per_ml')
            concentration_mg_per_ml = None
            if concentration_mcg_per_ml is not None:
                concentration_mg_per_ml = concentration_mcg_per_ml / 1000

            if operation == 'missing_input':
                missing_fields = ', '.join(dosage_result['missing'])
                speech = (
                    f"I need one more detail to solve that: {missing_fields}. "
                    f"For bac water math, I need the total peptide amount plus your target dose and how many IU or mL you want each shot to be."
                )
            elif operation == 'dose_from_iu':
                speech = (
                    f"Assuming a U-100 insulin syringe, "
                    f"{format_measurement(dosage_result['pulled_iu'], 'IU')} from "
                    f"{format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')} mixed with "
                    f"{format_measurement(dosage_result['total_volume_ml'], 'mL')} is "
                    f"{format_measurement(dosage_result['dose_mcg'], 'mcg')} per dose."
                )
            elif operation == 'dose_from_volume':
                speech = (
                    f"{format_measurement(dosage_result['dose_volume_ml'], 'mL')} from "
                    f"{format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')} mixed with "
                    f"{format_measurement(dosage_result['total_volume_ml'], 'mL')} is "
                    f"{format_measurement(dosage_result['dose_mcg'], 'mcg')} per dose, "
                    f"which is {format_measurement(dosage_result['required_iu'], 'IU')} on a U-100 insulin syringe."
                )
            elif operation == 'iu_from_target_dose':
                speech = (
                    f"Assuming a U-100 insulin syringe, "
                    f"{format_measurement(dosage_result['target_dose_mcg'], 'mcg')} from "
                    f"{format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')} mixed with "
                    f"{format_measurement(dosage_result['total_volume_ml'], 'mL')} is "
                    f"{format_measurement(dosage_result['required_iu'], 'IU')} "
                    f"which is {format_measurement(dosage_result['dose_volume_ml'], 'mL')}."
                )
            elif operation == 'volume_from_target_dose':
                speech = (
                    f"{format_measurement(dosage_result['target_dose_mcg'], 'mcg')} from "
                    f"{format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')} mixed with "
                    f"{format_measurement(dosage_result['total_volume_ml'], 'mL')} is "
                    f"{format_measurement(dosage_result['dose_volume_ml'], 'mL')} "
                    f"or {format_measurement(dosage_result['required_iu'], 'IU')} on a U-100 insulin syringe."
                )
            elif operation == 'diluent_volume_for_target_dose':
                shot_size_text = format_measurement(dosage_result['dose_volume_ml'], 'mL')
                if dosage_result.get('pulled_iu') is not None:
                    shot_size_text += f" ({format_measurement(dosage_result['pulled_iu'], 'IU')})"
                elif dosage_result.get('required_iu') is not None:
                    shot_size_text += f" ({format_measurement(dosage_result['required_iu'], 'IU')})"

                speech = (
                    f"To make each shot {format_measurement(dosage_result['target_dose_mcg'], 'mcg')} at "
                    f"{shot_size_text}, add {format_measurement(dosage_result['required_total_volume_ml'], 'mL')} "
                    f"of bac water to {format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')}."
                )
            elif operation == 'dose_count':
                speech = (
                    f"{format_measurement(dosage_result['total_peptide_mcg'] / 1000, 'mg')} contains "
                    f"{dosage_result['dose_count']:,.2f} doses of "
                    f"{format_measurement(dosage_result['target_dose_mcg'], 'mcg')}."
                )
            else:
                speech = (
                    f"That mix is {format_measurement(concentration_mg_per_ml, 'mg/mL')} "
                    f"which is {format_measurement(concentration_mcg_per_ml, 'mcg/mL')}."
                )

            return {'ok': True, 'speech': speech, 'data': result_data}

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
