"""Normalize the native Lua JSON encoder's one-based numeric object arrays.

RPC bridge replies already have arrays. Direct native JSON files can instead
contain {"1":...,"2":...}; noncontiguous numeric maps must remain dictionaries.
"""


def normalize_arrays(value):
    if isinstance(value,list):
        return [normalize_arrays(v)for v in value]
    if isinstance(value,dict):
        if value and set(value)=={str(i)for i in range(1,len(value)+1)}:
            return [normalize_arrays(value[str(i)])for i in range(1,len(value)+1)]
        return {k:normalize_arrays(v)for k,v in value.items()}
    return value
