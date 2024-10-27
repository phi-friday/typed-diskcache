# typed-diskcache

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-yellow.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation Status](https://readthedocs.org/projects/typed-diskcache/badge/?version=latest)](https://typed-diskcache.readthedocs.io/en/latest/?badge=latest)
[![PyPI version](https://badge.fury.io/py/typed-diskcache.svg)](https://badge.fury.io/py/typed-diskcache)
[![python version](https://img.shields.io/pypi/pyversions/typed-diskcache.svg)](#)

## how to install
```shell
$ pip install typed-diskcache
# or
$ pip install "typed-diskcache[asyncio]"
```

## why use `typed-diskcache`
While `python-diskcache` is a very nice library, it has two shortcomings.
1. it doesn't support type hints.
2. does not support asynchronous syntax.

I know there were some requests for this, but they were rejected.

I created a stub package to solve the type hinting issue.
And this time I wanted to create a wrapper that added asynchronous syntax.
But I decided that if I'm going to do this, I might as well just create a new one.

The logic used is mostly the same as the original.
However, instead of using queries directly, I used `sqlalchemy`.
There are some changes in the way data is stored in the DB and retrieved, so it's not exactly the same as before.

Some features were left out.
This is because I don't use them.
If I think I'll need them in the future, I'll add them.

This could be a performance issue.
That's because my focus was on working first, not performance.
I'll fix this later.

I haven't tested it yet, so I can't guarantee it will work.
I'll be adding more tests over time.

## TODO
- [ ] docstring
> There are still some, but most of them copied `python-diskcache`.
- [ ] docs
- [ ] tests
- [ ] performance

## License

Apache-2.0, see [LICENSE](https://github.com/phi-friday/typed-diskcache/blob/main/LICENSE).
