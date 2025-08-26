import logging
import os.path
import subprocess
import time
from pprint import pformat
from typing import Any, Optional

import IPython
import pylspclient  # type: ignore
from pylspclient.lsp_pydantic_strcuts import (  # type: ignore
    LanguageIdentifier,
    TextDocumentIdentifier,
    TextDocumentItem,
)

from utils import annotate, dump_semantic_tokens_full, readfile_whole, to_uri

os.makedirs("logs", exist_ok=True)
CompatLogFormat: str = "%(asctime)s - %(levelname)s - %(message)s"
VerboseLogFormat: str = (
    "\n%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d in %(funcName)s\n%(message)s"
)
file_handler = logging.FileHandler("logs/lsp_notifications.log")
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(VerboseLogFormat)
file_handler.setFormatter(formatter)
_notification_logger = logging.getLogger("LspNotification")
_notification_logger.setLevel(logging.INFO)
_notification_logger.addHandler(file_handler)


def _log_notification(name):
    def f(*args, **kwargs):
        _notification_logger.info(f"{name}: args={args}")
        _notification_logger.info(f"{name}: kwargs={kwargs}")

    return f


IntPair = tuple[int, int]


class PyLspClient:
    def _infer_language_id(self, initfile: str, workspace: str):
        if initfile is not None:
            initfile_suffix = {
                ".py": LanguageIdentifier.PYTHON,
                ".rs": LanguageIdentifier.RUST,
                ".c": LanguageIdentifier.C,
            }
            for k, v in initfile_suffix.items():
                if initfile.endswith(k):
                    return v
        if workspace is not None:
            keyfiles = {
                "Cargo.toml": LanguageIdentifier.RUST,
                "rust-project.json": LanguageIdentifier.RUST,
                "setup.py": LanguageIdentifier.PYTHON,
            }
            for k, v in keyfiles.items():
                keyfile = os.path.join(workspace, k)
                if os.path.exists(keyfile):
                    return v
        return None

    def _infer_workspace(self, initfile: str):
        if initfile is None:
            return None
        match self.language_id:
            case LanguageIdentifier.C:
                return os.path.dirname(initfile)
            case LanguageIdentifier.RUST:
                return os.path.dirname(os.path.dirname(initfile))
            case LanguageIdentifier.PYTHON:
                return os.path.dirname(initfile)
            case _:
                return None

    def __init__(
        self,
        language_id=None,
        initfile=None,
        workspace=None,
        post_init_wait=1,
        lsp_timeout=2,
        logfile="logs/lsp.log",
        verbose=False,
        cacher: Optional[Any] = None,
    ):
        assert (initfile or workspace) is not None
        self.post_init_wait = post_init_wait
        self.language_id = language_id or self._infer_language_id(initfile, workspace)
        self.initfile = initfile
        self.workspace = workspace or self._infer_workspace(initfile)
        self.lsp_timeout = lsp_timeout
        self.opened_docs: dict[str, TextDocumentIdentifier] = {}
        self.cacher = cacher

        file_handler = logging.FileHandler(logfile)
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(VerboseLogFormat)
        file_handler.setFormatter(formatter)

        self.logger = logging.getLogger("PyLspClient")
        log_level = logging.DEBUG if verbose else logging.INFO
        self.logger.setLevel(log_level)
        self.logger.addHandler(file_handler)

    def shutdown(self):
        self.lspcli.shutdown()
        self.lspcli.exit()
        self.srvproc.kill()
        stdout, stderr = self.srvproc.communicate()
        if stdout:
            print("Finish: LSP process stdout:\n", stdout.decode())
        if stderr:
            print("Finish: LSP process stderr:\n", stderr.decode())

    def compute_lspcmdlist(self):
        match self.language_id:
            case LanguageIdentifier.C:
                self.lsp_cmdlist = [
                    "clangd-18"
                ]  # , "--compile-commands-dir=/home/zhenyang/O/data/Programs/bytedance/abcoder/testdata/cduplicate/build"]
            case LanguageIdentifier.RUST:
                self.lsp_cmdlist = ["rust-analyzer"]
            case LanguageIdentifier.PYTHON:
                self.lsp_cmdlist = ["pylsp"]
            case _:
                raise ValueError("Invalid language argument")

    def initialize_lsp(self):
        try:
            self.srvproc = subprocess.Popen(
                self.lsp_cmdlist,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            print(f"The language server {self.lsp_cmdlist} is not found")
            print(f"Did you install it? Did you do `conda activate ...`?")
            exit(1)
        self.json_rpc = pylspclient.JsonRpcEndpoint(
            self.srvproc.stdin, self.srvproc.stdout
        )
        self.lsp_endpoint = pylspclient.LspEndpoint(
            self.json_rpc,
            notify_callbacks={
                "window/showMessage": _log_notification("windowShowMessage"),
                "textDocument/publishDiagnostics": _log_notification(
                    "publishDiagnostics"
                ),
            },
            timeout=self.lsp_timeout,
        )
        self.lspcli = pylspclient.LspClient(self.lsp_endpoint)
        # actually call initialize
        process_id, root_path = None, None
        root_uri = to_uri(self.workspace)
        initialization_options = None
        capabilities = {}
        trace = "off"
        workspace_folders = None
        self.init_response = self.lspcli.initialize(
            process_id,
            root_path,
            root_uri,
            initialization_options,
            capabilities,
            trace,
            workspace_folders,
        )

    def post_initialize_lsp(self):
        self.logger.info("initialize_response:\n" + pformat(self.init_response, 4))
        capabilities = self.init_response["capabilities"]
        if (
            "semanticTokensProvider" in capabilities
            and capabilities["semanticTokensProvider"] != False
        ):
            token_legend = capabilities["semanticTokensProvider"]["legend"]
            self.token_types = token_legend["tokenTypes"]
            self.token_modifiers = token_legend["tokenModifiers"]
            self.logger.info("token_types:\n" + pformat(self.token_types, 4))
            self.logger.info("token_modifiers:\n" + pformat(self.token_modifiers, 4))
        self.lspcli.initialized()
        time.sleep(self.post_init_wait)

    def get_toktype(self, t: int) -> str:
        if not self.token_types:
            return ""
        if t < 0 or t >= len(self.token_types):
            return f"UNKNOWN-TOKTYPE-{t}"
        return self.token_types[t]

    def get_tokmods(self, m: int) -> list[str]:
        if not self.token_modifiers:
            return []
        return [
            self.token_modifiers[i]
            for i in range(len(self.token_modifiers))
            if (m & (1 << i)) != 0
        ]

    def init(self):
        self.compute_lspcmdlist()
        self.initialize_lsp()
        self.post_initialize_lsp()

    def open_docfile(self, filepath: str) -> tuple[TextDocumentIdentifier, str]:
        print(f"open_docfile {filepath=}")
        if filepath in self.opened_docs:
            return self.opened_docs[filepath], readfile_whole(filepath)
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.workspace, filepath)
        uri = to_uri(filepath)
        text = readfile_whole(filepath)
        version = 1
        doc1 = TextDocumentItem(
            uri=uri, languageId=self.language_id, version=version, text=text
        )
        self.lspcli.didOpen(doc1)
        doc = TextDocumentIdentifier(uri=uri).model_dump()
        assert doc is not None
        self.opened_docs[filepath] = doc
        return doc, text

    def semantic_tokens(self, filepath: Optional[str] = None) -> dict[str, Any]:
        print("self.initfile", self.initfile)
        filepath = filepath or self.initfile
        print(f"{filepath=}")
        doc, text = self.open_docfile(filepath)
        print(f"{doc=}")
        res = self.lsp_endpoint.call_method(
            "textDocument/semanticTokens/full", textDocument=doc
        )
        tokens = res["data"]
        annots = dump_semantic_tokens_full(
            tokens, self.token_types, self.token_modifiers, text.splitlines()
        )
        print(annotate(text, annots))
        return res

    def generic(self, method: str, **kwargs):
        print(method, kwargs)
        res = self.lsp_endpoint.call_method(f"{method}", **kwargs)
        self.logger.debug(f"{method}:\n" + pformat(res, 4))
        return res

    def generic_notification(self, method: str, **kwargs):
        print("notification ", method, kwargs)
        res = self.lsp_endpoint.send_notification(f"{method}", **kwargs)
        self.logger.debug(f"notification {method}:\n" + pformat(res, 4))
        return res

    def generic_textdoc(
        self,
        method: str,
        filepath: Optional[str] = None,
        pos: Optional[IntPair] = None,
        range: Optional[tuple[IntPair, IntPair]] = None,
    ):
        key = f"{method=}:{filepath=}:{pos=}:{range=}"
        if self.cacher and (cached := self.cacher.get(key)) is not None:
            return cached
        filepath = filepath or self.initfile
        doc, _ = self.open_docfile(filepath)
        kwargs: dict[str, Any] = {}
        if pos is not None:
            kwargs["position"] = {"line": pos[0], "character": pos[1]}
        if range is not None:
            kwargs["range"] = {
                "start": {"line": range[0][0], "character": range[0][1]},
                "end": {"line": range[1][0], "character": range[1][1]},
            }
        res = self.lsp_endpoint.call_method(
            f"textDocument/{method}", textDocument=doc, **kwargs
        )
        if self.cacher:
            self.cacher.set(key, res)
        self.logger.debug(f"{method}: RETURNED {type(res)}:\n" + pformat(res, 4))
        return res


