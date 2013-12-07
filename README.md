meta-deps
=========

Load all python package dependencies from pypi:

``` bash
./pypi-metadata.py load
```

Query dependants on something:

``` bash
./pypi-metadata.py rev <package-name>
```

Show packages most depended upon:

``` bash
./pypi-metadata.py top
```

Based on [script by ssaboum](https://github.com/ssaboum/meta-deps).
