"""Pure projections of optional video-provider metadata for caller surfaces."""

from copy import deepcopy


def video_metadata_without_heygen(tool: dict) -> dict:
    """Hide HeyGen-only guidance and formats without mutating shared metadata."""
    projected = deepcopy(tool)
    projected['description'] = projected.get('description', '').partition(' Optional HeyGen Video 1')[0]
    properties = projected.get('parameters', {}).get('properties', {})
    for field, marker in {
        'provider': ' Optional heygen uses HeyGen Video 1',
        'duration': ' HeyGen:',
        'aspect_ratio': ' HeyGen supports ',
        'resolution': ' HeyGen:',
    }.items():
        if isinstance(properties.get(field), dict):
            description = properties[field].get('description', '')
            properties[field]['description'] = description.partition(marker)[0]
    for field, hidden_values in {
        'provider': {'heygen'},
        'aspect_ratio': {'21:9'},
        'resolution': {'768p', '2k'},
    }.items():
        parameter = properties.get(field, {})
        if isinstance(parameter.get('enum'), list):
            parameter['enum'] = [value for value in parameter['enum'] if value not in hidden_values]
    availability = projected.get('availability', {})
    requirements = availability.get('provider_requirements', {})
    if isinstance(requirements, dict):
        requirements.pop('heygen', None)
    if isinstance(availability.get('setup_hint'), str):
        availability['setup_hint'] = availability['setup_hint'].replace(', or optional HEYGEN_API_KEY', '')
    return projected
