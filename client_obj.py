import subprocess
import time
import argparse

import pylspclient
from pylspclient.lsp_pydantic_strcuts import (
    TextDocumentIdentifier,
    TextDocumentItem,
    LanguageIdentifier,
    Position,
)

from utils import *


def _log_notification(name):
    def f(*args, **kwargs):
        print(f"{name}: args=", args)
        print(f"{name}: kwargs=", kwargs)

    return f


def parse_args():
    parser = argparse.ArgumentParser(description="LSP client for testing")
    parser.add_argument("lang", type=str, choices=["c", "rust", "python"])
    parser.add_argument("file", nargs="?", type=str)
    parser.add_argument("workspace", nargs="?", type=str)
    parser.add_argument("-w", "--wait", type=int, default=3)
    parser.add_argument(
        "-r", "--raw", action="store_true", help="Dump semantic tokens as raw integers?"
    )
    args = parser.parse_args()
    if args.workspace is None:
        match args.lang:
            case "c":
                args.workspace = os.path.dirname(args.file)
            case "rust":
                args.workspace = os.path.dirname(os.path.dirname(args.file))
            case "python":
                args.workspace = os.path.dirname(args.file)
    return args


class PyLspClient:
    def _infer_language_id(self, initfile: str, workspace: str):
        initfile_suffix = {
            ".py": LanguageIdentifier.PYTHON,
            ".rs": LanguageIdentifier.RUST,
            ".c": LanguageIdentifier.C,
            "Cargo.toml": LanguageIdentifier.RUST,
        }
        if initfile is not None:
            for k, v in initfile_suffix.items():
                if initfile.endswith(k):
                    return v
        return None

    def _infer_workspace(self, initfile: str):
        print("_infer_workspace", initfile, self.language_id)
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
        self, language_id=None, initfile=None, workspace=None, post_init_wait=1
    ):
        assert (initfile or workspace) is not None
        self.post_init_wait = post_init_wait
        self.language_id = language_id or self._infer_language_id(initfile, workspace)
        self.initfile = initfile
        self.workspace = workspace or self._infer_workspace(initfile)
        print("workspace", self.workspace)

    def shutdown(self):
        self.lspcli.shutdown()
        self.lspcli.exit()
        self.srvproc.kill()
        self.srvproc.communicate()

    def compute_lspcmdlist(self):
        match self.language_id:
            case LanguageIdentifier.C:
                self.lsp_cmdlist = ["clangd-18"]
            case LanguageIdentifier.RUST:
                self.lsp_cmdlist = ["rust-analyzer"]
            case LanguageIdentifier.PYTHON:
                self.lsp_cmdlist = ["pylsp"]
            case _:
                raise ValueError("Invalid language argument")

    def initialize_lsp(self):
        self.srvproc = subprocess.Popen(
            self.lsp_cmdlist,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
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
        ppprint("initialize_response", self.init_response)
        capabilities = self.init_response["capabilities"]
        if (
            "semanticTokensProvider" in capabilities
            and capabilities["semanticTokensProvider"] != False
        ):
            token_legend = capabilities["semanticTokensProvider"]["legend"]
            self.token_types = token_legend["tokenTypes"]
            self.token_modifiers = token_legend["tokenModifiers"]
            ppprint("token_types", self.token_types)
            ppprint("token_modifiers", self.token_modifiers)
        self.lspcli.initialized()
        time.sleep(self.post_init_wait)

    def init(self):
        self.compute_lspcmdlist()
        self.initialize_lsp()
        self.post_initialize_lsp()

    def open_docfile(self, filepath):
        uri = to_uri(filepath)
        with open(filepath, "r") as fin:
            text = fin.read()
        version = 1
        self.lspcli.didOpen(
            TextDocumentItem(
                uri=uri, languageId=self.language_id, version=version, text=text
            )
        )
        doc = TextDocumentIdentifier(uri=uri).model_dump()
        assert doc is not None
        return doc, text

    def document_symbol(self, filepath=None):
        filepath = filepath or self.initfile
        doc, text = self.open_docfile(filepath)
        res = self.lsp_endpoint.call_method(
            "textDocument/documentSymbol", textDocument=doc
        )
        pprint(res)

    def semantic_tokens(self, filepath=None):
        filepath = filepath or self.initfile
        doc, text = self.open_docfile(filepath)
        res = self.lsp_endpoint.call_method(
            "textDocument/semanticTokens/full", textDocument=doc
        )
        tokens = res["data"]
        annots = dump_semantic_tokens_full(
            tokens, self.token_types, self.token_modifiers, text.splitlines()
        )
        print(annotate(text, annots))

    def type_definition(self, filepath=None, line=0, character=0):
        filepath = filepath or self.initfile
        doc, text = self.open_docfile(filepath)
        res = self.lsp_endpoint.call_method(
            "textDocument/typeDefinition",
            textDocument=doc,
            position=Position(line=line, character=character),
        )
        pprint(res)


cli = PyLspClient(initfile="testdata/python/test.py")
# cli = PyLspClient(initfile="/home/zhenyang/O/data/Programs/bytedance/dataset-readable/astropy/astropy/nddata/nddata_base.py")
# cli = PyLspClient(initfile="testdata/rust/src/main.rs", post_init_wait=3)
cli.init()
cli.document_symbol()
cli.semantic_tokens()
cli.type_definition(line=36, character=14)
cli.shutdown()
