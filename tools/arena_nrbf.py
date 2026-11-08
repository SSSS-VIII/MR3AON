"""Read the NRBF data subset used by offline level files, without executing types.

This is a structural reader, never a .NET BinaryFormatter deserializer. Unknown
records and primitives fail closed. References remain explicit in the raw graph.
"""
from __future__ import annotations

import io
import struct


class NrbfReader:
    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)
        self.objects = {}
        self.classes = {}
        self.root_id = None
        self.limit = len(data)

    def read(self, size):
        if size < 0 or size > self.limit:
            raise ValueError("Invalid NRBF length")
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError("Truncated NRBF stream")
        return data

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.read(struct.calcsize('<' + fmt)))[0]

    def string(self):
        length = 0
        for shift in range(0, 35, 7):
            byte = self.unpack('B')
            length |= (byte & 127) << shift
            if not byte & 128:
                return self.read(length).decode('utf-8')
        raise ValueError("Invalid NRBF string length")

    def count(self):
        count = self.unpack('i')
        if not 0 <= count <= self.limit:
            raise ValueError("Invalid NRBF count")
        return count

    def primitive(self, kind):
        formats = {1: '?', 2: 'B', 6: 'd', 7: 'h', 8: 'i', 9: 'q',
                   10: 'b', 11: 'f', 12: 'q', 13: 'Q', 14: 'H', 15: 'I', 16: 'Q'}
        if kind in formats:
            return self.unpack(formats[kind])
        if kind == 18:
            return self.string()
        raise ValueError(f"Unsupported NRBF primitive {kind}")

    def type_info(self, kinds):
        result = []
        for kind in kinds:
            if kind in (0, 7):
                extra = self.unpack('B')
            elif kind == 3:
                extra = self.string()
            elif kind == 4:
                extra = (self.string(), self.unpack('i'))
            elif kind in (1, 2, 5, 6):
                extra = None
            else:
                raise ValueError(f"Unsupported NRBF member type {kind}")
            result.append((kind, extra))
        return result

    def value(self, info):
        return self.primitive(info[1]) if info[0] == 0 else self.record()

    def members(self, object_id, schema):
        name, names, infos = schema
        obj = {'$type': name}
        self.objects[object_id] = obj
        for field, info in zip(names, infos):
            obj[field] = self.value(info)
        return {'$ref': object_id}

    def array(self, object_id, count, info):
        if count > self.limit:
            raise ValueError("NRBF array too large")
        values = []
        self.objects[object_id] = values
        while len(values) < count:
            item = self.value(info)
            if isinstance(item, dict) and '$nulls' in item:
                remaining = item['$nulls']
                if remaining <= 0 or len(values) + remaining > count:
                    raise ValueError("Invalid NRBF null run")
                values.extend([None] * remaining)
            else:
                values.append(item)
        return {'$ref': object_id}

    def record(self):
        kind = self.unpack('B')
        if kind == 0:
            self.root_id = self.unpack('i')
            self.read(12)
            return None
        if kind == 12:
            self.unpack('i')
            self.string()
            return self.record()  # Library declarations may precede a member.
        if kind == 1:
            object_id, metadata_id = self.unpack('i'), self.unpack('i')
            return self.members(object_id, self.classes[metadata_id])
        if kind in (2, 3, 4, 5):
            object_id, name, count = self.unpack('i'), self.string(), self.count()
            names = [self.string() for _ in range(count)]
            infos = self.type_info([self.unpack('B') for _ in range(count)]) if kind in (4, 5) else [(2, None)] * count
            if kind in (3, 5):
                self.unpack('i')
            schema = (name, names, infos)
            self.classes[object_id] = schema
            return self.members(object_id, schema)
        if kind == 6:
            object_id = self.unpack('i')
            self.objects[object_id] = self.string()
            return {'$ref': object_id}
        if kind == 7:
            object_id, array_kind, rank = self.unpack('i'), self.unpack('B'), self.count()
            if rank != 1 or array_kind not in (0, 1, 3, 4):
                raise ValueError("Only one-dimensional NRBF arrays are supported")
            count = self.count()
            if array_kind in (3, 4) and self.unpack('i') != 0:
                raise ValueError("Nonzero array lower bound")
            info = self.type_info([self.unpack('B')])[0]
            return self.array(object_id, count, info)
        if kind == 8:
            return self.primitive(self.unpack('B'))
        if kind == 9:
            return {'$ref': self.unpack('i')}
        if kind == 10:
            return None
        if kind in (13, 14):
            return {'$nulls': self.unpack('B') if kind == 13 else self.count()}
        if kind in (15, 16, 17):
            object_id, count = self.unpack('i'), self.count()
            info = (0, self.unpack('B')) if kind == 15 else (2, None)
            return self.array(object_id, count, info)
        if kind == 11:
            return {'$end': True}
        raise ValueError(f"Unsupported NRBF record {kind} at {self.stream.tell()-1}")

    def parse(self):
        if self.read(1) != b'\0':
            raise ValueError("Not an NRBF stream")
        self.stream.seek(0)
        while self.record() != {'$end': True}:
            pass
        if self.stream.tell() != self.limit:
            raise ValueError("Trailing NRBF bytes")
        if self.root_id not in self.objects:
            raise ValueError("Missing NRBF root")
        return self

    def expanded(self):
        def expand(obj, active):
            if isinstance(obj, dict) and '$ref' in obj:
                key = obj['$ref']
                if key in active:
                    return {'$ref': key}
                return expand(self.objects[key], active | {key})
            if isinstance(obj, list):
                return [expand(x, active) for x in obj]
            if isinstance(obj, dict):
                result = {k: expand(v, active) for k, v in obj.items()}
                if result.get('$type', '').startswith('System.Collections.Generic.List`1'):
                    return result['_items'][:result['_size']]
                return result
            return obj
        return expand({'$ref': self.root_id}, set())
