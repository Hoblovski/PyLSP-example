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


def parse_args():
    global args
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


def post_parse_args():
    global server_process_cmdlist, language_id
    if args.lang == "c":
        server_process_cmdlist = ["clangd-18"]
        language_id = LanguageIdentifier.C
    elif args.lang == "rust":
        server_process_cmdlist = ["rust-analyzer"]
        language_id = LanguageIdentifier.RUST
    elif args.lang == "python":
        server_process_cmdlist = ["pylsp"]
        # server_process_cmdlist = ["jedi-language-server"]
        language_id = LanguageIdentifier.RUST
    else:
        raise ValueError("Invalid language argument")


def log_notification(name):
    def f(*args, **kwargs):
        print(f"{name}: args=", args)
        print(f"{name}: kwargs=", kwargs)

    return f


def initialize_lsp():
    global srvproc, client, endpoint, initresp
    srvproc = subprocess.Popen(
        server_process_cmdlist,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    json_rpc = pylspclient.JsonRpcEndpoint(srvproc.stdin, srvproc.stdout)

    endpoint = pylspclient.LspEndpoint(
        json_rpc,
        notify_callbacks={
            "window/showMessage": log_notification("windowShowMessage"),
            "textDocument/publishDiagnostics": log_notification("publishDiagnostics"),
        },
    )
    client = pylspclient.LspClient(endpoint)
    process_id = None
    root_path = None
    root_uri = to_uri(args.workspace)
    initialization_options = None
    capabilities = {}
    trace = "off"
    workspace_folders = None
    initresp = client.initialize(
        process_id,
        root_path,
        root_uri,
        initialization_options,
        capabilities,
        trace,
        workspace_folders,
    )


def post_initialize(semtokens=False):
    global token_types, token_modifiers
    ppprint("initialize_response", initresp)
    if semtokens:
        token_legend = initresp["capabilities"]["semanticTokensProvider"]["legend"]
        token_modifiers = token_legend["tokenModifiers"]
        token_types = token_legend["tokenTypes"]
        ppprint("token_types", token_types)
        ppprint("token_modifiers", token_modifiers)
    client.initialized()
    time.sleep(args.wait)


def open_file():
    global textdoc, text, textlines
    uri = to_uri(args.file)
    text = open(args.file, "r").read()
    textlines = text.splitlines()
    version = 1
    client.didOpen(
        TextDocumentItem(uri=uri, languageId=language_id, version=version, text=text)
    )
    textdoc = TextDocumentIdentifier(uri=uri).model_dump()
    assert textdoc is not None


def do_semtokens():
    print("do semtokens")
    res = endpoint.call_method("textDocument/semanticTokens/full", textDocument=textdoc)
    tokens = res["data"]
    annots = dump_semantic_tokens_full(
        tokens, token_types, token_modifiers, textlines, print_raw=args.raw
    )
    print(annotate(text, annots))


def do_typedefn(line, char):
    print("do typedefn")
    res = endpoint.call_method(
        "textDocument/typeDefinition",
        textDocument=textdoc,
        position=Position(line=line, character=char),
    )
    # res = endpoint.call_method("textDocument/definition", textDocument=textdoc, position=Position(line=line, character=char))
    pprint(res)


def do_docsyms():
    print("do docsyms")
    res = endpoint.call_method("textDocument/documentSymbol", textDocument=textdoc)
    # res = endpoint.call_method("textDocument/definition", textDocument=textdoc, position=Position(line=line, character=char))
    pprint(res)


def shutdown():
    client.shutdown()
    client.exit()
    srvproc.kill()
    srvproc.communicate()


semtokens = True
parse_args()
post_parse_args()
initialize_lsp()
post_initialize(semtokens)
open_file()
do_docsyms()
# if semtokens:
#    do_semtokens()
# else:
#    #do_typedefn(31, 16) # IntPair
#    #do_typedefn(38, 24) # CharVariant
#    do_typedefn(29, 9) # list
shutdown()
