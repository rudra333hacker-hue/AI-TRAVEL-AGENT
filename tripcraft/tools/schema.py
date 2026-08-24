import inspect
import re
from typing import get_type_hints, Callable, Any, Union, List, Dict

def generate_tool_schema(func: Callable, name_override: str = None) -> dict:
    """
    Dynamically generates an OpenAI-compatible function tool definition schema
    from a Python function's signature, type hints, and docstring.
    """
    sig = inspect.signature(func)
    doc = func.__doc__ or ""
    
    # ── Parse Docstring ──
    # Extract overall function description
    doc_lines = [line.strip() for line in doc.split("\n")]
    description_parts = []
    param_descriptions = {}
    
    in_args_section = False
    
    # Regex to extract parameter description
    # Matches: "param_name: description" or "param_name (type): description" or ":param param_name: description"
    param_re = re.compile(r'^(?::param\s+|-\s*|\b)(?P<name>\w+)\b(?:\s*\([^)]+\))?\s*:\s*(?P<desc>.+)', re.IGNORECASE)
    
    for line in doc_lines:
        if not line:
            continue
        
        # Check if we hit an arguments section header
        if line.lower().startswith(("args:", "parameters:", "params:")):
            in_args_section = True
            continue
        
        # Try to parse as parameter description
        match = param_re.match(line)
        if match:
            p_name = match.group("name")
            p_desc = match.group("desc").strip()
            param_descriptions[p_name] = p_desc
        elif not in_args_section and not line.startswith(":"):
            description_parts.append(line)
            
    function_description = " ".join(description_parts).strip() or (name_override or func.__name__).replace("_", " ").title()

    # ── Parse Parameters ──
    try:
        type_hints = get_type_hints(func)
    except Exception:
        type_hints = {}
        
    properties = {}
    required = []
    
    for p_name, param in sig.parameters.items():
        # Skip self or cls if method
        if p_name in ("self", "cls"):
            continue
            
        p_type = type_hints.get(p_name, param.annotation)
        
        # Resolve Optional / Union types (e.g. Union[str, None] -> str)
        if hasattr(p_type, "__origin__") and p_type.__origin__ is Union:
            args = [arg for arg in p_type.__args__ if arg is not type(None)]
            if args:
                p_type = args[0]
        
        # Map python types to JSON schema types
        schema_type = "string"
        if p_type == int:
            schema_type = "integer"
        elif p_type == float:
            schema_type = "number"
        elif p_type == bool:
            schema_type = "boolean"
        elif p_type in (list, List) or str(p_type).startswith("typing.List"):
            schema_type = "array"
        elif p_type in (dict, Dict) or str(p_type).startswith("typing.Dict"):
            schema_type = "object"
            
        param_schema = {
            "type": schema_type,
            "description": param_descriptions.get(p_name, f"The {p_name} parameter.")
        }
        
        # Handle default values
        if param.default is not inspect.Parameter.empty:
            param_schema["default"] = param.default
        else:
            required.append(p_name)
            
        properties[p_name] = param_schema

    return {
        "type": "function",
        "function": {
            "name": name_override or func.__name__,
            "description": function_description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    }
