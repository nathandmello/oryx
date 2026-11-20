# Local English embedding model

oryx ships the 256-dimensional Model2Vec Potion base model. Minish Lab distilled it from BGE base English v1.5.
The data file contains 29,528 WordPiece tokens, their scales, and their signed 8-bit vectors.
Python verifies its SHA-256 digest before use.

The source revision is `bf8b056651a2c21b8d2565580b8569da283cab23`.
The source distribution is [Veto model 1.0.1](https://registry.npmjs.org/@jigyasudham/veto-model/-/veto-model-1.0.1.tgz).
It includes the [model license](LICENSE.potion-base-8M) and [distribution license](LICENSE).
Reproduce the data with `python3 tools/search_model/pack.py /path/to/veto-model-1.0.1.tgz`.
The packer checks the published archive digest and each upstream asset.
