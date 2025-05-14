# Introduction to LSP
Requires
* C: clangd-18
* Rust: rust-analyzer
* Python: python-lsp-server
* python 3.10+

Usage:
```sh
python pylspcli.py c testdata/c/main.c
python pylspcli.py rust testdata/rust/src/main.rs

# The LSP Client as an object, useful for libraries
python client_obj.py
```

# Example results
## C
![c](./assets/c.png)
## Rust
![rust](./assets/rust.png)
## Python
![python](./assets/python.png)
