"""Offline inference for the Hub's quantized English Model2Vec release."""

from collections import Counter
from functools import lru_cache
from hashlib import sha256
import math
from pathlib import Path
import struct
import unicodedata

VERSION = "c232e683403f6453863d609089b361580731b95e332580adc6e8bae8cb879dc5"
DIMENSIONS = 256
PACK = struct.Struct("<256f")
MODEL_PATH = Path(__file__).resolve().parents[3] / "tools/search_model/potion.bin"


def is_cjk(code):
    return (0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
            or 0x20000 <= code <= 0x2CEAF or 0x2F800 <= code <= 0x2FA1F)


class Encoder:
    def __init__(self, path):
        data = path.read_bytes()
        if sha256(data).hexdigest() != VERSION:
            raise ValueError("Invalid bundled model")
        size, = struct.unpack_from("<I", data)
        vocabulary = data[4:4 + size].decode("utf-8").split("\n")
        self.vocabulary = {label: index for index, label in enumerate(vocabulary)}
        self.scales = struct.unpack_from(f"<{len(vocabulary)}f", data, 4 + size)
        self.matrix = memoryview(data)[4 + size + 4 * len(vocabulary):].cast("b")

    def token_ids(self, text):
        cleaned = []
        for char in unicodedata.normalize("NFD", text.lower()):
            category = unicodedata.category(char)
            if char.isspace():
                cleaned.append(" ")
            elif category == "Mn" or category.startswith("C") or char == "\ufffd":
                continue
            elif category.startswith("P") or is_cjk(ord(char)) or (char.isascii() and not char.isalnum()):
                cleaned.extend((" ", char, " "))
            else:
                cleaned.append(char)
        for token in "".join(cleaned).split():
            if token in self.vocabulary:
                yield self.vocabulary[token]
                continue
            if len(token) > 100:
                continue
            start, pieces = 0, []
            while start < len(token):
                end = len(token)
                prefix = "##" if start else ""
                while end > start and prefix + token[start:end] not in self.vocabulary:
                    end -= 1
                if end == start:
                    break  # WordPiece drops the entire unknown word for this model.
                pieces.append(self.vocabulary[prefix + token[start:end]])
                start = end
            if start == len(token):
                yield from pieces

    def encode(self, text):
        vector = [0.0] * DIMENSIONS
        for index, count in Counter(self.token_ids(text)).items():
            scale = self.scales[index] * count
            start = index * DIMENSIONS
            vector = [total + value * scale for total, value in zip(vector, self.matrix[start:start + DIMENSIONS])]
        size = math.sqrt(sum(value * value for value in vector))
        return tuple(value / size for value in vector) if size else tuple(vector)


@lru_cache(maxsize=1)
def encoder():
    return Encoder(MODEL_PATH)


def similarity(left, right):
    return sum(a * b for a, b in zip(left, right))
