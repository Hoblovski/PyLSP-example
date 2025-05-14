import subprocess
import time
import argparse
import os.path
import logging
from pprint import pformat

import pylspclient
from pylspclient.lsp_pydantic_strcuts import (
    TextDocumentIdentifier,
    TextDocumentItem,
    LanguageIdentifier,
    Position,
)

from utils import *


file_handler = logging.FileHandler("lsp_notifications.log")
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
_notification_logger = logging.getLogger("LspNotification")
_notification_logger.setLevel(logging.INFO)
_notification_logger.addHandler(file_handler)


def _log_notification(name):
    def f(*args, **kwargs):
        _notification_logger.info(f"{name}: args={args}")
        _notification_logger.info(f"{name}: kwargs={kwargs}")

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
        logfile="lsp.log",
    ):
        assert (initfile or workspace) is not None
        self.post_init_wait = post_init_wait
        self.language_id = language_id or self._infer_language_id(initfile, workspace)
        self.initfile = initfile
        self.workspace = workspace or self._infer_workspace(initfile)
        self.lsp_timeout = lsp_timeout

        file_handler = logging.FileHandler(logfile)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)

        self.logger = logging.getLogger("PyLspClient")
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)

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

    def init(self):
        self.compute_lspcmdlist()
        self.initialize_lsp()
        self.post_initialize_lsp()

    def open_docfile(self, filepath):
        uri = to_uri(filepath)
        with open(to_path(filepath), "r") as fin:
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
        self.logger.debug("document_symbol:\n" + pformat(res, 4))
        return res

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
        return res

    def type_definition(self, filepath=None, line=0, character=0):
        filepath = filepath or self.initfile
        doc, text = self.open_docfile(filepath)
        res = self.lsp_endpoint.call_method(
            "textDocument/typeDefinition",
            textDocument=doc,
            position=Position(line=line, character=character),
        )
        self.logger.debug("type_definition:\n" + pformat(res, 4))
        return res


cli = PyLspClient(
    workspace="/home/zhenyang/O/data/Programs/bytedance/dataset-readable/astropy"
)
cli.init()
f = "/home/zhenyang/O/data/Programs/bytedance/dataset-readable/astropy/astropy/nddata/nddata_base.py"
f = "/home/zhenyang/O/data/Programs/bytedance/dataset-readable/astropy/astropy/units/quantity.py"
cli.document_symbol(f)
cli.semantic_tokens(f)
cli.type_definition(filepath=f, line=4, character=16)
cli.shutdown()
