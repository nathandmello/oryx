"""Reproduce the Hub data file from the pinned, data-only model distribution."""

from hashlib import sha256, sha512
import base64
import json
from pathlib import Path
import struct
import sys
import tarfile

ARCHIVE = "i2p81Nq+jHg1EqwXfXeegAG6YAPGQtNmsboUCEZQVB45x4KfJXRUnhdAPVa6n62aJ6JVlzpOujdJjRSbiqTFXw=="

def build(source, destination):
    if base64.b64encode(sha512(source.read_bytes()).digest()).decode() != ARCHIVE:
        raise ValueError("Expected the published @jigyasudham/veto-model 1.0.1 archive")
    with tarfile.open(source) as archive:
        def read(name):
            return archive.extractfile("package/" + name).read()
        model = json.loads(read("model/model.json"))
        files = {}
        for name, digest in model["files"].items():
            data = read("model/" + name)
            if sha256(data).hexdigest() != digest:
                raise ValueError("Model asset digest mismatch")
            files[name] = data
        vocab = json.loads(files["tokenizer.json"])["model"]["vocab"]
        labels = "\n".join(sorted(vocab, key=vocab.get)).encode("utf-8")
        destination.write_bytes(struct.pack("<I", len(labels)) + labels + files["scales.f32.bin"]
                                + files["embeddings.int8.bin"])
        for name in ("LICENSE", "LICENSE.potion-base-8M"):
            destination.with_name(name).write_bytes(read(name).replace(b"\r\n", b"\n"))

if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(__file__).with_name("potion.bin"))