def eval_inputkwargs(args: str) -> dict[str, Any]:
    retval = {}
    for arg in args.split(", "):
        if not args.strip():
            continue
        if "=" not in arg:
            raise ValueError(f"Invalid argument format: {arg}")
        k, v = arg.split("=", 1)
        if v[0].isnumeric():
            v = int(v) if "." not in v else float(v)  # type: ignore
        else:
            v = ensure_unquoted(v.strip())
        retval[k.strip()] = v.strip()
    return retval


def ensure_quoted(s: str) -> str:
    if s[0] != '"' and s[-1] != '"':
        return f'"{s}"'
    return s


def ensure_unquoted(s: str) -> str:
    if s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def make_inputer(lines):
    counter = 0
    lines = lines.splitlines()

    def f(prompt="", /):
        nonlocal counter
        counter += 1
        if counter > len(lines):
            raise EOFError()
        res = lines[counter - 1]
        print("-" * 78)
        print(prompt, res)
        return res

    return f


def main(inputer=input):
    try:
        while True:
            init_kwargs = inputer("Input initkwargs, separated by ,")
            init_kwargs = eval_inputkwargs(init_kwargs)
            client = PyLspClient(lsp_timeout=5, **init_kwargs)
            client.init()
            persistent_kwargs = {}
            while True:
                print(f"persisted: {persistent_kwargs}")
                print("Methods: q , set , semtoks , _")
                cmdline = inputer("Method:args >> ")
                if not cmdline.strip():
                    continue
                method, *args = cmdline.split(maxsplit=1)
                temp_kwargs = eval_inputkwargs("".join(args))
                try:
                    match method:
                        case "q":
                            break
                        case "set":
                            persistent_kwargs.update(temp_kwargs)
                            continue
                        case "ckres":
                            IPython.embed(header="See last result in `res`")
                        case "reset":
                            persistent_kwargs = {}
                            continue
                        case "semtoks":
                            res = client.semantic_tokens(
                                **(persistent_kwargs | temp_kwargs)
                            )
                            print(res)
                        case _:
                            method = method.strip()
                            res = client.generic_textdoc(
                                method, **(persistent_kwargs | temp_kwargs)
                            )
                except Exception as e:
                    print(f"FAILED\n{e}")
                else:
                    print(f"OK\n{res}")
    except EOFError:
        print("Exiting...")
        try:
            client.shutdown()
        except Exception as e:
            pass
        finally:
            exit(0)


demo_commands = """\
workspace=testdata/python, initfile=test.py
documentSymbol
semtoks
q"""

if __name__ == "__main__":
    is_demo = input("Demo? (y/n) ")
    if is_demo:
        main(make_inputer(demo_commands))
    else:
        main()
