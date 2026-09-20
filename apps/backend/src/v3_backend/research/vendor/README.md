Qlib source reuse
=================

`dump_bin.py` and `dump_pit.py` are unmodified Microsoft Qlib v0.9.7 files from
https://github.com/microsoft/qlib/tree/v0.9.7/scripts.
Copyright Microsoft Corporation; MIT license in `QLIB_LICENSE`.
Research adapters invoke these writers for market/PIT caches. They do not replace
Qlib's expression engine, PIT resolver, portfolio execution or performance metrics.
